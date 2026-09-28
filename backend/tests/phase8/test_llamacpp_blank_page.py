"""An empty prompt is a blank page, not nothing.

Given an empty string, llama-server evaluates no tokens (unless it adds BOS)
and the model says nothing; given an empty token list it refuses. A base model
has seen documents begin after its end-of-text token, so an empty document
starts there, and the record says so.
"""

from unittest.mock import AsyncMock

from qivis.providers.llamacpp import LlamaCppProvider


def _provider(adds_bos: bool, props: list[dict]) -> LlamaCppProvider:
    p = LlamaCppProvider(http_client=AsyncMock())
    p._server_adds_bos = AsyncMock(return_value=adds_bos)  # type: ignore[method-assign]
    p._props = AsyncMock(side_effect=props)  # type: ignore[method-assign]
    return p


async def test_blank_page_starts_after_end_of_text():
    p = _provider(False, [{"eos_token": "<|endoftext|>"}])
    assert await p._prompt_to_send("", None, "olmo") == ("<|endoftext|>", "<|endoftext|>")


async def test_sleeping_model_is_woken_to_learn_its_end_of_text():
    # A supervisor's stand-in props for a sleeping model have no eos_token
    p = _provider(False, [{"model_alias": "olmo"}, {"eos_token": "<|endoftext|>"}])
    assert (await p._prompt_to_send("", None, "olmo"))[0] == "<|endoftext|>"
    p._client.post.assert_awaited()  # type: ignore[attr-defined]


async def test_a_server_that_adds_bos_starts_from_it():
    p = _provider(True, [])
    send, effective = await p._prompt_to_send("", None, "llama")
    assert send == "" and effective == "<|begin_of_text|>"


async def test_written_prompts_are_unchanged():
    p = _provider(False, [])
    assert await p._prompt_to_send("Once upon", None, "olmo") == ("Once upon", None)
