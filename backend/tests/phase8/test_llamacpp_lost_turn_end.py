"""Lost end-of-turn detection in LlamaCppProvider.

Some fine-tunes (e.g. Sun, Llama 3.1 8B CPT+SFT) have a damaged
<|eot_id|> path: where the model means to end its turn, the next-token
distribution goes flat over junk (every candidate at ~-6 logprob) and a
fragment like "еристи", "аракт", or '">\\r\\r\\n' is sampled instead.
The provider cuts the reply at the first such flat position, using the
per-token distribution rather than guessing from text.
"""

import json
from unittest.mock import AsyncMock, MagicMock

from qivis.models import SamplingParams
from qivis.providers.base import GenerationRequest
from qivis.providers.llamacpp import LlamaCppProvider

LLAMA3_PROMPT = "<|begin_of_text|><|start_header_id|>assistant<|end_header_id|>\n\n"


def _tok(token: str, logprob: float, alts: list[tuple[str, float]]) -> dict:
    """A modern-format (build 8460+) completion_probabilities entry."""
    return {
        "id": 0,
        "token": token,
        "logprob": logprob,
        "bytes": list(token.encode()),
        "top_logprobs": [{"id": 0, "token": t, "logprob": lp} for t, lp in alts],
    }


def _normal(token: str) -> dict:
    return _tok(token, -0.1, [(token, -0.1), ("x", -2.5), ("y", -3.0)])


def _flat(token: str) -> dict:
    """The junk sampled where the turn should have ended (real Sun values)."""
    return _tok(token, -6.01, [("�始化", -5.99), ("еристи", -6.0), (" CLIIIK", -6.02)])


def _request(
    prompt_text: str = LLAMA3_PROMPT, logprobs: bool = True,
) -> GenerationRequest:
    return GenerationRequest(
        model="sun.gguf",
        messages=[],
        prompt_text=prompt_text,
        sampling_params=SamplingParams(
            logprobs=logprobs, top_logprobs=5 if logprobs else None, max_tokens=256,
        ),
    )


class MockStreamResponse:
    def __init__(self, lines: list[str]):
        self._lines = lines
        self.consumed = 0

    async def aiter_lines(self):
        for line in self._lines:
            self.consumed += 1
            yield line

    def raise_for_status(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _chunk(prob: dict) -> str:
    return "data: " + json.dumps(
        {"content": prob["token"], "stop": False, "completion_probabilities": [prob]}
    )


def _stream_client(lines: list[str]) -> tuple[AsyncMock, MockStreamResponse]:
    resp = MockStreamResponse(lines)
    client = AsyncMock()
    client.stream = MagicMock(return_value=resp)
    client.post = AsyncMock(side_effect=ConnectionError("no /tokenize in this mock"))
    return client, resp


async def _collect(provider: LlamaCppProvider, request: GenerationRequest):
    return [c async for c in provider.generate_stream(request)]


class TestStreamingCut:
    async def test_cuts_at_flat_token_and_never_shows_it(self):
        probs = [_normal("What"), _normal(" do"), _normal(" you"), _normal(" think?"),
                 _flat("еристи")]
        lines = [_chunk(p) for p in probs] + [
            _chunk(_normal("user")),
            'data: {"content": "", "stop": true}',
        ]
        client, resp = _stream_client(lines)
        chunks = await _collect(LlamaCppProvider(http_client=client), _request())

        deltas = "".join(c.text for c in chunks if c.type == "text_delta")
        assert deltas == "What do you think?"
        final = [c for c in chunks if c.is_final]
        assert len(final) == 1
        assert final[0].result.content == "What do you think?"
        assert final[0].result.finish_reason == "stop"
        assert [t.token for t in final[0].result.logprobs.tokens] == [
            "What", " do", " you", " think?",
        ]
        # Stops reading as soon as the lost turn end is seen
        assert resp.consumed == len(probs)

    async def test_stray_quote_junk_is_cut(self):
        probs = [_normal("Right"), _normal(" now?"), _flat('">\r\r\n'), _flat("ЎыџN")]
        client, _ = _stream_client([_chunk(p) for p in probs])
        chunks = await _collect(LlamaCppProvider(http_client=client), _request())
        assert [c for c in chunks if c.is_final][0].result.content == "Right now?"

    async def test_low_logprob_in_peaked_distribution_is_kept(self):
        """A surprising but real token: low logprob, yet the distribution isn't flat."""
        rare = _tok(" gleaming", -5.5, [(" bright", -0.3), (" warm", -1.9)])
        probs = [_normal("A"), rare, _normal(" day.")]
        lines = [_chunk(p) for p in probs] + ['data: {"content": "", "stop": true}']
        client, _ = _stream_client(lines)
        chunks = await _collect(LlamaCppProvider(http_client=client), _request())
        assert [c for c in chunks if c.is_final][0].result.content == "A gleaming day."

    async def test_flat_first_token_is_not_cut_to_empty(self):
        probs = [_flat("хм"), _normal(" okay.")]
        lines = [_chunk(p) for p in probs] + ['data: {"content": "", "stop": true}']
        client, _ = _stream_client(lines)
        chunks = await _collect(LlamaCppProvider(http_client=client), _request())
        assert [c for c in chunks if c.is_final][0].result.content == "хм okay."


class TestNonStreamingCut:
    async def test_generate_cuts_content_and_logprobs(self):
        """generate() collects the stream, so it gets the same cut."""
        probs = [_normal("Good."), _normal(" Me"), _normal(" too."), _flat("аракт")]
        client, _ = _stream_client([_chunk(p) for p in probs])
        result = await LlamaCppProvider(http_client=client).generate(_request())
        assert result.content == "Good. Me too."
        assert len(result.logprobs.tokens) == 3

    async def test_generate_survives_server_error_after_output(self):
        """llama.cpp 8460+ errors when it can't parse trailing junk bytes."""
        lines = [_chunk(_normal("Hi")), _chunk(_normal(" there.")),
                 'data: {"error": {"code": 500, "message": "Failed to parse input at pos 0"}}']
        client, _ = _stream_client(lines)
        result = await LlamaCppProvider(http_client=client).generate(_request())
        assert result.content == "Hi there."


class TestDetectionWithoutRequestedLogprobs:
    async def test_llama3_requests_probs_for_detection_but_returns_none(self):
        probs = [_normal("Hi."), _flat("илася")]
        lines = [_chunk(p) for p in probs]
        client, _ = _stream_client(lines)
        chunks = await _collect(
            LlamaCppProvider(http_client=client), _request(logprobs=False),
        )
        body = client.stream.call_args.kwargs["json"]
        assert body["n_probs"] >= 2
        final = [c for c in chunks if c.is_final][0].result
        assert final.content == "Hi."
        assert final.logprobs is None

    async def test_non_llama3_without_logprobs_requests_no_probs(self):
        client, _ = _stream_client(['data: {"content": "Hi", "stop": false}',
                                    'data: {"content": "", "stop": true}'])
        await _collect(
            LlamaCppProvider(http_client=client),
            _request(prompt_text="<|im_start|>assistant\n", logprobs=False),
        )
        assert "n_probs" not in client.stream.call_args.kwargs["json"]
