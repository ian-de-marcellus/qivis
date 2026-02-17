"""Contract tests for Phase 2.3: timestamps in context and metadata PATCH.

Tests ContextBuilder timestamp injection, tree metadata PATCH for include_timestamps,
and generation service integration.
"""

import json
import re

import pytest

from qivis.generation.context import ContextBuilder
from tests.fixtures import (
    create_test_tree,
    make_tree_created_envelope,
    make_tree_metadata_updated_envelope,
)


def _make_nodes_with_timestamps() -> list[dict]:
    """Sample linear tree with created_at timestamps."""
    return [
        {
            "node_id": "n1",
            "parent_id": None,
            "role": "system",
            "content": "Be helpful.",
            "created_at": "2026-02-15T10:00:00+00:00",
        },
        {
            "node_id": "n2",
            "parent_id": "n1",
            "role": "user",
            "content": "Hello",
            "created_at": "2026-02-15T10:01:00+00:00",
        },
        {
            "node_id": "n3",
            "parent_id": "n2",
            "role": "assistant",
            "content": "Hi there!",
            "created_at": "2026-02-15T10:01:05+00:00",
        },
        {
            "node_id": "n4",
            "parent_id": "n3",
            "role": "user",
            "content": "How are you?",
            "created_at": "2026-02-15T10:05:00+00:00",
        },
    ]


@pytest.fixture
def builder() -> ContextBuilder:
    return ContextBuilder()


class TestContextTimestamps:
    """ContextBuilder timestamp injection (user/tool only, not assistant)."""

    def test_no_timestamps_by_default(self, builder: ContextBuilder):
        """Default build() does not prepend timestamps to messages."""
        nodes = _make_nodes_with_timestamps()
        messages, _, _ = builder.build(
            nodes=nodes,
            target_node_id="n4",
            system_prompt="Be helpful.",
            model_context_limit=200_000,
        )
        for msg in messages:
            assert not msg["content"].startswith("[")

    def test_timestamps_prepended_to_user_messages(self, builder: ContextBuilder):
        """include_timestamps=True prepends [datetime] to user messages."""
        nodes = _make_nodes_with_timestamps()
        messages, _, _ = builder.build(
            nodes=nodes,
            target_node_id="n4",
            system_prompt="Be helpful.",
            model_context_limit=200_000,
            include_timestamps=True,
        )
        user_msgs = [m for m in messages if m["role"] == "user"]
        for msg in user_msgs:
            assert msg["content"].startswith("[")
            assert "] " in msg["content"]

    def test_timestamps_not_prepended_to_assistant_messages(self, builder: ContextBuilder):
        """include_timestamps=True does NOT prepend timestamps to assistant messages."""
        nodes = _make_nodes_with_timestamps()
        messages, _, _ = builder.build(
            nodes=nodes,
            target_node_id="n4",
            system_prompt="Be helpful.",
            model_context_limit=200_000,
            include_timestamps=True,
        )
        assistant_msgs = [m for m in messages if m["role"] == "assistant"]
        for msg in assistant_msgs:
            assert not msg["content"].startswith("[")

    def test_timestamp_format(self, builder: ContextBuilder):
        """Timestamps on user messages follow [YYYY-MM-DD HH:MM] format."""
        nodes = _make_nodes_with_timestamps()
        messages, _, _ = builder.build(
            nodes=nodes,
            target_node_id="n4",
            system_prompt="Be helpful.",
            model_context_limit=200_000,
            include_timestamps=True,
        )
        pattern = re.compile(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\] ")
        user_msgs = [m for m in messages if m["role"] == "user"]
        for msg in user_msgs:
            assert pattern.match(msg["content"]), f"Bad format: {msg['content'][:30]}"

    def test_original_content_preserved(self, builder: ContextBuilder):
        """Timestamps are prepended — original content follows after the bracket."""
        nodes = _make_nodes_with_timestamps()
        messages, _, _ = builder.build(
            nodes=nodes,
            target_node_id="n4",
            system_prompt="Be helpful.",
            model_context_limit=200_000,
            include_timestamps=True,
        )
        # n2 is user "Hello" at 10:01
        assert messages[0]["content"].endswith("Hello")
        assert "[2026-02-15 10:01] Hello" == messages[0]["content"]
        # n3 is assistant "Hi there!" — should be untouched
        assert messages[1]["content"] == "Hi there!"

    def test_system_role_excluded(self, builder: ContextBuilder):
        """System messages are excluded from messages array."""
        nodes = _make_nodes_with_timestamps()
        messages, _, _ = builder.build(
            nodes=nodes,
            target_node_id="n4",
            system_prompt="Be helpful.",
            model_context_limit=200_000,
            include_timestamps=True,
        )
        roles = [m["role"] for m in messages]
        assert "system" not in roles


class TestMetadataPatch:
    """PATCH /api/trees/{id} supports metadata field."""

    async def test_patch_metadata_sets_value(self, client):
        """PATCH with metadata field updates tree metadata."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        resp = await client.patch(
            f"/api/trees/{tree_id}",
            json={"metadata": {"include_timestamps": True}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["metadata"]["include_timestamps"] is True

    async def test_patch_metadata_roundtrips(self, client):
        """Metadata set via PATCH is visible on GET."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        await client.patch(
            f"/api/trees/{tree_id}",
            json={"metadata": {"include_timestamps": True}},
        )

        resp = await client.get(f"/api/trees/{tree_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["metadata"]["include_timestamps"] is True

    async def test_patch_metadata_preserves_other_fields(self, client):
        """PATCH metadata doesn't clobber other tree fields."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        await client.patch(
            f"/api/trees/{tree_id}",
            json={"metadata": {"include_timestamps": True}},
        )

        resp = await client.get(f"/api/trees/{tree_id}")
        data = resp.json()
        assert data["title"] == "Test Tree"


class TestMetadataProjector:
    """Projector roundtrip for metadata field."""

    async def test_projector_updates_metadata(self, event_store, projector):
        """TreeMetadataUpdated for 'metadata' updates the projected tree."""
        tree_event = make_tree_created_envelope()
        update_event = make_tree_metadata_updated_envelope(
            tree_id=tree_event.tree_id,
            field="metadata",
            old_value={},
            new_value={"include_timestamps": True},
        )

        await event_store.append(tree_event)
        await event_store.append(update_event)
        await projector.project([tree_event, update_event])

        tree = await projector.get_tree(tree_event.tree_id)
        assert tree is not None
        metadata = json.loads(tree["metadata"])
        assert metadata["include_timestamps"] is True
