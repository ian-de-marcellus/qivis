"""Contract tests for OllamaProvider with mocked AsyncOpenAI client."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from qivis.models import SamplingParams
from qivis.providers.base import GenerationRequest
from qivis.providers.ollama import OllamaProvider


# -- Helpers (same pattern as test_openai_provider.py) --


def _make_mock_completion(
    content: str = "Hello from Ollama!",
    model: str = "llama3.2:latest",
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
    text: str = "Hello world!",
    model: str = "llama3.2:latest",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
) -> list[MagicMock]:
    chunks = []

    # Role chunk
    c0 = MagicMock()
    c0.choices = [MagicMock()]
    c0.choices[0].delta = MagicMock(content=None, role="assistant")
    c0.choices[0].finish_reason = None
    c0.choices[0].logprobs = None
    c0.model = model
    c0.usage = None
    chunks.append(c0)

    # Content chunk
    c1 = MagicMock()
    c1.choices = [MagicMock()]
    c1.choices[0].delta = MagicMock(content=text)
    c1.choices[0].finish_reason = None
    c1.choices[0].logprobs = None
    c1.model = model
    c1.usage = None
    chunks.append(c1)

    # Finish chunk
    c2 = MagicMock()
    c2.choices = [MagicMock()]
    c2.choices[0].delta = MagicMock(content=None)
    c2.choices[0].finish_reason = "stop"
    c2.choices[0].logprobs = None
    c2.model = model
    c2.usage = None
    chunks.append(c2)

    # Usage chunk
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
    model: str = "llama3.2:latest",
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


class TestOllamaProviderIdentity:
    def test_name_returns_ollama(self):
        provider = OllamaProvider(client=_make_mock_client())
        assert provider.name == "ollama"

    def test_supported_params_includes_top_k(self):
        provider = OllamaProvider(client=_make_mock_client())
        assert "top_k" in provider.supported_params

    def test_supported_params_includes_standard_params(self):
        provider = OllamaProvider(client=_make_mock_client())
        for param in ["temperature", "top_p", "max_tokens", "frequency_penalty", "presence_penalty"]:
            assert param in provider.supported_params


class TestOllamaParamBuilding:
    async def test_passes_top_k_when_set(self):
        client = _make_mock_client()
        provider = OllamaProvider(client=client)
        await provider.generate(
            _make_request(sampling_params=SamplingParams(top_k=40, max_tokens=512))
        )
        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs.get("top_k") == 40

    async def test_omits_top_k_when_not_set(self):
        client = _make_mock_client()
        provider = OllamaProvider(client=client)
        await provider.generate(_make_request())
        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert "top_k" not in call_kwargs

    async def test_passes_temperature(self):
        client = _make_mock_client()
        provider = OllamaProvider(client=client)
        await provider.generate(
            _make_request(sampling_params=SamplingParams(temperature=0.5, max_tokens=512))
        )
        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.5


class TestOllamaGenerate:
    async def test_returns_correct_content(self):
        provider = OllamaProvider(
            client=_make_mock_client(_make_mock_completion("Hi from llama!"))
        )
        result = await provider.generate(_make_request())
        assert result.content == "Hi from llama!"

    async def test_returns_usage(self):
        provider = OllamaProvider(
            client=_make_mock_client(
                _make_mock_completion(prompt_tokens=20, completion_tokens=8)
            )
        )
        result = await provider.generate(_make_request())
        assert result.usage == {"input_tokens": 20, "output_tokens": 8}


class TestOllamaGenerateStream:
    async def test_yields_text_deltas_and_final(self):
        chunks = _make_mock_stream_chunks("Hello!")
        client = AsyncMock()
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=_async_iter(chunks))

        provider = OllamaProvider(client=client)
        received = []
        async for chunk in provider.generate_stream(_make_request()):
            received.append(chunk)

        text_chunks = [c for c in received if c.type == "text_delta"]
        assert len(text_chunks) > 0

        final = [c for c in received if c.is_final]
        assert len(final) == 1
        assert final[0].result is not None
        assert final[0].result.content == "Hello!"


class TestOllamaDiscoverModels:
    async def test_returns_sorted_model_list(self):
        client = _make_mock_client()
        # Mock client.models.list() to return model objects
        model_a = MagicMock()
        model_a.id = "mistral:latest"
        model_b = MagicMock()
        model_b.id = "llama3.2:latest"
        model_c = MagicMock()
        model_c.id = "codellama:13b"

        response = MagicMock()
        response.data = [model_a, model_b, model_c]
        client.models = MagicMock()
        client.models.list = AsyncMock(return_value=response)

        provider = OllamaProvider(client=client)
        models = await provider.discover_models()
        assert models == ["codellama:13b", "llama3.2:latest", "mistral:latest"]

    async def test_returns_empty_list_on_error(self):
        client = _make_mock_client()
        client.models = MagicMock()
        client.models.list = AsyncMock(side_effect=ConnectionError("Ollama not running"))

        provider = OllamaProvider(client=client)
        models = await provider.discover_models()
        assert models == []
