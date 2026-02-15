"""Contract tests for OpenAIProvider with mocked AsyncOpenAI client."""

from unittest.mock import AsyncMock, MagicMock

from qivis.models import SamplingParams
from qivis.providers.base import GenerationRequest
from qivis.providers.openai import OpenAIProvider


def _make_mock_completion(
    content: str = "Hello!",
    model: str = "gpt-4o",
    finish_reason: str = "stop",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    logprobs_content: list | None = None,
) -> MagicMock:
    """Create a mock OpenAI ChatCompletion response."""
    choice = MagicMock()
    choice.message = MagicMock()
    choice.message.content = content
    choice.finish_reason = finish_reason

    if logprobs_content is not None:
        choice.logprobs = MagicMock()
        choice.logprobs.content = logprobs_content
    else:
        choice.logprobs = None

    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens

    completion = MagicMock()
    completion.choices = [choice]
    completion.model = model
    completion.usage = usage
    completion.model_dump.return_value = {
        "id": "chatcmpl-test",
        "choices": [{"message": {"content": content}}],
    }
    return completion


def _make_mock_stream_chunks(
    text: str = "Hello world!",
    model: str = "gpt-4o",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
) -> list[MagicMock]:
    """Create a sequence of mock streaming chunks."""
    chunks = []

    # First chunk with role
    chunk0 = MagicMock()
    chunk0.choices = [MagicMock()]
    chunk0.choices[0].delta = MagicMock()
    chunk0.choices[0].delta.content = None
    chunk0.choices[0].delta.role = "assistant"
    chunk0.choices[0].finish_reason = None
    chunk0.model = model
    chunk0.usage = None
    chunks.append(chunk0)

    # Content chunk
    chunk1 = MagicMock()
    chunk1.choices = [MagicMock()]
    chunk1.choices[0].delta = MagicMock()
    chunk1.choices[0].delta.content = text
    chunk1.choices[0].finish_reason = None
    chunk1.model = model
    chunk1.usage = None
    chunks.append(chunk1)

    # Final chunk with finish_reason
    chunk2 = MagicMock()
    chunk2.choices = [MagicMock()]
    chunk2.choices[0].delta = MagicMock()
    chunk2.choices[0].delta.content = None
    chunk2.choices[0].finish_reason = "stop"
    chunk2.model = model
    chunk2.usage = None
    chunks.append(chunk2)

    # Usage chunk (stream_options=include_usage)
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
    model: str = "gpt-4o",
    sampling_params: SamplingParams | None = None,
) -> GenerationRequest:
    return GenerationRequest(
        model=model,
        messages=messages or [{"role": "user", "content": "Hello"}],
        system_prompt=system_prompt,
        sampling_params=sampling_params or SamplingParams(temperature=0.7, max_tokens=1024),
    )


class TestOpenAIProviderName:
    async def test_name_returns_openai(self):
        provider = OpenAIProvider(client=_make_mock_client())
        assert provider.name == "openai"


