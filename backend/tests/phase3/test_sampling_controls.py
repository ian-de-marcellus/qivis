"""Tests for Phase 3.3: Sampling Controls — merge resolution.

Covers merge_sampling_params() layering (request > tree defaults > base),
_parse_json_field() utility, backward compat for metadata.extended_thinking,
and integration with _resolve_context() via GenerationService.
"""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.service import GenerationService, merge_sampling_params
from qivis.models import SamplingParams
from qivis.providers.base import (
    GenerationRequest,
    GenerationResult,
    LLMProvider,
    StreamChunk,
)
from qivis.providers.registry import clear_providers, register_provider
from qivis.main import app
from qivis.trees.router import get_generation_service, get_tree_service
from qivis.trees.service import TreeService

from tests.fixtures import make_node_created_envelope, make_tree_created_envelope


# ---------------------------------------------------------------------------
# Unit tests: merge_sampling_params
# ---------------------------------------------------------------------------


class TestMergeSamplingParams:
    """Pure unit tests for the three-layer merge function."""

    def test_no_request_no_tree_defaults_returns_base(self):
        """With nothing supplied, result is a fresh SamplingParams()."""
        result = merge_sampling_params(None, None)
        base = SamplingParams()
        assert result.temperature == base.temperature
        assert result.top_p == base.top_p
        assert result.max_tokens == base.max_tokens
        assert result.extended_thinking == base.extended_thinking

    def test_tree_defaults_applied(self):
        """Tree-level defaults override the base."""
        tree_defaults = json.dumps({"temperature": 0.7, "top_p": 0.9})
        result = merge_sampling_params(None, tree_defaults)
        assert result.temperature == 0.7
        assert result.top_p == 0.9
        # Untouched fields stay at base
        assert result.max_tokens == SamplingParams().max_tokens

    def test_tree_defaults_as_dict(self):
        """Tree defaults can be passed as a dict (not just JSON string)."""
        result = merge_sampling_params(None, {"temperature": 0.3})
        assert result.temperature == 0.3

    def test_request_overrides_tree_defaults(self):
        """Explicitly-set request fields override tree defaults."""
        tree_defaults = json.dumps({"temperature": 0.7, "top_p": 0.9})
        request = SamplingParams(temperature=0.0)
        result = merge_sampling_params(request, tree_defaults)
        assert result.temperature == 0.0
        # top_p preserved from tree
        assert result.top_p == 0.9

    def test_partial_request_preserves_tree_defaults(self):
        """Fields not explicitly set in the request don't clobber tree defaults."""
        tree_defaults = {"temperature": 0.7, "top_k": 40, "max_tokens": 4096}
        # Only set top_k in request
        request = SamplingParams(top_k=50)
        result = merge_sampling_params(request, tree_defaults)
        assert result.top_k == 50  # overridden
        assert result.temperature == 0.7  # preserved from tree
        assert result.max_tokens == 4096  # preserved from tree

    def test_extended_thinking_from_tree_defaults(self):
        """Tree-level extended_thinking propagates through."""
        tree_defaults = {"extended_thinking": True, "thinking_budget": 8000}
        result = merge_sampling_params(None, tree_defaults)
        assert result.extended_thinking is True
        assert result.thinking_budget == 8000

    def test_request_overrides_extended_thinking(self):
        """Request can override tree-level extended_thinking."""
        tree_defaults = {"extended_thinking": True, "thinking_budget": 8000}
        request = SamplingParams(extended_thinking=False)
        result = merge_sampling_params(request, tree_defaults)
        assert result.extended_thinking is False
        # thinking_budget still from tree since not overridden
        assert result.thinking_budget == 8000

    def test_backward_compat_metadata_thinking(self):
        """When no tree defaults exist, metadata.extended_thinking is used."""
        metadata = {"extended_thinking": True, "thinking_budget": 10000}
        result = merge_sampling_params(None, None, metadata=metadata)
        assert result.extended_thinking is True
        assert result.thinking_budget == 10000

    def test_tree_defaults_take_priority_over_metadata(self):
        """Proper default_sampling_params wins over metadata hack."""
        tree_defaults = {"temperature": 0.5}
        metadata = {"extended_thinking": True, "thinking_budget": 5000}
        result = merge_sampling_params(None, tree_defaults, metadata=metadata)
        assert result.temperature == 0.5
        # metadata.extended_thinking is NOT applied when tree_defaults exist
        assert result.extended_thinking is False

    def test_null_tree_defaults_string(self):
        """A literal 'null' JSON string is treated as no defaults."""
        result = merge_sampling_params(None, "null")
        assert result.temperature == SamplingParams().temperature

    def test_malformed_tree_defaults_ignored(self):
        """Malformed JSON string is treated as no defaults."""
        result = merge_sampling_params(None, "not valid json")
        assert result.temperature == SamplingParams().temperature

    def test_all_three_layers(self):
        """Full three-layer merge: base < tree < request."""
        tree_defaults = {
            "temperature": 0.7,
            "top_p": 0.95,
            "max_tokens": 4096,
            "frequency_penalty": 0.5,
        }
        request = SamplingParams(temperature=1.0, max_tokens=8192)
        result = merge_sampling_params(request, tree_defaults)
        assert result.temperature == 1.0  # from request
        assert result.top_p == 0.95  # from tree
        assert result.max_tokens == 8192  # from request
        assert result.frequency_penalty == 0.5  # from tree


