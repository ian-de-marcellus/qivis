"""Tests for the annotation system (Phase 6.1).

Three sections:
1. Contract tests — projector handles AnnotationAdded/Removed events correctly
2. API integration tests — CRUD endpoints, aggregates, taxonomy
3. Event sourcing integrity — annotations survive replay
"""

import pytest

from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from tests.fixtures import (
    create_test_tree,
    create_tree_with_messages,
    make_annotation_added_envelope,
    make_annotation_removed_envelope,
    make_node_created_envelope,
    make_tree_created_envelope,
)


# ---------------------------------------------------------------------------
# Contract tests: event -> store -> projector -> verify state
# ---------------------------------------------------------------------------


class TestAnnotationProjection:
    """AnnotationAdded/Removed events project into the annotations table."""

    async def test_annotation_added_projects(self, event_store, projector, db):
        """AnnotationAdded inserts a row into the annotations table."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(tree_id=tree_ev.tree_id, content="Hello")

        for e in [tree_ev, node_ev]:
            await event_store.append(e)
        await projector.project([tree_ev, node_ev])

        ann_ev = make_annotation_added_envelope(
            tree_id=tree_ev.tree_id,
            node_id=node_ev.payload["node_id"],
            tag="interesting",
        )
        await event_store.append(ann_ev)
        await projector.project([ann_ev])

        row = await db.fetchone(
            "SELECT * FROM annotations WHERE annotation_id = ?",
            (ann_ev.payload["annotation_id"],),
        )
        assert row is not None
        assert row["tag"] == "interesting"
        assert row["node_id"] == node_ev.payload["node_id"]
        assert row["tree_id"] == tree_ev.tree_id

    async def test_annotation_removed_deletes_row(self, event_store, projector, db):
        """AnnotationRemoved deletes the annotation from the table."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(tree_id=tree_ev.tree_id, content="Hello")

        for e in [tree_ev, node_ev]:
            await event_store.append(e)
        await projector.project([tree_ev, node_ev])

        ann_ev = make_annotation_added_envelope(
            tree_id=tree_ev.tree_id,
            node_id=node_ev.payload["node_id"],
            tag="hallucination",
        )
        await event_store.append(ann_ev)
        await projector.project([ann_ev])

        remove_ev = make_annotation_removed_envelope(
            tree_id=tree_ev.tree_id,
            annotation_id=ann_ev.payload["annotation_id"],
        )
        await event_store.append(remove_ev)
        await projector.project([remove_ev])

        row = await db.fetchone(
            "SELECT * FROM annotations WHERE annotation_id = ?",
            (ann_ev.payload["annotation_id"],),
        )
        assert row is None

    async def test_annotation_with_value_and_notes(self, event_store, projector, db):
        """AnnotationAdded with value and notes persists both."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(tree_id=tree_ev.tree_id, content="Hello")

        for e in [tree_ev, node_ev]:
            await event_store.append(e)
        await projector.project([tree_ev, node_ev])

        ann_ev = make_annotation_added_envelope(
            tree_id=tree_ev.tree_id,
            node_id=node_ev.payload["node_id"],
            tag="emotional-response",
            value="strong",
            notes="Model showed empathy unprompted",
        )
        await event_store.append(ann_ev)
        await projector.project([ann_ev])

        row = await db.fetchone(
            "SELECT * FROM annotations WHERE annotation_id = ?",
            (ann_ev.payload["annotation_id"],),
        )
        assert row["value"] == '"strong"'  # JSON-serialized
        assert row["notes"] == "Model showed empathy unprompted"


# ---------------------------------------------------------------------------
# API integration tests: annotation CRUD
# ---------------------------------------------------------------------------


class TestAnnotationCRUD:
    """POST/GET/DELETE annotation endpoints."""

    async def test_add_annotation_returns_response(self, client):
        """POST annotation returns AnnotationResponse with correct fields."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        resp = await client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/annotations",
            json={"tag": "interesting"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["tag"] == "interesting"
        assert body["node_id"] == node_id
        assert body["tree_id"] == tree_id
        assert "annotation_id" in body
        assert "created_at" in body
        assert body["value"] is None
        assert body["notes"] is None

    async def test_add_annotation_with_value_and_notes(self, client):
        """POST annotation with value and notes persists both."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        resp = await client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/annotations",
            json={"tag": "hallucination", "value": True, "notes": "Fabricated a citation"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["tag"] == "hallucination"
        assert body["value"] is True
        assert body["notes"] == "Fabricated a citation"

    async def test_add_annotation_unique_ids(self, client):
        """Two annotations get distinct annotation_ids."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        resp1 = await client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/annotations",
            json={"tag": "interesting"},
        )
        resp2 = await client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/annotations",
            json={"tag": "hallucination"},
        )
        assert resp1.json()["annotation_id"] != resp2.json()["annotation_id"]

    async def test_get_node_annotations(self, client):
        """GET returns all annotations for a node, sorted by created_at."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        for tag in ["interesting", "hallucination", "contradiction"]:
            await client.post(
                f"/api/trees/{tree_id}/nodes/{node_id}/annotations",
                json={"tag": tag},
            )

        resp = await client.get(
            f"/api/trees/{tree_id}/nodes/{node_id}/annotations",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 3
        tags = [a["tag"] for a in body]
        assert "interesting" in tags
        assert "hallucination" in tags
        assert "contradiction" in tags

    async def test_get_annotations_empty(self, client):
        """GET annotations for unannotated node returns empty list."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        resp = await client.get(
            f"/api/trees/{tree_id}/nodes/{node_id}/annotations",
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_remove_annotation(self, client):
        """DELETE removes annotation; subsequent GET excludes it."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        add_resp = await client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/annotations",
            json={"tag": "interesting"},
        )
        annotation_id = add_resp.json()["annotation_id"]

        del_resp = await client.delete(
            f"/api/trees/{tree_id}/annotations/{annotation_id}",
        )
        assert del_resp.status_code == 204

        get_resp = await client.get(
            f"/api/trees/{tree_id}/nodes/{node_id}/annotations",
        )
        assert get_resp.json() == []

    async def test_remove_nonexistent_annotation_404(self, client):
        """DELETE on nonexistent annotation returns 404."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        resp = await client.delete(
            f"/api/trees/{tree_id}/annotations/no-such-annotation",
        )
        assert resp.status_code == 404

    async def test_add_annotation_nonexistent_tree_404(self, client):
        """POST annotation on nonexistent tree returns 404."""
        resp = await client.post(
            "/api/trees/no-such-tree/nodes/no-such-node/annotations",
            json={"tag": "interesting"},
        )
        assert resp.status_code == 404

    async def test_add_annotation_nonexistent_node_404(self, client):
        """POST annotation on nonexistent node returns 404."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        resp = await client.post(
            f"/api/trees/{tree_id}/nodes/no-such-node/annotations",
            json={"tag": "interesting"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Aggregate tests: annotation_count on NodeResponse
# ---------------------------------------------------------------------------


class TestAnnotationCount:
    """annotation_count on NodeResponse reflects actual annotation count."""

    async def test_annotation_count_reflects_annotations(self, client):
        """After adding annotations, annotation_count on the node is correct."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        await client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/annotations",
            json={"tag": "interesting"},
        )
        await client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/annotations",
            json={"tag": "hallucination"},
        )

        resp = await client.get(f"/api/trees/{tree_id}")
        tree = resp.json()
        node = next(n for n in tree["nodes"] if n["node_id"] == node_id)
        assert node["annotation_count"] == 2

    async def test_annotation_count_zero_for_unannotated(self, client):
        """Unannotated nodes have annotation_count = 0."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]

        resp = await client.get(f"/api/trees/{tree_id}")
        tree = resp.json()
        for node in tree["nodes"]:
            assert node["annotation_count"] == 0

    async def test_annotation_count_decrements_after_removal(self, client):
        """Removing an annotation decrements the count."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        add_resp = await client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/annotations",
            json={"tag": "interesting"},
        )
        annotation_id = add_resp.json()["annotation_id"]

        await client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/annotations",
            json={"tag": "hallucination"},
        )

        # Count should be 2
        resp = await client.get(f"/api/trees/{tree_id}")
        node = next(n for n in resp.json()["nodes"] if n["node_id"] == node_id)
        assert node["annotation_count"] == 2

        # Remove one
        await client.delete(f"/api/trees/{tree_id}/annotations/{annotation_id}")

        # Count should be 1
        resp = await client.get(f"/api/trees/{tree_id}")
        node = next(n for n in resp.json()["nodes"] if n["node_id"] == node_id)
        assert node["annotation_count"] == 1


