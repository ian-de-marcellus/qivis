"""Steering sessions: token-by-token generation where a researcher picks the path.

A session fixes the context once (the same load/prepare as any generation),
then answers "what could come next after these tokens?" as often as the UI
asks. The server remembers every distribution it showed, so when the reply
is committed, each token's probability and alternatives come from the model,
not from the client; the client only says who chose each token.
"""

import dataclasses
import math
import time
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from qivis.errors import InvalidRequestError, NotFoundError
from qivis.generation.service import GenerationService, Prepared, Target
from qivis.models import AlternativeToken, LogprobData, SamplingParams, TokenLogprob
from qivis.providers.base import GenerationResult, LLMProvider
from qivis.rhizomes.schemas import NodeResponse

MAX_SESSIONS = 16
DEFAULT_K = 20
# When a chosen token wasn't among those shown (typed), ask for the whole
# vocabulary: llama.cpp clamps to its size (~0.4 s for 128k), so every
# committed token has its true probability
LOOKUP_K = 1_000_000


class SteeringSessionNotFoundError(NotFoundError):
    def __init__(self, session_id: str) -> None:
        super().__init__(f"Steering session not found (it may have expired): {session_id}")


@dataclass
class SteeringSession:
    session_id: str
    prepared: Prepared
    created: float = field(default_factory=time.monotonic)
    # Every distribution shown, by the token ids that came before it
    shown: dict[tuple[int, ...], list[dict[str, Any]]] = field(default_factory=dict)
    logit_bias: dict[int, float] | None = None
    effective_prompt: str | None = None  # what the model saw, if it differs from the rendering


class SteeringService:
    def __init__(self, gen_service: GenerationService) -> None:
        self._gen = gen_service
        self._sessions: dict[str, SteeringSession] = {}

    async def start(
        self,
        rhizome_id: str,
        parent_id: str | None,
        provider: LLMProvider,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        sampling_params: SamplingParams | None = None,
    ) -> dict[str, Any]:
        """Fix the context for a steered reply to parent_id; returns the session."""
        if not hasattr(provider, "next_tokens"):
            raise InvalidRequestError(
                f"{provider.name} can't be steered token by token (llama.cpp models can)",
            )
        ctx = await self._gen.load(
            rhizome_id, parent_id, system_prompt=system_prompt, sampling_params=sampling_params,
        )
        [prepared] = await self._gen.prepare(ctx, [Target(provider, model, "completion")])
        if prepared.request.prompt_text is None:
            raise InvalidRequestError("Steering needs a completion-mode prompt")
        session = SteeringSession(str(uuid4()), dataclasses.replace(prepared, steered=True))
        self._sessions[session.session_id] = session
        while len(self._sessions) > MAX_SESSIONS:
            oldest = min(self._sessions.values(), key=lambda s: s.created)
            del self._sessions[oldest.session_id]
        return {
            "session_id": session.session_id,
            "model": prepared.model,
            "provider": provider.name,
            "prompt_text": prepared.request.prompt_text,
            "stop_sequences": prepared.request.sampling_params.stop_sequences or [],
            "context_usage": prepared.context_usage.model_dump(),
        }

    def _session(self, session_id: str) -> SteeringSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise SteeringSessionNotFoundError(session_id)
        return session

    async def next(
        self, session_id: str, continuation: list[int], k: int = DEFAULT_K,
    ) -> list[dict[str, Any]]:
        """The likeliest next tokens after the reply so far (token ids)."""
        session = self._session(session_id)
        key = tuple(continuation)
        shown = session.shown.get(key)
        if shown is None or len(shown) < k:
            result = await self._provider(session).next_tokens(
                session.prepared.request, continuation, k,
            )
            shown = result["candidates"]
            session.shown[key] = shown
            session.logit_bias = result["logit_bias"]
            session.effective_prompt = result["effective_prompt"]
        return shown[:k]

    async def commit(
        self,
        session_id: str,
        token_ids: list[int],
        chosen_by: list[Literal["model", "researcher"]],
    ) -> NodeResponse:
        """Store the steered reply as a node, with each token's provenance."""
        if len(chosen_by) != len(token_ids):
            raise InvalidRequestError("chosen_by must name who chose each token")
        if not token_ids:
            raise InvalidRequestError("Nothing to commit: no tokens chosen")
        session = self._sessions.pop(session_id, None)
        if session is None:
            raise SteeringSessionNotFoundError(session_id)
        try:
            tokens: list[TokenLogprob] = []
            for i, (tid, who) in enumerate(zip(token_ids, chosen_by, strict=True)):
                shown = await self._distribution(session, token_ids[:i], tid)
                chosen = next((c for c in shown if c["id"] == tid), None)
                if chosen is None:
                    raise InvalidRequestError(f"Token {tid} isn't in this model's vocabulary")
                tokens.append(TokenLogprob(
                    token=chosen["token"],
                    token_id=tid,
                    logprob=_log(chosen["prob"]),
                    linear_prob=chosen["prob"],
                    top_alternatives=[
                        AlternativeToken(
                            token=c["token"], logprob=_log(c["prob"]), linear_prob=c["prob"],
                        )
                        for c in shown[:DEFAULT_K] if c["id"] != tid
                    ],
                    chosen_by=who,
                ))

            # A reply that reaches the model's end-of-turn ends there, like any generation
            stops = session.prepared.request.sampling_params.stop_sequences or []
            finish = "researcher"
            kept = len(tokens)
            if tokens and tokens[-1].token in stops:
                finish, kept = "stop", len(tokens) - 1
            content = await self._provider(session).detokenize(token_ids[:kept])
        except Exception:
            self._sessions[session.session_id] = session  # let them retry the commit
            raise

        p = session.prepared
        return await self._gen.persist(p, GenerationResult(
            content=content,
            model=p.model,
            finish_reason=finish,
            logprobs=LogprobData(
                tokens=tokens, provider_format="llamacpp", top_k_available=DEFAULT_K,
            ),
            applied_sampling_params=(
                {"logit_bias": session.logit_bias} if session.logit_bias else None
            ),
            effective_prompt_text=session.effective_prompt,
        ))

    def discard(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    async def _distribution(
        self, session: SteeringSession, before: list[int], chosen: int,
    ) -> list[dict[str, Any]]:
        """What was shown before this token; widened if the token wasn't among it (typed)."""
        key = tuple(before)
        shown = session.shown.get(key)
        if shown is None or not any(c["id"] == chosen for c in shown):
            result = await self._provider(session).next_tokens(
                session.prepared.request, before, LOOKUP_K,
            )
            shown = result["candidates"]
            session.shown[key] = shown
        return shown

    @staticmethod
    def _provider(session: SteeringSession) -> Any:
        return session.prepared.provider


def _log(p: float) -> float:
    # A probability that underflowed to 0 is recorded at the float floor, not -inf
    # (which JSON can't carry)
    return math.log(max(p, 1e-300))
