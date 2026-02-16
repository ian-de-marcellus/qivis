"""Shared base class for OpenAI-compatible LLM providers.

Handles parameter building, response parsing, streaming, and logprob
normalization. OpenAIProvider and OpenRouterProvider are thin subclasses
that differ only in client configuration.
"""

import time
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from qivis.providers.base import (
    GenerationRequest,
    GenerationResult,
    LLMProvider,
    LogprobNormalizer,
    StreamChunk,
)


class OpenAICompatibleProvider(LLMProvider):
    """Base provider for any API that speaks the OpenAI chat completions protocol."""

    def __init__(self, client: AsyncOpenAI) -> None:
        self._client = client

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        params = self._build_params(request)
        start = time.monotonic()
        response = await self._client.chat.completions.create(**params)
        latency_ms = int((time.monotonic() - start) * 1000)

        choice = response.choices[0]
        content = choice.message.content or ""

        # Extract logprobs if present
        logprobs = None
        if choice.logprobs and choice.logprobs.content:
            logprobs = LogprobNormalizer.from_openai(choice.logprobs.content)

        return GenerationResult(
            content=content,
            model=response.model,
            finish_reason=choice.finish_reason,
            usage={
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            },
            latency_ms=latency_ms,
            logprobs=logprobs,
            raw_response=response.model_dump(),
        )

    async def generate_stream(
        self, request: GenerationRequest
    ) -> AsyncIterator[StreamChunk]:
        params = self._build_params(request)
        params["stream"] = True
        params["stream_options"] = {"include_usage": True}

        start = time.monotonic()
        accumulated_text = ""
        accumulated_logprobs: list[Any] = []
        finish_reason: str | None = None
        model = request.model
        input_tokens = 0
        output_tokens = 0

        stream = await self._client.chat.completions.create(**params)
        async for chunk in stream:
            # Update model from first chunk
            if chunk.model:
                model = chunk.model

            # Process choices
            if chunk.choices:
                choice = chunk.choices[0]
                delta = choice.delta
                text = delta.content
                if text:
                    accumulated_text += text
                    yield StreamChunk(type="text_delta", text=text)

                # Accumulate logprobs from each chunk
                if choice.logprobs and choice.logprobs.content:
                    accumulated_logprobs.extend(choice.logprobs.content)

                if choice.finish_reason:
                    finish_reason = choice.finish_reason

            # Usage comes in final chunk (no choices)
            if chunk.usage:
                input_tokens = chunk.usage.prompt_tokens
                output_tokens = chunk.usage.completion_tokens

        latency_ms = int((time.monotonic() - start) * 1000)
        logprobs = LogprobNormalizer.from_openai(accumulated_logprobs or None)
        yield StreamChunk(
            type="message_stop",
            is_final=True,
            result=GenerationResult(
                content=accumulated_text,
                model=model,
                finish_reason=finish_reason,
                usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
                latency_ms=latency_ms,
                logprobs=logprobs,
            ),
        )

    @staticmethod
    def _build_params(request: GenerationRequest) -> dict[str, Any]:
        """Build kwargs dict for client.chat.completions.create()."""
        sp = request.sampling_params
        messages: list[dict[str, str]] = []

        # System prompt → prepended as system message
        if request.system_prompt is not None:
            messages.append({"role": "system", "content": request.system_prompt})

        messages.extend(
            {"role": m["role"], "content": m["content"]} for m in request.messages
        )

        params: dict[str, Any] = {
            "model": request.model,
            "max_tokens": sp.max_tokens,
            "messages": messages,
        }

        if sp.temperature is not None:
            params["temperature"] = sp.temperature
        if sp.top_p is not None:
            params["top_p"] = sp.top_p
        # top_k silently ignored — OpenAI doesn't support it
        if sp.stop_sequences:
            params["stop"] = sp.stop_sequences
        if sp.frequency_penalty is not None:
            params["frequency_penalty"] = sp.frequency_penalty
        if sp.presence_penalty is not None:
            params["presence_penalty"] = sp.presence_penalty
        if sp.logprobs:
            params["logprobs"] = True
            if sp.top_logprobs is not None:
                params["top_logprobs"] = sp.top_logprobs

        return params
