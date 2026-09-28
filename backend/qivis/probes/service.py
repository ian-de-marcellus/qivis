"""Answer probes: short samples at one point, grouped by the answer each gives.

A probe asks the model for N short continuations at temperature 1 with no
truncation, so how often an answer comes up estimates how likely the model
is to give it. Each sample is kept as the node it would become (text and
full record), not as a node: a probe doesn't crowd the rhizome with
branches. Continuing from a sample records it as a reply like any other,
noting the probe it came from.
"""

import asyncio
import json
import logging
from typing import Any
from uuid import uuid4

from qivis.errors import InvalidRequestError, NotFoundError
from qivis.events.log import EventLog
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.service import GenerationService, Target
from qivis.models import NodeCreatedPayload, SamplingParams
from qivis.probes.judge import judge_samples
from qivis.providers.base import GenerationResult, LLMProvider
from qivis.providers.llamacpp import LlamaCppProvider
from qivis.providers.registry import get_provider
from qivis.rhizomes.schemas import NodeResponse
from qivis.rhizomes.service import RhizomeService

logger = logging.getLogger(__name__)

# Samples in flight at once (llama-server serves a few in parallel)
CONCURRENCY = 4


class ProbeNotFoundError(NotFoundError):
    def __init__(self, probe_id: str) -> None:
        super().__init__(f"Probe not found: {probe_id}")


def probe_sampling(max_tokens: int) -> SamplingParams:
    """Sampling that draws from the model's own distribution: temperature 1, no truncation."""
    return SamplingParams(
        temperature=1.0, top_p=1.0, top_k=0, max_tokens=max_tokens,
        logprobs=True, top_logprobs=5,
    )


class ProbeService:
    def __init__(
        self,
        rhizome_service: RhizomeService,
        gen_service: GenerationService,
        store: EventStore,
        projector: StateProjector,
    ) -> None:
        self._rhizomes = rhizome_service
        self._gen = gen_service
        self._events = EventLog(store, projector)
        self._projector = projector

    async def run(
        self,
        rhizome_id: str,
        node_id: str | None,
        provider: LLMProvider,
        model: str | None = None,
        n: int = 20,
        max_tokens: int = 24,
    ) -> dict[str, Any]:
        ctx = await self._gen.load(rhizome_id, node_id, sampling_params=probe_sampling(max_tokens))
        [p] = await self._gen.prepare(ctx, [Target(provider, model)])

        slots = asyncio.Semaphore(CONCURRENCY)

        async def sample() -> GenerationResult:
            async with slots:
                return self._gen.turn_ended(p, await provider.generate(p.request))

        results = await asyncio.gather(*[sample() for _ in range(n)], return_exceptions=True)
        done = [r for r in results if isinstance(r, GenerationResult)]
        failed = [r for r in results if isinstance(r, BaseException)]
        for error in failed:
            logger.warning("A probe sample failed: %r", error)
        if not done:
            raise failed[0]
        samples = [self._gen.node_record(p, r).model_dump(mode="json") for r in done]

        judge = await self._judge(samples)
        probe_id = str(uuid4())
        await self._events.emit(rhizome_id, "ProbeRecorded", {
            "probe_id": probe_id,
            "node_id": node_id,
            "provider": provider.name,
            "model": p.model,
            "samples": samples,
            "asked": n,
            "judge": judge,
        })
        return await self.get(rhizome_id, probe_id)

    async def _judge(self, samples: list[dict]) -> dict | None:
        try:
            llama = get_provider("llamacpp")
        except Exception:
            return None
        if not isinstance(llama, LlamaCppProvider):
            return None
        context = samples[0].get("prompt_text") or ""
        return await judge_samples(llama, context, [s["content"] for s in samples])

    async def judge_again(self, rhizome_id: str, probe_id: str) -> dict[str, Any]:
        row = await self._row(rhizome_id, probe_id)
        judge = await self._judge(json.loads(row["samples"]))
        if judge is None:
            raise InvalidRequestError("No judge model is available (see qivis/probes/judge.py)")
        await self._events.emit(rhizome_id, "ProbeJudged", {"probe_id": probe_id, "judge": judge})
        return await self.get(rhizome_id, probe_id)

    async def continue_from(self, rhizome_id: str, probe_id: str, index: int) -> NodeResponse:
        """Make a sample a reply: stored as it was sampled, noting the probe."""
        samples = json.loads((await self._row(rhizome_id, probe_id))["samples"])
        if not 0 <= index < len(samples):
            raise InvalidRequestError(f"No sample {index} in this probe")
        payload = NodeCreatedPayload.model_validate({
            **samples[index], "node_id": str(uuid4()), "from_probe": probe_id,
        })
        await self._events.emit(rhizome_id, "NodeCreated", payload)
        return await self._rhizomes.node_response(rhizome_id, payload.node_id)

    async def list(self, rhizome_id: str) -> list[dict[str, Any]]:
        return [_response(r) for r in await self._projector.get_probes(rhizome_id)]

    async def get(self, rhizome_id: str, probe_id: str) -> dict[str, Any]:
        return _response(await self._row(rhizome_id, probe_id))

    async def _row(self, rhizome_id: str, probe_id: str) -> dict:
        row = await self._projector.get_probe(rhizome_id, probe_id)
        if row is None:
            raise ProbeNotFoundError(probe_id)
        return row


def _response(row: dict) -> dict[str, Any]:
    samples = json.loads(row["samples"])
    judge = json.loads(row["judge"]) if row["judge"] else None
    return {
        "probe_id": row["probe_id"],
        "node_id": row["node_id"],
        "provider": row["provider"],
        "model": row["model"],
        "created_at": row["created_at"],
        # How many samples were asked for (some can fail); None for older probes
        "asked": row.get("asked"),
        "prompt_text": samples[0].get("prompt_text") if samples else None,
        "sampling_params": samples[0].get("sampling_params") if samples else None,
        "samples": [
            {
                "content": s["content"],
                "finish_reason": s.get("finish_reason"),
                "logprobs": s.get("logprobs"),
            }
            for s in samples
        ],
        "judge": None if judge is None else {
            "model": judge["model"], "answers": judge["answers"], "messages": judge["messages"],
        },
    }
