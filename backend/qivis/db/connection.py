"""Async SQLite connection wrapper with WAL mode and schema initialization."""

import aiosqlite

from qivis.db.schema import INDEX_SQL, TABLES_SQL, run_migrations


class Database:
    """Thin async wrapper around aiosqlite with WAL mode and auto-schema."""

    def __init__(self, connection: aiosqlite.Connection) -> None:
        self._conn = connection

    @classmethod
    async def connect(cls, path: str = "qivis.db") -> Database:
        """Create a connection with WAL mode, foreign keys, and schema init."""
        conn = await aiosqlite.connect(path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.execute("PRAGMA busy_timeout=5000")
        db = cls(conn)
        await db._ensure_schema()
        return db

    async def _ensure_schema(self) -> None:
        """Create tables if they don't exist. Idempotent.

        Handles three database states:
        1. Fresh DB: TABLES_SQL creates everything, migrations no-op, INDEX_SQL
        2. Existing DB (pre-rename): migrations rename tree→rhizome first,
           then TABLES_SQL no-ops (tables already exist), then INDEX_SQL
        3. Existing DB (post-rename): everything no-ops

        Migrations must run before TABLES_SQL on pre-rename DBs, otherwise
        TABLES_SQL creates an empty 'rhizomes' table that blocks the rename.
        """
        # Check if this is a pre-rename database (old 'trees' table exists)
        cursor = await self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='trees'"
        )
        if await cursor.fetchone():
            # Old DB: run migrations first to rename tables/columns.
            # If a previous failed startup already created an empty 'rhizomes'
            # table via TABLES_SQL, drop it so the rename migration can proceed.
            await self._conn.execute("DROP TABLE IF EXISTS rhizomes")
            await self._conn.commit()
            await run_migrations(self)

        await self._conn.executescript(TABLES_SQL)
        await self._conn.commit()
        await run_migrations(self)  # idempotent — skips already-applied
        await self._conn.executescript(INDEX_SQL)
        await self._conn.commit()

    async def execute(self, sql: str, params: tuple | None = None) -> aiosqlite.Cursor:
        """Execute a single SQL statement."""
        cursor = await self._conn.execute(sql, params or ())
        await self._conn.commit()
        return cursor

    async def fetchone(self, sql: str, params: tuple | None = None) -> aiosqlite.Row | None:
        """Execute and return a single row."""
        cursor = await self._conn.execute(sql, params or ())
        return await cursor.fetchone()

    async def fetchall(self, sql: str, params: tuple | None = None) -> list[aiosqlite.Row]:
        """Execute and return all rows."""
        cursor = await self._conn.execute(sql, params or ())
        return list(await cursor.fetchall())

    async def close(self) -> None:
        """Close the database connection."""
        await self._conn.close()
