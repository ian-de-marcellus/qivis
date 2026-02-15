"""OpenRouter LLM provider — thin subclass of OpenAICompatibleProvider.

OpenRouter is an OpenAI-compatible API that routes to hundreds of models
(Llama, Mistral, Gemini, etc.) via a single API key.
"""

from openai import AsyncOpenAI

from qivis.providers.openai_compat import OpenAICompatibleProvider

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(OpenAICompatibleProvider):
    """LLM provider backed by OpenRouter's API."""

    suggested_models = [
        "anthropic/claude-opus-4-6",
        "anthropic/claude-sonnet-4-5",
        "openai/gpt-5.2",
        "openai/gpt-4o",
        "google/gemini-3-flash",
        "google/gemini-3-pro",
        "deepseek/deepseek-v3.2",
        "deepseek/deepseek-chat",
        "meta-llama/llama-4-maverick",
        "meta-llama/llama-4-scout",
        "qwen/qwen3-235b-a22b",
        "mistralai/mistral-large-3",
        "moonshotai/kimi-k2.5",
        "arcee-ai/trinity-large-preview",
    ]

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
