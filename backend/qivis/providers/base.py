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


class GenerationResult(BaseModel):
    """Full response from a provider after generation completes."""

    content: str
    model: str
    finish_reason: str | None = None
    usage: dict[str, int] | None = None
    latency_ms: int | None = None
    logprobs: LogprobData | None = None
    raw_response: dict[str, Any] | None = None


class StreamChunk(BaseModel):
    """A single delta in a streaming response."""

    type: str  # "text_delta", "message_stop"
    text: str = ""
    is_final: bool = False
    result: GenerationResult | None = None


class LLMProvider(ABC):
    """Abstract interface for LLM providers."""

    suggested_models: list[str] = []

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
    def empty() -> LogprobData:
        """Return an empty LogprobData for providers that don't support logprobs."""
        return LogprobData(tokens=[], provider_format="none", top_k_available=0)
