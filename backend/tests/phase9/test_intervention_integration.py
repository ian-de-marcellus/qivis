"""Integration tests for context intervention pipeline (Phase 9.1a).

Tests the full flow: interventions configured in rhizome metadata → resolved
by GenerationService → applied during generation → snapshotted on node.
"""

import pytest

from tests.fixtures import (
    create_rhizome_with_messages,
    create_test_rhizome,
)


class TestInterventionSnapshotPersistence:
    """Tests that active_interventions is persisted on nodes."""

    async def test_node_without_interventions_has_null(self, client):
        """Nodes created without interventions have null active_interventions."""
        info = await create_rhizome_with_messages(client, n_messages=2)
        rhizome_id = info["rhizome_id"]

        resp = await client.get(f"/api/rhizomes/{rhizome_id}")
        data = resp.json()
        # User-created nodes should have null active_interventions
        for node in data["nodes"]:
            assert node.get("active_interventions") is None

    async def test_node_created_with_interventions_via_event(self, client, event_store, projector):
        """An assistant node with active_interventions set persists through the event pipeline."""
        from uuid import uuid4
        from datetime import UTC, datetime
        from qivis.models import EventEnvelope, NodeCreatedPayload

        rhizome = await create_test_rhizome(client)
        rhizome_id = rhizome["rhizome_id"]

        # Create a user node first
        user_resp = await client.post(
            f"/api/rhizomes/{rhizome_id}/nodes",
            json={"role": "user", "content": "Hello", "parent_id": None},
        )
        user_node = user_resp.json()

        # Simulate an assistant node with active_interventions via event
        node_id = str(uuid4())
        interventions = [
            {"type": "system_prompt_reposition", "config": {"placement": "first_user_message"}},
        ]
        payload = NodeCreatedPayload(
            node_id=node_id,
            parent_id=user_node["node_id"],
            role="assistant",
            content="Hi there!",
            model="test-model",
            provider="test",
            active_interventions=interventions,
        )
        envelope = EventEnvelope(
            event_id=str(uuid4()),
            rhizome_id=rhizome_id,
            timestamp=datetime.now(UTC),
            device_id="test",
            event_type="NodeCreated",
            payload=payload.model_dump(),
        )
        await event_store.append(envelope)
        await projector.project([envelope])

        resp = await client.get(f"/api/rhizomes/{rhizome_id}")
        data = resp.json()
        assistant_node = next(n for n in data["nodes"] if n["node_id"] == node_id)
        assert assistant_node["active_interventions"] == interventions


class TestInterventionTypesEndpoint:
    """Tests for GET /api/intervention-types."""

    async def test_intervention_types_returns_list(self, client):
        resp = await client.get("/api/intervention-types")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        # Should have at least zero types (built-in types added in 9.1b)
        for item in data:
            assert "type_name" in item
            assert "phase" in item
            assert "description" in item

    async def test_intervention_types_has_expected_fields(self, client):
        resp = await client.get("/api/intervention-types")
        data = resp.json()
        for item in data:
            assert isinstance(item["type_name"], str)
            assert item["phase"] in ("pre_eviction", "post_eviction")


class TestInterventionResolution:
    """Tests that interventions configured in rhizome metadata are resolved."""

    async def test_metadata_with_empty_interventions(self, client):
        """Rhizome with empty context_interventions list works normally."""
        rhizome = await create_test_rhizome(client)
        rhizome_id = rhizome["rhizome_id"]

        # Set empty interventions in metadata
        await client.patch(
            f"/api/rhizomes/{rhizome_id}",
            json={"metadata": {"context_interventions": []}},
        )

        resp = await client.get(f"/api/rhizomes/{rhizome_id}")
        assert resp.status_code == 200
        data = resp.json()
        meta = data.get("metadata", {})
        assert meta.get("context_interventions") == []
