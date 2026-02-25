"""Contract tests for OpenRouter completion mode.

Tests the httpx-based completion path specific to OpenRouter,
including HTTP 200 error response handling and 429 retry logic.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from qivis.models import SamplingParams
from qivis.providers.base import GenerationRequest
from qivis.providers.openrouter import OpenRouterProvider


def _make_request(
    prompt_text: str = "Hello, world!",
    logprobs: bool = False,
    top_logprobs: int | None = None,
    max_tokens: int = 100,
) -> GenerationRequest:
    return GenerationRequest(
        model="meta-llama/llama-3.1-405b",
        messages=[],
        prompt_text=prompt_text,
        sampling_params=SamplingParams(
            max_tokens=max_tokens,
            logprobs=logprobs,
            top_logprobs=top_logprobs,
        ),
    )


def _mock_http_response(data: dict, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=data,
        request=httpx.Request("POST", "https://openrouter.ai/api/v1/completions"),
    )


def _success_response() -> httpx.Response:
    return _mock_http_response({
        "choices": [{"text": "Generated text", "finish_reason": "stop"}],
        "model": "meta-llama/llama-3.1-405b",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    })


def _429_response() -> httpx.Response:
    return httpx.Response(
        status_code=429,
        json={"error": "too many requests"},
        request=httpx.Request("POST", "https://openrouter.ai/api/v1/completions"),
    )


class TestOpenRouterCompletionErrorHandling:
    """OpenRouter sometimes returns errors with HTTP 200 status."""

    async def test_error_with_200_status_raises_runtime_error(self):
        """HTTP 200 with error body should raise RuntimeError, not KeyError."""
        error_data = {
            "error": {
                "message": "Upstream error from Hyperbolic: Cannot use chat template functions",
                "code": 500,
            }
        }
        http = AsyncMock(spec=httpx.AsyncClient)
        http.post = AsyncMock(return_value=_mock_http_response(error_data))

        provider = OpenRouterProvider(client=AsyncMock(), http_client=http)

        with pytest.raises(RuntimeError, match="Cannot use chat template"):
            await provider._generate_completion(_make_request())

    async def test_error_with_string_message(self):
        """Error body can be a plain string instead of a dict."""
        error_data = {"error": "Rate limit exceeded"}
        http = AsyncMock(spec=httpx.AsyncClient)
        http.post = AsyncMock(return_value=_mock_http_response(error_data))

        provider = OpenRouterProvider(client=AsyncMock(), http_client=http)

        with pytest.raises(RuntimeError, match="Rate limit exceeded"):
            await provider._generate_completion(_make_request())

    @patch("qivis.providers.openrouter.asyncio.sleep", new_callable=AsyncMock)
    async def test_actual_http_error_raises(self, mock_sleep):
        """Non-200 status codes raise with the error detail from the body after retries exhaust."""
        http = AsyncMock(spec=httpx.AsyncClient)
        http.post = AsyncMock(return_value=_429_response())

        provider = OpenRouterProvider(client=AsyncMock(), http_client=http)

        with pytest.raises(RuntimeError, match="429.*too many requests"):
            await provider._generate_completion(_make_request())

        # Verify retries happened (2 retries = 2 sleep calls)
        assert mock_sleep.call_count == 2
        assert http.post.call_count == 3  # initial + 2 retries


class TestOpenRouterCompletionSuccess:
    """Happy path for OpenRouter completion mode via httpx."""

    async def test_returns_content_from_choice_text(self):
        data = {
            "choices": [{"text": "Generated text", "finish_reason": "stop"}],
            "model": "meta-llama/llama-3.1-405b",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        http = AsyncMock(spec=httpx.AsyncClient)
        http.post = AsyncMock(return_value=_mock_http_response(data))

        provider = OpenRouterProvider(client=AsyncMock(), http_client=http)
        result = await provider._generate_completion(_make_request())

        assert result.content == "Generated text"
        assert result.model == "meta-llama/llama-3.1-405b"
        assert result.usage == {"input_tokens": 10, "output_tokens": 5}
        assert result.finish_reason == "stop"

    async def test_request_body_has_prompt_not_messages(self):
        """The httpx request should use `prompt`, not `messages`."""
        data = {
            "choices": [{"text": "ok", "finish_reason": "stop"}],
            "model": "test",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }
        http = AsyncMock(spec=httpx.AsyncClient)
        http.post = AsyncMock(return_value=_mock_http_response(data))

        provider = OpenRouterProvider(client=AsyncMock(), http_client=http)
        await provider._generate_completion(_make_request(prompt_text="Hello!"))

        call_kwargs = http.post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert "prompt" in body
        assert body["prompt"] == "Hello!"
        assert "messages" not in body


class TestOpenRouterRetry:
    """429 retry with exponential backoff for upstream cold-start."""

    @patch("qivis.providers.openrouter.asyncio.sleep", new_callable=AsyncMock)
    async def test_retry_succeeds_after_429(self, mock_sleep):
        """First request 429, second request succeeds."""
        http = AsyncMock(spec=httpx.AsyncClient)
        http.post = AsyncMock(side_effect=[_429_response(), _success_response()])

        provider = OpenRouterProvider(client=AsyncMock(), http_client=http)
        result = await provider._generate_completion(_make_request())

        assert result.content == "Generated text"
        assert http.post.call_count == 2
        assert mock_sleep.call_count == 1

    @patch("qivis.providers.openrouter.asyncio.sleep", new_callable=AsyncMock)
    async def test_retry_respects_retry_after_header(self, mock_sleep):
        """Retry-After header overrides default backoff."""
        resp_429 = httpx.Response(
            status_code=429,
            json={"error": "rate limited"},
            headers={"retry-after": "5"},
            request=httpx.Request("POST", "https://openrouter.ai/api/v1/completions"),
        )
        http = AsyncMock(spec=httpx.AsyncClient)
        http.post = AsyncMock(side_effect=[resp_429, _success_response()])

        provider = OpenRouterProvider(client=AsyncMock(), http_client=http)
        result = await provider._generate_completion(_make_request())

        assert result.content == "Generated text"
        mock_sleep.assert_called_once_with(5.0)

    @patch("qivis.providers.openrouter.asyncio.sleep", new_callable=AsyncMock)
    async def test_non_429_errors_not_retried(self, mock_sleep):
        """500 errors are not retried."""
        resp = httpx.Response(
            status_code=500,
            json={"error": "internal server error"},
            request=httpx.Request("POST", "https://openrouter.ai/api/v1/completions"),
        )
        http = AsyncMock(spec=httpx.AsyncClient)
        http.post = AsyncMock(return_value=resp)

        provider = OpenRouterProvider(client=AsyncMock(), http_client=http)

        with pytest.raises(RuntimeError, match="500"):
            await provider._generate_completion(_make_request())

        assert http.post.call_count == 1
        mock_sleep.assert_not_called()

    @patch("qivis.providers.openrouter.asyncio.sleep", new_callable=AsyncMock)
    async def test_stream_retry_succeeds_after_429(self, mock_sleep):
        """Streaming: first attempt 429, second succeeds."""
        success_chunk = json.dumps({
            "choices": [{"text": "streamed", "finish_reason": "stop"}],
            "model": "meta-llama/llama-3.1-405b",
            "usage": {"prompt_tokens": 10, "completion_tokens": 1},
        })

        call_count = 0

        class Mock429Response:
            status_code = 429
            headers = {}

            async def aread(self):
                return b'{"error": "rate limited"}'

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        class MockSuccessResponse:
            status_code = 200

            async def aiter_lines(self):
                yield f"data: {success_chunk}"
                yield "data: [DONE]"

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        responses = [Mock429Response(), MockSuccessResponse()]

        def make_stream(*args, **kwargs):
            nonlocal call_count
            resp = responses[call_count]
            call_count += 1
            return resp

        http = AsyncMock(spec=httpx.AsyncClient)
        http.stream = MagicMock(side_effect=make_stream)

        provider = OpenRouterProvider(client=AsyncMock(), http_client=http)
        chunks = []
        async for chunk in provider._generate_completion_stream(_make_request()):
            chunks.append(chunk)

        assert any(c.text == "streamed" for c in chunks)
        assert chunks[-1].is_final
        assert mock_sleep.call_count == 1


class TestOpenRouterCompletionBody:
    """Tests for _build_completion_body parameter mapping."""

    def test_basic_params(self):
        request = _make_request(prompt_text="test prompt", max_tokens=200)
        body = OpenRouterProvider._build_completion_body(request)
        assert body["prompt"] == "test prompt"
        assert body["max_tokens"] == 200
        assert body["model"] == "meta-llama/llama-3.1-405b"

    def test_logprobs_always_excluded(self):
        """OpenRouter completion never sends logprobs — upstream providers mishandle them."""
        request = _make_request(logprobs=True, top_logprobs=5)
        body = OpenRouterProvider._build_completion_body(request)
        assert "logprobs" not in body
        assert "top_logprobs" not in body

    def test_temperature_and_top_p(self):
        request = GenerationRequest(
            model="test",
            messages=[],
            prompt_text="test",
            sampling_params=SamplingParams(
                temperature=0.5,
                top_p=0.9,
                max_tokens=100,
                logprobs=False,
            ),
        )
        body = OpenRouterProvider._build_completion_body(request)
        assert body["temperature"] == 0.5
        assert body["top_p"] == 0.9

    def test_stop_sequences(self):
        request = GenerationRequest(
            model="test",
            messages=[],
            prompt_text="test",
            sampling_params=SamplingParams(
                stop_sequences=["<|im_end|>", "###"],
                max_tokens=100,
                logprobs=False,
            ),
        )
        body = OpenRouterProvider._build_completion_body(request)
        assert body["stop"] == ["<|im_end|>", "###"]


class TestOpenRouterStreamErrorHandling:
    """Streaming completion should also catch 200-status errors."""

    async def test_error_in_stream_chunk_raises(self):
        """Error chunk in SSE stream raises RuntimeError."""
        error_chunk = json.dumps({
            "error": {"message": "Upstream error from provider"}
        })

        # Build a mock async stream response
        class MockStreamResponse:
            status_code = 200

            def raise_for_status(self):
                pass

            async def aiter_lines(self):
                yield f"data: {error_chunk}"

            async def aclose(self):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        http = AsyncMock(spec=httpx.AsyncClient)
        http.stream = MagicMock(return_value=MockStreamResponse())

        provider = OpenRouterProvider(client=AsyncMock(), http_client=http)
        request = _make_request()

        with pytest.raises(RuntimeError, match="Upstream error"):
            async for _ in provider._generate_completion_stream(request):
                pass
