"""Generic OpenAI-compatible LLM provider.

Connects to any server that speaks the OpenAI chat completions protocol:
vLLM, text-generation-webui, LocalAI, etc.
"""

from openai import AsyncOpenAI

from qivis.providers.openai_compat import OpenAICompatibleProvider


class GenericOpenAIProvider(OpenAICompatibleProvider):
    """LLM provider for any OpenAI-compatible API server."""

    def __init__(
        self,
        *,
        client: AsyncOpenAI | None = None,
        base_url: str,
        api_key: str = "",
        provider_name: str = "local",
    ) -> None:
        self._provider_name = provider_name
        if client is not None:
            super().__init__(client)
        else:
            super().__init__(
                AsyncOpenAI(
                    api_key=api_key or "not-needed",
                    base_url=base_url,
                )
            )

    @property
    def name(self) -> str:
        return self._provider_name
