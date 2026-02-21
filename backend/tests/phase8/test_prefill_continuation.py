"""Tests for Phase 8.1: Prefill / Continuation Mode.

The researcher writes a partial assistant response; the model continues from
there. The prefill text is stored separately from the model's continuation,
but the full combined text is what goes into future context.
"""

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.service import GenerationService
from qivis.main import app
from qivis.models import (
    GenerationStartedPayload,
    NodeCreatedPayload,
    SamplingParams,
)
from qivis.providers.base import (
    GenerationRequest,
    GenerationResult,
    LLMProvider,
    StreamChunk,
)
from qivis.providers.registry import clear_providers, register_provider
from qivis.trees.router import get_generation_service, get_tree_service
from qivis.trees.schemas import GenerateRequest, NodeResponse
from qivis.trees.service import TreeService
from tests.fixtures import (
    create_test_tree,
    make_node_created_envelope,
    make_tree_created_envelope,
)


# ---------------------------------------------------------------------------
# Test provider that captures its input and returns canned continuation
# ---------------------------------------------------------------------------


class CapturingProvider(LLMProvider):
    """Provider that records the messages it receives and returns a canned
    continuation. Useful for verifying that the service injects the
    trailing assistant message correctly."""

    def __init__(self, continuation: str = " is wonderful."):
        self.last_request: GenerationRequest | None = None
        self.continuation = continuation

    @property
    def name(self) -> str:
        return "fake"

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.last_request = request
        return GenerationResult(
            content=self.continuation,
            model="fake-model",
            finish_reason="end_turn",
            usage={"input_tokens": 10, "output_tokens": 5},
            latency_ms=42,
        )

    async def generate_stream(
        self, request: GenerationRequest
    ) -> AsyncIterator[StreamChunk]:
        self.last_request = request
        yield StreamChunk(type="text_delta", text=self.continuation)
        yield StreamChunk(
            type="message_stop",
            is_final=True,
            result=GenerationResult(
                content=self.continuation,
                model="fake-model",
                finish_reason="end_turn",
                usage={"input_tokens": 10, "output_tokens": 5},
                latency_ms=42,
            ),
        )


# ===================================================================
# Part 1: Contract tests — payload models
# ===================================================================


class TestPrefillPayloadModels:
    """Verify that the payload models accept prefill mode and content."""

    def test_node_created_payload_accepts_prefill_mode(self):
        payload = NodeCreatedPayload(
            node_id=str(uuid4()),
            role="assistant",
            content="I think this is great.",
            mode="prefill",
        )
        assert payload.mode == "prefill"

    def test_node_created_payload_accepts_prefill_content(self):
        payload = NodeCreatedPayload(
            node_id=str(uuid4()),
            role="assistant",
            content="I think this is great.",
            prefill_content="I think",
        )
        assert payload.prefill_content == "I think"

    def test_node_created_payload_prefill_content_defaults_none(self):
        payload = NodeCreatedPayload(
            node_id=str(uuid4()),
            role="assistant",
            content="Hello",
        )
        assert payload.prefill_content is None

    def test_generation_started_payload_accepts_prefill_mode(self):
        payload = GenerationStartedPayload(
            generation_id=str(uuid4()),
            parent_node_id=str(uuid4()),
            model="claude-sonnet-4-5-20250929",
            provider="anthropic",
            mode="prefill",
        )
        assert payload.mode == "prefill"

    def test_generation_started_payload_accepts_prefill_content(self):
        payload = GenerationStartedPayload(
            generation_id=str(uuid4()),
            parent_node_id=str(uuid4()),
            model="claude-sonnet-4-5-20250929",
            provider="anthropic",
            prefill_content="I think",
        )
        assert payload.prefill_content == "I think"

    def test_generate_request_accepts_prefill_content(self):
        req = GenerateRequest(prefill_content="I think")
        assert req.prefill_content == "I think"

    def test_generate_request_prefill_content_defaults_none(self):
        req = GenerateRequest()
        assert req.prefill_content is None


# ===================================================================
# Part 2: Contract tests — projection
# ===================================================================


