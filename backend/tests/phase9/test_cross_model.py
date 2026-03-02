"""Integration tests for replay and cross-model generation through the API (Phase 9.2a).

Tests streaming SSE, endpoint behavior, and context handling across replay modes.
"""

import json
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.replay import ReplayService
from qivis.generation.service import GenerationService
from qivis.models import LogprobData, TokenLogprob
from qivis.providers.base import (
    GenerationRequest,
    GenerationResult,
    LLMProvider,
    StreamChunk,
)
from qivis.providers.registry import clear_providers, register_provider
from qivis.main import app
from qivis.rhizomes.router import get_generation_service, get_replay_service, get_rhizome_service
from qivis.rhizomes.service import RhizomeService
from tests.fixtures import create_rhizome_with_messages


# -- Mock providers --


class RecordingProvider(LLMProvider):
    """Provider that records calls and returns identifiable responses."""

    supported_modes = ["chat"]
    supported_params = ["temperature", "max_tokens"]

    def __init__(self, name_str: str, prefix: str):
        self._name = name_str
        self._prefix = prefix
        self.calls: list[GenerationRequest] = []

    @property
    def name(self) -> str:
        return self._name

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.calls.append(request)
        content = f"{self._prefix} response"
        return GenerationResult(
            content=content,
            model=request.model,
            finish_reason="end_turn",
            usage={"input_tokens": 20, "output_tokens": 10},
            latency_ms=50,
            logprobs=LogprobData(
                tokens=[TokenLogprob(token="hi", logprob=-0.05, linear_prob=0.95, top_alternatives=[])],
                provider_format="mock",
                top_k_available=0,
            ),
        )

    async def generate_stream(
        self, request: GenerationRequest
    ) -> AsyncIterator[StreamChunk]:
        result = await self.generate(request)
        yield StreamChunk(type="text_delta", text=result.content)
        yield StreamChunk(
            type="message_stop",
            is_final=True,
            result=result,
        )


# -- Fixtures --


@pytest.fixture
async def api_client(db: Database) -> AsyncIterator[tuple[AsyncClient, dict]]:
    """Test client with two recording providers."""
    store = EventStore(db)
    projector = StateProjector(db)
    rhizome_svc = RhizomeService(db)
    gen_svc = GenerationService(rhizome_svc, store, projector)

    provider_x = RecordingProvider("provider-x", "X:")
    provider_y = RecordingProvider("provider-y", "Y:")

    clear_providers()
    register_provider(provider_x)
    register_provider(provider_y)

    replay_svc = ReplayService(rhizome_svc, gen_svc, store, projector)

    app.dependency_overrides[get_rhizome_service] = lambda: rhizome_svc
    app.dependency_overrides[get_generation_service] = lambda: gen_svc
    app.dependency_overrides[get_replay_service] = lambda: replay_svc

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client, {"provider_x": provider_x, "provider_y": provider_y}

    app.dependency_overrides.clear()
    clear_providers()


async def _create_conversation(client: AsyncClient) -> dict:
    """Create a 4-message conversation and return rhizome_id + node_ids."""
    data = await create_rhizome_with_messages(client, n_messages=4)
    return data


# ---------------------------------------------------------------------------
# Cross-model API endpoint tests
# ---------------------------------------------------------------------------


class TestCrossModelEndpoint:
    """Tests for POST /api/rhizomes/{id}/nodes/{nid}/generate-cross."""

    async def test_cross_model_endpoint_creates_siblings(self, api_client):
        """Non-streaming cross-model creates sibling nodes from different providers."""
        client, providers = api_client
        conv = await _create_conversation(client)

        # Cross-model from the last node
        last_node = conv["node_ids"][-1]
        resp = await client.post(
            f"/api/rhizomes/{conv['rhizome_id']}/nodes/{last_node}/generate-cross",
            json={
                "targets": [
                    {"provider": "provider-x", "model": "x-model"},
                    {"provider": "provider-y", "model": "y-model"},
                ],
                "stream": False,
            },
        )

        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 2

        # Both should be children of last_node
        for r in results:
            assert r["parent_id"] == last_node
            assert r["role"] == "assistant"

        # Different providers
        provider_names = {r["provider"] for r in results}
        assert provider_names == {"provider-x", "provider-y"}

    async def test_cross_model_respects_exclusions(self, api_client):
        """Cross-model generation respects context exclusions on the rhizome."""
        client, providers = api_client
        conv = await _create_conversation(client)

        # Exclude the second message (assistant, index 1)
        second_node = conv["node_ids"][1]
        last_node = conv["node_ids"][-1]

        await client.post(
            f"/api/rhizomes/{conv['rhizome_id']}/nodes/{second_node}/exclude",
            json={"scope_node_id": last_node},
        )

        resp = await client.post(
            f"/api/rhizomes/{conv['rhizome_id']}/nodes/{last_node}/generate-cross",
            json={
                "targets": [
                    {"provider": "provider-x", "model": "x-model"},
                ],
                "stream": False,
            },
        )

        assert resp.status_code == 200
        # The excluded node should not be in the context that was sent to provider
        # We can verify via the provider's recorded calls
        provider_x = providers["provider_x"]
        assert len(provider_x.calls) >= 1
        last_call = provider_x.calls[-1]
        # The excluded message should not appear in the messages
        msg_contents = [m["content"] for m in last_call.messages]
        assert "Message 2" not in msg_contents


