"""Ollama LLM provider — thin subclass of OpenAICompatibleProvider.

Ollama runs local models and exposes an OpenAI-compatible API at /v1.
This provider adds top_k support and model auto-discovery.
"""

from typing import Any

from openai import AsyncOpenAI

from qivis.providers.base import GenerationRequest
from qivis.providers.openai_compat import OpenAICompatibleProvider


class OllamaProvider(OpenAICompatibleProvider):
    """LLM provider backed by a local Ollama instance."""

    supported_params = [
        "temperature", "top_p", "top_k", "max_tokens", "stop_sequences",
        "frequency_penalty", "presence_penalty", "logprobs", "top_logprobs",
    ]

    def __init__(
        self,
        *,
        client: AsyncOpenAI | None = None,
        base_url: str = "http://localhost:11434",
    ) -> None:
        if client is not None:
            super().__init__(client)
        else:
            super().__init__(
                AsyncOpenAI(
                    api_key="ollama",
                    base_url=f"{base_url}/v1",
                )
            )

    @property
    def name(self) -> str:
        return "ollama"

    @staticmethod
    def _build_params(request: GenerationRequest) -> dict[str, Any]:
        params = OpenAICompatibleProvider._build_params(request)
        sp = request.sampling_params
        if sp.top_k is not None:
            params["top_k"] = sp.top_k
        return params
