"""Tests for research notes on nodes.

Three sections:
1. Contract tests — projector handles NoteAdded/Removed events correctly
2. API integration tests — CRUD endpoints, note_count, tree-wide queries
3. Event sourcing integrity — notes survive replay
"""

import pytest

from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from tests.fixtures import (
    create_test_tree,
    create_tree_with_messages,
    make_annotation_added_envelope,
    make_node_created_envelope,
    make_note_added_envelope,
    make_note_removed_envelope,
    make_tree_created_envelope,
)


# ---------------------------------------------------------------------------
# Contract tests: event -> store -> projector -> verify state
# ---------------------------------------------------------------------------


class TestNoteProjection:
    """NoteAdded/Removed events project into the notes table."""

    async def test_note_added_projects(self, event_store, projector, db):
        """NoteAdded inserts a row into the notes table."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(tree_id=tree_ev.tree_id, content="Hello")

        for e in [tree_ev, node_ev]:
            await event_store.append(e)
        await projector.project([tree_ev, node_ev])

        note_ev = make_note_added_envelope(
            tree_id=tree_ev.tree_id,
            node_id=node_ev.payload["node_id"],
            content="This is where the model starts hedging.",
        )
        await event_store.append(note_ev)
        await projector.project([note_ev])

        row = await db.fetchone(
            "SELECT * FROM notes WHERE note_id = ?",
            (note_ev.payload["note_id"],),
        )
        assert row is not None
        assert row["content"] == "This is where the model starts hedging."
        assert row["node_id"] == node_ev.payload["node_id"]
        assert row["tree_id"] == tree_ev.tree_id

    async def test_note_removed_deletes_row(self, event_store, projector, db):
        """NoteRemoved deletes the note from the table."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(tree_id=tree_ev.tree_id, content="Hello")

        for e in [tree_ev, node_ev]:
            await event_store.append(e)
        await projector.project([tree_ev, node_ev])

        note_ev = make_note_added_envelope(
            tree_id=tree_ev.tree_id,
            node_id=node_ev.payload["node_id"],
        )
        await event_store.append(note_ev)
        await projector.project([note_ev])

        remove_ev = make_note_removed_envelope(
            tree_id=tree_ev.tree_id,
            note_id=note_ev.payload["note_id"],
        )
        await event_store.append(remove_ev)
        await projector.project([remove_ev])

        row = await db.fetchone(
            "SELECT * FROM notes WHERE note_id = ?",
            (note_ev.payload["note_id"],),
        )
        assert row is None

    async def test_note_content_persists(self, event_store, projector, db):
        """Note content roundtrips through projection."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(tree_id=tree_ev.tree_id, content="Hello")

        for e in [tree_ev, node_ev]:
            await event_store.append(e)
        await projector.project([tree_ev, node_ev])

        long_content = "Compare this with the response on the other branch. " * 10
        note_ev = make_note_added_envelope(
            tree_id=tree_ev.tree_id,
            node_id=node_ev.payload["node_id"],
            content=long_content,
        )
        await event_store.append(note_ev)
        await projector.project([note_ev])

        row = await db.fetchone(
            "SELECT content FROM notes WHERE note_id = ?",
            (note_ev.payload["note_id"],),
        )
        assert row["content"] == long_content


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------


class TestNoteCRUD:
    """Note CRUD endpoints."""

    async def test_add_note(self, client):
        """POST creates a note and returns NoteResponse."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        resp = await client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/notes",
            json={"content": "Interesting hedging behavior here."},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["node_id"] == node_id
        assert body["tree_id"] == tree_id
        assert body["content"] == "Interesting hedging behavior here."
        assert "note_id" in body
        assert "created_at" in body

    async def test_add_multiple_notes_same_node(self, client):
        """Multiple notes can be added to the same node."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        for i in range(3):
            resp = await client.post(
                f"/api/trees/{tree_id}/nodes/{node_id}/notes",
                json={"content": f"Note {i + 1}"},
            )
            assert resp.status_code == 201

        resp = await client.get(f"/api/trees/{tree_id}/nodes/{node_id}/notes")
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    async def test_get_node_notes(self, client):
        """GET returns all notes for a specific node."""
        data = await create_tree_with_messages(client, n_messages=4)
        tree_id = data["tree_id"]
        node_a = data["node_ids"][0]
        node_b = data["node_ids"][1]

        await client.post(f"/api/trees/{tree_id}/nodes/{node_a}/notes",
                          json={"content": "Note on A"})
        await client.post(f"/api/trees/{tree_id}/nodes/{node_b}/notes",
                          json={"content": "Note on B"})

        resp = await client.get(f"/api/trees/{tree_id}/nodes/{node_a}/notes")
        assert resp.status_code == 200
        notes = resp.json()
        assert len(notes) == 1
        assert notes[0]["content"] == "Note on A"

    async def test_get_tree_notes(self, client):
        """GET tree-level endpoint returns notes across all nodes."""
        data = await create_tree_with_messages(client, n_messages=4)
        tree_id = data["tree_id"]

        await client.post(f"/api/trees/{tree_id}/nodes/{data['node_ids'][0]}/notes",
                          json={"content": "First note"})
        await client.post(f"/api/trees/{tree_id}/nodes/{data['node_ids'][1]}/notes",
                          json={"content": "Second note"})

        resp = await client.get(f"/api/trees/{tree_id}/notes")
        assert resp.status_code == 200
        notes = resp.json()
        assert len(notes) == 2

    async def test_get_tree_notes_search(self, client):
        """Tree notes endpoint filters by content with ?q= parameter."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        await client.post(f"/api/trees/{tree_id}/nodes/{node_id}/notes",
                          json={"content": "The model is hedging here."})
        await client.post(f"/api/trees/{tree_id}/nodes/{node_id}/notes",
                          json={"content": "Interesting personality shift."})

        resp = await client.get(f"/api/trees/{tree_id}/notes?q=hedging")
        assert resp.status_code == 200
        notes = resp.json()
        assert len(notes) == 1
        assert "hedging" in notes[0]["content"]

    async def test_remove_note(self, client):
        """DELETE removes a note."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        resp = await client.post(f"/api/trees/{tree_id}/nodes/{node_id}/notes",
                                 json={"content": "Temporary note"})
        note_id = resp.json()["note_id"]

        del_resp = await client.delete(f"/api/trees/{tree_id}/notes/{note_id}")
        assert del_resp.status_code == 204

        get_resp = await client.get(f"/api/trees/{tree_id}/nodes/{node_id}/notes")
        assert len(get_resp.json()) == 0

    async def test_remove_nonexistent_404(self, client):
        """DELETE on nonexistent note returns 404."""
        data = await create_tree_with_messages(client, n_messages=2)
        resp = await client.delete(f"/api/trees/{data['tree_id']}/notes/fake-id")
        assert resp.status_code == 404

    async def test_add_note_bad_tree_404(self, client):
        """POST to nonexistent tree returns 404."""
        resp = await client.post(
            "/api/trees/nonexistent/nodes/also-fake/notes",
            json={"content": "hello"},
        )
        assert resp.status_code == 404

    async def test_add_note_bad_node_404(self, client):
        """POST to nonexistent node returns 404."""
        data = await create_tree_with_messages(client, n_messages=2)
        resp = await client.post(
            f"/api/trees/{data['tree_id']}/nodes/nonexistent/notes",
            json={"content": "hello"},
        )
        assert resp.status_code == 404


class TestNoteCount:
    """note_count on NodeResponse."""

    async def test_note_count_reflects_notes(self, client):
        """note_count matches actual number of notes."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        for _ in range(3):
            await client.post(f"/api/trees/{tree_id}/nodes/{node_id}/notes",
                              json={"content": "A note"})

        resp = await client.get(f"/api/trees/{tree_id}")
        tree = resp.json()
        node = next(n for n in tree["nodes"] if n["node_id"] == node_id)
        assert node["note_count"] == 3

    async def test_note_count_zero_default(self, client):
        """Nodes with no notes have note_count = 0."""
        data = await create_tree_with_messages(client, n_messages=2)
        resp = await client.get(f"/api/trees/{data['tree_id']}")
        for node in resp.json()["nodes"]:
            assert node["note_count"] == 0

    async def test_note_count_decrements_on_removal(self, client):
        """note_count decreases after a note is removed."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        resp1 = await client.post(f"/api/trees/{tree_id}/nodes/{node_id}/notes",
                                  json={"content": "Note 1"})
        note_id = resp1.json()["note_id"]
        await client.post(f"/api/trees/{tree_id}/nodes/{node_id}/notes",
                          json={"content": "Note 2"})

        await client.delete(f"/api/trees/{tree_id}/notes/{note_id}")

        resp = await client.get(f"/api/trees/{tree_id}")
        node = next(n for n in resp.json()["nodes"] if n["node_id"] == node_id)
        assert node["note_count"] == 1


class TestTreeAnnotations:
    """Tree-wide annotation endpoint."""

    async def test_get_tree_annotations_returns_all(self, client):
        """GET /api/trees/{id}/annotations returns all annotations in the tree."""
        data = await create_tree_with_messages(client, n_messages=4)
        tree_id = data["tree_id"]

        await client.post(f"/api/trees/{tree_id}/nodes/{data['node_ids'][0]}/annotations",
                          json={"tag": "interesting"})
        await client.post(f"/api/trees/{tree_id}/nodes/{data['node_ids'][1]}/annotations",
                          json={"tag": "hallucination"})

        resp = await client.get(f"/api/trees/{tree_id}/annotations")
        assert resp.status_code == 200
        anns = resp.json()
        assert len(anns) == 2
        tags = {a["tag"] for a in anns}
        assert tags == {"interesting", "hallucination"}

    async def test_get_tree_annotations_empty(self, client):
        """Tree with no annotations returns empty list."""
        data = await create_tree_with_messages(client, n_messages=2)
        resp = await client.get(f"/api/trees/{data['tree_id']}/annotations")
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# Event sourcing integrity
# ---------------------------------------------------------------------------


class TestNoteEventReplay:
    """Notes survive full event replay."""

    async def test_notes_survive_replay(self, event_store, projector, db):
        """Wipe projections, replay all events, notes are reconstructed."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(tree_id=tree_ev.tree_id, content="Hello")
        note_ev = make_note_added_envelope(
            tree_id=tree_ev.tree_id,
            node_id=node_ev.payload["node_id"],
            content="Researcher observation",
        )

        for e in [tree_ev, node_ev, note_ev]:
            await event_store.append(e)
        await projector.project([tree_ev, node_ev, note_ev])

        # Verify note exists
        row = await db.fetchone("SELECT * FROM notes WHERE note_id = ?",
                                (note_ev.payload["note_id"],))
        assert row is not None

        # Wipe notes table
        await db.execute("DELETE FROM notes")
        row = await db.fetchone("SELECT * FROM notes WHERE note_id = ?",
                                (note_ev.payload["note_id"],))
        assert row is None

        # Replay all events
        events = await event_store.get_events(tree_ev.tree_id)
        await projector.project(events)

        # Note is back
        row = await db.fetchone("SELECT * FROM notes WHERE note_id = ?",
                                (note_ev.payload["note_id"],))
        assert row is not None
        assert row["content"] == "Researcher observation"