# ---------------------------------------------------------------------------
# Replay API endpoint tests
# ---------------------------------------------------------------------------


class TestReplayEndpoint:
    """Tests for POST /api/rhizomes/{id}/replay."""

    async def test_replay_endpoint_non_streaming(self, api_client):
        """Non-streaming replay creates a complete parallel branch."""
        client, providers = api_client
        conv = await _create_conversation(client)

        resp = await client.post(
            f"/api/rhizomes/{conv['rhizome_id']}/replay",
            json={
                "path_node_ids": conv["node_ids"],
                "provider": "provider-y",
                "model": "y-model",
                "mode": "context_faithful",
                "stream": False,
            },
        )

        assert resp.status_code == 200
        results = resp.json()
        # 4 nodes: 2 user copies + 2 assistant generations
        assert len(results) == 4
        roles = [r["role"] for r in results]
        assert roles == ["user", "assistant", "user", "assistant"]

    async def test_replay_context_faithful_endpoint(self, api_client):
        """Context-faithful replay gives the model original assistant messages in context."""
        client, providers = api_client
        conv = await _create_conversation(client)

        resp = await client.post(
            f"/api/rhizomes/{conv['rhizome_id']}/replay",
            json={
                "path_node_ids": conv["node_ids"],
                "provider": "provider-x",
                "model": "x-model",
                "mode": "context_faithful",
                "stream": False,
            },
        )

        assert resp.status_code == 200

        provider_x = providers["provider_x"]
        # Provider was called twice (for each assistant message to regenerate)
        assert len(provider_x.calls) == 2

        # Second call should contain original assistant message in context
        second_call = provider_x.calls[1]
        assistant_msgs = [m for m in second_call.messages if m["role"] == "assistant"]
        # Original assistant content is "Message 2" (from create_rhizome_with_messages)
        assert any("Message 2" in m["content"] for m in assistant_msgs)

    async def test_replay_trajectory_endpoint(self, api_client):
        """Trajectory replay gives the model its own prior responses in context."""
        client, providers = api_client
        conv = await _create_conversation(client)

        resp = await client.post(
            f"/api/rhizomes/{conv['rhizome_id']}/replay",
            json={
                "path_node_ids": conv["node_ids"],
                "provider": "provider-x",
                "model": "x-model",
                "mode": "trajectory",
                "stream": False,
            },
        )

        assert resp.status_code == 200

        provider_x = providers["provider_x"]
        assert len(provider_x.calls) == 2

        # Second call should contain provider_x's OWN first response, not the original
        second_call = provider_x.calls[1]
        assistant_msgs = [m for m in second_call.messages if m["role"] == "assistant"]
        # Provider X's responses start with "X:"
        assert any("X:" in m["content"] for m in assistant_msgs)

    async def test_replay_invalid_path_returns_400(self, api_client):
        """Replay with empty or invalid path returns 400."""
        client, _ = api_client
        conv = await _create_conversation(client)

        resp = await client.post(
            f"/api/rhizomes/{conv['rhizome_id']}/replay",
            json={
                "path_node_ids": [],
                "provider": "provider-x",
                "model": "x-model",
                "stream": False,
            },
        )

        assert resp.status_code == 400

    async def test_partial_replay_leaves_valid_branch(self, api_client):
        """A replay of only the first 2 messages creates a valid partial branch."""
        client, providers = api_client
        conv = await _create_conversation(client)

        # Replay only first 2 messages (user + assistant)
        resp = await client.post(
            f"/api/rhizomes/{conv['rhizome_id']}/replay",
            json={
                "path_node_ids": conv["node_ids"][:2],
                "provider": "provider-y",
                "model": "y-model",
                "stream": False,
            },
        )

        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 2
        assert results[0]["role"] == "user"
        assert results[1]["role"] == "assistant"
        # The partial branch is valid — can fetch the rhizome and see the new nodes
        detail_resp = await client.get(f"/api/rhizomes/{conv['rhizome_id']}")
        assert detail_resp.status_code == 200
        all_nodes = detail_resp.json()["nodes"]
        # Original 4 + 2 new = 6
        assert len(all_nodes) == 6
