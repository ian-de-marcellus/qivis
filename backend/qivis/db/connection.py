"""Async SQLite connection wrapper with WAL mode and schema initialization."""

import aiosqlite

from qivis.db.schema import SCHEMA_SQL


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
        """Create tables if they don't exist. Idempotent."""
        await self._conn.executescript(SCHEMA_SQL)
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
