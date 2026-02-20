"""Tests for the bookmark system (Phase 6.2).

Four sections:
1. Contract tests -- projector handles BookmarkCreated/Removed/SummaryGenerated
2. API integration tests -- CRUD endpoints, is_bookmarked, search
3. Summary generation -- mock provider, service-level test
4. Event sourcing integrity -- bookmarks survive replay
"""

import pytest

from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from tests.fixtures import (
    create_test_tree,
    create_tree_with_messages,
    make_bookmark_created_envelope,
    make_bookmark_removed_envelope,
    make_bookmark_summary_generated_envelope,
    make_node_created_envelope,
    make_tree_created_envelope,
)


# ---------------------------------------------------------------------------
# Contract tests: event -> store -> projector -> verify state
# ---------------------------------------------------------------------------


class TestBookmarkProjection:
    """BookmarkCreated/Removed/SummaryGenerated events project correctly."""

    async def test_bookmark_created_projects(self, event_store, projector, db):
        """BookmarkCreated inserts a row into the bookmarks table."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(tree_id=tree_ev.tree_id, content="Hello")

        for e in [tree_ev, node_ev]:
            await event_store.append(e)
        await projector.project([tree_ev, node_ev])

        bm_ev = make_bookmark_created_envelope(
            tree_id=tree_ev.tree_id,
            node_id=node_ev.payload["node_id"],
            label="Interesting point",
            notes="Worth revisiting",
        )
        await event_store.append(bm_ev)
        await projector.project([bm_ev])

        row = await db.fetchone(
            "SELECT * FROM bookmarks WHERE bookmark_id = ?",
            (bm_ev.payload["bookmark_id"],),
        )
        assert row is not None
        assert row["label"] == "Interesting point"
        assert row["notes"] == "Worth revisiting"
        assert row["node_id"] == node_ev.payload["node_id"]
        assert row["tree_id"] == tree_ev.tree_id
        assert row["summary"] is None
        assert row["summary_model"] is None

    async def test_bookmark_removed_deletes_row(self, event_store, projector, db):
        """BookmarkRemoved deletes the bookmark from the table."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(tree_id=tree_ev.tree_id, content="Hello")

        for e in [tree_ev, node_ev]:
            await event_store.append(e)
        await projector.project([tree_ev, node_ev])

        bm_ev = make_bookmark_created_envelope(
            tree_id=tree_ev.tree_id,
            node_id=node_ev.payload["node_id"],
        )
        await event_store.append(bm_ev)
        await projector.project([bm_ev])

        remove_ev = make_bookmark_removed_envelope(
            tree_id=tree_ev.tree_id,
            bookmark_id=bm_ev.payload["bookmark_id"],
        )
        await event_store.append(remove_ev)
        await projector.project([remove_ev])

        row = await db.fetchone(
            "SELECT * FROM bookmarks WHERE bookmark_id = ?",
            (bm_ev.payload["bookmark_id"],),
        )
        assert row is None

    async def test_bookmark_summary_generated_updates_row(self, event_store, projector, db):
        """BookmarkSummaryGenerated updates summary fields on existing bookmark."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(tree_id=tree_ev.tree_id, content="Hello")

        for e in [tree_ev, node_ev]:
            await event_store.append(e)
        await projector.project([tree_ev, node_ev])

        bm_ev = make_bookmark_created_envelope(
            tree_id=tree_ev.tree_id,
            node_id=node_ev.payload["node_id"],
        )
        await event_store.append(bm_ev)
        await projector.project([bm_ev])

        node_id = node_ev.payload["node_id"]
        summary_ev = make_bookmark_summary_generated_envelope(
            tree_id=tree_ev.tree_id,
            bookmark_id=bm_ev.payload["bookmark_id"],
            summary="User greeted the model and received a friendly response.",
            model="claude-haiku-4-5",
            summarized_node_ids=[node_id],
        )
        await event_store.append(summary_ev)
        await projector.project([summary_ev])

        row = await db.fetchone(
            "SELECT * FROM bookmarks WHERE bookmark_id = ?",
            (bm_ev.payload["bookmark_id"],),
        )
        assert row["summary"] == "User greeted the model and received a friendly response."
        assert row["summary_model"] == "claude-haiku-4-5"
        assert node_id in row["summarized_node_ids"]


# ---------------------------------------------------------------------------
# API integration tests: bookmark CRUD
# ---------------------------------------------------------------------------


class TestBookmarkCRUD:
    """POST/GET/DELETE bookmark endpoints."""

    async def test_add_bookmark_returns_response(self, client):
        """POST bookmark returns BookmarkResponse with correct fields."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        resp = await client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/bookmarks",
            json={"label": "Important moment"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["label"] == "Important moment"
        assert body["node_id"] == node_id
        assert body["tree_id"] == tree_id
        assert "bookmark_id" in body
        assert "created_at" in body
        assert body["notes"] is None
        assert body["summary"] is None

    async def test_add_bookmark_with_notes(self, client):
        """POST bookmark with notes persists them."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        resp = await client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/bookmarks",
            json={"label": "Flag", "notes": "Come back to this later"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["notes"] == "Come back to this later"

    async def test_get_tree_bookmarks(self, client):
        """GET returns all bookmarks for a tree."""
        data = await create_tree_with_messages(client, n_messages=4)
        tree_id = data["tree_id"]

        for i, node_id in enumerate(data["node_ids"][:3]):
            await client.post(
                f"/api/trees/{tree_id}/nodes/{node_id}/bookmarks",
                json={"label": f"Bookmark {i}"},
            )

        resp = await client.get(f"/api/trees/{tree_id}/bookmarks")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 3
        labels = [b["label"] for b in body]
        assert "Bookmark 0" in labels
        assert "Bookmark 1" in labels
        assert "Bookmark 2" in labels

    async def test_get_bookmarks_empty(self, client):
        """GET bookmarks on tree with none returns empty list."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        resp = await client.get(f"/api/trees/{tree_id}/bookmarks")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_remove_bookmark(self, client):
        """DELETE removes bookmark; subsequent GET excludes it."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        add_resp = await client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/bookmarks",
            json={"label": "Temp"},
        )
        bookmark_id = add_resp.json()["bookmark_id"]

        del_resp = await client.delete(
            f"/api/trees/{tree_id}/bookmarks/{bookmark_id}",
        )
        assert del_resp.status_code == 204

        get_resp = await client.get(f"/api/trees/{tree_id}/bookmarks")
        assert get_resp.json() == []

    async def test_remove_nonexistent_bookmark_404(self, client):
        """DELETE on nonexistent bookmark returns 404."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        resp = await client.delete(
            f"/api/trees/{tree_id}/bookmarks/no-such-bookmark",
        )
        assert resp.status_code == 404

    async def test_add_bookmark_nonexistent_tree_404(self, client):
        """POST bookmark on nonexistent tree returns 404."""
        resp = await client.post(
            "/api/trees/no-such-tree/nodes/no-such-node/bookmarks",
            json={"label": "Nope"},
        )
        assert resp.status_code == 404

    async def test_add_bookmark_nonexistent_node_404(self, client):
        """POST bookmark on nonexistent node returns 404."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        resp = await client.post(
            f"/api/trees/{tree_id}/nodes/no-such-node/bookmarks",
            json={"label": "Nope"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# is_bookmarked on NodeResponse
# ---------------------------------------------------------------------------


class TestIsBookmarked:
    """is_bookmarked flag on NodeResponse reflects bookmark state."""

    async def test_is_bookmarked_true_when_bookmarked(self, client):
        """After bookmarking, node has is_bookmarked=True."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        await client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/bookmarks",
            json={"label": "Marked"},
        )

        resp = await client.get(f"/api/trees/{tree_id}")
        tree = resp.json()
        node = next(n for n in tree["nodes"] if n["node_id"] == node_id)
        assert node["is_bookmarked"] is True

    async def test_is_bookmarked_false_by_default(self, client):
        """Unbookmarked nodes have is_bookmarked=False."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]

        resp = await client.get(f"/api/trees/{tree_id}")
        tree = resp.json()
        for node in tree["nodes"]:
            assert node["is_bookmarked"] is False

    async def test_is_bookmarked_reverts_after_removal(self, client):
        """After removing a bookmark, is_bookmarked reverts to False."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        add_resp = await client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/bookmarks",
            json={"label": "Temp"},
        )
        bookmark_id = add_resp.json()["bookmark_id"]

        await client.delete(f"/api/trees/{tree_id}/bookmarks/{bookmark_id}")

        resp = await client.get(f"/api/trees/{tree_id}")
        tree = resp.json()
        node = next(n for n in tree["nodes"] if n["node_id"] == node_id)
        assert node["is_bookmarked"] is False


