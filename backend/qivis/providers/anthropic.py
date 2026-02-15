"""Anthropic (Claude) LLM provider implementation."""

import time
from collections.abc import AsyncIterator
from typing import Any

from anthropic import AsyncAnthropic

from qivis.providers.base import (
    GenerationRequest,
    GenerationResult,
    LLMProvider,
    LogprobNormalizer,
    StreamChunk,
)


class AnthropicProvider(LLMProvider):
    """LLM provider backed by Anthropic's Messages API."""

    def __init__(self, client: AsyncAnthropic) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "anthropic"

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        params = self._build_params(request)
        start = time.monotonic()
        response = await self._client.messages.create(**params)
        latency_ms = int((time.monotonic() - start) * 1000)

        content = self._extract_text(response)
        return GenerationResult(
            content=content,
            model=response.model,
            finish_reason=response.stop_reason,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
            latency_ms=latency_ms,
            logprobs=LogprobNormalizer.from_anthropic(None),
            raw_response=response.model_dump(),
        )

    async def generate_stream(
        self, request: GenerationRequest
    ) -> AsyncIterator[StreamChunk]:
        params = self._build_params(request)
        start = time.monotonic()
        accumulated_text = ""
        input_tokens = 0
        output_tokens = 0
        stop_reason: str | None = None
        model = request.model

        stream = await self._client.messages.create(**params, stream=True)
        async for event in stream:
            if event.type == "message_start":
                model = event.message.model
                input_tokens = event.message.usage.input_tokens
            elif event.type == "content_block_delta":
                text = getattr(event.delta, "text", None)
                if text is not None:
                    accumulated_text += text
                    yield StreamChunk(type="text_delta", text=text)
            elif event.type == "message_delta":
                stop_reason = event.delta.stop_reason
                output_tokens = event.usage.output_tokens

        latency_ms = int((time.monotonic() - start) * 1000)
        yield StreamChunk(
            type="message_stop",
            is_final=True,
            result=GenerationResult(
                content=accumulated_text,
                model=model,
                finish_reason=stop_reason,
                usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
                latency_ms=latency_ms,
                logprobs=LogprobNormalizer.from_anthropic(None),
            ),
        )

    @staticmethod
    def _build_params(request: GenerationRequest) -> dict[str, Any]:
        """Build kwargs dict for client.messages.create()."""
        sp = request.sampling_params
        params: dict[str, Any] = {
            "model": request.model,
            "max_tokens": sp.max_tokens,
            "messages": [
                {"role": m["role"], "content": m["content"]} for m in request.messages
            ],
        }
        if request.system_prompt is not None:
            params["system"] = request.system_prompt
        if sp.temperature is not None:
            params["temperature"] = sp.temperature
        if sp.top_p is not None:
            params["top_p"] = sp.top_p
        if sp.top_k is not None:
            params["top_k"] = sp.top_k
        if sp.stop_sequences:
            params["stop_sequences"] = sp.stop_sequences
        return params

    @staticmethod
    def _extract_text(response: Any) -> str:
        """Extract text content from Anthropic Message response."""
        parts = []
        for block in response.content:
            if block.type == "text":
                parts.append(block.text)
        return "".join(parts)
