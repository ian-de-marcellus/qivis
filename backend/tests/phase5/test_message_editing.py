"""Tests for message editing (Phase 5.1).

Three sections:
1. Contract tests — event → projector → verify projected state
2. Context builder tests — edited_content resolved correctly
3. API integration tests — PATCH endpoint round-trips
"""

import pytest

from qivis.generation.context import ContextBuilder
from tests.fixtures import (
    create_test_tree,
    create_tree_with_messages,
    make_node_content_edited_envelope,
    make_node_created_envelope,
    make_tree_created_envelope,
)


# ---------------------------------------------------------------------------
# Contract tests: event → store → projector → verify state
# ---------------------------------------------------------------------------


class TestNodeContentEditedProjection:
    """NodeContentEdited events project edited_content onto the nodes table."""

    async def test_edit_sets_edited_content(self, event_store, projector):
        """Emitting NodeContentEdited sets edited_content on the projected node."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(
            tree_id=tree_ev.tree_id, content="Original text",
        )

        await event_store.append(tree_ev)
        await event_store.append(node_ev)
        await projector.project([tree_ev, node_ev])

        edit_ev = make_node_content_edited_envelope(
            tree_id=tree_ev.tree_id,
            node_id=node_ev.payload["node_id"],
            original_content="Original text",
            new_content="Edited text",
        )
        await event_store.append(edit_ev)
        await projector.project([edit_ev])

        nodes = await projector.get_nodes(tree_ev.tree_id)
        assert len(nodes) == 1
        assert nodes[0]["edited_content"] == "Edited text"

    async def test_restore_clears_edited_content(self, event_store, projector):
        """Emitting NodeContentEdited with new_content=None clears edited_content."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(
            tree_id=tree_ev.tree_id, content="Original",
        )

        await event_store.append(tree_ev)
        await event_store.append(node_ev)
        await projector.project([tree_ev, node_ev])

        node_id = node_ev.payload["node_id"]

        # Edit
        edit_ev = make_node_content_edited_envelope(
            tree_id=tree_ev.tree_id, node_id=node_id,
            original_content="Original", new_content="Changed",
        )
        await event_store.append(edit_ev)
        await projector.project([edit_ev])

        # Restore
        restore_ev = make_node_content_edited_envelope(
            tree_id=tree_ev.tree_id, node_id=node_id,
            original_content="Original", new_content=None,
        )
        await event_store.append(restore_ev)
        await projector.project([restore_ev])

        nodes = await projector.get_nodes(tree_ev.tree_id)
        assert nodes[0]["edited_content"] is None

    async def test_edit_preserves_original_content(self, event_store, projector):
        """The content column is never changed by NodeContentEdited."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(
            tree_id=tree_ev.tree_id, content="Immutable original",
        )

        await event_store.append(tree_ev)
        await event_store.append(node_ev)
        await projector.project([tree_ev, node_ev])

        edit_ev = make_node_content_edited_envelope(
            tree_id=tree_ev.tree_id,
            node_id=node_ev.payload["node_id"],
            original_content="Immutable original",
            new_content="Something different",
        )
        await event_store.append(edit_ev)
        await projector.project([edit_ev])

        nodes = await projector.get_nodes(tree_ev.tree_id)
        assert nodes[0]["content"] == "Immutable original"
        assert nodes[0]["edited_content"] == "Something different"

    async def test_multiple_edits_last_wins(self, event_store, projector):
        """Two edits to the same node — the last value wins."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(
            tree_id=tree_ev.tree_id, content="Original",
        )

        await event_store.append(tree_ev)
        await event_store.append(node_ev)
        await projector.project([tree_ev, node_ev])

        node_id = node_ev.payload["node_id"]

        edit1 = make_node_content_edited_envelope(
            tree_id=tree_ev.tree_id, node_id=node_id,
            original_content="Original", new_content="First edit",
        )
        edit2 = make_node_content_edited_envelope(
            tree_id=tree_ev.tree_id, node_id=node_id,
            original_content="Original", new_content="Second edit",
        )
        await event_store.append(edit1)
        await event_store.append(edit2)
        await projector.project([edit1, edit2])

        nodes = await projector.get_nodes(tree_ev.tree_id)
        assert nodes[0]["edited_content"] == "Second edit"

    async def test_edit_does_not_affect_other_nodes(self, event_store, projector):
        """Editing one node does not affect a sibling."""
        tree_ev = make_tree_created_envelope()
        node_a = make_node_created_envelope(
            tree_id=tree_ev.tree_id, content="Node A",
        )
        node_b = make_node_created_envelope(
            tree_id=tree_ev.tree_id, content="Node B",
        )

        events = [tree_ev, node_a, node_b]
        for e in events:
            await event_store.append(e)
        await projector.project(events)

        edit_ev = make_node_content_edited_envelope(
            tree_id=tree_ev.tree_id,
            node_id=node_a.payload["node_id"],
            original_content="Node A",
            new_content="Edited A",
        )
        await event_store.append(edit_ev)
        await projector.project([edit_ev])

        nodes = await projector.get_nodes(tree_ev.tree_id)
        by_id = {n["node_id"]: n for n in nodes}
        assert by_id[node_a.payload["node_id"]]["edited_content"] == "Edited A"
        assert by_id[node_b.payload["node_id"]]["edited_content"] is None