# ---------------------------------------------------------------------------
# Taxonomy tests
# ---------------------------------------------------------------------------


class TestTaxonomy:
    """GET /api/trees/{tree_id}/taxonomy returns base + used tags."""

    async def test_taxonomy_returns_base_tags(self, client):
        """Taxonomy includes the base tags from the YAML file."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        resp = await client.get(f"/api/trees/{tree_id}/taxonomy")
        assert resp.status_code == 200
        body = resp.json()
        assert "hallucination" in body["base_tags"]
        assert "interesting" in body["base_tags"]
        assert "personality-shift" in body["base_tags"]

    async def test_taxonomy_includes_custom_used_tags(self, client):
        """Custom tags from annotations appear in used_tags."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        await client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/annotations",
            json={"tag": "my-custom-tag"},
        )

        resp = await client.get(f"/api/trees/{tree_id}/taxonomy")
        body = resp.json()
        assert "my-custom-tag" in body["used_tags"]

    async def test_taxonomy_deduplicates_base_and_used(self, client):
        """Tags that are both base and used don't appear twice in used_tags needlessly."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        # Use a base tag as an annotation
        await client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/annotations",
            json={"tag": "hallucination"},
        )

        resp = await client.get(f"/api/trees/{tree_id}/taxonomy")
        body = resp.json()
        # hallucination should be in base_tags and in used_tags
        assert "hallucination" in body["base_tags"]
        assert "hallucination" in body["used_tags"]
        # used_tags should not have duplicates
        assert len(body["used_tags"]) == len(set(body["used_tags"]))


# ---------------------------------------------------------------------------
# Event sourcing integrity
# ---------------------------------------------------------------------------


class TestAnnotationEventReplay:
    """Annotations survive full event replay (rebuild projections from events)."""

    async def test_annotations_survive_replay(self, event_store, projector, db):
        """Rebuild all projections from scratch — annotations are consistent."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(tree_id=tree_ev.tree_id, content="Hello")

        for e in [tree_ev, node_ev]:
            await event_store.append(e)
        await projector.project([tree_ev, node_ev])

        node_id = node_ev.payload["node_id"]

        # Add two annotations
        ann1 = make_annotation_added_envelope(
            tree_id=tree_ev.tree_id, node_id=node_id, tag="interesting",
        )
        ann2 = make_annotation_added_envelope(
            tree_id=tree_ev.tree_id, node_id=node_id, tag="hallucination",
        )
        for e in [ann1, ann2]:
            await event_store.append(e)
        await projector.project([ann1, ann2])

        # Remove first annotation
        remove_ev = make_annotation_removed_envelope(
            tree_id=tree_ev.tree_id,
            annotation_id=ann1.payload["annotation_id"],
        )
        await event_store.append(remove_ev)
        await projector.project([remove_ev])

        # Wipe materialized tables and replay
        await db.execute("DELETE FROM annotations")
        await db.execute("DELETE FROM nodes")
        await db.execute("DELETE FROM trees")

        all_events = await event_store.get_events(tree_ev.tree_id)
        fresh_projector = StateProjector(db)
        await fresh_projector.project(all_events)

        # Only ann2 should remain
        rows = await db.fetchall(
            "SELECT * FROM annotations WHERE tree_id = ?",
            (tree_ev.tree_id,),
        )
        assert len(rows) == 1
        assert rows[0]["annotation_id"] == ann2.payload["annotation_id"]
        assert rows[0]["tag"] == "hallucination"
