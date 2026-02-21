"""Contract tests for GenericOpenAIProvider with mocked AsyncOpenAI client."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from qivis.models import SamplingParams
from qivis.providers.base import GenerationRequest
from qivis.providers.generic_openai import GenericOpenAIProvider


# -- Helpers --


def _make_mock_completion(
    content: str = "Hello from local!",
    model: str = "my-model",
    finish_reason: str = "stop",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
) -> MagicMock:
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
    completion.model_dump.return_value = {"id": "test", "choices": [{"message": {"content": content}}]}
    return completion


def _make_mock_stream_chunks(
    text: str = "Hi there!",
    model: str = "my-model",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
) -> list[MagicMock]:
    chunks = []

    c0 = MagicMock()
    c0.choices = [MagicMock()]
    c0.choices[0].delta = MagicMock(content=None, role="assistant")
    c0.choices[0].finish_reason = None
    c0.choices[0].logprobs = None
    c0.model = model
    c0.usage = None
    chunks.append(c0)

    c1 = MagicMock()
    c1.choices = [MagicMock()]
    c1.choices[0].delta = MagicMock(content=text)
    c1.choices[0].finish_reason = None
    c1.choices[0].logprobs = None
    c1.model = model
    c1.usage = None
    chunks.append(c1)

    c2 = MagicMock()
    c2.choices = [MagicMock()]
    c2.choices[0].delta = MagicMock(content=None)
    c2.choices[0].finish_reason = "stop"
    c2.choices[0].logprobs = None
    c2.model = model
    c2.usage = None
    chunks.append(c2)

    c3 = MagicMock()
    c3.choices = []
    c3.model = model
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    c3.usage = usage
    chunks.append(c3)

    return chunks


def _make_mock_client(completion: MagicMock | None = None) -> AsyncMock:
    client = AsyncMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=completion or _make_mock_completion()
    )
    return client


def _make_request(
    model: str = "my-model",
    sampling_params: SamplingParams | None = None,
) -> GenerationRequest:
    return GenerationRequest(
        model=model,
        messages=[{"role": "user", "content": "Hello"}],
        sampling_params=sampling_params or SamplingParams(temperature=0.7, max_tokens=1024),
    )


async def _async_iter(items: list) -> Any:
    for item in items:
        yield item


# -- Tests --


class TestGenericOpenAIProviderIdentity:
    def test_name_returns_configured_name(self):
        provider = GenericOpenAIProvider(
            client=_make_mock_client(),
            base_url="http://localhost:5000/v1",
            provider_name="vllm-server",
        )
        assert provider.name == "vllm-server"

    def test_name_defaults_to_local(self):
        provider = GenericOpenAIProvider(
            client=_make_mock_client(),
            base_url="http://localhost:5000/v1",
        )
        assert provider.name == "local"

    def test_top_k_not_in_supported_params(self):
        """GenericOpenAI inherits standard OpenAI behavior — no top_k."""
        provider = GenericOpenAIProvider(
            client=_make_mock_client(),
            base_url="http://localhost:5000/v1",
        )
        assert "top_k" not in provider.supported_params


class TestGenericOpenAIGenerate:
    async def test_returns_correct_content(self):
        provider = GenericOpenAIProvider(
            client=_make_mock_client(_make_mock_completion("Generated text")),
            base_url="http://localhost:5000/v1",
        )
        result = await provider.generate(_make_request())
        assert result.content == "Generated text"

    async def test_top_k_not_passed_to_api(self):
        """top_k should not appear in API call params (standard OpenAI behavior)."""
        client = _make_mock_client()
        provider = GenericOpenAIProvider(
            client=client,
            base_url="http://localhost:5000/v1",
        )
        await provider.generate(
            _make_request(sampling_params=SamplingParams(top_k=40, max_tokens=512))
        )
        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert "top_k" not in call_kwargs


class TestGenericOpenAIGenerateStream:
    async def test_yields_text_deltas_and_final(self):
        chunks = _make_mock_stream_chunks("Streamed!")
        client = AsyncMock()
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=_async_iter(chunks))

        provider = GenericOpenAIProvider(
            client=client,
            base_url="http://localhost:5000/v1",
        )
        received = []
        async for chunk in provider.generate_stream(_make_request()):
            received.append(chunk)

        text_chunks = [c for c in received if c.type == "text_delta"]
        assert len(text_chunks) > 0

        final = [c for c in received if c.is_final]
        assert len(final) == 1
        assert final[0].result is not None
        assert final[0].result.content == "Streamed!"


class TestGenericOpenAIDiscoverModels:
    async def test_returns_sorted_model_list(self):
        client = _make_mock_client()
        model_a = MagicMock()
        model_a.id = "model-z"
        model_b = MagicMock()
        model_b.id = "model-a"

        response = MagicMock()
        response.data = [model_a, model_b]
        client.models = MagicMock()
        client.models.list = AsyncMock(return_value=response)

        provider = GenericOpenAIProvider(
            client=client,
            base_url="http://localhost:5000/v1",
        )
        models = await provider.discover_models()
        assert models == ["model-a", "model-z"]

    async def test_returns_empty_list_on_error(self):
        client = _make_mock_client()
        client.models = MagicMock()
        client.models.list = AsyncMock(side_effect=ConnectionError("Server down"))

        provider = GenericOpenAIProvider(
            client=client,
            base_url="http://localhost:5000/v1",
        )
        models = await provider.discover_models()
        assert models == []
