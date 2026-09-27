"""Contract tests for root generation: POST /api/rhizomes/{id}/generate.

A root generation gives the model the floor with no prior turns: the
provider receives an empty message list (plus any system prompt), and the
resulting assistant node has no parent. In completion mode the rendered
prompt is just the template's opening of an assistant turn.
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from httpx import ASGITransport, AsyncClient

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.service import GenerationService
from qivis.main import app
from qivis.providers.base import (
    GenerationRequest,
    GenerationResult,
    LLMProvider,
    StreamChunk,
)
from qivis.providers.registry import clear_providers, register_provider
from qivis.rhizomes.router import get_generation_service, get_rhizome_service
from qivis.rhizomes.service import RhizomeService

LLAMA3_EMPTY_PROMPT = (
    "<|begin_of_text|><|start_header_id|>assistant<|end_header_id|>\n\n"
)


# -- Fixtures --


class RootCapturingProvider(LLMProvider):
    """Dual-mode provider that records every request it receives.

    Never indexes request.messages, since a root generation sends none.
    Set fail=True to simulate a provider rejecting the request.
    """

    supported_modes = ["chat", "completion"]

    def __init__(self):
        self.requests: list[GenerationRequest] = []
        self.fail = False

    @property
    def name(self) -> str:
        return "root-capturing"

    def _result(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(
            content="opening",
            model=request.model,
            finish_reason="stop",
            usage={"input_tokens": 3, "output_tokens": 1},
            latency_ms=5,
        )

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("messages: at least one message is required")
        return self._result(request)

    async def generate_stream(
        self, request: GenerationRequest,
    ) -> AsyncIterator[StreamChunk]:
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("messages: at least one message is required")
        yield StreamChunk(type="text_delta", text="open")
        yield StreamChunk(type="text_delta", text="ing")
        yield StreamChunk(
            type="message_stop", is_final=True, result=self._result(request),
        )


@dataclass
class RootHarness:
    client: AsyncClient
    store: EventStore
    provider: RootCapturingProvider


@pytest.fixture
async def harness(db: Database) -> AsyncIterator[RootHarness]:
    store = EventStore(db)
    projector = StateProjector(db)
    service = RhizomeService(db)
    gen_service = GenerationService(service, store, projector)

    clear_providers()
    provider = RootCapturingProvider()
    register_provider(provider)

    app.dependency_overrides[get_rhizome_service] = lambda: service
    app.dependency_overrides[get_generation_service] = lambda: gen_service

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        yield RootHarness(client, store, provider)

    app.dependency_overrides.clear()
    clear_providers()


async def _create_rhizome(
    client: AsyncClient,
    *,
    system_prompt: str | None = None,
    completion_template: str | None = None,
) -> str:
    body: dict = {"title": "Root test", "default_model": "m"}
    if system_prompt is not None:
        body["default_system_prompt"] = system_prompt
    resp = await client.post("/api/rhizomes", json=body)
    assert resp.status_code == 201
    rid = resp.json()["rhizome_id"]
    if completion_template:
        resp = await client.patch(f"/api/rhizomes/{rid}", json={"metadata": {
            "generation_mode": "completion",
            "prompt_template": completion_template,
        }})
        assert resp.status_code == 200
    return rid


async def _root_generate(client: AsyncClient, rid: str, **body):
    return await client.post(
        f"/api/rhizomes/{rid}/generate",
        json={"provider": "root-capturing", **body},
    )


async def _nodes(client: AsyncClient, rid: str) -> list[dict]:
    resp = await client.get(f"/api/rhizomes/{rid}")
    assert resp.status_code == 200
    return resp.json()["nodes"]


def _parse_sse_events(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_type = ""
        data = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_type = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if event_type and data is not None:
            events.append((event_type, data))
    return events


# -- Basic contract --


class TestRootGeneration:
    async def test_empty_rhizome_creates_root_assistant_node(self, harness):
        rid = await _create_rhizome(harness.client)
        resp = await _root_generate(harness.client, rid)
        assert resp.status_code == 201
        node = resp.json()
        assert node["role"] == "assistant"
        assert node["parent_id"] is None
        assert node["content"] == "opening"
        assert [n["node_id"] for n in await _nodes(harness.client, rid)] == [node["node_id"]]

    async def test_provider_receives_empty_context(self, harness):
        rid = await _create_rhizome(harness.client)
        await _root_generate(harness.client, rid)
        request = harness.provider.requests[-1]
        assert request.messages == []
        assert request.prompt_text is None

    async def test_system_prompt_still_passes_through(self, harness):
        rid = await _create_rhizome(harness.client, system_prompt="You have the floor.")
        await _root_generate(harness.client, rid)
        request = harness.provider.requests[-1]
        assert request.messages == []
        assert request.system_prompt == "You have the floor."

    async def test_additional_root_on_nonempty_rhizome(self, harness):
        rid = await _create_rhizome(harness.client)
        resp = await harness.client.post(
            f"/api/rhizomes/{rid}/nodes", json={"content": "hi", "role": "user"},
        )
        assert resp.status_code == 201
        resp = await _root_generate(harness.client, rid)
        assert resp.status_code == 201
        assert resp.json()["parent_id"] is None
        # The earlier user message is not part of a root generation's context
        assert harness.provider.requests[-1].messages == []
        roots = [n for n in await _nodes(harness.client, rid) if n["parent_id"] is None]
        assert len(roots) == 2
        assert all(n["sibling_count"] == 2 for n in roots)

    async def test_generation_started_event_has_no_parent(self, harness):
        rid = await _create_rhizome(harness.client)
        await _root_generate(harness.client, rid)
        events = await harness.store.get_events(rid)
        started = [e for e in events if e.event_type == "GenerationStarted"]
        assert len(started) == 1
        assert started[0].payload["parent_node_id"] is None
        created = [
            e for e in events
            if e.event_type == "NodeCreated" and e.payload["role"] == "assistant"
        ]
        assert created[0].payload["parent_id"] is None


# -- Completion mode --


class TestRootCompletionMode:
    async def test_llama3_prompt_is_just_the_open_assistant_turn(self, harness):
        rid = await _create_rhizome(harness.client, completion_template="llama3")
        resp = await _root_generate(harness.client, rid)
        assert resp.status_code == 201
        assert harness.provider.requests[-1].prompt_text == LLAMA3_EMPTY_PROMPT
        assert resp.json()["prompt_text"] == LLAMA3_EMPTY_PROMPT
        assert resp.json()["mode"] == "completion"

    async def test_llama3_system_prompt_precedes_assistant_turn(self, harness):
        rid = await _create_rhizome(
            harness.client, system_prompt="Hello, Sun.", completion_template="llama3",
        )
        await _root_generate(harness.client, rid)
        assert harness.provider.requests[-1].prompt_text == (
            "<|begin_of_text|>"
            "<|start_header_id|>system<|end_header_id|>\n\nHello, Sun.<|eot_id|>"
            "<|start_header_id|>assistant<|end_header_id|>\n\n"
        )

    async def test_prefill_at_root(self, harness):
        rid = await _create_rhizome(harness.client, completion_template="llama3")
        resp = await _root_generate(harness.client, rid, prefill_content="Well, ")
        assert resp.status_code == 201
        node = resp.json()
        assert node["mode"] == "prefill"
        assert node["content"] == "Well, opening"
        assert harness.provider.requests[-1].prompt_text == LLAMA3_EMPTY_PROMPT + "Well, "


# -- Streaming and n > 1 --


class TestRootStreamingAndN:
    async def test_streaming_root(self, harness):
        rid = await _create_rhizome(harness.client)
        resp = await _root_generate(harness.client, rid, stream=True)
        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)
        deltas = [d["text"] for t, d in events if t == "text_delta"]
        assert "".join(deltas) == "opening"
        stops = [d for t, d in events if t == "message_stop"]
        assert len(stops) == 1
        nodes = await _nodes(harness.client, rid)
        assert [n["node_id"] for n in nodes] == [stops[0]["node_id"]]
        assert nodes[0]["parent_id"] is None

    async def test_n_creates_sibling_roots(self, harness):
        rid = await _create_rhizome(harness.client)
        resp = await _root_generate(harness.client, rid, n=3)
        assert resp.status_code == 201
        nodes = await _nodes(harness.client, rid)
        assert len(nodes) == 3
        assert all(n["parent_id"] is None and n["role"] == "assistant" for n in nodes)
        assert all(n["sibling_count"] == 3 for n in nodes)

    async def test_streaming_n_creates_sibling_roots(self, harness):
        rid = await _create_rhizome(harness.client)
        resp = await _root_generate(harness.client, rid, n=3, stream=True)
        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)
        assert not [d for t, d in events if t == "error"]
        nodes = await _nodes(harness.client, rid)
        assert len(nodes) == 3
        assert all(n["parent_id"] is None for n in nodes)


# -- Errors --


class TestRootErrors:
    async def test_unknown_rhizome_404(self, harness):
        resp = await _root_generate(harness.client, "no-such-rhizome")
        assert resp.status_code == 404

    async def test_unknown_provider_400(self, harness):
        rid = await _create_rhizome(harness.client)
        resp = await harness.client.post(
            f"/api/rhizomes/{rid}/generate", json={"provider": "nope"},
        )
        assert resp.status_code == 400

    async def test_prefill_with_n_400(self, harness):
        rid = await _create_rhizome(harness.client)
        resp = await _root_generate(harness.client, rid, n=2, prefill_content="x")
        assert resp.status_code == 400

    async def test_provider_rejection_surfaces_as_502(self, harness):
        """E.g. a chat API that requires at least one message."""
        rid = await _create_rhizome(harness.client)
        harness.provider.fail = True
        resp = await _root_generate(harness.client, rid)
        assert resp.status_code == 502
        assert "at least one message" in resp.json()["detail"]
        assert await _nodes(harness.client, rid) == []

    async def test_provider_rejection_surfaces_as_sse_error(self, harness):
        rid = await _create_rhizome(harness.client)
        harness.provider.fail = True
        resp = await _root_generate(harness.client, rid, stream=True)
        events = _parse_sse_events(resp.text)
        errors = [d for t, d in events if t == "error"]
        assert errors and "at least one message" in errors[0]["error"]

    async def test_node_route_still_404s_for_missing_node(self, harness):
        rid = await _create_rhizome(harness.client)
        resp = await harness.client.post(
            f"/api/rhizomes/{rid}/nodes/no-such-node/generate",
            json={"provider": "root-capturing"},
        )
        assert resp.status_code == 404
