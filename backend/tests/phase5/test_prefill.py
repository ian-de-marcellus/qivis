"""Tests for prefill / manual mode (researcher-authored assistant messages).

Sections:
1. Contract tests — mode field projected correctly
2. API tests — CreateNodeRequest with mode field
3. Context builder — manual assistant nodes included in context
"""

import pytest

from qivis.generation.context import ContextBuilder
from tests.fixtures import (
    create_test_tree,
    make_node_created_envelope,
    make_tree_created_envelope,
)


# ---------------------------------------------------------------------------
# Contract tests: mode field projected correctly
# ---------------------------------------------------------------------------


class TestManualModeProjection:
    """NodeCreated with mode='manual' projects correctly."""

    async def test_manual_mode_projected(self, event_store, projector):
        """A node created with mode='manual' has mode='manual' in projection."""
        tree_ev = make_tree_created_envelope()
        user_ev = make_node_created_envelope(
            tree_id=tree_ev.tree_id, content="Question", role="user",
        )
        manual_ev = make_node_created_envelope(
            tree_id=tree_ev.tree_id,
            parent_id=user_ev.payload["node_id"],
            role="assistant",
            content="Manual answer",
            mode="manual",
        )

        for ev in [tree_ev, user_ev, manual_ev]:
            await event_store.append(ev)
        await projector.project([tree_ev, user_ev, manual_ev])

        nodes = await projector.get_nodes(tree_ev.tree_id)
        by_role = {n["role"]: n for n in nodes}
        assert by_role["assistant"]["mode"] == "manual"
        assert by_role["user"]["mode"] == "chat"

    async def test_manual_mode_in_event_payload(self, event_store, projector):
        """The event payload itself contains mode='manual'."""
        tree_ev = make_tree_created_envelope()
        manual_ev = make_node_created_envelope(
            tree_id=tree_ev.tree_id,
            role="assistant",
            content="Manual",
            mode="manual",
        )

        await event_store.append(tree_ev)
        await event_store.append(manual_ev)

        events = await event_store.get_events(tree_ev.tree_id)
        node_events = [e for e in events if e.event_type == "NodeCreated"]
        assert node_events[0].payload["mode"] == "manual"


# ---------------------------------------------------------------------------
# API tests: CreateNodeRequest with mode
# ---------------------------------------------------------------------------


class TestCreateNodeWithMode:
    """POST /api/trees/{tree_id}/nodes with mode field."""

    async def test_create_node_mode_manual(self, client):
        """Creating an assistant node with mode='manual' returns mode='manual'."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        # Create a user message first
        user_resp = await client.post(
            f"/api/trees/{tree_id}/nodes",
            json={"content": "What do you think of me?", "role": "user"},
        )
        assert user_resp.status_code == 201
        user_node = user_resp.json()

        # Prefill an assistant response with mode=manual
        resp = await client.post(
            f"/api/trees/{tree_id}/nodes",
            json={
                "content": "I hate you",
                "role": "assistant",
                "parent_id": user_node["node_id"],
                "mode": "manual",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["role"] == "assistant"
        assert body["mode"] == "manual"
        assert body["content"] == "I hate you"
        # Manual nodes have no model or provider
        assert body["model"] is None
        assert body["provider"] is None

    async def test_create_node_mode_defaults_to_chat(self, client):
        """Creating a node without mode field defaults to 'chat'."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        resp = await client.post(
            f"/api/trees/{tree_id}/nodes",
            json={"content": "Hello", "role": "user"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["mode"] == "chat"

    async def test_node_response_includes_mode(self, client):
        """GET tree returns nodes with their mode field."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        # Create a regular user node
        user_resp = await client.post(
            f"/api/trees/{tree_id}/nodes",
            json={"content": "Hello", "role": "user"},
        )
        user_node = user_resp.json()

        # Create a manual assistant node
        await client.post(
            f"/api/trees/{tree_id}/nodes",
            json={
                "content": "Manual",
                "role": "assistant",
                "parent_id": user_node["node_id"],
                "mode": "manual",
            },
        )

        # Fetch tree and verify modes
        tree_resp = await client.get(f"/api/trees/{tree_id}")
        assert tree_resp.status_code == 200
        nodes = tree_resp.json()["nodes"]

        by_role = {n["role"]: n for n in nodes}
        assert by_role["user"]["mode"] == "chat"
        assert by_role["assistant"]["mode"] == "manual"


# ---------------------------------------------------------------------------
# Context builder: manual assistant nodes included in context
# ---------------------------------------------------------------------------


@pytest.fixture
def builder() -> ContextBuilder:
    return ContextBuilder()


class TestContextBuilderManualNodes:
    """Manual assistant nodes appear in context like any other assistant message."""

    def test_context_builder_includes_manual_assistant(self, builder: ContextBuilder):
        """A manual assistant message appears in the context sent to the model."""
        nodes = [
            {"node_id": "n1", "parent_id": None, "role": "user",
             "content": "What do you think of me?", "edited_content": None},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant",
             "content": "I hate you", "edited_content": None},
            {"node_id": "n3", "parent_id": "n2", "role": "user",
             "content": "Why?", "edited_content": None},
        ]
        messages, _, _ = builder.build(
            nodes=nodes, target_node_id="n3",
            system_prompt=None, model_context_limit=200_000,
        )
        # All three messages in the path should be included
        assert len(messages) == 3
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "What do you think of me?"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "I hate you"
        assert messages[2]["role"] == "user"
        assert messages[2]["content"] == "Why?"
