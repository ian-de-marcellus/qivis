"""Integration tests for database connection and schema.

Verifies SQLite setup (WAL mode, foreign keys, table creation) and the
full event store → projector roundtrip.
"""

import os
import tempfile

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from tests.fixtures import make_node_created_envelope, make_tree_created_envelope


class TestDatabaseConnection:
    async def test_connect_creates_tables(self):
        """Database.connect creates events, trees, and nodes tables."""
        db = await Database.connect(":memory:")
        try:
            rows = await db.fetchall(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            table_names = {row["name"] for row in rows}
            assert "events" in table_names
            assert "trees" in table_names
            assert "nodes" in table_names
        finally:
            await db.close()

    async def test_wal_mode_on_file_database(self):
        """File-based database uses WAL journal mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.db")
            db = await Database.connect(path)
            try:
                row = await db.fetchone("PRAGMA journal_mode")
                assert row is not None
                assert row["journal_mode"] == "wal"
            finally:
                await db.close()

    async def test_foreign_keys_enabled(self):
        """Foreign keys are enforced."""
        db = await Database.connect(":memory:")
        try:
            row = await db.fetchone("PRAGMA foreign_keys")
            assert row is not None
            assert row["foreign_keys"] == 1
        finally:
            await db.close()

    async def test_schema_idempotent(self):
        """Calling _ensure_schema twice does not error."""
        db = await Database.connect(":memory:")
        try:
            await db._ensure_schema()  # second call
            # If we get here without error, it's idempotent
            rows = await db.fetchall(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            assert len(rows) >= 3
        finally:
            await db.close()


class TestFullRoundtrip:
    async def test_store_to_projector_roundtrip(self):
        """Full chain: append events via store, project, query via projector."""
        db = await Database.connect(":memory:")
        try:
            store = EventStore(db)
            projector = StateProjector(db)

            tree_event = make_tree_created_envelope(title="Roundtrip Test")
            node_event = make_node_created_envelope(
                tree_id=tree_event.tree_id, content="Hello from integration test",
            )

            await store.append(tree_event)
            await store.append(node_event)

            # Read back from store
            events = await store.get_events(tree_event.tree_id)
            assert len(events) == 2

            # Project into materialized tables
            await projector.project(events)

            # Query projected state
            tree = await projector.get_tree(tree_event.tree_id)
            assert tree is not None
            assert tree["title"] == "Roundtrip Test"

            nodes = await projector.get_nodes(tree_event.tree_id)
            assert len(nodes) == 1
            assert nodes[0]["content"] == "Hello from integration test"
        finally:
            await db.close()
