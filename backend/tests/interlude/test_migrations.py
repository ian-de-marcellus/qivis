"""Tests for the migration system: version tracking, error handling, idempotency."""

import aiosqlite
import pytest

from qivis.db.connection import Database
from qivis.db.schema import INDEX_SQL, TABLES_SQL, _MIGRATIONS, run_migrations


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _raw_connect(path: str = ":memory:") -> aiosqlite.Connection:
    """Open a raw aiosqlite connection with WAL mode but NO schema/migrations."""
    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    return conn


async def _apply_base_schema(conn: aiosqlite.Connection) -> None:
    """Apply tables + indexes without running migrations."""
    await conn.executescript(TABLES_SQL)
    await conn.executescript(INDEX_SQL)
    await conn.commit()


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------

class TestMigrationsContract:
    """Promises the migration system makes."""

    async def test_migrations_table_created(self):
        """After Database.connect(), schema_migrations table exists."""
        db = await Database.connect(":memory:")
        rows = await db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        )
        assert len(rows) == 1
        await db.close()

    async def test_new_migration_applied_and_recorded(self):
        """Fresh database: all migrations are applied and recorded in schema_migrations."""
        db = await Database.connect(":memory:")
        rows = await db.fetchall("SELECT name, applied_at FROM schema_migrations ORDER BY name")
        names = [row["name"] for row in rows]
        assert len(names) == len(_MIGRATIONS)
        for (expected_name, _sql), actual_name in zip(_MIGRATIONS, names):
            assert actual_name == expected_name
        # Verify timestamps are ISO format
        for row in rows:
            assert "T" in row["applied_at"]  # ISO 8601
        await db.close()

    async def test_already_applied_migration_skipped(self):
        """A migration already in schema_migrations is not re-executed."""
        db = await Database.connect(":memory:")
        # All migrations are applied. Now add a migration that would fail if run.
        # We do this by inserting a fake record and adding a bad migration to test.
        # Instead, simply re-run migrations and verify no errors and same row count.
        count_before = len(await db.fetchall("SELECT * FROM schema_migrations"))
        await run_migrations(db)
        count_after = len(await db.fetchall("SELECT * FROM schema_migrations"))
        assert count_before == count_after
        await db.close()

    async def test_duplicate_column_handled_gracefully(self):
        """Column exists from pre-tracking era: recorded as applied without error."""
        conn = await _raw_connect()
        await _apply_base_schema(conn)
        # Base schema already has the columns (thinking_content, etc.) because
        # TABLES_SQL includes them. But schema_migrations table has no records
        # (since we didn't run migrations). Wrap in Database and run migrations.
        db = Database(conn)
        await run_migrations(db)
        rows = await db.fetchall("SELECT name FROM schema_migrations ORDER BY name")
        names = [row["name"] for row in rows]
        # All migrations should be recorded even though columns already existed
        assert len(names) == len(_MIGRATIONS)
        await db.close()

    async def test_unexpected_error_propagates(self):
        """A migration with bad SQL raises instead of being silently swallowed."""
        conn = await _raw_connect()
        await _apply_base_schema(conn)
        db = Database(conn)
        # Patch _MIGRATIONS temporarily with a bad migration
        import qivis.db.schema as schema_mod
        original = schema_mod._MIGRATIONS
        schema_mod._MIGRATIONS = [
            ("999_bad_migration", "ALTER TABLE nonexistent_table ADD COLUMN foo TEXT"),
        ]
        try:
            with pytest.raises(aiosqlite.OperationalError):
                await run_migrations(db)
        finally:
            schema_mod._MIGRATIONS = original
            await db.close()

    async def test_migration_ordering_preserved(self):
        """Migrations are applied in the order they appear in _MIGRATIONS."""
        db = await Database.connect(":memory:")
        rows = await db.fetchall(
            "SELECT name, applied_at FROM schema_migrations ORDER BY rowid"
        )
        names = [row["name"] for row in rows]
        expected = [name for name, _sql in _MIGRATIONS]
        assert names == expected
        await db.close()

    async def test_idempotent_across_multiple_connects(self):
        """Connecting twice to the same database does not re-apply or error."""
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.db")
            db1 = await Database.connect(path)
            rows1 = await db1.fetchall("SELECT name FROM schema_migrations")
            await db1.close()

            db2 = await Database.connect(path)
            rows2 = await db2.fetchall("SELECT name FROM schema_migrations")
            await db2.close()

            assert len(rows1) == len(rows2) == len(_MIGRATIONS)


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------