# ---------------------------------------------------------------------------
# Context builder tests: edited_content resolves correctly
# ---------------------------------------------------------------------------


@pytest.fixture
def builder() -> ContextBuilder:
    return ContextBuilder()


class TestContextBuilderEditing:
    """ContextBuilder uses edited_content when present."""

    def test_uses_edited_content_when_present(self, builder: ContextBuilder):
        """When a node has edited_content, the context builder uses it."""
        nodes = [
            {"node_id": "n1", "parent_id": None, "role": "user",
             "content": "Original question", "edited_content": "Better question"},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant",
             "content": "Response", "edited_content": None},
        ]
        messages, _, _ = builder.build(
            nodes=nodes, target_node_id="n2",
            system_prompt=None, model_context_limit=200_000,
        )
        assert messages[0]["content"] == "Better question"

    def test_falls_back_to_content_when_no_edit(self, builder: ContextBuilder):
        """When edited_content is None, the original content is used."""
        nodes = [
            {"node_id": "n1", "parent_id": None, "role": "user",
             "content": "Original question", "edited_content": None},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant",
             "content": "Response", "edited_content": None},
        ]
        messages, _, _ = builder.build(
            nodes=nodes, target_node_id="n2",
            system_prompt=None, model_context_limit=200_000,
        )
        assert messages[0]["content"] == "Original question"

    def test_mixed_edited_and_unedited(self, builder: ContextBuilder):
        """Path with both edited and unedited nodes resolves each correctly."""
        nodes = [
            {"node_id": "n1", "parent_id": None, "role": "user",
             "content": "Unedited user msg", "edited_content": None},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant",
             "content": "Original response", "edited_content": "Rewritten response"},
            {"node_id": "n3", "parent_id": "n2", "role": "user",
             "content": "Follow up", "edited_content": None},
        ]
        messages, _, _ = builder.build(
            nodes=nodes, target_node_id="n3",
            system_prompt=None, model_context_limit=200_000,
        )
        assert messages[0]["content"] == "Unedited user msg"
        assert messages[1]["content"] == "Rewritten response"
        assert messages[2]["content"] == "Follow up"

    def test_timestamp_prepended_to_edited_content(self, builder: ContextBuilder):
        """With include_timestamps=True, timestamp is prepended to edited user content."""
        nodes = [
            {"node_id": "n1", "parent_id": None, "role": "user",
             "content": "Original", "edited_content": "Edited",
             "created_at": "2024-06-15T10:30:00"},
        ]
        messages, _, _ = builder.build(
            nodes=nodes, target_node_id="n1",
            system_prompt=None, model_context_limit=200_000,
            include_timestamps=True,
        )
        assert messages[0]["content"] == "[2024-06-15 10:30] Edited"

    def test_thinking_content_still_included_with_edit(self, builder: ContextBuilder):
        """Editing an assistant node doesn't affect thinking content prepend."""
        nodes = [
            {"node_id": "n1", "parent_id": None, "role": "user",
             "content": "Question", "edited_content": None},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant",
             "content": "Original answer", "edited_content": "Better answer",
             "thinking_content": "Let me think about this..."},
        ]
        messages, _, _ = builder.build(
            nodes=nodes, target_node_id="n2",
            system_prompt=None, model_context_limit=200_000,
            include_thinking=True,
        )
        assert "[Model thinking: Let me think about this...]" in messages[1]["content"]
        assert "Better answer" in messages[1]["content"]

    def test_no_edited_content_key_uses_content(self, builder: ContextBuilder):
        """Nodes without the edited_content key at all still work (backwards compat)."""
        nodes = [
            {"node_id": "n1", "parent_id": None, "role": "user", "content": "Hello"},
        ]
        messages, _, _ = builder.build(
            nodes=nodes, target_node_id="n1",
            system_prompt=None, model_context_limit=200_000,
        )
        assert messages[0]["content"] == "Hello"


