"""Cutting a reply short, to branch from one of its tokens.

The kept tokens are still the model's: the cut node must carry the original's
record for them (prompt, sampling, probabilities) and say only that the
researcher ended it there. And the text must be exactly what those tokens say.
"""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.service import GenerationService, Target
from qivis.main import app
from qivis.models import LogprobData, SamplingParams, TokenLogprob
from qivis.providers.base import GenerationRequest, GenerationResult, LLMProvider, StreamChunk
from qivis.rhizomes.router import get_rhizome_service
from qivis.rhizomes.schemas import CreateNodeRequest, CreateRhizomeRequest
from qivis.rhizomes.service import RhizomeService

TOKENS = [" It", " was", " cold", ".", "\n\n", "Ada", ":"]


class Base(LLMProvider):
    supported_modes = ["completion"]

    @property
    def name(self) -> str:
        return "base"

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(
            content="".join(TOKENS[:4]),  # like llama.cpp: the stop text is left out
            model="m",
            finish_reason="length",
            usage={"input_tokens": 12, "output_tokens": len(TOKENS)},
            latency_ms=30,
            effective_prompt_text="<BOS>" + (request.prompt_text or ""),
            logprobs=LogprobData(
                tokens=[TokenLogprob(token=t, logprob=-0.5, linear_prob=0.6, top_alternatives=[])
                        for t in TOKENS],
                provider_format="llamacpp",
                top_k_available=20,
            ),
        )

    async def generate_stream(self, request) -> AsyncIterator[StreamChunk]:
        raise AssertionError("not streamed")
        yield


async def _reply(db: Database, template: str):
    service = RhizomeService(db)
    gen = GenerationService(service, EventStore(db), StateProjector(db))
    rid = (await service.create_rhizome(CreateRhizomeRequest(
        title="t", default_provider="base", default_model="m",
        default_sampling_params=SamplingParams(temperature=0.9),
        metadata={"generation_mode": "completion", "prompt_template": template},
    ))).rhizome_id
    uid = (await service.create_node(rid, CreateNodeRequest(content="Frost came"))).node_id
    ctx = await gen.load(rid, uid)
    [p] = await gen.prepare(ctx, [Target(provider=Base(), model="m")])
    node = await gen.complete(p)
    return service, rid, node


async def test_cut_keeps_the_models_record(db: Database):
    service, rid, original = await _reply(db, "document")
    cut = await service.cut_node(rid, original.node_id, 3)

    assert cut.content == " It was cold"
    assert cut.parent_id == original.parent_id and cut.sibling_count == 2
    assert cut.finish_reason == "researcher"
    assert [t["token"] for t in cut.logprobs["tokens"]] == [" It", " was", " cold"]
    assert cut.prompt_text == original.prompt_text  # what the model actually saw
    assert (cut.model, cut.provider, cut.mode) == ("m", "base", "completion")
    assert cut.sampling_params == original.sampling_params
    assert cut.usage == {"input_tokens": 12, "output_tokens": 3}


async def test_cut_transcript_turn_drops_the_leading_space(db: Database):
    service, rid, original = await _reply(db, "transcript")
    assert original.content == "It was cold."
    cut = await service.cut_node(rid, original.node_id, 2)
    assert cut.content == "It was"


async def test_cut_event_names_its_origin(db: Database):
    service, rid, original = await _reply(db, "document")
    cut = await service.cut_node(rid, original.node_id, 1)
    events = await EventStore(db).get_events(rid)
    created = [e for e in events if e.event_type == "NodeCreated"][-1]
    assert created.payload["node_id"] == cut.node_id
    assert created.payload["cut_from"] == original.node_id


@pytest.mark.parametrize("keep", [0, 5, len(TOKENS)])
async def test_cut_must_fall_within_the_text(db: Database, keep: int):
    service, rid, original = await _reply(db, "document")
    app.dependency_overrides[get_rhizome_service] = lambda: service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/rhizomes/{rid}/nodes/{original.node_id}/cut", json={"keep": keep})
        assert r.status_code == 400
        user = original.parent_id
        r = await c.post(f"/api/rhizomes/{rid}/nodes/{user}/cut", json={"keep": 1})
        assert r.status_code == 400
        ok = await c.post(f"/api/rhizomes/{rid}/nodes/{original.node_id}/cut", json={"keep": 2})
        assert ok.status_code == 201 and ok.json()["content"] == " It was"
    app.dependency_overrides.clear()
