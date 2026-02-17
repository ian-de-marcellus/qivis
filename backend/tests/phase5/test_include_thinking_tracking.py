"""Tests for per-node tracking of include_thinking_in_context and include_timestamps."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from qivis.models import EventEnvelope, NodeCreatedPayload, TreeCreatedPayload


# ---- Contract tests ----


def test_node_created_payload_accepts_context_flags():
    """NodeCreatedPayload should accept include_thinking_in_context and include_timestamps."""
    payload = NodeCreatedPayload(
        node_id="n1",
        parent_id=None,
        role="assistant",
        content="hello",
        include_thinking_in_context=True,
        include_timestamps=True,
    )
    assert payload.include_thinking_in_context is True
    assert payload.include_timestamps is True


def test_node_created_payload_context_flags_default_false():
    """Both context flags should default to False."""
    payload = NodeCreatedPayload(
        node_id="n1",
        parent_id=None,
        role="assistant",
        content="hello",
    )
    assert payload.include_thinking_in_context is False
    assert payload.include_timestamps is False


def test_node_created_payload_serializes_context_flags():
    """Context flags should appear in serialized payload."""
    payload = NodeCreatedPayload(
        node_id="n1",
        parent_id=None,
        role="assistant",
        content="hello",
        include_thinking_in_context=True,
        include_timestamps=False,
    )
    dumped = payload.model_dump()
    assert dumped["include_thinking_in_context"] is True
    assert dumped["include_timestamps"] is False


# ---- Projection tests ----


def _make_envelope(tree_id: str, payload: NodeCreatedPayload) -> EventEnvelope:
    """Wrap a NodeCreatedPayload in an EventEnvelope for testing."""
    return EventEnvelope(
        event_id=f"evt-{payload.node_id}",
        tree_id=tree_id,
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="NodeCreated",
        payload=payload.model_dump(),
    )


@pytest.mark.anyio
async def test_context_flags_projected_from_event():
    """Context flags should be projected to the nodes table."""
    from qivis.db.connection import Database
    from qivis.events.projector import StateProjector
    from qivis.events.store import EventStore

    db = await Database.connect(":memory:")
    store = EventStore(db)
    projector = StateProjector(db)

    # Create a tree
    tree_event = EventEnvelope(
        event_id="e0",
        tree_id="t1",
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="TreeCreated",
        payload=TreeCreatedPayload(title="test").model_dump(),
    )
    await store.append(tree_event)
    await projector.project([tree_event])

    # Create a node with both flags set
    payload = NodeCreatedPayload(
        node_id="n1",
        parent_id=None,
        role="assistant",
        content="hello",
        include_thinking_in_context=True,
        include_timestamps=True,
    )
    event = _make_envelope("t1", payload)
    await store.append(event)
    await projector.project([event])

    rows = await projector.get_nodes("t1")
    assert len(rows) == 1
    assert rows[0]["include_thinking_in_context"] == 1
    assert rows[0]["include_timestamps"] == 1


@pytest.mark.anyio
async def test_context_flags_default_in_projection():
    """Context flags should default to 0 in projection when not set."""
    from qivis.db.connection import Database
    from qivis.events.projector import StateProjector
    from qivis.events.store import EventStore

    db = await Database.connect(":memory:")
    store = EventStore(db)
    projector = StateProjector(db)

    tree_event = EventEnvelope(
        event_id="e0",
        tree_id="t1",
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="TreeCreated",
        payload=TreeCreatedPayload(title="test").model_dump(),
    )
    await store.append(tree_event)
    await projector.project([tree_event])

    payload = NodeCreatedPayload(
        node_id="n1",
        parent_id=None,
        role="user",
        content="hello",
    )
    event = _make_envelope("t1", payload)
    await store.append(event)
    await projector.project([event])

    rows = await projector.get_nodes("t1")
    assert len(rows) == 1
    assert rows[0]["include_thinking_in_context"] == 0
    assert rows[0]["include_timestamps"] == 0


# ---- API tests ----


@pytest.mark.anyio
async def test_node_response_includes_context_flags(client: AsyncClient):
    """NodeResponse should include both context flags."""
    r = await client.post("/api/trees", json={"title": "test"})
    tree_id = r.json()["tree_id"]

    r = await client.post(
        f"/api/trees/{tree_id}/nodes",
        json={"content": "hello", "role": "user"},
    )
    node = r.json()
    assert "include_thinking_in_context" in node
    assert "include_timestamps" in node
    assert node["include_thinking_in_context"] is False
    assert node["include_timestamps"] is False