class TestPrefillProjection:
    """Verify that prefill_content is stored and retrieved from the nodes table."""

    @pytest.fixture
    async def projected(self, db: Database):
        """Project a tree with a prefill node, return (projector, tree_id, node_id)."""
        store = EventStore(db)
        projector = StateProjector(db)

        tree_id = str(uuid4())
        node_id = str(uuid4())
        user_id = str(uuid4())

        tree_ev = make_tree_created_envelope(tree_id=tree_id)
        user_ev = make_node_created_envelope(
            tree_id=tree_id, node_id=user_id, role="user", content="Hello",
        )
        prefill_ev = make_node_created_envelope(
            tree_id=tree_id,
            node_id=node_id,
            parent_id=user_id,
            role="assistant",
            content="I think this is great.",
            mode="prefill",
            prefill_content="I think",
        )

        for ev in [tree_ev, user_ev, prefill_ev]:
            await store.append(ev)
        await projector.project([tree_ev, user_ev, prefill_ev])

        return projector, tree_id, node_id

    async def test_prefill_content_projected(self, projected):
        projector, tree_id, node_id = projected
        nodes = await projector.get_nodes(tree_id)
        node = next(n for n in nodes if n["node_id"] == node_id)
        assert node["prefill_content"] == "I think"

    async def test_prefill_mode_projected(self, projected):
        projector, tree_id, node_id = projected
        nodes = await projector.get_nodes(tree_id)
        node = next(n for n in nodes if n["node_id"] == node_id)
        assert node["mode"] == "prefill"

    async def test_null_prefill_content_projected(self, db: Database):
        store = EventStore(db)
        projector = StateProjector(db)
        tree_id = str(uuid4())
        node_id = str(uuid4())

        tree_ev = make_tree_created_envelope(tree_id=tree_id)
        node_ev = make_node_created_envelope(
            tree_id=tree_id, node_id=node_id, role="user", content="Hello",
        )
        for ev in [tree_ev, node_ev]:
            await store.append(ev)
        await projector.project([tree_ev, node_ev])

        nodes = await projector.get_nodes(tree_id)
        node = next(n for n in nodes if n["node_id"] == node_id)
        assert node["prefill_content"] is None

    async def test_prefill_content_on_node_response(self, projected):
        """NodeResponse includes prefill_content."""
        projector, tree_id, node_id = projected
        nodes = await projector.get_nodes(tree_id)
        node_row = next(n for n in nodes if n["node_id"] == node_id)
        sibling_info = TreeService._compute_sibling_info(nodes)
        resp = TreeService._node_from_row(node_row, sibling_info=sibling_info)
        assert resp.prefill_content == "I think"


# ===================================================================
# Part 3: Contract tests — generation service
# ===================================================================


class TestPrefillGenerationService:
    """Verify that the generation service injects the trailing assistant
    message, concatenates the result, and sets mode/prefill_content."""

    @pytest.fixture
    async def service_env(self, db: Database):
        """Set up a tree with a user node and return (gen_service, provider, tree_id, user_node_id)."""
        store = EventStore(db)
        projector = StateProjector(db)
        tree_service = TreeService(db)
        gen_service = GenerationService(tree_service, store, projector)

        tree_id = str(uuid4())
        user_id = str(uuid4())

        tree_ev = make_tree_created_envelope(tree_id=tree_id)
        user_ev = make_node_created_envelope(
            tree_id=tree_id, node_id=user_id, role="user", content="What do you think?",
        )
        for ev in [tree_ev, user_ev]:
            await store.append(ev)
        await projector.project([tree_ev, user_ev])

        provider = CapturingProvider(continuation=" is wonderful.")
        return gen_service, provider, tree_id, user_id

    async def test_prefill_injects_trailing_assistant_message(self, service_env):
        gen_service, provider, tree_id, user_id = service_env
        await gen_service.generate(
            tree_id, user_id, provider,
            prefill_content="I think life",
        )
        assert provider.last_request is not None
        last_msg = provider.last_request.messages[-1]
        assert last_msg["role"] == "assistant"
        assert last_msg["content"] == "I think life"

    async def test_prefill_concatenates_result(self, service_env):
        gen_service, provider, tree_id, user_id = service_env
        node = await gen_service.generate(
            tree_id, user_id, provider,
            prefill_content="I think life",
        )
        assert node.content == "I think life is wonderful."

    async def test_prefill_stores_prefill_content(self, service_env):
        gen_service, provider, tree_id, user_id = service_env
        node = await gen_service.generate(
            tree_id, user_id, provider,
            prefill_content="I think life",
        )
        assert node.prefill_content == "I think life"

    async def test_prefill_sets_mode(self, service_env):
        gen_service, provider, tree_id, user_id = service_env
        node = await gen_service.generate(
            tree_id, user_id, provider,
            prefill_content="I think life",
        )
        assert node.mode == "prefill"

    async def test_no_prefill_unchanged(self, service_env):
        gen_service, provider, tree_id, user_id = service_env
        node = await gen_service.generate(
            tree_id, user_id, provider,
        )
        assert provider.last_request is not None
        last_msg = provider.last_request.messages[-1]
        assert last_msg["role"] == "user"
        assert node.mode == "chat"
        assert node.prefill_content is None


