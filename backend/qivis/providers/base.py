"""Abstract LLM provider interface and shared data types."""

import math
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, Field

from qivis.models import AlternativeToken, LogprobData, SamplingParams, TokenLogprob


class GenerationRequest(BaseModel):
    """Everything a provider needs to make an API call."""

    model: str
    messages: list[dict[str, str]]
    system_prompt: str | None = None
    sampling_params: SamplingParams = Field(default_factory=SamplingParams)
    prompt_text: str | None = None  # Set for completion mode (replaces messages)


class GenerationResult(BaseModel):
    """Full response from a provider after generation completes."""

    content: str
    model: str
    finish_reason: str | None = None
    usage: dict[str, int] | None = None
    latency_ms: int | None = None
    logprobs: LogprobData | None = None
    thinking_content: str | None = None
    raw_response: dict[str, Any] | None = None


class StreamChunk(BaseModel):
    """A single delta in a streaming response."""

    type: str  # "text_delta", "thinking_delta", "message_stop", "generation_complete"
    text: str = ""
    thinking: str = ""
    is_final: bool = False
    result: GenerationResult | None = None
    completion_index: int | None = None


class LLMProvider(ABC):
    """Abstract interface for LLM providers."""

    suggested_models: list[str] = []
    supported_params: list[str] = []
    supported_modes: list[str] = ["chat"]

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g., 'anthropic')."""
        ...

    @abstractmethod
    async def generate(self, request: GenerationRequest) -> GenerationResult:
        """Send a non-streaming generation request. Returns the full result."""
        ...

    @abstractmethod
    def generate_stream(
        self, request: GenerationRequest
    ) -> AsyncIterator[StreamChunk]:
        """Send a streaming generation request. Yields chunks."""
        ...


class LogprobNormalizer:
    """Normalize logprob data from various provider formats to canonical LogprobData."""

    @staticmethod
    def from_anthropic(raw: Any) -> LogprobData | None:
        """Convert Anthropic logprob data to canonical format.

        Stub — Anthropic does not yet expose logprobs in the Messages API.
        Returns None. Plumbing is here for when support arrives.
        """
        return None

    @staticmethod
    def from_openai(logprobs_content: Any) -> LogprobData | None:
        """Convert OpenAI logprob data to canonical format.

        Expects the `logprobs.content` list from an OpenAI ChatCompletion response.
        Each entry has token, logprob, and top_logprobs[]. OpenAI returns natural
        log (base e), which matches our canonical format — no conversion needed.

        Returns None if input is None or empty.
        """
        if not logprobs_content:
            return None

        tokens: list[TokenLogprob] = []
        max_alts = 0

        for entry in logprobs_content:
            logprob = entry.logprob
            linear_prob = math.exp(logprob)

            alternatives: list[AlternativeToken] = []
            top_logprobs = getattr(entry, "top_logprobs", None) or []
            for alt in top_logprobs:
                if alt.token != entry.token:
                    alternatives.append(
                        AlternativeToken(
                            token=alt.token,
                            logprob=alt.logprob,
                            linear_prob=math.exp(alt.logprob),
                        )
                    )
            max_alts = max(max_alts, len(top_logprobs))

            tokens.append(
                TokenLogprob(
                    token=entry.token,
                    logprob=logprob,
                    linear_prob=linear_prob,
                    top_alternatives=alternatives,
                )
            )

        return LogprobData(
            tokens=tokens,
            provider_format="openai",
            top_k_available=max_alts,
        )

    @staticmethod
    def from_llamacpp(completion_probabilities: Any) -> LogprobData | None:
        """Convert llama.cpp completion_probabilities to canonical format.

        Supports two formats:
        - Legacy: {content, probs: [{tok_str, prob}, ...]} per token
        - Modern (build 8460+): {token, logprob, top_logprobs: [{token, logprob}, ...]}
        """
        if not completion_probabilities:
            return None

        tokens: list[TokenLogprob] = []
        max_alts = 0

        for entry in completion_probabilities:
            # Modern format (build 8460+): top_logprobs with logprob values
            if "top_logprobs" in entry:
                chosen_logprob = entry.get("logprob", 0.0)
                chosen_prob = math.exp(chosen_logprob) if chosen_logprob > -30 else 0.0
                chosen_token = entry.get("token", "")

                alternatives: list[AlternativeToken] = []
                for p in entry["top_logprobs"][1:]:  # Skip first (chosen token)
                    lp = p.get("logprob", float("-inf"))
                    prob = math.exp(lp) if lp > -30 else 0.0
                    alternatives.append(
                        AlternativeToken(
                            token=p.get("token", ""),
                            logprob=lp,
                            linear_prob=prob,
                        )
                    )

                max_alts = max(max_alts, len(entry["top_logprobs"]))
                tokens.append(
                    TokenLogprob(
                        token=chosen_token,
                        logprob=chosen_logprob,
                        linear_prob=chosen_prob,
                        top_alternatives=alternatives,
                    )
                )
                continue

            # Legacy format: probs with tok_str and prob (linear)
            all_probs = entry.get("probs", [])
            if not all_probs:
                continue

            chosen = all_probs[0]
            chosen_prob = chosen["prob"]
            chosen_logprob = math.log(chosen_prob) if chosen_prob > 0 else float("-inf")

            alternatives = []
            for p in all_probs[1:]:
                prob = p["prob"]
                alternatives.append(
                    AlternativeToken(
                        token=p["tok_str"],
                        logprob=math.log(prob) if prob > 0 else float("-inf"),
                        linear_prob=prob,
                    )
                )

            max_alts = max(max_alts, len(all_probs))

            tokens.append(
                TokenLogprob(
                    token=chosen["tok_str"],
                    logprob=chosen_logprob,
                    linear_prob=chosen_prob,
                    top_alternatives=alternatives,
                )
            )

        return LogprobData(
            tokens=tokens,
            provider_format="llamacpp",
            top_k_available=max_alts,
            full_vocab_available=max_alts > 100,
        )

    @staticmethod
    def from_openai_completion(logprobs: Any) -> LogprobData | None:
        """Convert OpenAI text completions logprobs to canonical format.

        Completions API returns a different structure from chat completions:
        logprobs.tokens (list[str]), logprobs.token_logprobs (list[float]),
        logprobs.top_logprobs (list[dict[str, float]]).
        """
        if logprobs is None:
            return None

        token_list = getattr(logprobs, "tokens", None)
        logprob_list = getattr(logprobs, "token_logprobs", None)
        top_list = getattr(logprobs, "top_logprobs", None)

        if not token_list or not logprob_list:
            return None

        tokens: list[TokenLogprob] = []
        max_alts = 0

        for i, token_str in enumerate(token_list):
            lp = logprob_list[i]
            if lp is None:
                continue
            linear_prob = math.exp(lp)

            alternatives: list[AlternativeToken] = []
            if top_list and i < len(top_list) and top_list[i]:
                top_dict = top_list[i]
                max_alts = max(max_alts, len(top_dict))
                for alt_token, alt_lp in top_dict.items():
                    if alt_token != token_str:
                        alternatives.append(
                            AlternativeToken(
                                token=alt_token,
                                logprob=alt_lp,
                                linear_prob=math.exp(alt_lp),
                            )
                        )

            tokens.append(
                TokenLogprob(
                    token=token_str,
                    logprob=lp,
                    linear_prob=linear_prob,
                    top_alternatives=alternatives,
                )
            )

        return LogprobData(
            tokens=tokens,
            provider_format="openai",
            top_k_available=max_alts,
        )

    @staticmethod
    def empty() -> LogprobData:
        """Return an empty LogprobData for providers that don't support logprobs."""
        return LogprobData(tokens=[], provider_format="none", top_k_available=0)
