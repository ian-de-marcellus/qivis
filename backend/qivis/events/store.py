"""Append-only event store backed by SQLite."""

import json

from qivis.db.connection import Database
from qivis.models import EventEnvelope


class EventStore:
    """Append-only event store. The write side of the CQRS pattern."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def append(self, envelope: EventEnvelope) -> int:
        """Append an event and return the assigned sequence_num.

        Raises IntegrityError if event_id is not unique.
        """
        cursor = await self._db.execute(
            """
            INSERT INTO events
                (event_id, tree_id, timestamp, device_id, user_id, event_type, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                envelope.event_id,
                envelope.tree_id,
                envelope.timestamp.isoformat(),
                envelope.device_id,
                envelope.user_id,
                envelope.event_type,
                json.dumps(envelope.payload),
            ),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    async def get_events(self, tree_id: str) -> list[EventEnvelope]:
        """Get all events for a tree, ordered by sequence_num."""
        rows = await self._db.fetchall(
            "SELECT * FROM events WHERE tree_id = ? ORDER BY sequence_num",
            (tree_id,),
        )
        return [self._row_to_envelope(row) for row in rows]

    async def get_events_since(self, sequence_num: int) -> list[EventEnvelope]:
        """Get all events across all trees after the given sequence_num."""
        rows = await self._db.fetchall(
            "SELECT * FROM events WHERE sequence_num > ? ORDER BY sequence_num",
            (sequence_num,),
        )
        return [self._row_to_envelope(row) for row in rows]

    @staticmethod
    def _row_to_envelope(row) -> EventEnvelope:
        """Convert a database row to an EventEnvelope."""
        return EventEnvelope(
            event_id=row["event_id"],
            tree_id=row["tree_id"],
            timestamp=row["timestamp"],
            device_id=row["device_id"],
            user_id=row["user_id"],
            event_type=row["event_type"],
            payload=json.loads(row["payload"]),
            sequence_num=row["sequence_num"],
        )
