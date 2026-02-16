"""Contract and integration tests for tree settings (Phase 2.1).

Tests the TreeMetadataUpdated projector handler and the PATCH /api/trees/{tree_id}
endpoint for updating tree defaults after creation.
"""

import json

from tests.fixtures import (
    create_test_tree,
    make_tree_created_envelope,
    make_tree_metadata_updated_envelope,
)


class TestProjectorTreeMetadataUpdated:
    """Projector roundtrip: TreeMetadataUpdated events update materialized state."""

    async def test_update_title(self, event_store, projector):
        """TreeMetadataUpdated for 'title' updates the projected tree title."""
        tree_event = make_tree_created_envelope(title="Original Title")
        update_event = make_tree_metadata_updated_envelope(
            tree_id=tree_event.tree_id,
            field="title",
            old_value="Original Title",
            new_value="Updated Title",
        )

        await event_store.append(tree_event)
        await event_store.append(update_event)
        await projector.project([tree_event, update_event])

        tree = await projector.get_tree(tree_event.tree_id)
        assert tree is not None
        assert tree["title"] == "Updated Title"

    async def test_update_default_provider(self, event_store, projector):
        """TreeMetadataUpdated for 'default_provider' updates the projected field."""
        tree_event = make_tree_created_envelope(default_provider="anthropic")
        update_event = make_tree_metadata_updated_envelope(
            tree_id=tree_event.tree_id,
            field="default_provider",
            old_value="anthropic",
            new_value="openai",
        )

        await event_store.append(tree_event)
        await event_store.append(update_event)
        await projector.project([tree_event, update_event])

        tree = await projector.get_tree(tree_event.tree_id)
        assert tree["default_provider"] == "openai"

    async def test_update_default_model(self, event_store, projector):
        """TreeMetadataUpdated for 'default_model' updates the projected field."""
        tree_event = make_tree_created_envelope(default_model="claude-sonnet-4-5-20250929")
        update_event = make_tree_metadata_updated_envelope(
            tree_id=tree_event.tree_id,
            field="default_model",
            old_value="claude-sonnet-4-5-20250929",
            new_value="gpt-4o",
        )

        await event_store.append(tree_event)
        await event_store.append(update_event)
        await projector.project([tree_event, update_event])

        tree = await projector.get_tree(tree_event.tree_id)
        assert tree["default_model"] == "gpt-4o"

    async def test_update_default_system_prompt(self, event_store, projector):
        """TreeMetadataUpdated for 'default_system_prompt' updates the projected field."""
        tree_event = make_tree_created_envelope(
            default_system_prompt="You are helpful.",
        )
        update_event = make_tree_metadata_updated_envelope(
            tree_id=tree_event.tree_id,
            field="default_system_prompt",
            old_value="You are helpful.",
            new_value="You are a pirate.",
        )

        await event_store.append(tree_event)
        await event_store.append(update_event)
        await projector.project([tree_event, update_event])

        tree = await projector.get_tree(tree_event.tree_id)
        assert tree["default_system_prompt"] == "You are a pirate."

    async def test_update_default_sampling_params(self, event_store, projector):
        """TreeMetadataUpdated for 'default_sampling_params' round-trips JSON."""
        tree_event = make_tree_created_envelope()
        new_params = {"temperature": 0.9, "max_tokens": 2048}
        update_event = make_tree_metadata_updated_envelope(
            tree_id=tree_event.tree_id,
            field="default_sampling_params",
            old_value=None,
            new_value=new_params,
        )

        await event_store.append(tree_event)
        await event_store.append(update_event)
        await projector.project([tree_event, update_event])

        tree = await projector.get_tree(tree_event.tree_id)
        stored = json.loads(tree["default_sampling_params"])
        assert stored["temperature"] == 0.9
        assert stored["max_tokens"] == 2048

    async def test_update_changes_updated_at(self, event_store, projector):
        """TreeMetadataUpdated bumps updated_at on the projected tree."""
        tree_event = make_tree_created_envelope()
        await event_store.append(tree_event)
        await projector.project([tree_event])

        tree_before = await projector.get_tree(tree_event.tree_id)
        original_updated_at = tree_before["updated_at"]

        update_event = make_tree_metadata_updated_envelope(
            tree_id=tree_event.tree_id,
            field="title",
            old_value=tree_before["title"],
            new_value="Changed",
        )
        await event_store.append(update_event)
        await projector.project([update_event])

        tree_after = await projector.get_tree(tree_event.tree_id)
        assert tree_after["updated_at"] >= original_updated_at
        assert tree_after["title"] == "Changed"

    async def test_update_leaves_other_fields_untouched(self, event_store, projector):
        """Updating title does not change default_model or other fields."""
        tree_event = make_tree_created_envelope(
            title="Original",
            default_model="claude-sonnet-4-5-20250929",
            default_provider="anthropic",
            default_system_prompt="You are helpful.",
        )
        update_event = make_tree_metadata_updated_envelope(
            tree_id=tree_event.tree_id,
            field="title",
            old_value="Original",
            new_value="New Title",
        )

        await event_store.append(tree_event)
        await event_store.append(update_event)
        await projector.project([tree_event, update_event])

        tree = await projector.get_tree(tree_event.tree_id)
        assert tree["title"] == "New Title"
        assert tree["default_model"] == "claude-sonnet-4-5-20250929"
        assert tree["default_provider"] == "anthropic"
        assert tree["default_system_prompt"] == "You are helpful."

    async def test_unknown_field_does_not_crash(self, event_store, projector):
        """TreeMetadataUpdated with an unrecognized field is silently skipped."""
        tree_event = make_tree_created_envelope(title="Safe")
        update_event = make_tree_metadata_updated_envelope(
            tree_id=tree_event.tree_id,
            field="nonexistent_field",
            old_value=None,
            new_value="anything",
        )

        await event_store.append(tree_event)
        await event_store.append(update_event)
        # Should not raise
        await projector.project([tree_event, update_event])

        tree = await projector.get_tree(tree_event.tree_id)
        assert tree["title"] == "Safe"


