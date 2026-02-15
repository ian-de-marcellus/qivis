"""OpenRouter LLM provider — thin subclass of OpenAICompatibleProvider.

OpenRouter is an OpenAI-compatible API that routes to hundreds of models
(Llama, Mistral, Gemini, etc.) via a single API key.
"""

from openai import AsyncOpenAI

from qivis.providers.openai_compat import OpenAICompatibleProvider

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(OpenAICompatibleProvider):
    """LLM provider backed by OpenRouter's API."""

    def __init__(self, *, client: AsyncOpenAI | None = None, api_key: str | None = None) -> None:
        if client is not None:
            super().__init__(client)
        else:
            super().__init__(
                AsyncOpenAI(
                    api_key=api_key,
                    base_url=OPENROUTER_BASE_URL,
                    default_headers={
                        "HTTP-Referer": "https://github.com/qivis",
                        "X-Title": "Qivis",
                    },
                )
            )

    @property
    def name(self) -> str:
        return "openrouter"
