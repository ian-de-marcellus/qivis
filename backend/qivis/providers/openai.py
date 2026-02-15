"""OpenAI LLM provider — thin subclass of OpenAICompatibleProvider."""

from openai import AsyncOpenAI

from qivis.providers.openai_compat import OpenAICompatibleProvider


class OpenAIProvider(OpenAICompatibleProvider):
    """LLM provider backed by OpenAI's Chat Completions API."""

    def __init__(self, *, client: AsyncOpenAI | None = None, api_key: str | None = None) -> None:
        if client is not None:
            super().__init__(client)
        else:
            super().__init__(AsyncOpenAI(api_key=api_key))

    @property
    def name(self) -> str:
        return "openai"