class TestMigrationTransition:
    """Transition from pre-tracking databases."""

    async def test_existing_database_transition(self):
        """Database with columns but no tracking table transitions cleanly.

        Simulates a database created with the old system: columns exist from
        bare ALTER TABLE statements, but no schema_migrations table.
        """
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "legacy.db")

            # Create a "legacy" database: schema + columns but no tracking table
            conn = await _raw_connect(path)
            await _apply_base_schema(conn)
            # Drop the schema_migrations table to simulate pre-tracking era
            await conn.execute("DROP TABLE IF EXISTS schema_migrations")
            await conn.commit()
            await conn.close()

            # Now connect with the new system
            db = await Database.connect(path)

            # schema_migrations should exist and have all migrations recorded
            rows = await db.fetchall("SELECT name FROM schema_migrations ORDER BY name")
            names = [row["name"] for row in rows]
            assert len(names) == len(_MIGRATIONS)

            # Columns should still be there (not duplicated)
            cursor = await db.fetchall("PRAGMA table_info(nodes)")
            col_names = [row["name"] for row in cursor]
            assert "thinking_content" in col_names
            assert "edited_content" in col_names

            await db.close()

    async def test_pre_rename_database_migrates(self):
        """Database with old 'trees' table and 'tree_id' columns migrates on connect.

        Simulates an existing database from before the tree→rhizome rename:
        tables use old names (trees, tree_id). Database.connect() should run
        018 rename migrations before TABLES_SQL, avoiding conflicts.
        """
        import tempfile
        import os

        # Old schema with tree_id columns (pre-rename)
        OLD_SCHEMA = """
        CREATE TABLE IF NOT EXISTS events (
            sequence_num INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE NOT NULL,
            tree_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            device_id TEXT NOT NULL DEFAULT 'local',
            user_id TEXT,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS trees (
            tree_id TEXT PRIMARY KEY,
            title TEXT,
            metadata TEXT NOT NULL DEFAULT '{}',
            default_model TEXT,
            default_provider TEXT,
            default_system_prompt TEXT,
            default_sampling_params TEXT,
            conversation_mode TEXT NOT NULL DEFAULT 'single',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            archived INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS nodes (
            node_id TEXT PRIMARY KEY,
            tree_id TEXT NOT NULL,
            parent_id TEXT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            model TEXT,
            provider TEXT,
            system_prompt TEXT,
            sampling_params TEXT,
            mode TEXT DEFAULT 'chat',
            usage TEXT,
            latency_ms INTEGER,
            finish_reason TEXT,
            logprobs TEXT,
            context_usage TEXT,
            participant_id TEXT,
            participant_name TEXT,
            thinking_content TEXT,
            edited_content TEXT,
            include_thinking_in_context INTEGER NOT NULL DEFAULT 0,
            include_timestamps INTEGER NOT NULL DEFAULT 0,
            prefill_content TEXT,
            prompt_text TEXT,
            created_at TEXT NOT NULL,
            archived INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (tree_id) REFERENCES trees(tree_id)
        );
        CREATE TABLE IF NOT EXISTS annotations (
            annotation_id TEXT PRIMARY KEY,
            tree_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            tag TEXT NOT NULL,
            value TEXT,
            notes TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bookmarks (
            bookmark_id TEXT PRIMARY KEY,
            tree_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            label TEXT NOT NULL,
            notes TEXT,
            summary TEXT,
            summary_model TEXT,
            summarized_node_ids TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS node_exclusions (
            tree_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            scope_node_id TEXT NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (tree_id, node_id, scope_node_id)
        );
        CREATE TABLE IF NOT EXISTS digression_groups (
            group_id TEXT PRIMARY KEY,
            tree_id TEXT NOT NULL,
            label TEXT NOT NULL,
            included INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS digression_group_nodes (
            group_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (group_id, node_id)
        );
        CREATE TABLE IF NOT EXISTS node_anchors (
            tree_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (tree_id, node_id)
        );
        CREATE TABLE IF NOT EXISTS notes (
            note_id TEXT PRIMARY KEY,
            tree_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS summaries (
            summary_id TEXT PRIMARY KEY,
            tree_id TEXT NOT NULL,
            anchor_node_id TEXT NOT NULL,
            scope TEXT NOT NULL,
            summary_type TEXT NOT NULL,
            summary TEXT NOT NULL,
            model TEXT NOT NULL,
            node_ids TEXT NOT NULL,
            prompt_used TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS schema_migrations (
            name TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        );
        """

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "old.db")

            # Create a database with old table/column names and pre-018 migrations applied
            conn = await _raw_connect(path)
            await conn.executescript(OLD_SCHEMA)
            await conn.commit()
            # Record pre-018 migrations as already applied
            for name, _sql in _MIGRATIONS:
                if name.startswith("018"):
                    break
                await conn.execute(
                    "INSERT INTO schema_migrations (name, applied_at) VALUES (?, '2025-01-01T00:00:00')",
                    (name,),
                )
            await conn.commit()
            # Insert a test row to verify data survives the rename
            await conn.execute(
                "INSERT INTO trees (tree_id, title, created_at, updated_at) "
                "VALUES ('test-id', 'Test Tree', '2025-01-01', '2025-01-01')"
            )
            await conn.commit()
            await conn.close()

            # Connect with the new system — this must not crash
            db = await Database.connect(path)

            # 'rhizomes' table should exist with renamed columns
            tables = await db.fetchall(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='rhizomes'"
            )
            assert len(tables) == 1

            # Old 'trees' table should be gone
            old_tables = await db.fetchall(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='trees'"
            )
            assert len(old_tables) == 0

            # Data survived the rename
            row = await db.fetchone("SELECT title FROM rhizomes WHERE rhizome_id = 'test-id'")
            assert row is not None
            assert row["title"] == "Test Tree"

            # All migrations recorded
            rows = await db.fetchall("SELECT name FROM schema_migrations ORDER BY name")
            assert len(rows) == len(_MIGRATIONS)

            await db.close()
