"""Abstract LLM provider interface and shared data types."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, Field

from qivis.models import LogprobData, SamplingParams


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
    def empty() -> LogprobData:
        """Return an empty LogprobData for providers that don't support logprobs."""
        return LogprobData(tokens=[], provider_format="none", top_k_available=0)
