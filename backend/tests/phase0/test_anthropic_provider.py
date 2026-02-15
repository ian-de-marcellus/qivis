"""Contract tests for AnthropicProvider with mocked AsyncAnthropic client."""

from unittest.mock import AsyncMock, MagicMock

from qivis.models import SamplingParams
from qivis.providers.anthropic import AnthropicProvider
from qivis.providers.base import GenerationRequest


def _make_mock_message(
    content_text: str = "Hello!",
    model: str = "claude-sonnet-4-5-20250929",
    stop_reason: str = "end_turn",
    input_tokens: int = 10,
    output_tokens: int = 5,
) -> MagicMock:
    """Create a mock Anthropic Message response."""
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = content_text

    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens

    message = MagicMock()
    message.content = [text_block]
    message.model = model
    message.stop_reason = stop_reason
    message.usage = usage
    message.model_dump.return_value = {
        "id": "msg_test",
        "content": [{"type": "text", "text": content_text}],
    }
    return message


def _make_request(
    messages: list[dict[str, str]] | None = None,
    system_prompt: str | None = None,
    model: str = "claude-sonnet-4-5-20250929",
    sampling_params: SamplingParams | None = None,
) -> GenerationRequest:
    return GenerationRequest(
        model=model,
        messages=messages or [{"role": "user", "content": "Hello"}],
        system_prompt=system_prompt,
        sampling_params=sampling_params or SamplingParams(temperature=0.7, max_tokens=1024),
    )


def _make_mock_client(message: MagicMock | None = None) -> AsyncMock:
    """Create a mock AsyncAnthropic client."""
    client = AsyncMock()
    client.messages.create = AsyncMock(return_value=message or _make_mock_message())
    return client


class TestAnthropicProviderName:
    async def test_name_returns_anthropic(self):
        provider = AnthropicProvider(_make_mock_client())
        assert provider.name == "anthropic"


class TestAnthropicGenerate:
    async def test_returns_correct_content(self):
        provider = AnthropicProvider(_make_mock_client(_make_mock_message("Hi there!")))
        result = await provider.generate(_make_request())
        assert result.content == "Hi there!"

    async def test_returns_usage(self):
        provider = AnthropicProvider(
            _make_mock_client(_make_mock_message(input_tokens=25, output_tokens=10))
        )
        result = await provider.generate(_make_request())
        assert result.usage == {"input_tokens": 25, "output_tokens": 10}

    async def test_returns_finish_reason(self):
        provider = AnthropicProvider(
            _make_mock_client(_make_mock_message(stop_reason="max_tokens"))
        )
        result = await provider.generate(_make_request())
        assert result.finish_reason == "max_tokens"

    async def test_returns_model(self):
        provider = AnthropicProvider(
            _make_mock_client(_make_mock_message(model="claude-opus-4-6"))
        )
        result = await provider.generate(_make_request())
        assert result.model == "claude-opus-4-6"

    async def test_measures_latency(self):
        provider = AnthropicProvider(_make_mock_client())
        result = await provider.generate(_make_request())
        assert result.latency_ms is not None
        assert result.latency_ms >= 0

    async def test_passes_system_prompt(self):
        client = _make_mock_client()
        provider = AnthropicProvider(client)
        await provider.generate(_make_request(system_prompt="Be helpful."))
        call_kwargs = client.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "Be helpful."

    async def test_omits_system_when_none(self):
        client = _make_mock_client()
        provider = AnthropicProvider(client)
        await provider.generate(_make_request(system_prompt=None))
        call_kwargs = client.messages.create.call_args.kwargs
        assert "system" not in call_kwargs

    async def test_passes_temperature(self):
        client = _make_mock_client()
        provider = AnthropicProvider(client)
        await provider.generate(
            _make_request(sampling_params=SamplingParams(temperature=0.5, max_tokens=512))
        )
        call_kwargs = client.messages.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.5

    async def test_omits_none_temperature(self):
        client = _make_mock_client()
        provider = AnthropicProvider(client)
        await provider.generate(
            _make_request(sampling_params=SamplingParams(temperature=None, max_tokens=512))
        )
        call_kwargs = client.messages.create.call_args.kwargs
        assert "temperature" not in call_kwargs


class TestAnthropicGenerateStream:
    async def test_yields_text_deltas(self):
        """generate_stream yields StreamChunks with text content."""
        # Create mock streaming events
        events = _make_mock_stream_events("Hello world!")
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=_async_iter(events))

        provider = AnthropicProvider(client)
        chunks = []
        async for chunk in provider.generate_stream(_make_request()):
            chunks.append(chunk)

        text_chunks = [c for c in chunks if c.type == "text_delta"]
        assert len(text_chunks) > 0
        assert all(c.text for c in text_chunks)

    async def test_final_chunk_has_accumulated_content(self):
        """The final StreamChunk carries the full accumulated content."""
        events = _make_mock_stream_events("Hello world!")
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=_async_iter(events))

        provider = AnthropicProvider(client)
        chunks = []
        async for chunk in provider.generate_stream(_make_request()):
            chunks.append(chunk)

        final = [c for c in chunks if c.is_final]
        assert len(final) == 1
        assert final[0].result is not None
        assert final[0].result.content == "Hello world!"

    async def test_final_chunk_has_usage(self):
        events = _make_mock_stream_events("Hi", input_tokens=20, output_tokens=8)
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=_async_iter(events))

        provider = AnthropicProvider(client)
        chunks = []
        async for chunk in provider.generate_stream(_make_request()):
            chunks.append(chunk)

        final = next(c for c in chunks if c.is_final)
        assert final.result is not None
        assert final.result.usage == {"input_tokens": 20, "output_tokens": 8}


# -- Helpers for streaming mocks --


def _make_mock_stream_events(
    text: str,
    model: str = "claude-sonnet-4-5-20250929",
    input_tokens: int = 10,
    output_tokens: int = 5,
) -> list[MagicMock]:
    """Create a sequence of mock RawMessageStreamEvent objects."""
    events = []

    # message_start
    msg_start = MagicMock()
    msg_start.type = "message_start"
    msg_start.message = MagicMock()
    msg_start.message.model = model
    msg_start.message.usage = MagicMock()
    msg_start.message.usage.input_tokens = input_tokens
    events.append(msg_start)

    # content_block_start
    block_start = MagicMock()
    block_start.type = "content_block_start"
    events.append(block_start)

    # content_block_delta (one per character for simplicity)
    delta = MagicMock()
    delta.type = "content_block_delta"
    delta.delta = MagicMock()
    delta.delta.text = text
    events.append(delta)

    # content_block_stop
    block_stop = MagicMock()
    block_stop.type = "content_block_stop"
    events.append(block_stop)

    # message_delta
    msg_delta = MagicMock()
    msg_delta.type = "message_delta"
    msg_delta.delta = MagicMock()
    msg_delta.delta.stop_reason = "end_turn"
    msg_delta.usage = MagicMock()
    msg_delta.usage.output_tokens = output_tokens
    events.append(msg_delta)

    return events


async def _async_iter(items: list) -> None:  # type: ignore[override]
    """Create an async iterator from a list. Used as mock stream."""
    for item in items:
        yield item  # type: ignore[misc]
