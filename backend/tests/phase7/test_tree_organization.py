"""Tests for tree organization: archive/unarchive + enriched RhizomeSummary (Phase 7.4).

Three sections:
1. Contract tests -- projector handles TreeArchived/TreeUnarchived events
2. Integration tests -- API endpoints for archive, list filtering
3. RhizomeSummary enrichment tests -- folders/tags parsed from metadata
"""

import pytest

from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.rhizomes.service import RhizomeNotFoundError, RhizomeService
from tests.fixtures import (
    create_test_rhizome,
    make_rhizome_archived_envelope,
    make_rhizome_created_envelope,
    make_rhizome_unarchived_envelope,
)


# ---------------------------------------------------------------------------
# Contract tests: event -> store -> projector -> verify state
# ---------------------------------------------------------------------------


class TestArchiveProjection:
    """TreeArchived/TreeUnarchived events update the archived flag."""

    async def test_tree_archived_sets_flag(self, event_store, projector, db):
        """TreeArchived sets archived = 1 in the trees table."""
        tree_ev = make_rhizome_created_envelope()
        await event_store.append(tree_ev)
        await projector.project([tree_ev])

        archive_ev = make_rhizome_archived_envelope(rhizome_id=tree_ev.rhizome_id, reason="done")
        await event_store.append(archive_ev)
        await projector.project([archive_ev])

        row = await db.fetchone(
            "SELECT archived FROM rhizomes WHERE rhizome_id = ?",
            (tree_ev.rhizome_id,),
        )
        assert row is not None
        assert row["archived"] == 1

    async def test_tree_unarchived_clears_flag(self, event_store, projector, db):
        """TreeUnarchived sets archived = 0 in the trees table."""
        tree_ev = make_rhizome_created_envelope()
        await event_store.append(tree_ev)
        await projector.project([tree_ev])

        archive_ev = make_rhizome_archived_envelope(rhizome_id=tree_ev.rhizome_id)
        await event_store.append(archive_ev)
        await projector.project([archive_ev])

        unarchive_ev = make_rhizome_unarchived_envelope(rhizome_id=tree_ev.rhizome_id)
        await event_store.append(unarchive_ev)
        await projector.project([unarchive_ev])

        row = await db.fetchone(
            "SELECT archived FROM rhizomes WHERE rhizome_id = ?",
            (tree_ev.rhizome_id,),
        )
        assert row is not None
        assert row["archived"] == 0

    async def test_archive_events_survive_replay(self, event_store, projector, db):
        """Archive state survives full event replay from scratch."""
        tree_ev = make_rhizome_created_envelope()
        archive_ev = make_rhizome_archived_envelope(rhizome_id=tree_ev.rhizome_id)

        all_events = [tree_ev, archive_ev]
        for e in all_events:
            await event_store.append(e)

        # Clear and replay
        await db.execute("DELETE FROM rhizomes")
        fresh_projector = StateProjector(db)
        await fresh_projector.project(all_events)

        row = await db.fetchone(
            "SELECT archived FROM rhizomes WHERE rhizome_id = ?",
            (tree_ev.rhizome_id,),
        )
        assert row is not None
        assert row["archived"] == 1


# ---------------------------------------------------------------------------
# Integration tests: API round-trips
# ---------------------------------------------------------------------------


