"""Integration tests for POST /api/trees/{id}/nodes/{nid}/generate."""

from collections.abc import AsyncIterator

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
from qivis.trees.router import get_generation_service, get_tree_service
from qivis.trees.service import TreeService


class FakeProvider(LLMProvider):
    """Test provider that returns canned responses."""

    @property
    def name(self) -> str:
        return "fake"

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(
            content="Fake response",
            model="fake-model",
            finish_reason="end_turn",
            usage={"input_tokens": 10, "output_tokens": 5},
            latency_ms=42,
        )

    async def generate_stream(
        self, request: GenerationRequest
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(type="text_delta", text="Fake ")
        yield StreamChunk(type="text_delta", text="response")
        yield StreamChunk(
            type="message_stop",
            is_final=True,
            result=GenerationResult(
                content="Fake response",
                model="fake-model",
                finish_reason="end_turn",
                usage={"input_tokens": 10, "output_tokens": 5},
                latency_ms=42,
            ),
        )


@pytest.fixture
async def gen_client(db: Database) -> AsyncIterator[AsyncClient]:
    """Test client with FakeProvider wired in."""
    store = EventStore(db)
    projector = StateProjector(db)
    service = TreeService(db)
    gen_service = GenerationService(service, store, projector)

    clear_providers()
    register_provider(FakeProvider())

    app.dependency_overrides[get_tree_service] = lambda: service
    app.dependency_overrides[get_generation_service] = lambda: gen_service

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()
    clear_providers()


class TestGenerateEndpoint:
    async def test_creates_assistant_node(self, gen_client: AsyncClient):
        """POST generate returns a new assistant node with correct fields."""
        tree = (await gen_client.post("/api/trees", json={"title": "Gen Test"})).json()
        node = (
            await gen_client.post(
                f"/api/trees/{tree['tree_id']}/nodes",
                json={"content": "Hello AI"},
            )
        ).json()

        resp = await gen_client.post(
            f"/api/trees/{tree['tree_id']}/nodes/{node['node_id']}/generate",
            json={"provider": "fake"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["role"] == "assistant"
        assert data["content"] == "Fake response"
        assert data["parent_id"] == node["node_id"]
        assert data["model"] == "fake-model"
        assert data["finish_reason"] == "end_turn"

    async def test_node_appears_in_tree(self, gen_client: AsyncClient):
        """Generated node shows up when you GET the tree."""
        tree = (await gen_client.post("/api/trees", json={"title": "Gen Test"})).json()
        node = (
            await gen_client.post(
                f"/api/trees/{tree['tree_id']}/nodes",
                json={"content": "Hello"},
            )
        ).json()

        await gen_client.post(
            f"/api/trees/{tree['tree_id']}/nodes/{node['node_id']}/generate",
            json={"provider": "fake"},
        )

        tree_detail = (await gen_client.get(f"/api/trees/{tree['tree_id']}")).json()
        nodes = tree_detail["nodes"]
        assert len(nodes) == 2
        roles = {n["role"] for n in nodes}
        assert "user" in roles
        assert "assistant" in roles

    async def test_nonexistent_tree_404(self, gen_client: AsyncClient):
        resp = await gen_client.post(
            "/api/trees/nonexistent/nodes/whatever/generate",
            json={"provider": "fake"},
        )
        assert resp.status_code == 404

    async def test_nonexistent_node_404(self, gen_client: AsyncClient):
        tree = (await gen_client.post("/api/trees", json={"title": "Test"})).json()
        resp = await gen_client.post(
            f"/api/trees/{tree['tree_id']}/nodes/nonexistent/generate",
            json={"provider": "fake"},
        )
        assert resp.status_code == 404

    async def test_unknown_provider_400(self, gen_client: AsyncClient):
        tree = (await gen_client.post("/api/trees", json={"title": "Test"})).json()
        node = (
            await gen_client.post(
                f"/api/trees/{tree['tree_id']}/nodes",
                json={"content": "Hello"},
            )
        ).json()
        resp = await gen_client.post(
            f"/api/trees/{tree['tree_id']}/nodes/{node['node_id']}/generate",
            json={"provider": "nonexistent_provider"},
        )
        assert resp.status_code == 400

    async def test_full_workflow(self, gen_client: AsyncClient):
        """Create tree → add user message → generate → tree has both messages."""
        # Create tree
        tree = (
            await gen_client.post(
                "/api/trees",
                json={"title": "Workflow Test", "default_system_prompt": "Be helpful."},
            )
        ).json()
        tree_id = tree["tree_id"]

        # Add user message
        node = (
            await gen_client.post(
                f"/api/trees/{tree_id}/nodes",
                json={"content": "What is 2+2?"},
            )
        ).json()

        # Generate
        gen_resp = await gen_client.post(
            f"/api/trees/{tree_id}/nodes/{node['node_id']}/generate",
            json={"provider": "fake"},
        )
        assert gen_resp.status_code == 201
        assistant_node = gen_resp.json()
        assert assistant_node["role"] == "assistant"
        assert assistant_node["parent_id"] == node["node_id"]

        # Verify tree has both
        tree_detail = (await gen_client.get(f"/api/trees/{tree_id}")).json()
        assert len(tree_detail["nodes"]) == 2


class TestStreamingEndpoint:
    async def test_stream_returns_sse(self, gen_client: AsyncClient):
        """Streaming mode returns SSE with text_delta and message_stop events."""
        tree = (await gen_client.post("/api/trees", json={"title": "Stream Test"})).json()
        node = (
            await gen_client.post(
                f"/api/trees/{tree['tree_id']}/nodes",
                json={"content": "Hello"},
            )
        ).json()

        resp = await gen_client.post(
            f"/api/trees/{tree['tree_id']}/nodes/{node['node_id']}/generate",
            json={"provider": "fake", "stream": True},
        )
        assert resp.status_code == 200  # StreamingResponse is 200
        assert "text/event-stream" in resp.headers["content-type"]
        body = resp.text
        assert "event: text_delta" in body
        assert "event: message_stop" in body
        assert "Fake " in body
