"""Direct lookups (llama.cpp itself, not through llama-server) give the numbers
llama-server gives, within its own run-to-run variation.

Needs a real model: set QIVIS_TEST_GGUF to a model file llama-server is
serving (by its file name) at QIVIS_TEST_LLAMACPP (default localhost:8080).
Skipped otherwise.
"""

import os
from pathlib import Path

import pytest

from qivis.models import SamplingParams
from qivis.names import direct, engine
from qivis.names.cache import LOOKUP_K
from qivis.providers.base import GenerationRequest
from qivis.providers.llamacpp import LlamaCppProvider

GGUF = os.environ.get("QIVIS_TEST_GGUF", "")
pytestmark = pytest.mark.skipif(not GGUF, reason="QIVIS_TEST_GGUF not set")


async def test_direct_lookups_match_llama_server():
    llama = LlamaCppProvider(base_url=os.environ.get("QIVIS_TEST_LLAMACPP", "http://localhost:8080"))
    model = Path(GGUF).name
    prompt = (await llama.document_start(model)) + "There is an electronic mind. Her name is"
    request = GenerationRequest(model=model, messages=[], prompt_text=prompt,
                                sampling_params=SamplingParams())
    text, bias, _ = await llama.lookup_inputs(request)
    eng = direct.DirectEngine()
    try:
        for path in ([], [(await llama.tokenize(" Ele", model))[0]["id"]]):
            mine = await eng.summary(GGUF, text, path, bias)
            theirs = engine.summarize((await llama.next_tokens(request, path, LOOKUP_K))["candidates"])
            assert mine.ends == pytest.approx(theirs.ends, rel=1e-3)
            assert mine.ends_with_punctuation == pytest.approx(theirs.ends_with_punctuation, rel=1e-2)
            top = list(theirs.ids[:20])
            assert set(top) <= set(mine.ids[:25])
            for tid in top:
                assert mine.prob(tid) == pytest.approx(theirs.prob(tid), rel=1e-2)
                assert mine.token(tid) == theirs.token(tid)
    finally:
        await eng.close()