class TestOpenAIGenerate:
    async def test_returns_correct_content(self):
        provider = OpenAIProvider(client=_make_mock_client(_make_mock_completion("Hi there!")))
        result = await provider.generate(_make_request())
        assert result.content == "Hi there!"

    async def test_returns_usage_with_canonical_keys(self):
        provider = OpenAIProvider(
            client=_make_mock_client(
                _make_mock_completion(prompt_tokens=25, completion_tokens=10)
            )
        )
        result = await provider.generate(_make_request())
        assert result.usage == {"input_tokens": 25, "output_tokens": 10}

    async def test_returns_finish_reason(self):
        provider = OpenAIProvider(
            client=_make_mock_client(_make_mock_completion(finish_reason="length"))
        )
        result = await provider.generate(_make_request())
        assert result.finish_reason == "length"

    async def test_returns_model(self):
        provider = OpenAIProvider(
            client=_make_mock_client(_make_mock_completion(model="gpt-4o-2024-05-13"))
        )
        result = await provider.generate(_make_request())
        assert result.model == "gpt-4o-2024-05-13"

    async def test_measures_latency(self):
        provider = OpenAIProvider(client=_make_mock_client())
        result = await provider.generate(_make_request())
        assert result.latency_ms is not None
        assert result.latency_ms >= 0

    async def test_system_prompt_prepended_as_message(self):
        client = _make_mock_client()
        provider = OpenAIProvider(client=client)
        await provider.generate(_make_request(system_prompt="Be helpful."))
        call_kwargs = client.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "Be helpful."

    async def test_no_system_message_when_none(self):
        client = _make_mock_client()
        provider = OpenAIProvider(client=client)
        await provider.generate(_make_request(system_prompt=None))
        call_kwargs = client.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]
        assert all(m["role"] != "system" for m in messages)

    async def test_passes_temperature(self):
        client = _make_mock_client()
        provider = OpenAIProvider(client=client)
        await provider.generate(
            _make_request(sampling_params=SamplingParams(temperature=0.5, max_tokens=512))
        )
        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.5

    async def test_passes_frequency_penalty(self):
        client = _make_mock_client()
        provider = OpenAIProvider(client=client)
        await provider.generate(
            _make_request(
                sampling_params=SamplingParams(frequency_penalty=0.8, max_tokens=512)
            )
        )
        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs["frequency_penalty"] == 0.8

    async def test_passes_presence_penalty(self):
        client = _make_mock_client()
        provider = OpenAIProvider(client=client)
        await provider.generate(
            _make_request(
                sampling_params=SamplingParams(presence_penalty=0.5, max_tokens=512)
            )
        )
        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs["presence_penalty"] == 0.5

    async def test_passes_stop_sequences(self):
        client = _make_mock_client()
        provider = OpenAIProvider(client=client)
        await provider.generate(
            _make_request(
                sampling_params=SamplingParams(stop_sequences=["END"], max_tokens=512)
            )
        )
        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs["stop"] == ["END"]

    async def test_top_k_not_passed(self):
        """top_k is silently ignored — OpenAI doesn't support it."""
        client = _make_mock_client()
        provider = OpenAIProvider(client=client)
        await provider.generate(
            _make_request(sampling_params=SamplingParams(top_k=40, max_tokens=512))
        )
        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert "top_k" not in call_kwargs

    async def test_extracts_logprobs(self):
        """Logprobs are extracted and normalized when present."""
        entry = MagicMock()
        entry.token = "Hello"
        entry.logprob = -0.5
        entry.top_logprobs = [MagicMock(token="Hello", logprob=-0.5)]

        completion = _make_mock_completion(logprobs_content=[entry])
        provider = OpenAIProvider(client=_make_mock_client(completion))
        result = await provider.generate(_make_request())
        assert result.logprobs is not None
        assert len(result.logprobs.tokens) == 1
        assert result.logprobs.tokens[0].token == "Hello"
        assert result.logprobs.provider_format == "openai"

    async def test_logprobs_none_when_not_returned(self):
        """When the API returns no logprobs, result.logprobs is None."""
        completion = _make_mock_completion(logprobs_content=None)
        provider = OpenAIProvider(client=_make_mock_client(completion))
        result = await provider.generate(_make_request())
        assert result.logprobs is None


class TestOpenAIGenerateStream:
    async def test_yields_text_deltas(self):
        chunks = _make_mock_stream_chunks("Hello world!")
        client = AsyncMock()
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=_async_iter(chunks))

        provider = OpenAIProvider(client=client)
        received = []
        async for chunk in provider.generate_stream(_make_request()):
            received.append(chunk)

        text_chunks = [c for c in received if c.type == "text_delta"]
        assert len(text_chunks) > 0
        assert all(c.text for c in text_chunks)

    async def test_final_chunk_has_accumulated_content(self):
        chunks = _make_mock_stream_chunks("Hello world!")
        client = AsyncMock()
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=_async_iter(chunks))

        provider = OpenAIProvider(client=client)
        received = []
        async for chunk in provider.generate_stream(_make_request()):
            received.append(chunk)

        final = [c for c in received if c.is_final]
        assert len(final) == 1
        assert final[0].result is not None
        assert final[0].result.content == "Hello world!"

    async def test_final_chunk_has_usage(self):
        chunks = _make_mock_stream_chunks("Hi", prompt_tokens=20, completion_tokens=8)
        client = AsyncMock()
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=_async_iter(chunks))

        provider = OpenAIProvider(client=client)
        received = []
        async for chunk in provider.generate_stream(_make_request()):
            received.append(chunk)

        final = next(c for c in received if c.is_final)
        assert final.result is not None
        assert final.result.usage == {"input_tokens": 20, "output_tokens": 8}


# -- Helpers --


async def _async_iter(items: list):  # type: ignore[override]
    for item in items:
        yield item  # type: ignore[misc]
