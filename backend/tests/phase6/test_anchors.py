"""Tests for the anchor system (Phase 6.4a).

Three sections:
1. Contract tests -- projector handles NodeAnchored/NodeUnanchored
2. API integration tests -- toggle endpoint, is_anchored on NodeResponse
3. Event sourcing integrity -- anchors survive replay
"""

import pytest

from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from tests.fixtures import (
    create_test_tree,
    create_tree_with_messages,
    make_node_anchored_envelope,
    make_node_created_envelope,
    make_node_unanchored_envelope,
    make_tree_created_envelope,
)


# ---------------------------------------------------------------------------
# Contract tests: event -> store -> projector -> verify state
# ---------------------------------------------------------------------------


class TestAnchorProjection:
    """NodeAnchored/NodeUnanchored events project correctly."""

    async def test_node_anchored_projects(self, event_store, projector, db):
        """NodeAnchored inserts a row into the node_anchors table."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(tree_id=tree_ev.tree_id, content="Hello")
        node_id = node_ev.payload["node_id"]

        for e in [tree_ev, node_ev]:
            await event_store.append(e)
        await projector.project([tree_ev, node_ev])

        anchor_ev = make_node_anchored_envelope(
            tree_id=tree_ev.tree_id, node_id=node_id,
        )
        await event_store.append(anchor_ev)
        await projector.project([anchor_ev])

        row = await db.fetchone(
            "SELECT * FROM node_anchors WHERE tree_id = ? AND node_id = ?",
            (tree_ev.tree_id, node_id),
        )
        assert row is not None
        assert row["node_id"] == node_id
        assert row["tree_id"] == tree_ev.tree_id

    async def test_node_unanchored_removes_row(self, event_store, projector, db):
        """NodeUnanchored deletes the anchor from the table."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(tree_id=tree_ev.tree_id, content="Hello")
        node_id = node_ev.payload["node_id"]

        for e in [tree_ev, node_ev]:
            await event_store.append(e)
        await projector.project([tree_ev, node_ev])

        anchor_ev = make_node_anchored_envelope(
            tree_id=tree_ev.tree_id, node_id=node_id,
        )
        await event_store.append(anchor_ev)
        await projector.project([anchor_ev])

        unanchor_ev = make_node_unanchored_envelope(
            tree_id=tree_ev.tree_id, node_id=node_id,
        )
        await event_store.append(unanchor_ev)
        await projector.project([unanchor_ev])

        row = await db.fetchone(
            "SELECT * FROM node_anchors WHERE tree_id = ? AND node_id = ?",
            (tree_ev.tree_id, node_id),
        )
        assert row is None


# ---------------------------------------------------------------------------
# API integration: is_anchored flag + toggle endpoint
# ---------------------------------------------------------------------------


class TestAnchorAPI:
    """Anchor toggle endpoint and is_anchored on NodeResponse."""

    async def test_is_anchored_reflects_state(self, client):
        """After anchoring, the node's is_anchored is True in tree detail."""
        tree = await create_tree_with_messages(client, n_messages=2)
        tree_id = tree["tree_id"]
        node_ids = tree["node_ids"]
        user_node_id = node_ids[0]

        # Before anchoring
        resp = await client.get(f"/api/trees/{tree_id}")
        assert resp.status_code == 200
        nodes = resp.json()["nodes"]
        user_node = next(n for n in nodes if n["node_id"] == user_node_id)
        assert user_node["is_anchored"] is False

        # Anchor it
        resp = await client.post(
            f"/api/trees/{tree_id}/nodes/{user_node_id}/anchor"
        )
        assert resp.status_code == 200
        assert resp.json()["is_anchored"] is True

        # Verify in tree detail
        resp = await client.get(f"/api/trees/{tree_id}")
        nodes = resp.json()["nodes"]
        user_node = next(n for n in nodes if n["node_id"] == user_node_id)
        assert user_node["is_anchored"] is True

    async def test_toggle_unanchors(self, client):
        """Toggling an anchored node unanchors it."""
        tree = await create_tree_with_messages(client, n_messages=2)
        tree_id = tree["tree_id"]
        node_id = tree["node_ids"][0]

        # Anchor
        resp = await client.post(f"/api/trees/{tree_id}/nodes/{node_id}/anchor")
        assert resp.json()["is_anchored"] is True

        # Toggle again — unanchor
        resp = await client.post(f"/api/trees/{tree_id}/nodes/{node_id}/anchor")
        assert resp.status_code == 200
        assert resp.json()["is_anchored"] is False

        # Verify in tree detail
        resp = await client.get(f"/api/trees/{tree_id}")
        nodes = resp.json()["nodes"]
        node = next(n for n in nodes if n["node_id"] == node_id)
        assert node["is_anchored"] is False


# ---------------------------------------------------------------------------
# Event sourcing integrity: anchors survive replay
# ---------------------------------------------------------------------------


class TestAnchorReplay:
    """Anchors survive event log replay."""

    async def test_anchors_survive_replay(self, event_store, db):
        """Wipe projections, replay events, anchors still there."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(tree_id=tree_ev.tree_id, content="Hello")
        node_id = node_ev.payload["node_id"]

        projector = StateProjector(db)
        for e in [tree_ev, node_ev]:
            await event_store.append(e)
        await projector.project([tree_ev, node_ev])

        anchor_ev = make_node_anchored_envelope(
            tree_id=tree_ev.tree_id, node_id=node_id,
        )
        await event_store.append(anchor_ev)
        await projector.project([anchor_ev])

        # Wipe projections
        await db.execute("DELETE FROM node_anchors")
        row = await db.fetchone(
            "SELECT * FROM node_anchors WHERE node_id = ?", (node_id,)
        )
        assert row is None

        # Replay all events
        all_events = await event_store.get_events(tree_ev.tree_id)
        fresh_projector = StateProjector(db)
        # Clear all projected state first (nodes before trees for FK)
        await db.execute("DELETE FROM node_anchors")
        await db.execute("DELETE FROM nodes")
        await db.execute("DELETE FROM trees")
        await fresh_projector.project(all_events)

        row = await db.fetchone(
            "SELECT * FROM node_anchors WHERE node_id = ?", (node_id,)
        )
        assert row is not None
        assert row["node_id"] == node_id
