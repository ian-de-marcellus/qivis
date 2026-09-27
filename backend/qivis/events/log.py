"""Writing to the event log: append an event and project it, together."""

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel

from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.models import EventEnvelope


class EventLog:
    """The one way services record something.

    The append and its projection commit together, so the log never holds an
    event the read tables haven't seen (or the reverse).
    """

    def __init__(self, store: EventStore, projector: StateProjector) -> None:
        self.store = store
        self.projector = projector

    async def emit(
        self,
        rhizome_id: str,
        event_type: str,
        payload: BaseModel | dict,
        *,
        timestamp: datetime | None = None,
        device_id: str = "local",
    ) -> EventEnvelope:
        event = self.envelope(
            rhizome_id, event_type, payload, timestamp=timestamp, device_id=device_id,
        )
        await self.record([event])
        return event

    async def record(self, events: list[EventEnvelope]) -> None:
        """Append and project several events as one unit."""
        async with self.store.db.transaction():
            for event in events:
                await self.store.append(event)
            await self.projector.project(events)

    @staticmethod
    def envelope(
        rhizome_id: str,
        event_type: str,
        payload: BaseModel | dict,
        *,
        timestamp: datetime | None = None,
        device_id: str = "local",
    ) -> EventEnvelope:
        return EventEnvelope(
            event_id=str(uuid4()),
            rhizome_id=rhizome_id,
            timestamp=timestamp or datetime.now(UTC),
            device_id=device_id,
            event_type=event_type,
            payload=payload.model_dump() if isinstance(payload, BaseModel) else payload,
        )
