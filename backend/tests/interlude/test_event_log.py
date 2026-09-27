"""The event log and its projections never disagree.

EventLog appends and projects inside one transaction; the database's write
lock keeps another request's commit from landing in the middle of it.
"""

import asyncio

import pytest

from qivis.db.connection import Database
from qivis.events.log import EventLog
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.models import NodeCreatedPayload, RhizomeCreatedPayload


class BrokenProjector(StateProjector):
    async def project(self, events):
        await super().project(events)
        raise RuntimeError("projection failed halfway")


async def _count(db: Database, table: str) -> int:
    row = await db.fetchone(f"SELECT COUNT(*) AS n FROM {table}")
    return row["n"]


async def test_emit_appends_and_projects(db: Database):
    log = EventLog(EventStore(db), StateProjector(db))
    await log.emit("r1", "RhizomeCreated", RhizomeCreatedPayload(title="t"))
    assert await _count(db, "events") == 1
    assert await _count(db, "rhizomes") == 1


async def test_failed_projection_leaves_no_event_behind(db: Database):
    log = EventLog(EventStore(db), BrokenProjector(db))
    with pytest.raises(RuntimeError, match="halfway"):
        await log.emit("r1", "RhizomeCreated", RhizomeCreatedPayload(title="t"))
    assert await _count(db, "events") == 0
    assert await _count(db, "rhizomes") == 0


async def test_record_is_all_or_nothing(db: Database):
    log = EventLog(EventStore(db), StateProjector(db))
    good = log.envelope("r1", "RhizomeCreated", RhizomeCreatedPayload(title="t"))
    duplicate = good.model_copy()  # same event_id: the second append violates uniqueness
    with pytest.raises(Exception):
        await log.record([good, duplicate])
    assert await _count(db, "events") == 0


async def test_other_writers_wait_for_the_transaction(db: Database):
    log = EventLog(EventStore(db), StateProjector(db))
    await log.emit("r1", "RhizomeCreated", RhizomeCreatedPayload(title="t"))
    order: list[str] = []

    async def slow_transaction():
        async with db.transaction():
            await db.execute("UPDATE rhizomes SET title = 'inside' WHERE rhizome_id = 'r1'")
            order.append("tx wrote")
            await asyncio.sleep(0.01)  # another writer gets its chance to interleave here
            order.append("tx done")

    async def other_writer():
        await asyncio.sleep(0)
        await log.emit("r1", "NodeCreated", NodeCreatedPayload(
            node_id="n1", parent_id=None, role="user", content="hi"))
        order.append("other wrote")

    await asyncio.gather(slow_transaction(), other_writer())
    assert order == ["tx wrote", "tx done", "other wrote"]