# ---------------------------------------------------------------------------
# API integration tests: PATCH endpoint
# ---------------------------------------------------------------------------


class TestEditNodeContentAPI:
    """PATCH /api/trees/{tree_id}/nodes/{node_id}/content"""

    async def test_patch_edit_returns_updated_node(self, client):
        """PATCH with edited_content sets it; content unchanged."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]  # first user message

        resp = await client.patch(
            f"/api/trees/{tree_id}/nodes/{node_id}/content",
            json={"edited_content": "Revised message"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["edited_content"] == "Revised message"
        assert body["content"] == "Message 1"  # original unchanged

    async def test_patch_restore_clears_edit(self, client):
        """PATCH with edited_content=null clears the edit."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        # Edit first
        await client.patch(
            f"/api/trees/{tree_id}/nodes/{node_id}/content",
            json={"edited_content": "Revised"},
        )

        # Restore
        resp = await client.patch(
            f"/api/trees/{tree_id}/nodes/{node_id}/content",
            json={"edited_content": None},
        )
        assert resp.status_code == 200
        assert resp.json()["edited_content"] is None

    async def test_patch_nonexistent_tree_404(self, client):
        resp = await client.patch(
            "/api/trees/no-such-tree/nodes/no-such-node/content",
            json={"edited_content": "x"},
        )
        assert resp.status_code == 404

    async def test_patch_nonexistent_node_404(self, client):
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]
        resp = await client.patch(
            f"/api/trees/{tree_id}/nodes/no-such-node/content",
            json={"edited_content": "x"},
        )
        assert resp.status_code == 404

    async def test_edit_then_get_tree_reflects_edit(self, client):
        """After editing, GET tree includes edited_content on the node."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        await client.patch(
            f"/api/trees/{tree_id}/nodes/{node_id}/content",
            json={"edited_content": "Revised message"},
        )

        resp = await client.get(f"/api/trees/{tree_id}")
        assert resp.status_code == 200
        tree = resp.json()
        edited_node = next(n for n in tree["nodes"] if n["node_id"] == node_id)
        assert edited_node["edited_content"] == "Revised message"
        assert edited_node["content"] == "Message 1"

    async def test_edit_empty_string_normalizes_to_null(self, client):
        """Editing to empty string is treated as 'no edit' (null)."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        resp = await client.patch(
            f"/api/trees/{tree_id}/nodes/{node_id}/content",
            json={"edited_content": ""},
        )
        assert resp.status_code == 200
        assert resp.json()["edited_content"] is None

    async def test_edit_matching_original_normalizes_to_null(self, client):
        """Editing to the same content as original is treated as no edit."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        resp = await client.patch(
            f"/api/trees/{tree_id}/nodes/{node_id}/content",
            json={"edited_content": "Message 1"},  # same as original
        )
        assert resp.status_code == 200
        assert resp.json()["edited_content"] is None

    async def test_edit_emits_event(self, client, db):
        """Editing a node records a NodeContentEdited event."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        await client.patch(
            f"/api/trees/{tree_id}/nodes/{node_id}/content",
            json={"edited_content": "Revised"},
        )

        # Check event log
        from qivis.events.store import EventStore
        store = EventStore(db)
        events = await store.get_events(tree_id)
        edit_events = [e for e in events if e.event_type == "NodeContentEdited"]
        assert len(edit_events) == 1
        payload = edit_events[0].payload
        assert payload["node_id"] == node_id
        assert payload["new_content"] == "Revised"
        assert payload["original_content"] == "Message 1"