# ---------------------------------------------------------------------------
# Search tests
# ---------------------------------------------------------------------------


class TestBookmarkSearch:
    """GET /api/trees/{tree_id}/bookmarks?q= filters by label/summary/notes."""

    async def test_search_by_label(self, client):
        """Search bookmarks by label substring."""
        data = await create_tree_with_messages(client, n_messages=4)
        tree_id = data["tree_id"]

        await client.post(
            f"/api/trees/{tree_id}/nodes/{data['node_ids'][0]}/bookmarks",
            json={"label": "The hallucination moment"},
        )
        await client.post(
            f"/api/trees/{tree_id}/nodes/{data['node_ids'][1]}/bookmarks",
            json={"label": "Personality shift"},
        )

        resp = await client.get(f"/api/trees/{tree_id}/bookmarks?q=hallucination")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["label"] == "The hallucination moment"

    async def test_search_by_summary(self, event_store, projector, db, client):
        """Search bookmarks by summary content (injected via projection)."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        # Add a bookmark via API
        add_resp = await client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/bookmarks",
            json={"label": "Test bookmark"},
        )
        bookmark_id = add_resp.json()["bookmark_id"]

        # Inject a summary via event projection (simulating what the service would do)
        summary_ev = make_bookmark_summary_generated_envelope(
            tree_id=tree_id,
            bookmark_id=bookmark_id,
            summary="The user discussed quantum physics with the model.",
            summarized_node_ids=[node_id],
        )
        await event_store.append(summary_ev)
        await projector.project([summary_ev])

        # Search by summary content
        resp = await client.get(f"/api/trees/{tree_id}/bookmarks?q=quantum")
        body = resp.json()
        assert len(body) == 1
        assert "quantum" in body[0]["summary"].lower()


# ---------------------------------------------------------------------------
# Summary generation (service-level with mock)
# ---------------------------------------------------------------------------


class TestBookmarkSummaryGeneration:
    """generate_bookmark_summary calls the summary client and stores result."""

    async def test_generate_summary_stores_result(self, client, db):
        """Summary generation creates a BookmarkSummaryGenerated event and updates the bookmark."""
        from unittest.mock import AsyncMock, MagicMock

        from qivis.trees.service import TreeService

        # Create a tree with messages
        data = await create_tree_with_messages(client, n_messages=4)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][-1]  # Bookmark the last node

        # Create a service with a mock summary client
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="A summary of the conversation branch.")]
        mock_response.model = "claude-haiku-4-5-20251001"
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        service = TreeService(db, summary_client=mock_client)

        # Add a bookmark
        from qivis.trees.schemas import CreateBookmarkRequest

        bookmark = await service.add_bookmark(
            tree_id, node_id, CreateBookmarkRequest(label="Test"),
        )

        # Generate summary
        result = await service.generate_bookmark_summary(tree_id, bookmark.bookmark_id)

        assert result.summary == "A summary of the conversation branch."
        assert result.summary_model == "claude-haiku-4-5-20251001"
        assert result.summarized_node_ids is not None
        assert len(result.summarized_node_ids) > 0
        assert node_id in result.summarized_node_ids

        # Verify the mock was called with the configurable summary model
        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs["model"] == "claude-haiku-4-5-20251001"


# ---------------------------------------------------------------------------
# Event sourcing integrity
# ---------------------------------------------------------------------------


class TestBookmarkEventReplay:
    """Bookmarks + summaries survive full event replay."""

    async def test_bookmarks_survive_replay(self, event_store, projector, db):
        """Rebuild all projections from scratch -- bookmarks are consistent."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(tree_id=tree_ev.tree_id, content="Hello")

        for e in [tree_ev, node_ev]:
            await event_store.append(e)
        await projector.project([tree_ev, node_ev])

        node_id = node_ev.payload["node_id"]

        # Add two bookmarks
        bm1 = make_bookmark_created_envelope(
            tree_id=tree_ev.tree_id, node_id=node_id, label="First",
        )
        bm2 = make_bookmark_created_envelope(
            tree_id=tree_ev.tree_id, node_id=node_id, label="Second",
        )
        for e in [bm1, bm2]:
            await event_store.append(e)
        await projector.project([bm1, bm2])

        # Generate summary on bm2
        summary_ev = make_bookmark_summary_generated_envelope(
            tree_id=tree_ev.tree_id,
            bookmark_id=bm2.payload["bookmark_id"],
            summary="A test summary.",
            summarized_node_ids=[node_id],
        )
        await event_store.append(summary_ev)
        await projector.project([summary_ev])

        # Remove bm1
        remove_ev = make_bookmark_removed_envelope(
            tree_id=tree_ev.tree_id,
            bookmark_id=bm1.payload["bookmark_id"],
        )
        await event_store.append(remove_ev)
        await projector.project([remove_ev])

        # Wipe materialized tables and replay
        await db.execute("DELETE FROM bookmarks")
        await db.execute("DELETE FROM annotations")
        await db.execute("DELETE FROM nodes")
        await db.execute("DELETE FROM trees")

        all_events = await event_store.get_events(tree_ev.tree_id)
        fresh_projector = StateProjector(db)
        await fresh_projector.project(all_events)

        # Only bm2 should remain, with its summary
        rows = await db.fetchall(
            "SELECT * FROM bookmarks WHERE tree_id = ?",
            (tree_ev.tree_id,),
        )
        assert len(rows) == 1
        assert rows[0]["bookmark_id"] == bm2.payload["bookmark_id"]
        assert rows[0]["label"] == "Second"
        assert rows[0]["summary"] == "A test summary."
