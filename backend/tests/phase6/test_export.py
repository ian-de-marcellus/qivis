"""Tests for the export system (Phase 6.4d).

Tests JSON export, CSV export, and tree paths endpoint.
"""

import csv
import io
import json

import pytest
from httpx import ASGITransport, AsyncClient

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.export.router import get_export_service
from qivis.export.service import ExportService
from qivis.main import app
from qivis.trees.router import get_tree_service
from qivis.trees.service import TreeService
from tests.fixtures import (
    create_test_tree,
    create_tree_with_messages,
)


@pytest.fixture
async def export_client(db: Database) -> AsyncClient:
    """Test client with export routes available."""
    service = TreeService(db)
    store = EventStore(db)
    projector = StateProjector(db)
    export_svc = ExportService(db, store, projector)
    app.dependency_overrides[get_tree_service] = lambda: service
    app.dependency_overrides[get_export_service] = lambda: export_svc
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def export_service(db: Database) -> ExportService:
    """ExportService backed by in-memory DB."""
    store = EventStore(db)
    projector = StateProjector(db)
    return ExportService(db, store, projector)


# ---------------------------------------------------------------------------
# JSON export tests
# ---------------------------------------------------------------------------


class TestJsonExport:
    """JSON export includes tree metadata, nodes, and research data."""

    async def test_json_includes_tree_metadata(self, export_client):
        """Export JSON contains tree-level metadata."""
        data = await create_tree_with_messages(export_client, n_messages=4)
        tree_id = data["tree_id"]

        resp = await export_client.get(f"/api/trees/{tree_id}/export?format=json")
        assert resp.status_code == 200
        export = resp.json()

        assert export["source"] == "qivis"
        assert export["version"] == "1.0"
        assert "exported_at" in export
        assert export["tree"]["tree_id"] == tree_id
        assert "title" in export["tree"]
        assert "created_at" in export["tree"]
        assert "updated_at" in export["tree"]

    async def test_json_includes_all_nodes(self, export_client):
        """Export JSON contains all nodes with content and metadata."""
        data = await create_tree_with_messages(export_client, n_messages=4)
        tree_id = data["tree_id"]
        node_ids = data["node_ids"]

        resp = await export_client.get(f"/api/trees/{tree_id}/export?format=json")
        export = resp.json()

        exported_ids = {n["node_id"] for n in export["nodes"]}
        for nid in node_ids:
            assert nid in exported_ids

        # Check node structure
        node = export["nodes"][0]
        assert "node_id" in node
        assert "parent_id" in node
        assert "role" in node
        assert "content" in node
        assert "created_at" in node

    async def test_json_includes_annotations(self, export_client, db):
        """Export JSON has annotations inlined on nodes."""
        data = await create_tree_with_messages(export_client, n_messages=4)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        # Add an annotation
        resp = await export_client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/annotations",
            json={"tag": "interesting", "value": 0.8, "notes": "good one"},
        )
        assert resp.status_code == 201

        resp = await export_client.get(f"/api/trees/{tree_id}/export?format=json")
        export = resp.json()

        annotated_node = next(n for n in export["nodes"] if n["node_id"] == node_id)
        assert len(annotated_node["annotations"]) == 1
        assert annotated_node["annotations"][0]["tag"] == "interesting"

    async def test_json_includes_bookmarks(self, export_client):
        """Export JSON has bookmarks section."""
        data = await create_tree_with_messages(export_client, n_messages=4)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][-1]

        # Add a bookmark
        resp = await export_client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/bookmarks",
            json={"label": "Key moment"},
        )
        assert resp.status_code == 201

        resp = await export_client.get(f"/api/trees/{tree_id}/export?format=json")
        export = resp.json()

        assert len(export["bookmarks"]) == 1
        assert export["bookmarks"][0]["label"] == "Key moment"

    async def test_json_includes_exclusions(self, export_client):
        """Export JSON has exclusions section."""
        data = await create_tree_with_messages(export_client, n_messages=4)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][1]
        scope_id = data["node_ids"][-1]

        resp = await export_client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/exclude",
            json={"scope_node_id": scope_id},
        )
        assert resp.status_code == 200

        resp = await export_client.get(f"/api/trees/{tree_id}/export?format=json")
        export = resp.json()

        assert len(export["exclusions"]) >= 1

    async def test_json_includes_digression_groups(self, export_client):
        """Export JSON has digression_groups section."""
        data = await create_tree_with_messages(export_client, n_messages=4)
        tree_id = data["tree_id"]

        resp = await export_client.post(
            f"/api/trees/{tree_id}/digression-groups",
            json={
                "node_ids": data["node_ids"][:2],
                "label": "Tangent",
            },
        )
        assert resp.status_code == 201

        resp = await export_client.get(f"/api/trees/{tree_id}/export?format=json")
        export = resp.json()

        assert len(export["digression_groups"]) == 1
        assert export["digression_groups"][0]["label"] == "Tangent"

    async def test_json_with_events(self, export_client):
        """include_events=true adds the event log."""
        data = await create_tree_with_messages(export_client, n_messages=2)
        tree_id = data["tree_id"]

        resp = await export_client.get(
            f"/api/trees/{tree_id}/export?format=json&include_events=true"
        )
        export = resp.json()

        assert "events" in export
        assert len(export["events"]) > 0
        assert export["events"][0]["event_type"] == "TreeCreated"

    async def test_json_without_events(self, export_client):
        """include_events=false (default) omits event log."""
        data = await create_tree_with_messages(export_client, n_messages=2)
        tree_id = data["tree_id"]

        resp = await export_client.get(f"/api/trees/{tree_id}/export?format=json")
        export = resp.json()

        assert "events" not in export


