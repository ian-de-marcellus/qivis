"""OpenAI LLM provider — thin subclass of OpenAICompatibleProvider."""

from openai import AsyncOpenAI

from qivis.providers.openai_compat import OpenAICompatibleProvider


class OpenAIProvider(OpenAICompatibleProvider):
    """LLM provider backed by OpenAI's Chat Completions API."""

    suggested_models = [
        "gpt-5.2",
        "gpt-5.2-pro",
        "gpt-5-mini",
        "gpt-4o",
        "gpt-4o-mini",
        "o4-mini",
    ]

    def __init__(self, *, client: AsyncOpenAI | None = None, api_key: str | None = None) -> None:
        if client is not None:
            super().__init__(client)
        else:
            super().__init__(AsyncOpenAI(api_key=api_key))

    @property
    def name(self) -> str:
        return "openai"
