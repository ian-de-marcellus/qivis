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
from qivis.probes import exact as exact_probe
from qivis.probes.judge import bucket_answers, judge_answers, judge_samples, resolve_judge
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

    async def run_exact(
        self,
        rhizome_id: str,
        node_id: str | None,
        provider: LLMProvider,
        model: str | None = None,
        epsilon: float = exact_probe.EPSILON,
        max_tokens: int = 24,
        tail: int = exact_probe.TAIL,
        menu: list[str] | None = None,
        judge: dict | None = None,
        grain: str | None = None,
    ) -> dict[str, Any]:
        """An exact probe (qivis.probes.exact): one-line answers enumerated down to
        epsilon, the pruned rest sampled, then judged and grouped."""
        if not isinstance(provider, LlamaCppProvider):
            raise InvalidRequestError(
                "Exact probes need a llama.cpp model (they read its distributions)",
            )
        ctx = await self._gen.load(rhizome_id, node_id, sampling_params=probe_sampling(max_tokens))
        [p] = await self._gen.prepare(ctx, [Target(provider, model)])
        if p.request.prompt_text is None:
            raise InvalidRequestError("Exact probes work on completion-mode prompts")
        lookups = await exact_probe.answer_lookups(provider, p.request)
        found = await exact_probe.enumerate_answers(lookups, epsilon, max_tokens)
        await exact_probe.release_lookups(provider)
        tails = await exact_probe.rollouts(provider, p.request, found.stubs, tail, max_tokens)
        template = self._gen.node_record(
            p, GenerationResult(content="", model=p.model),
        ).model_dump(mode="json")
        record = {
            "settings": {"epsilon": epsilon, "max_tokens": max_tokens, "tail": tail,
                         "menu": menu, "grain": grain, "stop": "end of line"},
            # The node an answer becomes if continued from (its text filled in then)
            "template": template,
            "strip": p.template == "transcript",
            "leaves": [{"text": x.text, "ids": x.ids, "p": x.p, "finish": x.finish}
                       for x in found.leaves],
            "tail": [{"text": r.text, "from_ids": r.from_ids, "ids": r.ids, "weight": r.weight,
                      "finish": r.finish} for r in tails],
            "explored": found.explored,
            "cut_off": found.cut_off,
            "pruned": found.pruned,
            "lookups": found.lookups,
            "stopped_early": found.stopped_early,
        }
        judged = await self._judge_exact(record, judge)
        probe_id = str(uuid4())
        await self._events.emit(rhizome_id, "ProbeRecorded", {
            "probe_id": probe_id, "node_id": node_id, "provider": provider.name,
            "model": p.model, "samples": [], "asked": None, "judge": judged, "exact": record,
        })
        return await self.get(rhizome_id, probe_id)

    async def _judge_exact(self, record: dict, spec: dict | None) -> dict | None:
        """Label every distinct answer text, then group the labels (unless there's a menu)."""
        try:
            llama = get_provider("llamacpp")
        except Exception:
            llama = None
        if llama is not None and not isinstance(llama, LlamaCppProvider):
            llama = None
        judge = await resolve_judge(llama, spec)
        if judge is None:
            return None
        items = _exact_items(record)
        texts = list(dict.fromkeys(_shown(i["text"], record) for i in items))
        context = record["template"].get("prompt_text") or ""
        menu = record["settings"].get("menu")
        labelled = await judge_answers(llama, judge, context, texts, menu)
        label_of = dict(zip(texts, labelled["answers"], strict=True))
        answers = [label_of[_shown(i["text"], record)] for i in items]
        masses: dict[str, float] = {}
        for i, a in zip(items, answers, strict=True):
            masses[a] = masses.get(a, 0.0) + i["mass"]
        if menu:
            # The menu's answers stay as they are; answers off the menu ("other: ...")
            # are grouped like free labels
            others = {a: m for a, m in masses.items() if a.startswith("other")}
            grouped = await bucket_answers(llama, judge, context, others,
                                           record["settings"].get("grain"))
            grouped["buckets"] = {
                **{a: a for a in masses},
                **{a: g if g.startswith("other") else f"other: {g}"
                   for a, g in grouped["buckets"].items()},
            }
        else:
            grouped = await bucket_answers(llama, judge, context, masses,
                                           record["settings"].get("grain"))
        return {
            "provider": judge["provider"], "model": judge["model"],
            "messages": labelled["messages"], "raw": labelled["raw"], "texts": texts,
            "answers": answers, "menu": menu,
            "buckets": grouped["buckets"],
            "bucket_judge": {
                k: grouped.get(k) for k in ("provider", "model", "messages", "raw", "grain")
            },
        }

    async def _judge(self, samples: list[dict]) -> dict | None:
        try:
            llama = get_provider("llamacpp")
        except Exception:
            return None
        if not isinstance(llama, LlamaCppProvider):
            return None
        context = samples[0].get("prompt_text") or ""
        return await judge_samples(llama, context, [s["content"] for s in samples])

    async def judge_again(self, rhizome_id: str, probe_id: str,
                          judge_spec: dict | None = None) -> dict[str, Any]:
        row = await self._row(rhizome_id, probe_id)
        if row.get("exact"):
            judge = await self._judge_exact(json.loads(row["exact"]), judge_spec)
        else:
            judge = await self._judge(json.loads(row["samples"]))
        if judge is None:
            raise InvalidRequestError("No judge model is available (see qivis/probes/judge.py)")
        await self._events.emit(rhizome_id, "ProbeJudged", {"probe_id": probe_id, "judge": judge})
        return await self.get(rhizome_id, probe_id)

    async def continue_from(self, rhizome_id: str, probe_id: str, index: int) -> NodeResponse:
        """Make a sample a reply: stored as it was sampled, noting the probe."""
        row = await self._row(rhizome_id, probe_id)
        if row.get("exact"):
            return await self._continue_exact(rhizome_id, probe_id, json.loads(row["exact"]), index)
        samples = json.loads(row["samples"])
        if not 0 <= index < len(samples):
            raise InvalidRequestError(f"No sample {index} in this probe")
        payload = NodeCreatedPayload.model_validate({
            **samples[index], "node_id": str(uuid4()), "from_probe": probe_id,
        })
        await self._events.emit(rhizome_id, "NodeCreated", payload)
        return await self._rhizomes.node_response(rhizome_id, payload.node_id)

    async def _continue_exact(self, rhizome_id: str, probe_id: str, record: dict,
                              index: int) -> NodeResponse:
        """Make an enumerated answer (or a tail rollout) the reply. Its record says
        which: an enumerated one wasn't sampled, so its raw_response notes that and
        its exact probability."""
        items = _exact_items(record)
        if not 0 <= index < len(items):
            raise InvalidRequestError(f"No answer {index} in this probe")
        item = items[index]
        provenance = (
            {"enumerated": True, "probability": item["mass"], "token_ids": item["ids"]}
            if item["kind"] == "leaf" else
            {"tail_rollout": True, "weight": item["mass"], "token_ids": item["ids"]}
        )
        payload = NodeCreatedPayload.model_validate({
            **record["template"], "node_id": str(uuid4()), "from_probe": probe_id,
            "content": _shown(item["text"], record), "finish_reason": item["finish"],
            "logprobs": None, "raw_response": provenance,
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


def _exact_items(record: dict) -> list[dict]:
    """An exact probe's answers in one list: the enumerated ones, then the tail
    rollouts; "mass" is a leaf's exact probability or a rollout's weight."""
    return (
        [{"kind": "leaf", "text": x["text"], "ids": x["ids"], "mass": x["p"], "finish": x["finish"]}
         for x in record["leaves"]]
        + [{"kind": "tail", "text": r["text"], "ids": r["from_ids"] + r["ids"], "mass": r["weight"],
            "finish": r["finish"]} for r in record["tail"]]
    )


def _shown(text: str, record: dict) -> str:
    """An answer's text as its node would store it (a transcript turn is stripped)."""
    return text.strip() if record.get("strip") else text


def _exact_response(row: dict, base: dict) -> dict[str, Any]:
    record = json.loads(row["exact"])
    judge = json.loads(row["judge"]) if row["judge"] else None
    items = _exact_items(record)
    answers = judge["answers"] if judge else None
    buckets = judge["buckets"] if judge else None
    groups: dict[str, dict] = {}
    for i, item in enumerate(items):
        label = answers[i] if answers else ""
        name = buckets.get(label, label) if buckets else label
        g = groups.setdefault(name, {"answer": name, "exact": 0.0, "tail": 0.0, "labels": {}})
        lab = g["labels"].setdefault(
            label, {"label": label, "exact": 0.0, "tail": 0.0, "items": []},
        )
        key = "exact" if item["kind"] == "leaf" else "tail"
        g[key] += item["mass"]
        lab[key] += item["mass"]
        lab["items"].append(i)
    ordered = sorted(
        groups.values(), key=lambda g: (g["answer"] == "no answer", -(g["exact"] + g["tail"])),
    )
    for g in ordered:
        g["labels"] = sorted(g["labels"].values(), key=lambda x: -(x["exact"] + x["tail"]))
    return {
        **base,
        "mode": "exact",
        "prompt_text": record["template"].get("prompt_text"),
        "sampling_params": record["template"].get("sampling_params"),
        "samples": [],
        "exact": {
            "settings": record["settings"], "explored": record["explored"],
            "cut_off": record["cut_off"], "pruned": record["pruned"],
            "lookups": record["lookups"], "stopped_early": record["stopped_early"],
            "items": [{"kind": x["kind"], "text": _shown(x["text"], record), "mass": x["mass"],
                       "finish": x["finish"]} for x in items],
            "groups": ordered,
        },
        "judge": None if judge is None else {
            "provider": judge.get("provider"), "model": judge["model"],
            "answers": judge["answers"], "messages": judge["messages"], "raw": judge.get("raw"),
            "menu": judge.get("menu"), "buckets": judge.get("buckets"),
            "bucket_judge": judge.get("bucket_judge"),
        },
    }


def _response(row: dict) -> dict[str, Any]:
    if row.get("exact"):
        return _exact_response(row, {
            "probe_id": row["probe_id"], "node_id": row["node_id"], "provider": row["provider"],
            "model": row["model"], "created_at": row["created_at"], "asked": None,
        })
    samples = json.loads(row["samples"])
    judge = json.loads(row["judge"]) if row["judge"] else None
    return {
        "mode": "sample",
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
            # What the judge actually wrote, before spellings were merged
            "raw": judge.get("raw"),
        },
    }