# ---------------------------------------------------------------------------
# CSV export tests
# ---------------------------------------------------------------------------


class TestCsvExport:
    """CSV export with one row per node."""

    async def test_csv_one_row_per_node(self, export_client):
        """CSV has one row per node with correct headers."""
        data = await create_tree_with_messages(export_client, n_messages=4)
        tree_id = data["tree_id"]

        resp = await export_client.get(f"/api/trees/{tree_id}/export?format=csv")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert "attachment" in resp.headers.get("content-disposition", "")

        reader = csv.DictReader(io.StringIO(resp.text))
        rows = list(reader)

        assert len(rows) == 4
        assert "node_id" in reader.fieldnames
        assert "parent_id" in reader.fieldnames
        assert "role" in reader.fieldnames
        assert "content" in reader.fieldnames
        assert "created_at" in reader.fieldnames

    async def test_csv_annotation_tags_comma_separated(self, export_client):
        """CSV has annotation_tags as comma-separated values."""
        data = await create_tree_with_messages(export_client, n_messages=4)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        # Add two annotations
        await export_client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/annotations",
            json={"tag": "interesting"},
        )
        await export_client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/annotations",
            json={"tag": "coherent"},
        )

        resp = await export_client.get(f"/api/trees/{tree_id}/export?format=csv")
        reader = csv.DictReader(io.StringIO(resp.text))
        rows = list(reader)

        annotated = next(r for r in rows if r["node_id"] == node_id)
        tags = annotated["annotation_tags"]
        assert "interesting" in tags
        assert "coherent" in tags


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestExportErrors:
    """Export endpoints handle errors gracefully."""

    async def test_nonexistent_tree_404(self, export_client):
        """Export of nonexistent tree returns 404."""
        resp = await export_client.get("/api/trees/nonexistent/export?format=json")
        assert resp.status_code == 404

    async def test_invalid_format_422(self, export_client):
        """Invalid format parameter returns 422."""
        data = await create_tree_with_messages(export_client, n_messages=2)
        tree_id = data["tree_id"]
        resp = await export_client.get(f"/api/trees/{tree_id}/export?format=xml")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Paths endpoint
# ---------------------------------------------------------------------------


class TestTreePaths:
    """GET /paths returns all root-to-leaf paths."""

    async def test_linear_one_path(self, export_client):
        """Linear conversation has exactly one path."""
        data = await create_tree_with_messages(export_client, n_messages=4)
        tree_id = data["tree_id"]

        resp = await export_client.get(f"/api/trees/{tree_id}/paths")
        assert resp.status_code == 200
        paths = resp.json()["paths"]

        assert len(paths) == 1
        assert paths[0] == data["node_ids"]

    async def test_branching_multiple_paths(self, export_client):
        """Branching conversation produces multiple paths."""
        data = await create_tree_with_messages(export_client, n_messages=4)
        tree_id = data["tree_id"]

        # Create a branch from node_ids[1] (the second node)
        branch_parent = data["node_ids"][1]
        resp = await export_client.post(
            f"/api/trees/{tree_id}/nodes",
            json={"content": "Branch message", "role": "user", "parent_id": branch_parent},
        )
        assert resp.status_code == 201
        branch_node_id = resp.json()["node_id"]

        resp = await export_client.get(f"/api/trees/{tree_id}/paths")
        paths = resp.json()["paths"]

        assert len(paths) == 2
        # One path goes through the original chain
        assert any(data["node_ids"][-1] in p for p in paths)
        # Another path goes through the branch
        assert any(branch_node_id in p for p in paths)

    async def test_empty_tree_no_paths(self, export_client):
        """Tree with no nodes has no paths."""
        tree = await create_test_tree(export_client)
        tree_id = tree["tree_id"]

        resp = await export_client.get(f"/api/trees/{tree_id}/paths")
        paths = resp.json()["paths"]
        assert len(paths) == 0

    async def test_paths_nonexistent_tree_404(self, export_client):
        """Paths of nonexistent tree returns 404."""
        resp = await export_client.get("/api/trees/nonexistent/paths")
        assert resp.status_code == 404
