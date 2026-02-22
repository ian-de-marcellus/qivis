"""Contract tests for OpenAI-compatible completion mode.

Tests that OpenAICompatibleProvider dispatches to the completions API
when request.prompt_text is set, and uses existing chat path otherwise.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from qivis.models import SamplingParams
from qivis.providers.base import GenerationRequest
from qivis.providers.openai_compat import OpenAICompatibleProvider
from qivis.providers.openai import OpenAIProvider
from qivis.providers.openrouter import OpenRouterProvider
from qivis.providers.generic_openai import GenericOpenAIProvider
from qivis.providers.ollama import OllamaProvider


# -- Helpers --


def _make_mock_completion_response(
    text: str = "Hello from completion!",
    model: str = "base-model",
    finish_reason: str = "stop",
    prompt_tokens: int = 50,
    completion_tokens: int = 10,
    logprobs: Any = None,
) -> MagicMock:
    """Mock response from client.completions.create() (non-streaming)."""
    choice = MagicMock()
    choice.text = text
    choice.finish_reason = finish_reason
    choice.logprobs = logprobs

    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens

    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    resp.model = model
    return resp


def _make_mock_chat_response(
    content: str = "Hello from chat!",
    model: str = "chat-model",
) -> MagicMock:
    """Mock response from client.chat.completions.create() (non-streaming)."""
    message = MagicMock()
    message.content = content

    choice = MagicMock()
    choice.message = message
    choice.finish_reason = "stop"
    choice.logprobs = None

    usage = MagicMock()
    usage.prompt_tokens = 30
    usage.completion_tokens = 5
    usage.completion_tokens_details = None

    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    resp.model = model
    resp.model_dump.return_value = {}
    return resp


def _make_mock_client(
    completion_response: MagicMock | None = None,
    chat_response: MagicMock | None = None,
) -> AsyncMock:
    """Build a mock AsyncOpenAI with completions.create and chat.completions.create."""
    client = AsyncMock()

    # completions.create (for completion mode)
    completions = AsyncMock()
    completions.create = AsyncMock(
        return_value=completion_response or _make_mock_completion_response()
    )
    client.completions = completions

    # chat.completions.create (for chat mode)
    chat_completions = AsyncMock()
    chat_completions.create = AsyncMock(
        return_value=chat_response or _make_mock_chat_response()
    )
    client.chat = MagicMock()
    client.chat.completions = chat_completions

    return client


def _make_chat_request() -> GenerationRequest:
    """Chat request — no prompt_text, dispatches to chat path."""
    return GenerationRequest(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Hi"}],
        sampling_params=SamplingParams(temperature=0.7, max_tokens=256),
    )


def _make_completion_request(
    prompt_text: str = "<|im_start|>user\nHi<|im_end|>\n<|im_start|>assistant\n",
    sampling_params: SamplingParams | None = None,
) -> GenerationRequest:
    """Completion request — prompt_text set, dispatches to completions path."""
    return GenerationRequest(
        model="base-model",
        messages=[],
        prompt_text=prompt_text,
        sampling_params=sampling_params or SamplingParams(temperature=0.7, max_tokens=256),
    )


class ConcreteProvider(OpenAICompatibleProvider):
    """Concrete subclass for testing the ABC."""

    @property
    def name(self) -> str:
        return "test"


# -- Tests --


class TestCompletionDispatch:
    async def test_dispatches_to_completions_when_prompt_text_set(self):
        client = _make_mock_client()
        provider = ConcreteProvider(client)
        result = await provider.generate(_make_completion_request())
        client.completions.create.assert_awaited_once()
        client.chat.completions.create.assert_not_awaited()
        assert result.content == "Hello from completion!"

    async def test_dispatches_to_chat_when_prompt_text_none(self):
        client = _make_mock_client()
        provider = ConcreteProvider(client)
        result = await provider.generate(_make_chat_request())
        client.chat.completions.create.assert_awaited_once()
        client.completions.create.assert_not_awaited()
        assert result.content == "Hello from chat!"


class TestCompletionGenerate:
    async def test_returns_content_from_choice_text(self):
        client = _make_mock_client(
            completion_response=_make_mock_completion_response(text="Generated text")
        )
        provider = ConcreteProvider(client)
        result = await provider.generate(_make_completion_request())
        assert result.content == "Generated text"

    async def test_returns_usage(self):
        client = _make_mock_client(
            completion_response=_make_mock_completion_response(
                prompt_tokens=100, completion_tokens=25
            )
        )
        provider = ConcreteProvider(client)
        result = await provider.generate(_make_completion_request())
        assert result.usage == {"input_tokens": 100, "output_tokens": 25}

    async def test_returns_finish_reason(self):
        client = _make_mock_client(
            completion_response=_make_mock_completion_response(finish_reason="length")
        )
        provider = ConcreteProvider(client)
        result = await provider.generate(_make_completion_request())
        assert result.finish_reason == "length"

    async def test_returns_model(self):
        client = _make_mock_client(
            completion_response=_make_mock_completion_response(model="meta-llama/llama-3.1-8b")
        )
        provider = ConcreteProvider(client)
        result = await provider.generate(_make_completion_request())
        assert result.model == "meta-llama/llama-3.1-8b"

    async def test_maps_completion_params(self):
        client = _make_mock_client()
        provider = ConcreteProvider(client)
        await provider.generate(
            _make_completion_request(
                sampling_params=SamplingParams(
                    temperature=0.5,
                    top_p=0.9,
                    max_tokens=512,
                    stop_sequences=["END"],
                    logprobs=True,
                    top_logprobs=5,
                )
            )
        )
        call_kwargs = client.completions.create.call_args.kwargs
        assert call_kwargs["prompt"] == "<|im_start|>user\nHi<|im_end|>\n<|im_start|>assistant\n"
        assert call_kwargs["max_tokens"] == 512
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["top_p"] == 0.9
        assert call_kwargs["stop"] == ["END"]
        assert call_kwargs["logprobs"] == 5

    async def test_extracts_logprobs_via_normalizer(self):
        """Completion logprobs use the different Completions API format."""

        class MockLogprobs:
            tokens = ["Hello"]
            token_logprobs = [-0.5]
            top_logprobs = [{"Hello": -0.5, "Hi": -1.0}]

        client = _make_mock_client(
            completion_response=_make_mock_completion_response(logprobs=MockLogprobs())
        )
        provider = ConcreteProvider(client)
        result = await provider.generate(_make_completion_request())
        assert result.logprobs is not None
        assert result.logprobs.provider_format == "openai"
        assert len(result.logprobs.tokens) == 1
        assert result.logprobs.tokens[0].token == "Hello"

    async def test_logprobs_none_when_not_present(self):
        client = _make_mock_client(
            completion_response=_make_mock_completion_response(logprobs=None)
        )
        provider = ConcreteProvider(client)
        result = await provider.generate(_make_completion_request())
        assert result.logprobs is None


class TestCompletionStream:
    async def test_yields_text_deltas_and_final(self):
        """Streaming completion yields text_delta chunks then a final message_stop."""
        # Build mock stream chunks
        chunk1 = MagicMock()
        chunk1.model = "base-model"
        choice1 = MagicMock()
        choice1.text = "Hello"
        choice1.finish_reason = None
        chunk1.choices = [choice1]
        chunk1.usage = None

        chunk2 = MagicMock()
        chunk2.model = "base-model"
        choice2 = MagicMock()
        choice2.text = " world"
        choice2.finish_reason = "stop"
        chunk2.choices = [choice2]
        chunk2.usage = None

        chunk3 = MagicMock()
        chunk3.model = "base-model"
        chunk3.choices = []
        usage = MagicMock()
        usage.prompt_tokens = 10
        usage.completion_tokens = 2
        chunk3.usage = usage

        class MockAsyncStream:
            """Mimics openai.AsyncStream — awaitable create() returns async iterable."""

            def __aiter__(self):
                return self._iter()

            async def _iter(self):
                for c in [chunk1, chunk2, chunk3]:
                    yield c

        client = _make_mock_client()
        client.completions.create = AsyncMock(return_value=MockAsyncStream())

        provider = ConcreteProvider(client)
        received = []
        async for chunk in provider.generate_stream(_make_completion_request()):
            received.append(chunk)

        text_chunks = [c for c in received if c.type == "text_delta"]
        assert len(text_chunks) == 2
        assert text_chunks[0].text == "Hello"
        assert text_chunks[1].text == " world"

        final = [c for c in received if c.is_final]
        assert len(final) == 1
        assert final[0].result is not None
        assert final[0].result.content == "Hello world"
        assert final[0].result.usage == {"input_tokens": 10, "output_tokens": 2}


class TestSupportedModes:
    def test_openai_supports_completion(self):
        provider = OpenAIProvider(client=AsyncMock())
        assert "completion" in provider.supported_modes
        assert "chat" in provider.supported_modes

    def test_openrouter_supports_completion(self):
        provider = OpenRouterProvider(client=AsyncMock())
        assert "completion" in provider.supported_modes
        assert "chat" in provider.supported_modes

    def test_generic_openai_supports_completion(self):
        provider = GenericOpenAIProvider(
            client=AsyncMock(), base_url="http://localhost:8000", provider_name="test"
        )
        assert "completion" in provider.supported_modes
        assert "chat" in provider.supported_modes

    def test_ollama_does_not_support_completion(self):
        provider = OllamaProvider(client=AsyncMock())
        assert "completion" not in provider.supported_modes
        assert provider.supported_modes == ["chat"]
