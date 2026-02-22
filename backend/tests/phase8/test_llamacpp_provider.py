"""Contract tests for LlamaCppProvider with mocked httpx client."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from qivis.models import SamplingParams
from qivis.providers.base import GenerationRequest
from qivis.providers.llamacpp import LlamaCppProvider


# -- Helpers --


def _make_completion_response(
    content: str = "Hello!",
    model: str = "test-model.gguf",
    stop: bool = True,
    tokens_evaluated: int = 50,
    tokens_predicted: int = 10,
    completion_probabilities: list | None = None,
) -> dict:
    return {
        "content": content,
        "stop": stop,
        "model": model,
        "tokens_evaluated": tokens_evaluated,
        "tokens_predicted": tokens_predicted,
        "timings": {
            "predicted_ms": 200.0,
            "prompt_ms": 100.0,
        },
        "completion_probabilities": completion_probabilities,
    }


def _make_mock_response(data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


def _make_mock_client(response_data: dict | None = None) -> AsyncMock:
    client = AsyncMock()
    data = response_data or _make_completion_response()
    client.post = AsyncMock(return_value=_make_mock_response(data))
    return client


def _make_request(
    prompt_text: str = "<|im_start|>user\nHello<|im_end|>\n<|im_start|>assistant\n",
    model: str = "test-model.gguf",
    sampling_params: SamplingParams | None = None,
) -> GenerationRequest:
    return GenerationRequest(
        model=model,
        messages=[],
        prompt_text=prompt_text,
        sampling_params=sampling_params or SamplingParams(temperature=0.7, max_tokens=256),
    )


class MockStreamResponse:
    """Mock httpx streaming response context manager."""

    def __init__(self, lines: list[str]):
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    def raise_for_status(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


# -- Tests --


class TestLlamaCppProviderIdentity:
    def test_name_returns_llamacpp(self):
        provider = LlamaCppProvider(http_client=_make_mock_client())
        assert provider.name == "llamacpp"

    def test_supported_modes_is_completion(self):
        provider = LlamaCppProvider(http_client=_make_mock_client())
        assert provider.supported_modes == ["completion"]

    def test_supported_params_includes_top_k(self):
        provider = LlamaCppProvider(http_client=_make_mock_client())
        assert "top_k" in provider.supported_params
        assert "temperature" in provider.supported_params
        assert "max_tokens" in provider.supported_params


class TestLlamaCppRequestBuilding:
    async def test_maps_sampling_params(self):
        client = _make_mock_client()
        provider = LlamaCppProvider(http_client=client)
        await provider.generate(
            _make_request(
                sampling_params=SamplingParams(
                    temperature=0.5,
                    top_p=0.9,
                    top_k=40,
                    max_tokens=512,
                    stop_sequences=["END"],
                )
            )
        )
        call_kwargs = client.post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert body["temperature"] == 0.5
        assert body["top_p"] == 0.9
        assert body["top_k"] == 40
        assert body["n_predict"] == 512
        assert body["stop"] == ["END"]

    async def test_maps_logprobs_to_n_probs(self):
        client = _make_mock_client()
        provider = LlamaCppProvider(http_client=client)
        await provider.generate(
            _make_request(
                sampling_params=SamplingParams(
                    logprobs=True, top_logprobs=20, max_tokens=256
                )
            )
        )
        call_kwargs = client.post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert body["n_probs"] == 20

    async def test_always_sets_special_true(self):
        client = _make_mock_client()
        provider = LlamaCppProvider(http_client=client)
        await provider.generate(
            _make_request(prompt_text="<|im_start|>user\nHi<|im_end|>")
        )
        call_kwargs = client.post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert body["special"] is True

    async def test_logit_bias_present_for_llama3_template(self):
        client = _make_mock_client()
        provider = LlamaCppProvider(http_client=client)
        llama3_prompt = (
            "<|begin_of_text|>"
            "<|start_header_id|>user<|end_header_id|>\n\nHello<|eot_id|>"
            "<|start_header_id|>assistant<|end_header_id|>\n\n"
        )
        await provider.generate(_make_request(prompt_text=llama3_prompt))
        call_kwargs = client.post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert "logit_bias" in body
        bias = body["logit_bias"]
        # Should cover 128011-128255 (245 entries)
        assert len(bias) == 245
        assert bias[0] == [128011, -100.0]
        assert bias[-1] == [128255, -100.0]

    async def test_no_logit_bias_for_chatml_template(self):
        client = _make_mock_client()
        provider = LlamaCppProvider(http_client=client)
        chatml_prompt = "<|im_start|>user\nHello<|im_end|>\n<|im_start|>assistant\n"
        await provider.generate(_make_request(prompt_text=chatml_prompt))
        call_kwargs = client.post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert "logit_bias" not in body


class TestLlamaCppGenerate:
    async def test_returns_correct_content(self):
        provider = LlamaCppProvider(
            http_client=_make_mock_client(
                _make_completion_response(content="Hi from llama.cpp!")
            )
        )
        result = await provider.generate(_make_request())
        assert result.content == "Hi from llama.cpp!"

    async def test_returns_usage(self):
        provider = LlamaCppProvider(
            http_client=_make_mock_client(
                _make_completion_response(tokens_evaluated=100, tokens_predicted=25)
            )
        )
        result = await provider.generate(_make_request())
        assert result.usage == {"input_tokens": 100, "output_tokens": 25}

    async def test_returns_finish_reason_stop(self):
        provider = LlamaCppProvider(
            http_client=_make_mock_client(_make_completion_response(stop=True))
        )
        result = await provider.generate(_make_request())
        assert result.finish_reason == "stop"

    async def test_returns_finish_reason_length(self):
        provider = LlamaCppProvider(
            http_client=_make_mock_client(_make_completion_response(stop=False))
        )
        result = await provider.generate(_make_request())
        assert result.finish_reason == "length"

    async def test_extracts_logprobs(self):
        probs = [
            {
                "content": "Hi",
                "probs": [
                    {"tok_str": "Hi", "prob": 0.85},
                    {"tok_str": "Hello", "prob": 0.08},
                ],
            }
        ]
        provider = LlamaCppProvider(
            http_client=_make_mock_client(
                _make_completion_response(completion_probabilities=probs)
            )
        )
        result = await provider.generate(_make_request())
        assert result.logprobs is not None
        assert len(result.logprobs.tokens) == 1
        assert result.logprobs.tokens[0].token == "Hi"
        assert result.logprobs.provider_format == "llamacpp"

    async def test_logprobs_none_without_probabilities(self):
        provider = LlamaCppProvider(
            http_client=_make_mock_client(
                _make_completion_response(completion_probabilities=None)
            )
        )
        result = await provider.generate(_make_request())
        assert result.logprobs is None


class TestLlamaCppGenerateStream:
    async def test_yields_text_deltas_and_final(self):
        lines = [
            f'data: {json.dumps({"content": "Hello", "stop": False})}',
            f'data: {json.dumps({"content": " world", "stop": False})}',
            f'data: {json.dumps({"content": "", "stop": True, "model": "test.gguf", "tokens_evaluated": 10, "tokens_predicted": 2})}',
        ]
        client = AsyncMock()
        client.stream = MagicMock(return_value=MockStreamResponse(lines))

        provider = LlamaCppProvider(http_client=client)
        received = []
        async for chunk in provider.generate_stream(_make_request()):
            received.append(chunk)

        text_chunks = [c for c in received if c.type == "text_delta"]
        assert len(text_chunks) == 2
        assert text_chunks[0].text == "Hello"
        assert text_chunks[1].text == " world"

        final = [c for c in received if c.is_final]
        assert len(final) == 1
        assert final[0].result is not None
        assert final[0].result.content == "Hello world"


class TestTurnBoundaryDetection:
    """Test the _truncate_at_boundary method against known output patterns."""

    def test_cyrillic_garbage(self):
        # Screenshot 1: Cyrillic bytes from <|eot_id|><|start_header_id|>
        text = "Hey! What's going on?\u0438\u043b\u0430\u0441\u044fuser\u040e\u044b\u0446N Not much"
        result = LlamaCppProvider._truncate_at_boundary(text, is_llama3=True)
        assert result == "Hey! What's going on?"

    def test_semicolon_garbage(self):
        # Screenshot 2: semicolons
        text = "Hey! What's up?; user\n\nNot much."
        result = LlamaCppProvider._truncate_at_boundary(text, is_llama3=True)
        assert result == "Hey! What's up?"

    def test_identifier_garbage(self):
        # Screenshot 3: "TokenNameIdentifier"
        text = "Hi there! What's up? TokenNameIdentifieruser\u25c6 Not much."
        result = LlamaCppProvider._truncate_at_boundary(text, is_llama3=True)
        assert result == "Hi there! What's up?"

    def test_no_space_before_user(self):
        # From curl output: no space at all
        text = "Hi! What's up?user\n\nI'm writing a story"
        result = LlamaCppProvider._truncate_at_boundary(text, is_llama3=True)
        assert result == "Hi! What's up?"

    def test_assistant_boundary(self):
        text = "Sure thing!\u0438\u043b\u0430assistant\u044b\u0446"
        result = LlamaCppProvider._truncate_at_boundary(text, is_llama3=True)
        assert result == "Sure thing!"

    def test_normal_text_not_truncated(self):
        # "the user" in normal prose should NOT trigger
        text = "I told the user about the new feature. They liked it."
        result = LlamaCppProvider._truncate_at_boundary(text, is_llama3=True)
        assert result == text

    def test_normal_assistant_not_truncated(self):
        text = "She works as an assistant at the law firm."
        result = LlamaCppProvider._truncate_at_boundary(text, is_llama3=True)
        assert result == text

    def test_short_text_not_checked(self):
        # Too short to check (< 10 chars)
        text = "Hi user!"
        result = LlamaCppProvider._truncate_at_boundary(text, is_llama3=True)
        assert result == text

    def test_not_llama3_passthrough(self):
        text = "Hey! What's up?user\n\n"
        result = LlamaCppProvider._truncate_at_boundary(text, is_llama3=False)
        assert result == text


class TestLlamaCppExtraStops:
    async def test_probe_adds_byte_form_when_different(self):
        """When /detokenize returns bytes different from text form, add as extra stop."""
        client = AsyncMock()

        # /props response for discover_models
        props_resp = _make_mock_response({"model_alias": "test.gguf"})
        client.get = AsyncMock(return_value=props_resp)

        # /detokenize returns Cyrillic bytes instead of <|eot_id|>
        detok_responses = {
            128009: "\u0438\u043b\u0430\u0441\u044f",  # garbled bytes
            128006: "\u0414\u044b\u0446",                # garbled bytes
            128007: "\u0423\u044b\u0446",                # garbled bytes
        }
        call_count = 0

        async def mock_post(url, **kwargs):
            nonlocal call_count
            if "/detokenize" in url:
                tokens = kwargs.get("json", {}).get("tokens", [])
                if tokens:
                    content = detok_responses.get(tokens[0], "")
                    return _make_mock_response({"content": content})
            call_count += 1
            return _make_mock_response(_make_completion_response())

        client.post = AsyncMock(side_effect=mock_post)

        provider = LlamaCppProvider(http_client=client)
        models = await provider.discover_models()

        assert models == ["test.gguf"]
        # All 3 garbled byte forms should be extra stops
        assert len(provider._extra_stops) == 3

    async def test_extra_stops_merged_into_request(self):
        """Extra stops from probe get included in the request body."""
        client = _make_mock_client()
        provider = LlamaCppProvider(http_client=client)
        # Simulate probed byte form
        provider._extra_stops = ["\u0438\u043b\u0430"]

        await provider.generate(
            _make_request(
                sampling_params=SamplingParams(
                    max_tokens=256, stop_sequences=["<|eot_id|>"]
                )
            )
        )
        call_kwargs = client.post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert "<|eot_id|>" in body["stop"]
        assert "\u0438\u043b\u0430" in body["stop"]

    async def test_probe_ignores_matching_text_form(self):
        """When /detokenize returns the expected text, don't add as extra stop."""
        client = AsyncMock()
        props_resp = _make_mock_response({"model_alias": "test.gguf"})
        client.get = AsyncMock(return_value=props_resp)

        # /detokenize returns the normal text form (server decodes with special=true)
        async def mock_post(url, **kwargs):
            if "/detokenize" in url:
                tokens = kwargs.get("json", {}).get("tokens", [])
                # Return the expected text forms
                mapping = {128009: "<|eot_id|>", 128006: "<|start_header_id|>", 128007: "<|end_header_id|>"}
                content = mapping.get(tokens[0], "") if tokens else ""
                return _make_mock_response({"content": content})
            return _make_mock_response(_make_completion_response())

        client.post = AsyncMock(side_effect=mock_post)

        provider = LlamaCppProvider(http_client=client)
        await provider.discover_models()

        # No extra stops needed — text forms match
        assert provider._extra_stops == []


class TestLlamaCppDiscoverModels:
    async def test_returns_model_from_props(self):
        client = AsyncMock()
        resp = _make_mock_response(
            {"default_generation_settings": {"model": "llama-3-8b.gguf"}}
        )
        client.get = AsyncMock(return_value=resp)
        provider = LlamaCppProvider(http_client=client)
        models = await provider.discover_models()
        assert models == ["llama-3-8b.gguf"]

    async def test_returns_empty_on_error(self):
        client = AsyncMock()
        client.get = AsyncMock(side_effect=ConnectionError("not running"))
        provider = LlamaCppProvider(http_client=client)
        models = await provider.discover_models()
        assert models == []