# ===================================================================
# Part 4: Integration tests — HTTP endpoint
# ===================================================================


@pytest.fixture
async def prefill_client(db: Database) -> AsyncIterator[tuple[AsyncClient, CapturingProvider]]:
    """Test client with CapturingProvider wired in."""
    store = EventStore(db)
    projector = StateProjector(db)
    service = TreeService(db)
    gen_service = GenerationService(service, store, projector)

    provider = CapturingProvider(continuation=" is wonderful.")
    clear_providers()
    register_provider(provider)

    app.dependency_overrides[get_tree_service] = lambda: service
    app.dependency_overrides[get_generation_service] = lambda: gen_service

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client, provider

    app.dependency_overrides.clear()
    clear_providers()


class TestPrefillContinuationAPI:
    """End-to-end tests through the HTTP endpoint."""

    async def _create_tree_with_user_node(self, client: AsyncClient) -> tuple[str, str]:
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]
        resp = await client.post(
            f"/api/trees/{tree_id}/nodes",
            json={"content": "What do you think?", "role": "user"},
        )
        assert resp.status_code == 201
        return tree_id, resp.json()["node_id"]

    async def test_generate_with_prefill_returns_correct_node(self, prefill_client):
        client, provider = prefill_client
        tree_id, user_id = await self._create_tree_with_user_node(client)

        resp = await client.post(
            f"/api/trees/{tree_id}/nodes/{user_id}/generate",
            json={"provider": "fake", "prefill_content": "I think life"},
        )
        assert resp.status_code == 201
        node = resp.json()
        assert node["mode"] == "prefill"
        assert node["prefill_content"] == "I think life"
        assert node["content"] == "I think life is wonderful."

    async def test_prefill_node_in_tree_response(self, prefill_client):
        client, provider = prefill_client
        tree_id, user_id = await self._create_tree_with_user_node(client)

        await client.post(
            f"/api/trees/{tree_id}/nodes/{user_id}/generate",
            json={"provider": "fake", "prefill_content": "I think life"},
        )

        resp = await client.get(f"/api/trees/{tree_id}")
        assert resp.status_code == 200
        tree = resp.json()
        prefill_nodes = [n for n in tree["nodes"] if n.get("prefill_content")]
        assert len(prefill_nodes) == 1
        assert prefill_nodes[0]["prefill_content"] == "I think life"
        assert prefill_nodes[0]["content"] == "I think life is wonderful."

    async def test_streaming_with_prefill(self, prefill_client):
        client, provider = prefill_client
        tree_id, user_id = await self._create_tree_with_user_node(client)

        resp = await client.post(
            f"/api/trees/{tree_id}/nodes/{user_id}/generate",
            json={"provider": "fake", "prefill_content": "I think life", "stream": True},
        )
        assert resp.status_code == 200

        body = resp.text
        # Should contain text_delta with continuation only
        assert "text_delta" in body
        # message_stop should have the full content (prefill + continuation)
        assert "I think life is wonderful." in body

    async def test_prefill_with_n_greater_than_1_rejected(self, prefill_client):
        client, provider = prefill_client
        tree_id, user_id = await self._create_tree_with_user_node(client)

        resp = await client.post(
            f"/api/trees/{tree_id}/nodes/{user_id}/generate",
            json={"provider": "fake", "prefill_content": "I think", "n": 3},
        )
        assert resp.status_code == 400
