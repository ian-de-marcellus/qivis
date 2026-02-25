"""OpenRouter LLM provider — thin subclass of OpenAICompatibleProvider.

OpenRouter is an OpenAI-compatible API that routes to hundreds of models
(Llama, Mistral, Gemini, etc.) via a single API key.

Completion mode: OpenRouter rejects requests with both `prompt` and `messages`,
and the OpenAI SDK requires `messages` for chat.completions.create(). For
completion mode, we bypass the SDK and use httpx directly to send `prompt`
(without `messages`) to the /v1/completions endpoint for text completions.

Note: OpenRouter sometimes returns errors with HTTP 200 status. Both
completion methods check for `error` in the response body.

Retry: Upstream providers behind OpenRouter (e.g. Hyperbolic) often return 429
on cold-start — the first request after inactivity triggers model warm-up but
gets rejected. We retry 429s with exponential backoff so the user doesn't have
to manually retry.
"""

import asyncio
import json
import logging
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

logger = logging.getLogger(__name__)

# Retry config for 429 (upstream cold-start / rate-limit)
_MAX_RETRIES_429 = 2
_RETRY_BACKOFF_BASE = 2.0  # seconds


def _retry_delay(resp: httpx.Response, attempt: int) -> float:
    """Compute retry delay, respecting Retry-After header if present."""
    retry_after = resp.headers.get("retry-after")
    if retry_after:
        try:
            return min(float(retry_after), 10.0)
        except ValueError:
            pass
    return _RETRY_BACKOFF_BASE * (2 ** attempt)

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

        # Retry loop for 429 (upstream cold-start)
        start = time.monotonic()
        resp: httpx.Response | None = None
        for attempt in range(1 + _MAX_RETRIES_429):
            resp = await self._http.post(
                f"{OPENROUTER_BASE_URL}/completions",
                json=body,
                headers=self._completion_headers,
            )
            if resp.status_code == 429 and attempt < _MAX_RETRIES_429:
                delay = _retry_delay(resp, attempt)
                logger.info(
                    "OpenRouter 429 for %s, retrying in %.1fs (%d/%d)",
                    request.model, delay, attempt + 1, _MAX_RETRIES_429,
                )
                await asyncio.sleep(delay)
                continue
            break
        assert resp is not None

        if resp.status_code >= 400:
            # Read the full body — OpenRouter nests details in error.metadata,
            # provider_errors, etc.
            detail = resp.text
            try:
                err_data = resp.json()
                if "error" in err_data:
                    err = err_data["error"]
                    if isinstance(err, dict):
                        # Prefer the most specific message available
                        parts = []
                        if err.get("message"):
                            parts.append(err["message"])
                        # metadata.raw often has the upstream provider error
                        meta = err.get("metadata", {})
                        if isinstance(meta, dict) and meta.get("raw"):
                            parts.append(f"[upstream: {meta['raw']}]")
                        detail = " ".join(parts) if parts else str(err)
                    else:
                        detail = str(err)
            except Exception:
                pass
            logger.warning(
                "OpenRouter /completions %d for model %s: %s",
                resp.status_code, request.model, resp.text,
            )
            raise RuntimeError(
                f"OpenRouter completion error ({resp.status_code}): {detail}"
            )
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
        logger.info("OpenRouter completion stream request: model=%s body=%s", request.model, body)

        start = time.monotonic()
        accumulated = ""
        finish_reason: str | None = None
        model = request.model
        input_tokens = 0
        output_tokens = 0

        # Retry loop for 429 (upstream cold-start). Each attempt opens a new
        # stream; we close it cleanly before retrying.
        stream_cm = None
        resp = None
        for attempt in range(1 + _MAX_RETRIES_429):
            stream_cm = self._http.stream(
                "POST",
                f"{OPENROUTER_BASE_URL}/completions",
                json=body,
                headers=self._completion_headers,
            )
            resp = await stream_cm.__aenter__()
            if resp.status_code == 429 and attempt < _MAX_RETRIES_429:
                await resp.aread()
                await stream_cm.__aexit__(None, None, None)
                stream_cm = None
                delay = _retry_delay(resp, attempt)
                logger.info(
                    "OpenRouter 429 stream for %s, retrying in %.1fs (%d/%d)",
                    request.model, delay, attempt + 1, _MAX_RETRIES_429,
                )
                await asyncio.sleep(delay)
                continue
            break
        assert resp is not None and stream_cm is not None

        try:
            if resp.status_code >= 400:
                body_bytes = await resp.aread()
                raw = body_bytes.decode(errors="replace")
                detail = raw
                try:
                    err_data = json.loads(raw)
                    if "error" in err_data:
                        err = err_data["error"]
                        if isinstance(err, dict):
                            parts = []
                            if err.get("message"):
                                parts.append(err["message"])
                            meta = err.get("metadata", {})
                            if isinstance(meta, dict) and meta.get("raw"):
                                parts.append(f"[upstream: {meta['raw']}]")
                            detail = " ".join(parts) if parts else str(err)
                        else:
                            detail = str(err)
                except Exception:
                    pass
                logger.warning(
                    "OpenRouter /completions stream %d for model %s: %s",
                    resp.status_code, request.model, raw,
                )
                raise RuntimeError(
                    f"OpenRouter completion error ({resp.status_code}): {detail}"
                )
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
        finally:
            await stream_cm.__aexit__(None, None, None)

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
