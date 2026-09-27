"""Steered generation: a researcher picks the reply token by token.

The record must say what the model thought of each token (its probability
and alternatives, from the model, never from the client) and who chose it.
"""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.service import GenerationService
from qivis.main import app
from qivis.providers.base import GenerationRequest, GenerationResult, LLMProvider, StreamChunk
from qivis.providers.registry import clear_providers, register_provider
from qivis.rhizomes.router import get_rhizome_service
from qivis.rhizomes.service import RhizomeService
from qivis.steering.router import get_steering_service
from qivis.steering.service import SteeringService

VOCAB = {1: "Hi", 2: " there", 3: "!", 4: "<|eot_id|>", 5: " friend"}


class SteerableModel(LLMProvider):
    """A completion model with a fixed next-token distribution."""

    supported_modes = ["completion"]

    def __init__(self) -> None:
        self.calls: list[tuple[list[int], int]] = []

    @property
    def name(self) -> str:
        return "steerable"

    async def next_tokens(self, request: GenerationRequest, continuation: list[int], k: int):
        self.calls.append((list(continuation), k))
        dist = [(1, 0.6), (2, 0.25), (3, 0.1), (4, 0.04), (5, 0.01)]
        return {
            "candidates": [{"id": i, "token": VOCAB[i], "bytes": None, "prob": p} for i, p in dist[:k]],
            "logit_bias": {4: 1.5},
            "effective_prompt": "<BOS><BOS>" + (request.prompt_text or ""),
        }

    async def detokenize(self, ids: list[int]) -> str:
        return "".join(VOCAB[i] for i in ids)

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        raise AssertionError("steering never samples")

    async def generate_stream(self, request) -> AsyncIterator[StreamChunk]:
        raise AssertionError("steering never samples")
        yield


class ChatOnly(SteerableModel):
    supported_modes = ["chat"]

    @property
    def name(self) -> str:
        return "chatonly"


@pytest.fixture
async def env(db: Database):
    store, projector, service = EventStore(db), StateProjector(db), RhizomeService(db)
    steering = SteeringService(GenerationService(service, store, projector))
    model = SteerableModel()
    clear_providers()
    register_provider(model)
    register_provider(ChatOnly())
    app.dependency_overrides[get_rhizome_service] = lambda: service
    app.dependency_overrides[get_steering_service] = lambda: steering
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        rid = (await c.post("/api/rhizomes", json={
            "title": "steer", "default_provider": "steerable", "default_model": "m",
            "metadata": {"prompt_template": "llama3"},
        })).json()["rhizome_id"]
        nid = (await c.post(f"/api/rhizomes/{rid}/nodes", json={"content": "hello"})).json()["node_id"]
        yield c, model, rid, nid
    app.dependency_overrides.clear()
    clear_providers()


async def _start(c, rid, nid, provider="steerable"):
    return await c.post(f"/api/rhizomes/{rid}/nodes/{nid}/steer", json={"provider": provider})


async def test_steer_and_commit_records_provenance(env):
    c, model, rid, nid = env
    s = (await _start(c, rid, nid)).json()
    assert s["prompt_text"].endswith("<|start_header_id|>assistant<|end_header_id|>\n\n")
    first = (await c.post(f"/api/steer/{s['session_id']}/next", json={"continuation": [], "k": 3})).json()
    assert [t["token"] for t in first] == ["Hi", " there", "!"]
    await c.post(f"/api/steer/{s['session_id']}/next", json={"continuation": [1], "k": 3})

    r = await c.post(f"/api/steer/{s['session_id']}/commit", json={
        "token_ids": [1, 2], "chosen_by": ["model", "researcher"],
    })
    assert r.status_code == 201, r.text
    node = r.json()
    assert node["mode"] == "steered" and node["content"] == "Hi there"
    assert node["finish_reason"] == "researcher"
    tokens = node["logprobs"]["tokens"]
    assert [(t["token"], t["chosen_by"], t["linear_prob"]) for t in tokens] == [
        ("Hi", "model", 0.6), (" there", "researcher", 0.25),
    ]
    assert [a["token"] for a in tokens[0]["top_alternatives"]][:2] == [" there", "!"]
    assert node["sampling_params"]["logit_bias"] == {"4": 1.5}
    assert node["prompt_text"].startswith("<BOS><BOS>")  # what the model actually saw


async def test_typed_token_gets_its_true_probability(env):
    c, model, rid, nid = env
    s = (await _start(c, rid, nid)).json()
    await c.post(f"/api/steer/{s['session_id']}/next", json={"continuation": [], "k": 2})
    # " friend" (id 5) was never shown at k=2: commit looks it up, not guesses
    node = (await c.post(f"/api/steer/{s['session_id']}/commit", json={
        "token_ids": [5], "chosen_by": ["researcher"],
    })).json()
    assert node["logprobs"]["tokens"][0]["linear_prob"] == 0.01
    assert model.calls[-1][1] > 1000


async def test_reaching_end_of_turn_ends_like_a_generation(env):
    c, _, rid, nid = env
    s = (await _start(c, rid, nid)).json()
    node = (await c.post(f"/api/steer/{s['session_id']}/commit", json={
        "token_ids": [1, 3, 4], "chosen_by": ["researcher", "researcher", "researcher"],
    })).json()
    assert node["content"] == "Hi!" and node["finish_reason"] == "stop"


async def test_errors(env):
    c, _, rid, nid = env
    assert (await _start(c, rid, nid, provider="chatonly")).status_code == 400
    assert (await _start(c, rid, nid, provider="nope")).status_code == 400
    r = await c.post("/api/steer/nope/next", json={"continuation": []})
    assert r.status_code == 404
    s = (await _start(c, rid, nid)).json()
    bad = await c.post(f"/api/steer/{s['session_id']}/commit", json={"token_ids": [1], "chosen_by": []})
    assert bad.status_code == 400
    # A failed commit keeps the session, so it can be retried
    ok = await c.post(f"/api/steer/{s['session_id']}/commit", json={
        "token_ids": [1], "chosen_by": ["researcher"]})
    assert ok.status_code == 201
