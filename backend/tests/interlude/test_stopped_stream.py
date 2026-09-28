"""A stopped stream keeps what the model said, with its record.

Stopping used to have the browser save the partial text as a bare node: no
model, prompt, or token probabilities, and labeled "chat". Now the server
stores it, as the model's reply with everything that produced it, ended by
the researcher.
"""

import asyncio
from collections.abc import AsyncIterator

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.service import GenerationService, Target
from qivis.models import LogprobData, TokenLogprob
from qivis.providers.base import GenerationRequest, GenerationResult, LLMProvider, StreamChunk
from qivis.rhizomes.schemas import CreateNodeRequest, CreateRhizomeRequest
from qivis.rhizomes.service import RhizomeService


def _delta(text: str) -> StreamChunk:
    return StreamChunk(type="text_delta", text=text, logprobs=LogprobData(
        tokens=[TokenLogprob(token=text, logprob=-0.2, linear_prob=0.8, top_alternatives=[])],
        provider_format="llamacpp", top_k_available=5,
    ))


class Endless(LLMProvider):
    """Says a few tokens, then keeps going until stopped."""

    supported_modes = ["completion"]

    def __init__(self, words: list[str]) -> None:
        self.words = words
        self.closed = False
        self.said = asyncio.Event()

    @property
    def name(self) -> str:
        return "endless"

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        raise AssertionError("streamed only")

    async def generate_stream(self, request: GenerationRequest) -> AsyncIterator[StreamChunk]:
        try:
            yield StreamChunk(type="prompt", result=GenerationResult(
                content="", model="m", effective_prompt_text="<BOS>" + (request.prompt_text or ""),
                applied_sampling_params={"logit_bias": {"7": -1.0}},
            ))
            for word in self.words:
                yield _delta(word)
            self.said.set()
            await asyncio.Event().wait()  # generating on and on
            yield _delta("never")
        finally:
            self.closed = True


async def _setup(db: Database, provider: LLMProvider):
    service = RhizomeService(db)
    gen = GenerationService(service, EventStore(db), StateProjector(db))
    rid = (await service.create_rhizome(CreateRhizomeRequest(
        title="t", default_provider="endless", default_model="m",
        metadata={"generation_mode": "completion", "prompt_template": "document"},
    ))).rhizome_id
    uid = (await service.create_node(rid, CreateNodeRequest(content="Once"))).node_id
    [p] = await gen.prepare(await gen.load(rid, uid), [Target(provider=provider, model="m")])
    return service, gen, rid, uid, p


async def _replies(service: RhizomeService, rid: str) -> list:
    return [n for n in (await service.get_rhizome(rid)).nodes if n.role == "assistant"]


async def _settle(gen: GenerationService) -> None:
    await asyncio.gather(*gen._background)


async def test_cancelled_stream_is_stored_with_its_record(db: Database):
    model = Endless([" upon", " a", " time"])
    service, gen, rid, uid, p = await _setup(db, model)

    async def consume():
        async for _ in gen.stream(p):
            pass

    task = asyncio.create_task(consume())
    await model.said.wait()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await _settle(gen)

    [reply] = await _replies(service, rid)
    assert reply.content == " upon a time"
    assert reply.parent_id == uid
    assert (reply.provider, reply.model, reply.mode) == ("endless", "m", "completion")
    assert reply.finish_reason == "researcher"
    assert [t["token"] for t in reply.logprobs["tokens"]] == [" upon", " a", " time"]
    assert reply.prompt_text == "<BOS>Once"  # what the model actually saw
    assert reply.sampling_params["logit_bias"] == {"7": -1.0}
    assert model.closed  # and the model's request was ended too


async def test_abandoned_stream_is_stored(db: Database):
    """A client that goes away mid-stream closes the generator instead."""
    service, gen, rid, _, p = await _setup(db, Endless([" upon", " a"]))
    stream = gen.stream(p)
    assert (await anext(stream)).text == " upon"
    await stream.aclose()
    await _settle(gen)
    [reply] = await _replies(service, rid)
    assert reply.content == " upon" and reply.finish_reason == "researcher"


async def test_stopped_before_any_text_stores_nothing(db: Database):
    model = Endless([])
    service, gen, rid, _, p = await _setup(db, model)
    task = asyncio.create_task(anext(gen.stream(p)))
    await model.said.wait()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await _settle(gen)
    assert await _replies(service, rid) == []
