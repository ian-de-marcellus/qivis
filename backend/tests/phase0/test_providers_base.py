"""Contract tests for provider ABC, data types, and LogprobNormalizer."""

from qivis.models import LogprobData, SamplingParams
from qivis.providers.base import (
    GenerationRequest,
    GenerationResult,
    LogprobNormalizer,
    StreamChunk,
)


class TestGenerationRequest:
    def test_serializes_with_defaults(self):
        req = GenerationRequest(
            model="claude-sonnet-4-5-20250929",
            messages=[{"role": "user", "content": "Hello"}],
        )
        assert req.model == "claude-sonnet-4-5-20250929"
        assert req.system_prompt is None
        assert req.sampling_params.max_tokens == 2048

    def test_serializes_with_all_fields(self):
        req = GenerationRequest(
            model="claude-sonnet-4-5-20250929",
            messages=[{"role": "user", "content": "Hello"}],
            system_prompt="Be helpful.",
            sampling_params=SamplingParams(temperature=0.7, max_tokens=1024),
        )
        assert req.system_prompt == "Be helpful."
        assert req.sampling_params.temperature == 0.7
        assert req.sampling_params.max_tokens == 1024


class TestGenerationResult:
    def test_serializes_all_fields(self):
        result = GenerationResult(
            content="Hello there!",
            model="claude-sonnet-4-5-20250929",
            finish_reason="end_turn",
            usage={"input_tokens": 10, "output_tokens": 5},
            latency_ms=42,
        )
        assert result.content == "Hello there!"
        assert result.model == "claude-sonnet-4-5-20250929"
        assert result.finish_reason == "end_turn"
        assert result.usage == {"input_tokens": 10, "output_tokens": 5}
        assert result.latency_ms == 42
        assert result.logprobs is None
        assert result.raw_response is None


class TestStreamChunk:
    def test_text_delta_chunk(self):
        chunk = StreamChunk(type="text_delta", text="Hello")
        assert chunk.type == "text_delta"
        assert chunk.text == "Hello"
        assert chunk.is_final is False
        assert chunk.result is None

    def test_final_chunk_with_result(self):
        result = GenerationResult(
            content="Hello there!",
            model="test-model",
            finish_reason="end_turn",
            usage={"input_tokens": 10, "output_tokens": 5},
            latency_ms=42,
        )
        chunk = StreamChunk(type="message_stop", is_final=True, result=result)
        assert chunk.is_final is True
        assert chunk.result is not None
        assert chunk.result.content == "Hello there!"


class TestLogprobNormalizer:
    def test_empty_returns_valid_logprob_data(self):
        data = LogprobNormalizer.empty()
        assert isinstance(data, LogprobData)
        assert data.tokens == []
        assert data.provider_format == "none"
        assert data.top_k_available == 0
        assert data.full_vocab_available is False

    def test_from_anthropic_returns_none(self):
        """Anthropic logprobs are not yet available; stub returns None."""
        result = LogprobNormalizer.from_anthropic(None)
        assert result is None
