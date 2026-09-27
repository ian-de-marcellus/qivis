"""LlamaCppProvider — native llama.cpp /completion API via httpx."""

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from qivis.models import LogprobData, TokenLogprob
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
_LLAMA3_BOS = "<|begin_of_text|>"
_LLAMA3_BOS_ID = 128000

_TURN_BOUNDARY_RE = re.compile(r"(?<!\w )(user|assistant)(?![a-zA-Z])")

# Lost end-of-turn: in Llama 3 fine-tunes that never trained lm_head (e.g.
# Sun 1.0: CPT and SFT on one LoRA adapter), <|eot_id|>'s output row is still
# the untrained placeholder shared by ~385 other tokens. Where the model means
# to end its turn, the mass splits evenly across all of them -- each near
# -ln(386) = -5.96 -- and a random twin like "еристи" or '">\r\r\n' is sampled.
# Real text never looks like this: even a surprising token comes from a
# distribution whose best candidate is reasonably likely. Validated on 44
# stored Sun turns (1811 tokens): fires only at turn ends, no false cuts.
# (Sun 1.0.1 fixes this at the source; this remains a fallback.)
_LOST_TURN_END_SAMPLED = -5.0  # sampled token's logprob is below this...
_LOST_TURN_END_BEST = -4.0  # ...and so is every candidate's
# Probes requested for detection when the caller didn't ask for logprobs
_DETECTION_N_PROBS = 2


def _is_lost_turn_end(tok: TokenLogprob) -> bool:
    best = max([tok.logprob] + [a.logprob for a in tok.top_alternatives])
    return tok.logprob < _LOST_TURN_END_SAMPLED and best < _LOST_TURN_END_BEST


