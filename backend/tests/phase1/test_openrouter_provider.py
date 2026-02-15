"""Contract tests for OpenRouterProvider — constructor config, headers, inherited behavior."""

from unittest.mock import AsyncMock, MagicMock

from qivis.models import SamplingParams
from qivis.providers.base import GenerationRequest
from qivis.providers.openrouter import OpenRouterProvider


def _make_mock_completion(
    content: str = "Hello!",
    model: str = "anthropic/claude-3.5-sonnet",
    finish_reason: str = "stop",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
) -> MagicMock:
    """Create a mock OpenAI ChatCompletion response."""
    choice = MagicMock()
    choice.message = MagicMock()
    choice.message.content = content
    choice.finish_reason = finish_reason
    choice.logprobs = None

    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens

    completion = MagicMock()
    completion.choices = [choice]
    completion.model = model
    completion.usage = usage
    completion.model_dump.return_value = {
        "id": "gen-test",
        "choices": [{"message": {"content": content}}],
    }
    return completion


def _make_mock_stream_chunks(
    text: str = "Hello!",
    model: str = "anthropic/claude-3.5-sonnet",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
) -> list[MagicMock]:
    """Create a sequence of mock streaming chunks."""
    chunks = []

    chunk0 = MagicMock()
    chunk0.choices = [MagicMock()]
    chunk0.choices[0].delta = MagicMock()
    chunk0.choices[0].delta.content = None
    chunk0.choices[0].delta.role = "assistant"
    chunk0.choices[0].finish_reason = None
    chunk0.model = model
    chunk0.usage = None
    chunks.append(chunk0)

    chunk1 = MagicMock()
    chunk1.choices = [MagicMock()]
    chunk1.choices[0].delta = MagicMock()
    chunk1.choices[0].delta.content = text
    chunk1.choices[0].finish_reason = None
    chunk1.model = model
    chunk1.usage = None
    chunks.append(chunk1)

    chunk2 = MagicMock()
    chunk2.choices = [MagicMock()]
    chunk2.choices[0].delta = MagicMock()
    chunk2.choices[0].delta.content = None
    chunk2.choices[0].finish_reason = "stop"
    chunk2.model = model
    chunk2.usage = None
    chunks.append(chunk2)

    chunk3 = MagicMock()
    chunk3.choices = []
    chunk3.model = model
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    chunk3.usage = usage
    chunks.append(chunk3)

    return chunks


def _make_mock_client(completion: MagicMock | None = None) -> AsyncMock:
    """Create a mock AsyncOpenAI client."""
    client = AsyncMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=completion or _make_mock_completion()
    )
    return client


def _make_request(
    messages: list[dict[str, str]] | None = None,
    system_prompt: str | None = None,
    model: str = "anthropic/claude-3.5-sonnet",
    sampling_params: SamplingParams | None = None,
) -> GenerationRequest:
    return GenerationRequest(
        model=model,
        messages=messages or [{"role": "user", "content": "Hello"}],
        system_prompt=system_prompt,
        sampling_params=sampling_params or SamplingParams(temperature=0.7, max_tokens=1024),
    )


class TestOpenRouterProviderName:
    async def test_name_returns_openrouter(self):
        provider = OpenRouterProvider(client=_make_mock_client())
        assert provider.name == "openrouter"


class TestOpenRouterGenerate:
    async def test_returns_correct_content(self):
        provider = OpenRouterProvider(
            client=_make_mock_client(_make_mock_completion("Routed response"))
        )
        result = await provider.generate(_make_request())
        assert result.content == "Routed response"

    async def test_returns_usage(self):
        provider = OpenRouterProvider(
            client=_make_mock_client(
                _make_mock_completion(prompt_tokens=30, completion_tokens=15)
            )
        )
        result = await provider.generate(_make_request())
        assert result.usage == {"input_tokens": 30, "output_tokens": 15}

    async def test_constructs_with_custom_base_url(self):
        """OpenRouterProvider should use OpenRouter's base URL."""
        provider = OpenRouterProvider(api_key="test-key")
        assert provider._client.base_url.host == "openrouter.ai"

    async def test_constructs_with_headers(self):
        """OpenRouterProvider should set HTTP-Referer and X-Title headers."""
        provider = OpenRouterProvider(api_key="test-key")
        headers = provider._client.default_headers
        assert "HTTP-Referer" in headers
        assert headers["X-Title"] == "Qivis"


class TestOpenRouterGenerateStream:
    async def test_yields_text_deltas(self):
        chunks = _make_mock_stream_chunks("Routed stream!")
        client = AsyncMock()
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=_async_iter(chunks))

        provider = OpenRouterProvider(client=client)
        received = []
        async for chunk in provider.generate_stream(_make_request()):
            received.append(chunk)

        text_chunks = [c for c in received if c.type == "text_delta"]
        assert len(text_chunks) > 0

    async def test_final_chunk_has_accumulated_content(self):
        chunks = _make_mock_stream_chunks("Routed stream!")
        client = AsyncMock()
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=_async_iter(chunks))

        provider = OpenRouterProvider(client=client)
        received = []
        async for chunk in provider.generate_stream(_make_request()):
            received.append(chunk)

        final = [c for c in received if c.is_final]
        assert len(final) == 1
        assert final[0].result is not None
        assert final[0].result.content == "Routed stream!"


# -- Helpers --


async def _async_iter(items: list):  # type: ignore[override]
    for item in items:
        yield item  # type: ignore[misc]