# ---------------------------------------------------------------------------
# EventStore.get_events_by_type tests
# ---------------------------------------------------------------------------


class TestGetEventsByType:
    """EventStore.get_events_by_type filters and orders correctly."""

    async def test_filters_by_event_type(self, event_store, projector):
        """Only events matching the given type are returned."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(
            tree_id=tree_ev.tree_id, content="Hello",
        )
        edit_ev = make_node_content_edited_envelope(
            tree_id=tree_ev.tree_id,
            node_id=node_ev.payload["node_id"],
            original_content="Hello",
            new_content="Hi there",
        )

        for e in [tree_ev, node_ev, edit_ev]:
            await event_store.append(e)
        await projector.project([tree_ev, node_ev, edit_ev])

        results = await event_store.get_events_by_type(
            tree_ev.tree_id, "NodeContentEdited",
        )
        assert len(results) == 1
        assert results[0].event_type == "NodeContentEdited"

    async def test_scoped_to_tree(self, event_store, projector):
        """Events from other trees are excluded."""
        tree1 = make_tree_created_envelope()
        tree2 = make_tree_created_envelope()
        node1 = make_node_created_envelope(tree_id=tree1.tree_id, content="A")
        node2 = make_node_created_envelope(tree_id=tree2.tree_id, content="B")

        for e in [tree1, tree2, node1, node2]:
            await event_store.append(e)
        await projector.project([tree1, tree2, node1, node2])

        edit1 = make_node_content_edited_envelope(
            tree_id=tree1.tree_id, node_id=node1.payload["node_id"],
            original_content="A", new_content="A edited",
        )
        edit2 = make_node_content_edited_envelope(
            tree_id=tree2.tree_id, node_id=node2.payload["node_id"],
            original_content="B", new_content="B edited",
        )
        await event_store.append(edit1)
        await event_store.append(edit2)

        results = await event_store.get_events_by_type(
            tree1.tree_id, "NodeContentEdited",
        )
        assert len(results) == 1
        assert results[0].payload["node_id"] == node1.payload["node_id"]

    async def test_ordered_by_sequence(self, event_store, projector):
        """Results are ordered by sequence_num."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(
            tree_id=tree_ev.tree_id, content="Original",
        )
        await event_store.append(tree_ev)
        await event_store.append(node_ev)
        await projector.project([tree_ev, node_ev])

        node_id = node_ev.payload["node_id"]
        edits = []
        for i in range(3):
            ev = make_node_content_edited_envelope(
                tree_id=tree_ev.tree_id, node_id=node_id,
                original_content="Original", new_content=f"Edit {i}",
            )
            await event_store.append(ev)
            edits.append(ev)

        results = await event_store.get_events_by_type(
            tree_ev.tree_id, "NodeContentEdited",
        )
        assert len(results) == 3
        # sequence_num should be monotonically increasing
        seq_nums = [r.sequence_num for r in results]
        assert seq_nums == sorted(seq_nums)