def _find_lost_turn_end(tokens: list[TokenLogprob], offset: int = 0) -> int | None:
    """Index of the first lost end-of-turn token, never the reply's first token."""
    for i, tok in enumerate(tokens):
        if offset + i > 0 and _is_lost_turn_end(tok):
            return i
    return None


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
        model_defaults: dict[str, dict] | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        # Per-model sampling defaults, keyed by the served model's name (see
        # model_defaults.example.json). Currently only logit_bias is used.
        self._model_defaults = {
            name: {
                **cfg,
                "logit_bias": {int(t): float(b) for t, b in (cfg.get("logit_bias") or {}).items()},
            }
            for name, cfg in (model_defaults or {}).items()
            if isinstance(cfg, dict)  # skip "_comment" and other notes
        }
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
        # Whether the server prepends BOS to string prompts; probed once
        self._adds_bos: bool | None = None
        # Special-token byte forms are probed on first generation, not at
        # discovery, so starting Qivis never wakes an on-demand model server
        self._probed_stops = False
        self._probe_lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return "llamacpp"

    # Reserved token IDs in the Llama 3 vocabulary (128011-128255) that are
    # unused by the format.  LoRA fine-tunes often have damaged embeddings for
    # these, causing the model to emit them instead of real special tokens.
    _LLAMA3_RESERVED_RANGE = range(128011, 128256)

    async def _props(self) -> dict:
        try:
            resp = await self._client.get(f"{self._base_url}/props")
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    async def _served_model(self) -> str | None:
        """Name of the model llama-server actually has loaded (it ignores the requested name)."""
        data = await self._props()
        name = data.get("model_alias") or (data.get("model_path") or "").rsplit("/", 1)[-1]
        return name if isinstance(name, str) and name else None

    async def context_window(self, model: str) -> int | None:
        """llama-server's n_ctx: the one window it serves, whatever model is asked for."""
        settings = (await self._props()).get("default_generation_settings") or {}
        n_ctx = settings.get("n_ctx")
        return n_ctx if isinstance(n_ctx, int) and n_ctx > 0 else None

    def _effective_logit_bias(
        self, request: GenerationRequest, served: str | None,
    ) -> dict[int, float] | None:
        """The served model's default logit_bias, overridden per token by the request's."""
        defaults = self._model_defaults.get(served or "", {}).get("logit_bias", {})
        merged = {**defaults, **(request.sampling_params.logit_bias or {})}
        return merged or None

    async def _server_adds_bos(self) -> bool | None:
        """Whether llama-server prepends BOS to string prompts (None if unknown)."""
        if self._adds_bos is None:
            try:
                resp = await self._client.post(
                    f"{self._base_url}/tokenize",
                    json={"content": "x", "add_special": True, "parse_special": False},
                )
                resp.raise_for_status()
                tokens = resp.json().get("tokens")
                if isinstance(tokens, list) and tokens and isinstance(tokens[0], int):
                    self._adds_bos = tokens[0] == _LLAMA3_BOS_ID
            except Exception:
                return None
        return self._adds_bos

    async def _prompt_for_bos_count(
        self, prompt: str, served: str | None,
    ) -> tuple[str, str | None]:
        """Adjust a llama3 prompt so the model sees exactly `bos_tokens` BOS.

        Returns (prompt to send, effective prompt if it differs from the
        rendered one). Standard Llama 3 models expect one BOS; some fine-tunes
        were trained with two (Sun 1.0: her SFT text began with
        <|begin_of_text|> and the trainer added another). The count is a
        per-model setting, default 1.
        """
        if not prompt.startswith(_LLAMA3_BOS):
            return prompt, None
        adds = await self._server_adds_bos()
        if adds is None:
            return prompt, None  # can't tell what the server does; send as rendered
        want = int(self._model_defaults.get(served or "", {}).get("bos_tokens", 1))
        body = prompt
        while body.startswith(_LLAMA3_BOS):
            body = body[len(_LLAMA3_BOS):]
        in_text = max(want - int(adds), 0)
        send = _LLAMA3_BOS * in_text + body
        effective = _LLAMA3_BOS * (in_text + int(adds)) + body
        return send, (effective if effective != prompt else None)

    def _build_request_body(
        self, request: GenerationRequest, logit_bias: dict[int, float] | None = None,
    ) -> dict[str, Any]:
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
        elif self._is_llama3(request):
            # Needed to detect a lost end-of-turn; not returned to the caller
            body["n_probs"] = _DETECTION_N_PROBS

        bias: dict[int, float] = {}
        # Llama 3 template-specific adjustments
        if request.prompt_text and "<|begin_of_text|>" in request.prompt_text:
            # Suppress reserved tokens (128011-128255): their output rows are
            # untrained placeholders, identical to each other and, in fine-tunes
            # that never trained lm_head, to <|eot_id|>'s own row.
            bias.update({tid: -100.0 for tid in self._LLAMA3_RESERVED_RANGE})
        # Model defaults and request overrides (already merged) take precedence
        bias.update(logit_bias or {})
        if bias:
            body["logit_bias"] = [[tid, b] for tid, b in bias.items()]

        return body

    @staticmethod
    def _is_llama3(request: GenerationRequest) -> bool:
        return bool(request.prompt_text and "<|begin_of_text|>" in request.prompt_text)

    @staticmethod
    def _returned_logprobs(
        request: GenerationRequest, logprobs: LogprobData | None,
    ) -> LogprobData | None:
        """Drop probes that were requested only for lost turn-end detection."""
        sp = request.sampling_params
        return logprobs if sp.logprobs and sp.top_logprobs is not None else None

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
        """Non-streaming completion, collected from the streaming path.

        llama.cpp 8460+ returns a 500 for a non-streamed completion when the
        output ends in bytes it can't parse (e.g. a model's damaged
        end-of-turn), discarding the whole reply.  The streaming path
        recovers from that and detects lost turn ends, so every caller gets
        the same, clean result either way.
        """
        result: GenerationResult | None = None
        async for chunk in self.generate_stream(request):
            if chunk.is_final and chunk.result is not None:
                result = chunk.result
        if result is None:
            raise RuntimeError("llama.cpp stream ended without a final result")
        return result

    async def generate_stream(
        self, request: GenerationRequest
    ) -> AsyncIterator[StreamChunk]:
        """Stream a completion; report any logit_bias applied beyond the reserved range."""
        if not self._probed_stops:
            # Concurrent streams (n>1, cross-model) wait for the one probe
            async with self._probe_lock:
                if not self._probed_stops:
                    await self._probe_special_token_stops()
        served = await self._served_model() if self._model_defaults else None
        applied = self._effective_logit_bias(request, served)
        body = self._build_request_body(request, applied)
        effective_prompt = None
        if request.prompt_text:
            body["prompt"], effective_prompt = await self._prompt_for_bos_count(
                request.prompt_text, served,
            )
        async for chunk in self._stream_completion(request, body):
            if chunk.result is not None:
                if applied:
                    chunk.result.applied_sampling_params = {"logit_bias": applied}
                if effective_prompt is not None:
                    chunk.result.effective_prompt_text = effective_prompt
            yield chunk

    async def _stream_completion(
        self, request: GenerationRequest, body: dict[str, Any],
    ) -> AsyncIterator[StreamChunk]:
        """Streaming completion via POST /completion with stream=true.

        llama.cpp sends SSE lines: 'data: {...}\\n\\n'. The final chunk
        has stop=true and includes usage info.

        For Llama 3 templates, monitors the stream for leaked turn boundaries
        (garbled special tokens + role name) and stops early, saving just the
        clean response text.  A few garbage characters may briefly appear in
        the streaming display but the persisted node content will be clean.
        """
        body["stream"] = True

        accumulated_text = ""
        accumulated_probs: list[dict] = []
        is_llama3 = self._is_llama3(request)

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
                        logprobs = self._returned_logprobs(
                            request, LogprobNormalizer.from_llamacpp(accumulated_probs)
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
                    chunk_probs = data.get("completion_probabilities", [])

                    # Lost end-of-turn: stop before the junk is ever shown
                    if is_llama3 and chunk_probs:
                        chunk_lp = LogprobNormalizer.from_llamacpp(chunk_probs)
                        idx = (
                            _find_lost_turn_end(chunk_lp.tokens, len(accumulated_probs))
                            if chunk_lp else None
                        )
                        if chunk_lp is not None and idx is not None:
                            kept = "".join(t.token for t in chunk_lp.tokens[:idx])
                            if kept:
                                accumulated_text += kept
                                yield StreamChunk(type="text_delta", text=kept)
                            accumulated_probs.extend(chunk_probs[:idx])
                            logger.info(
                                "Lost end-of-turn after %d chars, ending turn",
                                len(accumulated_text),
                            )
                            yield StreamChunk(
                                type="message_stop",
                                is_final=True,
                                result=GenerationResult(
                                    content=accumulated_text,
                                    model=data.get("model", request.model),
                                    finish_reason="stop",
                                    usage={},
                                    logprobs=self._returned_logprobs(
                                        request,
                                        LogprobNormalizer.from_llamacpp(accumulated_probs),
                                    ),
                                ),
                            )
                            return

                    accumulated_text += content
                    # Collect per-token logprob data from streaming chunks
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
                            logprobs = self._returned_logprobs(
                                request, LogprobNormalizer.from_llamacpp(accumulated_probs)
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
                    logprobs = self._returned_logprobs(
                        request, LogprobNormalizer.from_llamacpp(accumulated_probs)
                    )
                    stopped_at_limit = (
                        data.get("stop_type") == "limit" or data.get("stopped_limit")
                    )
                    yield StreamChunk(
                        type="message_stop",
                        is_final=True,
                        result=GenerationResult(
                            content=accumulated_text,
                            model=data.get("model", request.model),
                            finish_reason="length" if stopped_at_limit else "stop",
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
        found: list[str] = []
        for token_id, expected_text in _SPECIAL_TOKEN_IDS.items():
            try:
                resp = await self._client.post(
                    f"{self._base_url}/detokenize",
                    json={"tokens": [token_id]},
                )
                if resp.status_code != 200:
                    return  # server not ready or no /detokenize: try again next time
                byte_form = resp.json().get("content", "")
                if byte_form and byte_form != expected_text:
                    found.append(byte_form)
                    logger.info(
                        "Special token %d decodes as %r (expected %r) — "
                        "added as extra stop sequence",
                        token_id, byte_form, expected_text,
                    )
            except Exception:
                return
        self._extra_stops = found
        self._probed_stops = True

        if self._extra_stops:
            logger.info(
                "Probed %d extra stop sequences for byte-decoded special tokens",
                len(self._extra_stops),
            )

    async def next_tokens(
        self, request: GenerationRequest, continuation: list[int], k: int,
    ) -> dict[str, Any]:
        """The top-k next tokens after the prompt plus `continuation` (token ids).

        Probabilities are the distribution sampling would draw from: the
        model's logit bias applied, no truncation, temperature 1. Returns
        {"candidates": [{id, token, bytes, prob}], "logit_bias", "effective_prompt"}.
        """
        served = await self._served_model() if self._model_defaults else None
        applied = self._effective_logit_bias(request, served)
        body = self._build_request_body(request, applied)
        prompt = body["prompt"]
        effective_prompt = None
        if isinstance(prompt, str):
            prompt, effective_prompt = await self._prompt_for_bos_count(prompt, served)
        body.update({
            # Text first (the server adds its BOS as for a string prompt), then ids
            "prompt": [prompt, *continuation] if prompt else list(continuation),
            "n_predict": 1,
            "n_probs": k,
            "post_sampling_probs": True,
            "temperature": 1.0, "top_k": 0, "top_p": 1.0, "min_p": 0.0,
            "cache_prompt": True,
        })
        body.pop("stop", None)
        resp = await self._client.post(f"{self._base_url}/completion", json=body)
        resp.raise_for_status()
        probs = (resp.json().get("completion_probabilities") or [{}])[0]
        candidates = [
            {"id": c["id"], "token": c["token"], "bytes": c.get("bytes"), "prob": c["prob"]}
            for c in probs.get("top_probs", [])
        ]
        return {
            "candidates": candidates, "logit_bias": applied, "effective_prompt": effective_prompt,
        }

    async def tokenize(self, text: str) -> list[dict[str, Any]]:
        """Text as this model's tokens (no BOS): [{id, piece}]."""
        resp = await self._client.post(
            f"{self._base_url}/tokenize",
            json={
                "content": text, "add_special": False, "parse_special": True, "with_pieces": True,
            },
        )
        resp.raise_for_status()
        return [
            {"id": t["id"], "token": _piece_text(t["piece"])}
            for t in resp.json().get("tokens", [])
        ]

    async def detokenize(self, ids: list[int]) -> str:
        resp = await self._client.post(f"{self._base_url}/detokenize", json={"tokens": ids})
        resp.raise_for_status()
        return resp.json().get("content", "")

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

            return [model] if model else []
        except Exception:
            return []


def _piece_text(piece: str | list[int]) -> str:
    """A token's text; llama.cpp gives raw bytes for part of a multi-byte character."""
    return piece if isinstance(piece, str) else bytes(piece).decode("utf-8", errors="replace")