# ---------------------------------------------------------------------------
# Integration tests: _resolve_context with merge
# ---------------------------------------------------------------------------


class CapturingProvider(LLMProvider):
    """Provider that captures the GenerationRequest it receives."""

    def __init__(self):
        self.last_request: GenerationRequest | None = None

    @property
    def name(self) -> str:
        return "capturing"

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.last_request = request
        return GenerationResult(
            content="ok", model=request.model,
            finish_reason="end_turn",
            usage={"input_tokens": 5, "output_tokens": 2},
            latency_ms=10,
        )

    async def generate_stream(
        self, request: GenerationRequest,
    ) -> AsyncIterator[StreamChunk]:
        self.last_request = request
        yield StreamChunk(
            type="message_stop", is_final=True,
            result=GenerationResult(
                content="ok", model=request.model,
                finish_reason="end_turn",
                usage={"input_tokens": 5, "output_tokens": 2},
                latency_ms=10,
            ),
        )


@pytest.fixture
async def gen_client(db: Database) -> AsyncIterator[AsyncClient]:
    """Test client with CapturingProvider."""
    store = EventStore(db)
    projector = StateProjector(db)
    service = TreeService(db)
    gen_service = GenerationService(service, store, projector)

    clear_providers()
    provider = CapturingProvider()
    register_provider(provider)

    app.dependency_overrides[get_tree_service] = lambda: service
    app.dependency_overrides[get_generation_service] = lambda: gen_service

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()
    clear_providers()


class TestResolveContextMerge:
    """Integration: tree defaults merge into resolved params via the API."""

    async def test_tree_with_default_sampling_params(self, gen_client: AsyncClient):
        """Tree-level default_sampling_params are used when request has none."""
        # Create tree with default_sampling_params
        resp = await gen_client.post("/api/trees", json={
            "title": "Sampling Test",
            "default_sampling_params": {"temperature": 0.7, "top_p": 0.9},
        })
        assert resp.status_code == 201
        tree = resp.json()

        # Add a user node
        node_resp = await gen_client.post(
            f"/api/trees/{tree['tree_id']}/nodes",
            json={"content": "Hello"},
        )
        node = node_resp.json()

        # Generate with no sampling_params override
        gen_resp = await gen_client.post(
            f"/api/trees/{tree['tree_id']}/nodes/{node['node_id']}/generate",
            json={"provider": "capturing"},
        )
        assert gen_resp.status_code == 201
        data = gen_resp.json()
        sp = data.get("sampling_params", {})
        assert sp["temperature"] == 0.7
        assert sp["top_p"] == 0.9

    async def test_request_overrides_tree_defaults_via_api(self, gen_client: AsyncClient):
        """Request-level sampling_params override tree defaults."""
        resp = await gen_client.post("/api/trees", json={
            "title": "Override Test",
            "default_sampling_params": {"temperature": 0.7},
        })
        tree = resp.json()

        node_resp = await gen_client.post(
            f"/api/trees/{tree['tree_id']}/nodes",
            json={"content": "Hello"},
        )
        node = node_resp.json()

        gen_resp = await gen_client.post(
            f"/api/trees/{tree['tree_id']}/nodes/{node['node_id']}/generate",
            json={
                "provider": "capturing",
                "sampling_params": {"temperature": 0.0},
            },
        )
        assert gen_resp.status_code == 201
        data = gen_resp.json()
        sp = data.get("sampling_params", {})
        assert sp["temperature"] == 0.0

    async def test_metadata_thinking_backward_compat(self, gen_client: AsyncClient):
        """metadata.extended_thinking works when no default_sampling_params set.

        This covers trees that have thinking enabled via metadata (the old way)
        but haven't been migrated to default_sampling_params yet.
        """
        # Create tree, then PATCH metadata to set extended_thinking
        resp = await gen_client.post("/api/trees", json={
            "title": "Thinking Compat Test",
        })
        tree = resp.json()

        patch_resp = await gen_client.patch(
            f"/api/trees/{tree['tree_id']}",
            json={"metadata": {"extended_thinking": True, "thinking_budget": 5000}},
        )
        assert patch_resp.status_code == 200

        node_resp = await gen_client.post(
            f"/api/trees/{tree['tree_id']}/nodes",
            json={"content": "Think about this"},
        )
        node = node_resp.json()

        gen_resp = await gen_client.post(
            f"/api/trees/{tree['tree_id']}/nodes/{node['node_id']}/generate",
            json={"provider": "capturing"},
        )
        assert gen_resp.status_code == 201
        data = gen_resp.json()
        sp = data.get("sampling_params", {})
        assert sp["extended_thinking"] is True
        assert sp["thinking_budget"] == 5000