# ---------------------------------------------------------------------------
# Edit history service tests
# ---------------------------------------------------------------------------


class TestGetEditHistory:
    """TreeService.get_edit_history returns correct edit history."""

    async def test_empty_for_unedited_node(self, client):
        """Unedited node returns empty entries, current_content = original."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        resp = await client.get(
            f"/api/trees/{tree_id}/nodes/{node_id}/edit-history",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["node_id"] == node_id
        assert body["original_content"] == "Message 1"
        assert body["current_content"] == "Message 1"
        assert body["entries"] == []

    async def test_single_edit(self, client):
        """One edit returns one entry with correct fields."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        await client.patch(
            f"/api/trees/{tree_id}/nodes/{node_id}/content",
            json={"edited_content": "Revised"},
        )

        resp = await client.get(
            f"/api/trees/{tree_id}/nodes/{node_id}/edit-history",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["original_content"] == "Message 1"
        assert body["current_content"] == "Revised"
        assert len(body["entries"]) == 1
        entry = body["entries"][0]
        assert entry["new_content"] == "Revised"
        assert "event_id" in entry
        assert "timestamp" in entry
        assert "sequence_num" in entry

    async def test_multiple_edits_ordered(self, client):
        """Three edits return three entries in sequence order."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        for text in ["First edit", "Second edit", "Third edit"]:
            await client.patch(
                f"/api/trees/{tree_id}/nodes/{node_id}/content",
                json={"edited_content": text},
            )

        resp = await client.get(
            f"/api/trees/{tree_id}/nodes/{node_id}/edit-history",
        )
        body = resp.json()
        assert body["current_content"] == "Third edit"
        assert len(body["entries"]) == 3
        contents = [e["new_content"] for e in body["entries"]]
        assert contents == ["First edit", "Second edit", "Third edit"]
        # Verify sequence ordering
        seq_nums = [e["sequence_num"] for e in body["entries"]]
        assert seq_nums == sorted(seq_nums)

    async def test_restore_appears_in_history(self, client):
        """Edit then restore produces two entries (edit + null restore)."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        await client.patch(
            f"/api/trees/{tree_id}/nodes/{node_id}/content",
            json={"edited_content": "Edited"},
        )
        await client.patch(
            f"/api/trees/{tree_id}/nodes/{node_id}/content",
            json={"edited_content": None},
        )

        resp = await client.get(
            f"/api/trees/{tree_id}/nodes/{node_id}/edit-history",
        )
        body = resp.json()
        assert body["current_content"] == "Message 1"  # restored
        assert len(body["entries"]) == 2
        assert body["entries"][0]["new_content"] == "Edited"
        assert body["entries"][1]["new_content"] is None

    async def test_scoped_to_node(self, client):
        """Edits on a sibling node are excluded."""
        data = await create_tree_with_messages(client, n_messages=4)
        tree_id = data["tree_id"]
        node_a = data["node_ids"][0]
        node_b = data["node_ids"][2]  # another user message

        await client.patch(
            f"/api/trees/{tree_id}/nodes/{node_a}/content",
            json={"edited_content": "Edit A"},
        )
        await client.patch(
            f"/api/trees/{tree_id}/nodes/{node_b}/content",
            json={"edited_content": "Edit B"},
        )

        resp = await client.get(
            f"/api/trees/{tree_id}/nodes/{node_a}/edit-history",
        )
        body = resp.json()
        assert len(body["entries"]) == 1
        assert body["entries"][0]["new_content"] == "Edit A"

    async def test_nonexistent_tree_404(self, client):
        resp = await client.get(
            "/api/trees/no-such-tree/nodes/no-such-node/edit-history",
        )
        assert resp.status_code == 404

    async def test_nonexistent_node_404(self, client):
        tree = await create_test_tree(client)
        resp = await client.get(
            f"/api/trees/{tree['tree_id']}/nodes/no-such-node/edit-history",
        )
        assert resp.status_code == 404
