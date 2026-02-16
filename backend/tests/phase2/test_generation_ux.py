"""Contract tests for generation UX improvements (Phase 2.2).

Tests n>1 generation: schema validation, sibling creation, metadata correctness.
"""

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


class CountingProvider(LLMProvider):
    """Test provider that returns numbered responses for n>1 testing."""

    def __init__(self) -> None:
        self._call_count = 0

    @property
    def name(self) -> str:
        return "counting"

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self._call_count += 1
        return GenerationResult(
            content=f"Response {self._call_count}",
            model="counting-model",
            finish_reason="end_turn",
            usage={"input_tokens": 10, "output_tokens": 5},
            latency_ms=42,
        )

    async def generate_stream(
        self, request: GenerationRequest
    ) -> AsyncIterator[StreamChunk]:
        self._call_count += 1
        text = f"Response {self._call_count}"
        yield StreamChunk(type="text_delta", text=text)
        yield StreamChunk(
            type="message_stop",
            is_final=True,
            result=GenerationResult(
                content=text,
                model="counting-model",
                finish_reason="end_turn",
                usage={"input_tokens": 10, "output_tokens": 5},
                latency_ms=42,
            ),
        )


@pytest.fixture
async def gen_client(db: Database) -> AsyncIterator[AsyncClient]:
    """Test client with CountingProvider wired in."""
    store = EventStore(db)
    projector = StateProjector(db)
    service = TreeService(db)
    gen_service = GenerationService(service, store, projector)

    clear_providers()
    register_provider(CountingProvider())

    app.dependency_overrides[get_tree_service] = lambda: service
    app.dependency_overrides[get_generation_service] = lambda: gen_service

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()
    clear_providers()


async def _setup_tree_with_user_node(client: AsyncClient) -> tuple[str, str]:
    """Create a tree and a user node, return (tree_id, node_id)."""
    tree = (await client.post("/api/trees", json={"title": "N>1 Test"})).json()
    tree_id = tree["tree_id"]
    node = (
        await client.post(
            f"/api/trees/{tree_id}/nodes",
            json={"content": "Hello"},
        )
    ).json()
    return tree_id, node["node_id"]


class TestGenerateNSchema:
    """GenerateRequest schema accepts n field."""

    async def test_n_defaults_to_1(self, gen_client: AsyncClient):
        """Without n field, generation produces 1 node (backward compat)."""
        tree_id, node_id = await _setup_tree_with_user_node(gen_client)

        resp = await gen_client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/generate",
            json={"provider": "counting"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["role"] == "assistant"

        # Verify only 1 assistant node in tree
        tree = (await gen_client.get(f"/api/trees/{tree_id}")).json()
        assistant_nodes = [n for n in tree["nodes"] if n["role"] == "assistant"]
        assert len(assistant_nodes) == 1

    async def test_n_accepted_in_request(self, gen_client: AsyncClient):
        """Request with n=1 is accepted and behaves normally."""
        tree_id, node_id = await _setup_tree_with_user_node(gen_client)

        resp = await gen_client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/generate",
            json={"provider": "counting", "n": 1},
        )
        assert resp.status_code == 201

    async def test_n_zero_rejected(self, gen_client: AsyncClient):
        """n=0 is rejected by validation."""
        tree_id, node_id = await _setup_tree_with_user_node(gen_client)

        resp = await gen_client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/generate",
            json={"provider": "counting", "n": 0},
        )
        assert resp.status_code == 422

    async def test_n_negative_rejected(self, gen_client: AsyncClient):
        """n=-1 is rejected by validation."""
        tree_id, node_id = await _setup_tree_with_user_node(gen_client)

        resp = await gen_client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/generate",
            json={"provider": "counting", "n": -1},
        )
        assert resp.status_code == 422

    async def test_n_over_max_rejected(self, gen_client: AsyncClient):
        """n=11 exceeds max (10) and is rejected."""
        tree_id, node_id = await _setup_tree_with_user_node(gen_client)

        resp = await gen_client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/generate",
            json={"provider": "counting", "n": 11},
        )
        assert resp.status_code == 422


