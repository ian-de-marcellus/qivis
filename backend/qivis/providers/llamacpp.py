"""LlamaCppProvider — native llama.cpp /completion API via httpx."""

import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from qivis.providers.base import (
    GenerationRequest,
    GenerationResult,
    LLMProvider,
    LogprobNormalizer,
    StreamChunk,
)

logger = logging.getLogger(__name__)

# Special token IDs whose byte representations we probe via /detokenize.
_SPECIAL_TOKEN_IDS: dict[int, str] = {
    128009: "<|eot_id|>",
    128006: "<|start_header_id|>",
    128007: "<|end_header_id|>",
}

# Detects a leaked Llama 3 turn boundary in completion output.
#
# When special tokens decode as garbage bytes, the model's output looks like:
#   "Hi! What's up?[garbage]user[garbage]\n\n..."
# The role name ("user"/"assistant") is always clear text because it's regular
# tokens.  The lookbehind rejects normal English ("the user", "an assistant")
# by requiring that the char before the role name is NOT a space preceded by
# a word char.  The lookahead uses [a-zA-Z] instead of \w because garbage
# bytes from decoded special tokens are often Unicode (Cyrillic etc.) which
# Python's \w would match, preventing detection.
_TURN_BOUNDARY_RE = re.compile(r"(?<!\w )(user|assistant)(?![a-zA-Z])")


