"""Steering sessions: token-by-token generation where a researcher picks the path.

A session fixes the context once (the same load/prepare as any generation),
then answers "what could come next after these tokens?" as often as the UI
asks. The server remembers every distribution it showed, so when the reply
is committed, each token's probability and alternatives come from the model,
not from the client; the client only says who chose each token.
"""

import dataclasses
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from qivis.errors import InvalidRequestError, NotFoundError
from qivis.generation.service import GenerationService, Prepared, Target
from qivis.generation.templates import HEALED_SPACE
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
    # Special tokens' text by id: llama.cpp reports them with empty text
    special_text: dict[int, str] = field(default_factory=dict)


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
        session.special_text = await self._special_text(provider, prepared)
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
        # A healed trailing space: the first token must start a word. Show the
        # options given that (renormalized, marked), from the whole vocabulary
        grammar = session.prepared.request.sampling_params.grammar
        healed = not continuation and grammar == HEALED_SPACE
        want = LOOKUP_K if healed else k
        shown = session.shown.get(key)
        if shown is None or len(shown) < want:
            result = await self._provider(session).next_tokens(
                session.prepared.request, continuation, want,
            )
            shown = self._named(session, result["candidates"])
            session.shown[key] = shown
            session.logit_bias = result["logit_bias"]
            session.effective_prompt = result["effective_prompt"]
        if healed:
            return starting_a_word(shown)[:k]
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
            tokens = await self._records(session, [], token_ids, chosen_by)

            # A reply that reaches the model's end of turn ends there, like any
            # generation: a stop token (chat templates) or a stop string the text
            # ends with (a transcript's next speaker line)
            stops = session.prepared.request.sampling_params.stop_sequences or []
            finish = "researcher"
            kept = len(tokens)
            if tokens and tokens[-1].token in stops:
                finish, kept = "stop", len(tokens) - 1
            content = await self._provider(session).detokenize(
                token_ids[:kept], session.prepared.model,
            )
            for stop in stops:
                if finish != "stop" and stop and content.endswith(stop):
                    finish, content = "stop", content[: -len(stop)]
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

    async def _records(
        self,
        session: SteeringSession,
        before: list[int],
        token_ids: list[int],
        chosen_by: list[Literal["model", "researcher"]],
    ) -> list[TokenLogprob]:
        """Each token's record: the model's probability for it where it was chosen
        (after `before` and the tokens ahead of it), its alternatives, who chose it."""
        tokens: list[TokenLogprob] = []
        for i, (tid, who) in enumerate(zip(token_ids, chosen_by, strict=True)):
            shown = await self._distribution(session, before + token_ids[:i], tid)
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
        return tokens

    async def branch_start(
        self,
        rhizome_id: str,
        node: NodeResponse,
        keep: int,
        token_ids: list[int],
        provider: LLMProvider,
    ) -> tuple[str, list[TokenLogprob]]:
        """The start of a new version of a reply: its first `keep` tokens (the
        model's, with their records), then tokens the researcher chose (each with
        the probability the model gave it there). Returns the text and records."""
        tokens = [TokenLogprob.model_validate(t) for t in (node.logprobs or {}).get("tokens") or []]
        if node.role != "assistant" or node.edited_content is not None:
            raise InvalidRequestError("Only an unedited reply can be branched from its tokens")
        if not 0 <= keep <= len(tokens):
            raise InvalidRequestError(f"Can keep between 0 and {len(tokens)} tokens")
        kept = tokens[:keep]
        text = "".join(t.token for t in kept)
        if not token_ids:
            return text, kept
        session = await self.start(
            rhizome_id, node.parent_id, provider, model=node.model,
        )
        try:
            state = self._session(session["session_id"])
            tokenize = getattr(provider, "tokenize")  # steerable providers have it
            before = [t["id"] for t in await tokenize(text, state.prepared.model)] if text else []
            chosen = await self._records(state, before, token_ids, ["researcher"] * len(token_ids))
        finally:
            self.discard(session["session_id"])
        return text + "".join(t.token for t in chosen), kept + chosen

    async def tokenize(self, session_id: str, text: str) -> list[dict[str, Any]]:
        """Typed text as the session model's tokens, to append as researcher choices."""
        session = self._session(session_id)
        return await self._provider(session).tokenize(text, session.prepared.model)

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
            shown = self._named(session, result["candidates"])
            session.shown[key] = shown
        return shown

    @staticmethod
    async def _special_text(provider: Any, prepared: Prepared) -> dict[int, str]:
        """Ids of the special tokens this conversation uses (its template's, and the
        stop sequences), so a distribution can name them: end of turn especially."""
        specials = set(re.findall(r"<\|[^|<>]+\|>", prepared.request.prompt_text or ""))
        specials |= set(prepared.request.sampling_params.stop_sequences or [])
        if not specials:
            return {}
        pieces = await provider.tokenize("".join(sorted(specials)), prepared.model)
        return {p["id"]: p["token"] for p in pieces if p["token"] in specials}

    @staticmethod
    def _named(session: SteeringSession, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {**c, "token": session.special_text.get(c["id"], c["token"])} if not c["token"] else c
            for c in candidates
        ]

    @staticmethod
    def _provider(session: SteeringSession) -> Any:
        return session.prepared.provider


def _log(p: float) -> float:
    # A probability that underflowed to 0 is recorded at the float floor, not -inf
    # (which JSON can't carry)
    return math.log(max(p, 1e-300))


def starting_a_word(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The candidates that begin with a space and then a word, their probabilities
    renormalized among themselves (conditional on starting a word). The record keeps
    the model's own probabilities: this is only what's shown."""
    allowed = [c for c in candidates if re.match(r" [^ \t\n]", c["token"])]
    total = sum(c["prob"] for c in allowed) or 1.0
    return [
        {**c, "prob": c["prob"] / total, "raw_prob": c["prob"], "conditional": True}
        for c in allowed
    ]
