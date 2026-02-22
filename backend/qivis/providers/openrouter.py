"""OpenRouter LLM provider — thin subclass of OpenAICompatibleProvider.

OpenRouter is an OpenAI-compatible API that routes to hundreds of models
(Llama, Mistral, Gemini, etc.) via a single API key.

Completion mode: OpenRouter rejects requests with both `prompt` and `messages`,
and the OpenAI SDK requires `messages` for chat.completions.create(). For
completion mode, we bypass the SDK and use httpx directly to send `prompt`
(without `messages`) to the /v1/completions endpoint for text completions.

Note: OpenRouter sometimes returns errors with HTTP 200 status. Both
completion methods check for `error` in the response body.
"""

import json
import time
from collections.abc import AsyncIterator

import httpx
from openai import AsyncOpenAI

from qivis.providers.base import (
    GenerationRequest,
    GenerationResult,
    LogprobNormalizer,
    StreamChunk,
)
from qivis.providers.openai_compat import OpenAICompatibleProvider

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(OpenAICompatibleProvider):
    """LLM provider backed by OpenRouter's API."""

    suggested_models = [
        "anthropic/claude-opus-4-6",
        "anthropic/claude-sonnet-4-5",
        "openai/gpt-5.2",
        "openai/gpt-4o",
        "google/gemini-3-flash",
        "google/gemini-3-pro",
        "deepseek/deepseek-v3.2",
        "deepseek/deepseek-chat",
        "meta-llama/llama-4-maverick",
        "meta-llama/llama-4-scout",
        "qwen/qwen3-235b-a22b",
        "mistralai/mistral-large-3",
        "moonshotai/kimi-k2.5",
        "arcee-ai/trinity-large-preview",
    ]

    def __init__(
        self,
        *,
        client: AsyncOpenAI | None = None,
        api_key: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if client is not None:
            super().__init__(client)
        else:
            super().__init__(
                AsyncOpenAI(
                    api_key=api_key,
                    base_url=OPENROUTER_BASE_URL,
                    default_headers={
                        "HTTP-Referer": "https://github.com/qivis",
                        "X-Title": "Qivis",
                    },
                )
            )
        # For completion mode: httpx bypasses SDK's messages requirement
        self._http = http_client or httpx.AsyncClient()
        self._completion_headers = {
            "Authorization": f"Bearer {api_key or ''}",
            "HTTP-Referer": "https://github.com/qivis",
            "X-Title": "Qivis",
            "Content-Type": "application/json",
        }

    @property
    def name(self) -> str:
        return "openrouter"

    # -- Completion mode overrides --
    # The OpenAI SDK's completions.create() adds extra parameters that cause
    # OpenRouter to misroute some requests. We use httpx directly to send clean
    # requests to /v1/completions (text completions format: choice.text, not
    # choice.message.content).

    async def _generate_completion(self, request: GenerationRequest) -> GenerationResult:
        body = self._build_completion_body(request)
        start = time.monotonic()
        resp = await self._http.post(
            f"{OPENROUTER_BASE_URL}/completions",
            json=body,
            headers=self._completion_headers,
        )
        resp.raise_for_status()
        latency_ms = int((time.monotonic() - start) * 1000)
        data = resp.json()

        # OpenRouter sometimes returns errors with HTTP 200 status
        if "error" in data:
            error_msg = data["error"]
            if isinstance(error_msg, dict):
                error_msg = error_msg.get("message", str(error_msg))
            raise RuntimeError(f"OpenRouter error: {error_msg}")

        choice = data["choices"][0]

        logprobs = None
        lp = choice.get("logprobs")
        if lp:
            logprobs = LogprobNormalizer.from_openai_completion(lp)

        return GenerationResult(
            content=choice.get("text") or "",
            model=data.get("model", request.model),
            finish_reason=choice.get("finish_reason"),
            usage={
                "input_tokens": data.get("usage", {}).get("prompt_tokens", 0),
                "output_tokens": data.get("usage", {}).get("completion_tokens", 0),
            },
            latency_ms=latency_ms,
            logprobs=logprobs,
        )

    async def _generate_completion_stream(
        self, request: GenerationRequest,
    ) -> AsyncIterator[StreamChunk]:
        body = self._build_completion_body(request)
        body["stream"] = True

        start = time.monotonic()
        accumulated = ""
        finish_reason: str | None = None
        model = request.model
        input_tokens = 0
        output_tokens = 0

        async with self._http.stream(
            "POST",
            f"{OPENROUTER_BASE_URL}/completions",
            json=body,
            headers=self._completion_headers,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:].strip()
                if payload == "[DONE]":
                    break
                chunk = json.loads(payload)

                # OpenRouter sometimes returns errors with HTTP 200 status
                if "error" in chunk:
                    error_msg = chunk["error"]
                    if isinstance(error_msg, dict):
                        error_msg = error_msg.get("message", str(error_msg))
                    raise RuntimeError(f"OpenRouter error: {error_msg}")

                if chunk.get("model"):
                    model = chunk["model"]

                choices = chunk.get("choices", [])
                if choices:
                    choice = choices[0]
                    # Text completions format: choice.text (not delta.content)
                    text = choice.get("text") or ""
                    if text:
                        accumulated += text
                        yield StreamChunk(type="text_delta", text=text)
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]

                usage = chunk.get("usage")
                if usage:
                    input_tokens = usage.get("prompt_tokens", 0)
                    output_tokens = usage.get("completion_tokens", 0)

        latency_ms = int((time.monotonic() - start) * 1000)
        yield StreamChunk(
            type="message_stop",
            is_final=True,
            result=GenerationResult(
                content=accumulated,
                model=model,
                finish_reason=finish_reason,
                usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
                latency_ms=latency_ms,
            ),
        )

    @staticmethod
    def _build_completion_body(request: GenerationRequest) -> dict:
        """Build request body with `prompt` (no `messages`) for OpenRouter.

        Logprobs are deliberately excluded: many upstream providers behind
        OpenRouter (e.g. Hyperbolic) misroute completion requests to their
        chat endpoint when logprobs params are present, causing failures
        on base models. Logprobs for completion mode are better served by
        local providers (llama.cpp) which return full-vocabulary distributions.
        """
        sp = request.sampling_params
        body: dict = {
            "model": request.model,
            "prompt": request.prompt_text or "",
            "max_tokens": sp.max_tokens,
        }
        if sp.temperature is not None:
            body["temperature"] = sp.temperature
        if sp.top_p is not None:
            body["top_p"] = sp.top_p
        if sp.stop_sequences:
            body["stop"] = sp.stop_sequences
        # Note: logprobs intentionally omitted — see docstring
        return body