class LlamaCppProvider(LLMProvider):
    """Provider for llama.cpp's native /completion endpoint.

    Uses httpx.AsyncClient (not the OpenAI SDK) because llama.cpp's API
    is a different protocol: prompt text in, probabilities out. Supports
    full-vocabulary logprob distributions via n_probs.
    """

    supported_modes = ["completion"]
    supported_params = [
        "temperature",
        "top_p",
        "top_k",
        "max_tokens",
        "stop_sequences",
        "frequency_penalty",
        "presence_penalty",
    ]

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:8080",
        http_client: httpx.AsyncClient | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        # Local inference on CPU can take a long time for prompt evaluation
        # before the first token arrives — default 5s is far too short.
        self._client = http_client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0),
        )
        # Byte representations of special tokens discovered via /detokenize.
        # Used as extra stop sequences when the server decodes special tokens
        # as raw bytes instead of their text form.
        self._extra_stops: list[str] = []

    @property
    def name(self) -> str:
        return "llamacpp"

    # Reserved token IDs in the Llama 3 vocabulary (128011-128255) that are
    # unused by the format.  LoRA fine-tunes often have damaged embeddings for
    # these, causing the model to emit them instead of real special tokens.
    _LLAMA3_RESERVED_RANGE = range(128011, 128256)

    def _build_request_body(self, request: GenerationRequest) -> dict[str, Any]:
        """Map GenerationRequest to llama.cpp /completion request body."""
        body: dict[str, Any] = {
            "prompt": request.prompt_text or "",
            # Parse special tokens (<|eot_id|> etc.) as token IDs, not text
            "special": True,
        }

        sp = request.sampling_params

        if sp.max_tokens is not None:
            body["n_predict"] = sp.max_tokens
        if sp.temperature is not None:
            body["temperature"] = sp.temperature
        if sp.top_p is not None:
            body["top_p"] = sp.top_p
        if sp.top_k is not None:
            body["top_k"] = sp.top_k
        stops = list(sp.stop_sequences or [])
        for s in self._extra_stops:
            if s not in stops:
                stops.append(s)
        if stops:
            body["stop"] = stops
        if sp.frequency_penalty is not None:
            body["frequency_penalty"] = sp.frequency_penalty
        if sp.presence_penalty is not None:
            body["presence_penalty"] = sp.presence_penalty
        if sp.logprobs and sp.top_logprobs is not None:
            body["n_probs"] = sp.top_logprobs

        # Llama 3 template-specific adjustments
        if request.prompt_text and "<|begin_of_text|>" in request.prompt_text:
            # Suppress reserved tokens (128011-128255) — LoRA fine-tunes often
            # have damaged embeddings for these unused vocabulary slots.
            body["logit_bias"] = [
                [tid, -100.0] for tid in self._LLAMA3_RESERVED_RANGE
            ]

        return body

    @staticmethod
    def _truncate_at_boundary(text: str, is_llama3: bool) -> str:
        """Strip leaked turn-boundary garbage from completion output.

        When llama.cpp doesn't stop on <|eot_id|>, the output contains the
        model's real response followed by garbled special-token bytes and
        a role name like "user" or "assistant".  This method finds the
        boundary and returns just the clean response text.
        """
        if not is_llama3 or len(text) < 10:
            return text

        # Only search after the first 10 chars to avoid matching role names
        # that might legitimately appear very early in a response.
        match = _TURN_BOUNDARY_RE.search(text, pos=10)
        if not match:
            return text

        # Walk backward from the match to find the end of the real response.
        # The garbage between the response and the role name can be anything:
        # Cyrillic bytes, ASCII identifiers like "TokenNameIdentifier",
        # semicolons, etc.  The most reliable anchor is the last sentence-
        # ending punctuation (.!?) or closing quote/bracket before the match.
        pos = match.start()
        # Find the last "clean end" character before the boundary
        end_chars = set('.!?"\')]}')
        clean_end = -1
        for i in range(pos - 1, -1, -1):
            if text[i] in end_chars:
                clean_end = i + 1
                break
        if clean_end > 0:
            return text[:clean_end].rstrip()
        # No punctuation found — the garbage starts at the beginning of what
        # we can see, so just strip everything from the match backward.
        return text[:pos].rstrip()

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        """Non-streaming completion via POST /completion."""
        body = self._build_request_body(request)
        resp = await self._client.post(f"{self._base_url}/completion", json=body)
        resp.raise_for_status()
        data = resp.json()

        logprobs = LogprobNormalizer.from_llamacpp(
            data.get("completion_probabilities")
        )

        content = data.get("content", "")
        is_llama3 = bool(request.prompt_text and "<|begin_of_text|>" in request.prompt_text)
        content = self._truncate_at_boundary(content, is_llama3)

        return GenerationResult(
            content=content,
            model=data.get("model", request.model),
            finish_reason="stop" if data.get("stop", True) else "length",
            usage={
                "input_tokens": data.get("tokens_evaluated", 0),
                "output_tokens": data.get("tokens_predicted", 0),
            },
            logprobs=logprobs,
        )

    async def generate_stream(
        self, request: GenerationRequest
    ) -> AsyncIterator[StreamChunk]:
        """Streaming completion via POST /completion with stream=true.

        llama.cpp sends SSE lines: 'data: {...}\\n\\n'. The final chunk
        has stop=true and includes usage info.

        For Llama 3 templates, monitors the stream for leaked turn boundaries
        (garbled special tokens + role name) and stops early, saving just the
        clean response text.  A few garbage characters may briefly appear in
        the streaming display but the persisted node content will be clean.
        """
        body = self._build_request_body(request)
        body["stream"] = True

        accumulated_text = ""
        accumulated_probs: list[dict] = []
        is_llama3 = bool(
            request.prompt_text and "<|begin_of_text|>" in request.prompt_text
        )

        async with self._client.stream(
            "POST", f"{self._base_url}/completion", json=body
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = json.loads(line[6:])

                # llama.cpp build 8460+ may emit an error event when it
                # encounters raw-byte EOG tokens during stop-sequence
                # matching.  If we already have accumulated text, treat
                # this as a successful completion rather than an error.
                if "error" in data:
                    if accumulated_text.strip():
                        logger.warning(
                            "llama.cpp stream error after %d chars of "
                            "output, treating as completion: %s",
                            len(accumulated_text),
                            data["error"].get("message", "")[:120],
                        )
                        clean = self._truncate_at_boundary(
                            accumulated_text, is_llama3
                        )
                        logprobs = LogprobNormalizer.from_llamacpp(
                            accumulated_probs
                        )
                        yield StreamChunk(
                            type="message_stop",
                            is_final=True,
                            result=GenerationResult(
                                content=clean,
                                model=request.model,
                                finish_reason="stop",
                                usage={},
                                logprobs=logprobs,
                            ),
                        )
                        return
                    raise RuntimeError(
                        f"llama.cpp error: {data['error'].get('message', '')}"
                    )

                content = data.get("content", "")
                is_stop = data.get("stop", False)

                if content and not is_stop:
                    accumulated_text += content
                    # Collect per-token logprob data from streaming chunks
                    chunk_probs = data.get("completion_probabilities", [])
                    if chunk_probs:
                        accumulated_probs.extend(chunk_probs)
                    yield StreamChunk(type="text_delta", text=content)

                    # Check for leaked turn boundary after each chunk
                    if is_llama3:
                        clean = self._truncate_at_boundary(
                            accumulated_text, is_llama3
                        )
                        if clean != accumulated_text:
                            logger.info(
                                "Detected turn boundary after %d chars, "
                                "truncating to %d",
                                len(accumulated_text), len(clean),
                            )
                            logprobs = LogprobNormalizer.from_llamacpp(
                                accumulated_probs
                            )
                            yield StreamChunk(
                                type="message_stop",
                                is_final=True,
                                result=GenerationResult(
                                    content=clean,
                                    model=data.get("model", request.model),
                                    finish_reason="stop",
                                    usage={
                                        "input_tokens": data.get(
                                            "tokens_evaluated", 0
                                        ),
                                        "output_tokens": data.get(
                                            "tokens_predicted", 0
                                        ),
                                    },
                                    logprobs=logprobs,
                                ),
                            )
                            return

                if is_stop:
                    # Include any probs from the final chunk itself
                    final_probs = data.get("completion_probabilities", [])
                    if final_probs:
                        accumulated_probs.extend(final_probs)
                    logprobs = LogprobNormalizer.from_llamacpp(
                        accumulated_probs
                    )
                    yield StreamChunk(
                        type="message_stop",
                        is_final=True,
                        result=GenerationResult(
                            content=accumulated_text,
                            model=data.get("model", request.model),
                            finish_reason="stop",
                            usage={
                                "input_tokens": data.get("tokens_evaluated", 0),
                                "output_tokens": data.get("tokens_predicted", 0),
                            },
                            logprobs=logprobs,
                        ),
                    )

    async def _probe_special_token_stops(self) -> None:
        """Discover byte representations of special tokens via /detokenize.

        llama.cpp may decode special tokens (like <|eot_id|>) as raw bytes
        in streaming output rather than their text form.  When that happens,
        text-based stop sequences like "<|eot_id|>" never match.

        This method calls /detokenize for each key special token ID.  If the
        result differs from the expected text, we add the byte form as an
        extra stop sequence so we catch both representations.
        """
        for token_id, expected_text in _SPECIAL_TOKEN_IDS.items():
            try:
                resp = await self._client.post(
                    f"{self._base_url}/detokenize",
                    json={"tokens": [token_id]},
                )
                if resp.status_code != 200:
                    continue
                byte_form = resp.json().get("content", "")
                if byte_form and byte_form != expected_text:
                    self._extra_stops.append(byte_form)
                    logger.info(
                        "Special token %d decodes as %r (expected %r) — "
                        "added as extra stop sequence",
                        token_id, byte_form, expected_text,
                    )
            except Exception:
                pass

        if self._extra_stops:
            logger.info(
                "Probed %d extra stop sequences for byte-decoded special tokens",
                len(self._extra_stops),
            )

    async def discover_models(self) -> list[str]:
        """Discover loaded model via GET /props."""
        try:
            resp = await self._client.get(f"{self._base_url}/props")
            resp.raise_for_status()
            data = resp.json()
            # llama.cpp exposes model name at top level, not inside default_generation_settings
            model = (
                data.get("model_alias")
                or data.get("default_generation_settings", {}).get("model")
            )

            # Probe special token byte representations for stop matching
            await self._probe_special_token_stops()

            return [model] if model else []
        except Exception:
            return []
