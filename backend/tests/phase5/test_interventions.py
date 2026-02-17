"""Tests for the intervention timeline endpoint (Phase 5.4).

Tests that GET /api/trees/{tree_id}/interventions returns a chronological
list of NodeContentEdited and system-prompt TreeMetadataUpdated events.
"""

import pytest

from tests.fixtures import (
    create_test_tree,
    create_tree_with_messages,
)


class TestInterventionTimeline:
    """API integration tests for GET /api/trees/{tree_id}/interventions."""

    async def test_empty_tree_returns_empty_interventions(self, client):
        """A tree with no edits or metadata changes has no interventions."""
        tree = await create_test_tree(client)
        resp = await client.get(f"/api/trees/{tree['tree_id']}/interventions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tree_id"] == tree["tree_id"]
        assert data["interventions"] == []

    async def test_single_node_edit(self, client):
        """Editing a node produces one intervention of type 'node_edited'."""
        info = await create_tree_with_messages(client, n_messages=2)
        tree_id = info["tree_id"]
        node_id = info["node_ids"][0]

        await client.patch(
            f"/api/trees/{tree_id}/nodes/{node_id}/content",
            json={"edited_content": "Edited message"},
        )

        resp = await client.get(f"/api/trees/{tree_id}/interventions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["interventions"]) == 1

        entry = data["interventions"][0]
        assert entry["intervention_type"] == "node_edited"
        assert entry["node_id"] == node_id
        assert entry["new_content"] == "Edited message"
        assert entry["original_content"] == "Message 1"
        assert entry["event_id"]
        assert entry["sequence_num"] > 0
        assert entry["timestamp"]

    async def test_multiple_edits_sorted_by_sequence(self, client):
        """Multiple edits return interventions sorted by sequence_num."""
        info = await create_tree_with_messages(client, n_messages=4)
        tree_id = info["tree_id"]

        # Edit two different nodes
        await client.patch(
            f"/api/trees/{tree_id}/nodes/{info['node_ids'][0]}/content",
            json={"edited_content": "First edit"},
        )
        await client.patch(
            f"/api/trees/{tree_id}/nodes/{info['node_ids'][2]}/content",
            json={"edited_content": "Second edit"},
        )

        resp = await client.get(f"/api/trees/{tree_id}/interventions")
        data = resp.json()
        assert len(data["interventions"]) == 2

        # Should be sorted by sequence_num
        assert data["interventions"][0]["sequence_num"] < data["interventions"][1]["sequence_num"]
        assert data["interventions"][0]["new_content"] == "First edit"
        assert data["interventions"][1]["new_content"] == "Second edit"

    async def test_system_prompt_change_appears(self, client):
        """Changing the system prompt produces an intervention of type 'system_prompt_changed'."""
        tree = await create_test_tree(client, system_prompt="Original prompt")
        tree_id = tree["tree_id"]

        await client.patch(
            f"/api/trees/{tree_id}",
            json={"default_system_prompt": "New prompt"},
        )

        resp = await client.get(f"/api/trees/{tree_id}/interventions")
        data = resp.json()
        assert len(data["interventions"]) == 1

        entry = data["interventions"][0]
        assert entry["intervention_type"] == "system_prompt_changed"
        assert entry["old_value"] == "Original prompt"
        assert entry["new_value"] == "New prompt"
        assert entry["node_id"] is None

    async def test_mixed_edits_and_system_prompt_sorted(self, client):
        """Edits and system prompt changes are merged and sorted by sequence_num."""
        info = await create_tree_with_messages(client, n_messages=2, system_prompt="Prompt v1")
        tree_id = info["tree_id"]

        # Edit a node first
        await client.patch(
            f"/api/trees/{tree_id}/nodes/{info['node_ids'][0]}/content",
            json={"edited_content": "Edited message"},
        )

        # Then change system prompt
        await client.patch(
            f"/api/trees/{tree_id}",
            json={"default_system_prompt": "Prompt v2"},
        )

        resp = await client.get(f"/api/trees/{tree_id}/interventions")
        data = resp.json()
        assert len(data["interventions"]) == 2

        # Should be sorted by sequence_num (edit first, then system prompt change)
        assert data["interventions"][0]["intervention_type"] == "node_edited"
        assert data["interventions"][1]["intervention_type"] == "system_prompt_changed"
        assert data["interventions"][0]["sequence_num"] < data["interventions"][1]["sequence_num"]

    async def test_non_system_prompt_metadata_excluded(self, client):
        """Model/provider changes in TreeMetadataUpdated are NOT included."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        # Change model and provider — these should NOT appear
        await client.patch(
            f"/api/trees/{tree_id}",
            json={"default_model": "gpt-4o", "default_provider": "openai"},
        )

        resp = await client.get(f"/api/trees/{tree_id}/interventions")
        data = resp.json()
        assert len(data["interventions"]) == 0

    async def test_nonexistent_tree_returns_404(self, client):
        """Requesting interventions for a nonexistent tree returns 404."""
        resp = await client.get("/api/trees/nonexistent-id/interventions")
        assert resp.status_code == 404