class TestGenerateNCreation:
    """n>1 creates the correct number of sibling nodes."""

    async def test_n3_creates_3_siblings(self, gen_client: AsyncClient):
        """n=3 creates 3 assistant nodes as siblings of the same parent."""
        tree_id, node_id = await _setup_tree_with_user_node(gen_client)

        resp = await gen_client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/generate",
            json={"provider": "counting", "n": 3},
        )
        assert resp.status_code == 201

        # Verify 3 assistant nodes exist
        tree = (await gen_client.get(f"/api/trees/{tree_id}")).json()
        assistant_nodes = [n for n in tree["nodes"] if n["role"] == "assistant"]
        assert len(assistant_nodes) == 3

        # All share the same parent_id
        parent_ids = {n["parent_id"] for n in assistant_nodes}
        assert parent_ids == {node_id}

    async def test_n3_sibling_metadata_correct(self, gen_client: AsyncClient):
        """n=3 siblings have correct sibling_count=3 and distinct sibling_index."""
        tree_id, node_id = await _setup_tree_with_user_node(gen_client)

        await gen_client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/generate",
            json={"provider": "counting", "n": 3},
        )

        tree = (await gen_client.get(f"/api/trees/{tree_id}")).json()
        assistant_nodes = [n for n in tree["nodes"] if n["role"] == "assistant"]

        # All should have sibling_count = 3
        for node in assistant_nodes:
            assert node["sibling_count"] == 3

        # Indices should be {0, 1, 2}
        indices = {n["sibling_index"] for n in assistant_nodes}
        assert indices == {0, 1, 2}

    async def test_n3_each_has_distinct_content(self, gen_client: AsyncClient):
        """n=3 produces 3 nodes with distinct content (provider called 3 times)."""
        tree_id, node_id = await _setup_tree_with_user_node(gen_client)

        await gen_client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/generate",
            json={"provider": "counting", "n": 3},
        )

        tree = (await gen_client.get(f"/api/trees/{tree_id}")).json()
        assistant_nodes = [n for n in tree["nodes"] if n["role"] == "assistant"]
        contents = {n["content"] for n in assistant_nodes}

        # CountingProvider returns "Response 1", "Response 2", "Response 3"
        assert len(contents) == 3

    async def test_n3_returns_first_node(self, gen_client: AsyncClient):
        """n=3 endpoint returns the first generated node (not all 3)."""
        tree_id, node_id = await _setup_tree_with_user_node(gen_client)

        resp = await gen_client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/generate",
            json={"provider": "counting", "n": 3},
        )
        data = resp.json()

        # Response is a single node
        assert "node_id" in data
        assert data["role"] == "assistant"
        assert data["parent_id"] == node_id

    async def test_n2_adds_to_existing_siblings(self, gen_client: AsyncClient):
        """n=2 after an existing generation creates 3 total siblings."""
        tree_id, node_id = await _setup_tree_with_user_node(gen_client)

        # First generation: 1 response
        await gen_client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/generate",
            json={"provider": "counting", "n": 1},
        )

        # Second generation: 2 more responses
        await gen_client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/generate",
            json={"provider": "counting", "n": 2},
        )

        tree = (await gen_client.get(f"/api/trees/{tree_id}")).json()
        assistant_nodes = [n for n in tree["nodes"] if n["role"] == "assistant"]
        assert len(assistant_nodes) == 3

        # Sibling metadata should reflect total count
        for node in assistant_nodes:
            assert node["sibling_count"] == 3


class TestGenerateNStreamingRejected:
    """Streaming + n>1 is rejected until Phase 2.2b."""

    async def test_streaming_n2_returns_400(self, gen_client: AsyncClient):
        """stream=true with n=2 returns 400."""
        tree_id, node_id = await _setup_tree_with_user_node(gen_client)

        resp = await gen_client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/generate",
            json={"provider": "counting", "n": 2, "stream": True},
        )
        assert resp.status_code == 400

    async def test_streaming_n1_still_works(self, gen_client: AsyncClient):
        """stream=true with n=1 (default) still works fine."""
        tree_id, node_id = await _setup_tree_with_user_node(gen_client)

        resp = await gen_client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/generate",
            json={"provider": "counting", "n": 1, "stream": True},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