class TestArchiveAPI:
    """API endpoints for tree archiving."""

    async def test_archive_tree(self, client, db):
        """POST /archive returns the tree with archived flag set."""
        tree = await create_test_rhizome(client, title="To Archive")
        rhizome_id = tree["rhizome_id"]

        resp = await client.post(f"/api/rhizomes/{rhizome_id}/archive")
        assert resp.status_code == 200
        data = resp.json()
        assert data["archived"] == 1

    async def test_archived_tree_excluded_from_list(self, client, db):
        """Archived tree is excluded from GET /trees by default."""
        tree = await create_test_rhizome(client, title="Archivable")
        rhizome_id = tree["rhizome_id"]

        await client.post(f"/api/rhizomes/{rhizome_id}/archive")

        resp = await client.get("/api/rhizomes")
        rhizome_ids = [t["rhizome_id"] for t in resp.json()]
        assert rhizome_id not in rhizome_ids

    async def test_include_archived_query_param(self, client, db):
        """GET /trees?include_archived=true includes archived trees."""
        tree = await create_test_rhizome(client, title="Archivable")
        rhizome_id = tree["rhizome_id"]

        await client.post(f"/api/rhizomes/{rhizome_id}/archive")

        resp = await client.get("/api/rhizomes?include_archived=true")
        rhizome_ids = [t["rhizome_id"] for t in resp.json()]
        assert rhizome_id in rhizome_ids

    async def test_unarchive_tree(self, client, db):
        """POST /unarchive restores tree to the list."""
        tree = await create_test_rhizome(client, title="Restoring")
        rhizome_id = tree["rhizome_id"]

        await client.post(f"/api/rhizomes/{rhizome_id}/archive")
        resp = await client.post(f"/api/rhizomes/{rhizome_id}/unarchive")
        assert resp.status_code == 200
        assert resp.json()["archived"] == 0

        # Should be back in the list
        list_resp = await client.get("/api/rhizomes")
        rhizome_ids = [t["rhizome_id"] for t in list_resp.json()]
        assert rhizome_id in rhizome_ids

    async def test_archive_nonexistent_404(self, client, db):
        """POST /archive on nonexistent tree returns 404."""
        resp = await client.post("/api/rhizomes/nonexistent/archive")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# RhizomeSummary enrichment tests: folders and tags from metadata
# ---------------------------------------------------------------------------


class TestRhizomeSummaryEnrichment:
    """list_trees returns folders and tags parsed from metadata."""

    async def test_empty_folders_tags_by_default(self, client, db):
        """Trees without folders/tags return empty lists."""
        await create_test_rhizome(client, title="Plain")

        resp = await client.get("/api/rhizomes")
        tree = resp.json()[0]
        assert tree["folders"] == []
        assert tree["tags"] == []

    async def test_folders_from_metadata(self, client, db):
        """Folders in metadata appear in RhizomeSummary."""
        tree = await create_test_rhizome(client, title="Organized")
        rhizome_id = tree["rhizome_id"]

        # Set folders via metadata update
        await client.patch(f"/api/rhizomes/{rhizome_id}", json={
            "metadata": {"folders": ["Research/Emotions", "Research/Claude"]}
        })

        resp = await client.get("/api/rhizomes")
        found = next(t for t in resp.json() if t["rhizome_id"] == rhizome_id)
        assert set(found["folders"]) == {"Research/Emotions", "Research/Claude"}

    async def test_tags_from_metadata(self, client, db):
        """Tags in metadata appear in RhizomeSummary."""
        tree = await create_test_rhizome(client, title="Tagged")
        rhizome_id = tree["rhizome_id"]

        await client.patch(f"/api/rhizomes/{rhizome_id}", json={
            "metadata": {"tags": ["in-progress", "interesting"]}
        })

        resp = await client.get("/api/rhizomes")
        found = next(t for t in resp.json() if t["rhizome_id"] == rhizome_id)
        assert set(found["tags"]) == {"in-progress", "interesting"}

    async def test_folders_tags_with_other_metadata(self, client, db):
        """Folders/tags coexist with other metadata fields."""
        tree = await create_test_rhizome(client, title="Full Metadata")
        rhizome_id = tree["rhizome_id"]

        await client.patch(f"/api/rhizomes/{rhizome_id}", json={
            "metadata": {
                "folders": ["Research"],
                "tags": ["wip"],
                "include_timestamps": True,
                "stream_responses": False,
            }
        })

        resp = await client.get("/api/rhizomes")
        found = next(t for t in resp.json() if t["rhizome_id"] == rhizome_id)
        assert found["folders"] == ["Research"]
        assert found["tags"] == ["wip"]

    async def test_archived_field_in_summary(self, client, db):
        """RhizomeSummary includes archived field."""
        tree = await create_test_rhizome(client, title="Archive Check")
        rhizome_id = tree["rhizome_id"]

        resp = await client.get("/api/rhizomes")
        found = next(t for t in resp.json() if t["rhizome_id"] == rhizome_id)
        assert found["archived"] == 0

        await client.post(f"/api/rhizomes/{rhizome_id}/archive")

        resp = await client.get("/api/rhizomes?include_archived=true")
        found = next(t for t in resp.json() if t["rhizome_id"] == rhizome_id)
        assert found["archived"] == 1