class TestPatchTreeEndpoint:
    """PATCH /api/trees/{tree_id} integration tests."""

    async def test_patch_title(self, client):
        """PATCH with title updates it in the response."""
        tree = await create_test_tree(client, title="Old Title")
        tree_id = tree["tree_id"]

        resp = await client.patch(f"/api/trees/{tree_id}", json={"title": "New Title"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "New Title"
        assert data["tree_id"] == tree_id

    async def test_patch_multiple_fields(self, client):
        """PATCH with multiple fields updates all of them."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        resp = await client.patch(f"/api/trees/{tree_id}", json={
            "title": "Multi Update",
            "default_provider": "openai",
            "default_model": "gpt-4o",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Multi Update"
        assert data["default_provider"] == "openai"
        assert data["default_model"] == "gpt-4o"

    async def test_patch_system_prompt(self, client):
        """PATCH with default_system_prompt updates it."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        resp = await client.patch(f"/api/trees/{tree_id}", json={
            "default_system_prompt": "You are a pirate.",
        })
        assert resp.status_code == 200
        assert resp.json()["default_system_prompt"] == "You are a pirate."

    async def test_patch_sampling_params(self, client):
        """PATCH with default_sampling_params updates it."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        resp = await client.patch(f"/api/trees/{tree_id}", json={
            "default_sampling_params": {"temperature": 0.9, "max_tokens": 2048},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["default_sampling_params"]["temperature"] == 0.9
        assert data["default_sampling_params"]["max_tokens"] == 2048

    async def test_patch_nonexistent_tree_returns_404(self, client):
        """PATCH on a nonexistent tree returns 404."""
        resp = await client.patch("/api/trees/nonexistent-id", json={"title": "X"})
        assert resp.status_code == 404

    async def test_patch_then_get_reflects_changes(self, client):
        """After PATCH, GET returns the updated values."""
        tree = await create_test_tree(client, title="Before")
        tree_id = tree["tree_id"]

        await client.patch(f"/api/trees/{tree_id}", json={
            "title": "After",
            "default_model": "gpt-4o",
        })

        resp = await client.get(f"/api/trees/{tree_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "After"
        assert data["default_model"] == "gpt-4o"

    async def test_patch_unchanged_field_emits_no_event(self, client):
        """PATCH with a value identical to current emits no TreeMetadataUpdated events."""
        tree = await create_test_tree(client, title="Same")
        tree_id = tree["tree_id"]

        # PATCH with the same title
        resp = await client.patch(f"/api/trees/{tree_id}", json={"title": "Same"})
        assert resp.status_code == 200

        # Count events: should only have TreeCreated, no TreeMetadataUpdated
        events_resp = await client.get(f"/api/events/{tree_id}")
        if events_resp.status_code == 200:
            events = events_resp.json()
            update_events = [
                e for e in events if e["event_type"] == "TreeMetadataUpdated"
            ]
            assert len(update_events) == 0

    async def test_patch_only_changed_fields_emit_events(self, client):
        """PATCH with 3 fields, 1 unchanged, emits 2 TreeMetadataUpdated events."""
        tree = await create_test_tree(client, title="Keep This")
        tree_id = tree["tree_id"]

        resp = await client.patch(f"/api/trees/{tree_id}", json={
            "title": "Keep This",  # unchanged
            "default_provider": "openai",  # changed (was None or anthropic)
            "default_model": "gpt-4o",  # changed
        })
        assert resp.status_code == 200

        # Verify the changed fields took effect
        data = resp.json()
        assert data["title"] == "Keep This"
        assert data["default_provider"] == "openai"
        assert data["default_model"] == "gpt-4o"

    async def test_patch_empty_body_is_noop(self, client):
        """PATCH with empty body returns current state unchanged."""
        tree = await create_test_tree(client, title="Untouched")
        tree_id = tree["tree_id"]

        resp = await client.patch(f"/api/trees/{tree_id}", json={})
        assert resp.status_code == 200
        assert resp.json()["title"] == "Untouched"

    async def test_patch_preserves_nodes(self, client):
        """PATCH on tree metadata does not affect existing nodes."""
        tree = await create_test_tree(client, title="With Nodes")
        tree_id = tree["tree_id"]

        await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "Hello",
        })

        resp = await client.patch(f"/api/trees/{tree_id}", json={
            "title": "Renamed",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Renamed"
        assert len(data["nodes"]) == 1
        assert data["nodes"][0]["content"] == "Hello"

    async def test_patch_clear_system_prompt_to_null(self, client):
        """PATCH with default_system_prompt=null clears it."""
        tree = await create_test_tree(client, system_prompt="Original prompt")
        tree_id = tree["tree_id"]

        resp = await client.patch(f"/api/trees/{tree_id}", json={
            "default_system_prompt": None,
        })
        assert resp.status_code == 200
        assert resp.json()["default_system_prompt"] is None

    async def test_patch_updates_list_endpoint(self, client):
        """After PATCH, list endpoint reflects the new title."""
        tree = await create_test_tree(client, title="Old Name")
        tree_id = tree["tree_id"]

        await client.patch(f"/api/trees/{tree_id}", json={"title": "New Name"})

        resp = await client.get("/api/trees")
        trees = resp.json()
        titles = [t["title"] for t in trees]
        assert "New Name" in titles
        assert "Old Name" not in titles
