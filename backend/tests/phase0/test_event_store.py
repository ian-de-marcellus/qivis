"""Contract tests for the EventStore.

test_event_roundtrip is THE CANARY — if it ever fails, something
fundamental is broken. Stop everything and investigate.
"""

import pytest

from tests.fixtures import (
    make_node_created_envelope,
    make_tree_created_envelope,
)


class TestEventStoreCanary:
    """THE CANARY TESTS. Must never break."""

    async def test_event_roundtrip(self, event_store):
        """Append a TreeCreated event, get_events returns it with correct fields."""
        event = make_tree_created_envelope(title="Canary Test")

        await event_store.append(event)
        events = await event_store.get_events(event.tree_id)

        assert len(events) == 1
        assert events[0].event_type == "TreeCreated"
        assert events[0].payload["title"] == "Canary Test"
        assert events[0].event_id == event.event_id
        assert events[0].tree_id == event.tree_id

    async def test_event_roundtrip_with_node(self, event_store):
        """Append TreeCreated + NodeCreated, both returned in order."""
        tree_event = make_tree_created_envelope()
        node_event = make_node_created_envelope(
            tree_id=tree_event.tree_id, content="Hello world",
        )

        await event_store.append(tree_event)
        await event_store.append(node_event)
        events = await event_store.get_events(tree_event.tree_id)

        assert len(events) == 2
        assert events[0].event_type == "TreeCreated"
        assert events[1].event_type == "NodeCreated"
        assert events[1].payload["content"] == "Hello world"


class TestEventStoreAppend:
    async def test_append_assigns_sequence_num(self, event_store):
        """After append, the returned sequence_num is a positive integer."""
        event = make_tree_created_envelope()
        seq = await event_store.append(event)
        assert isinstance(seq, int)
        assert seq > 0

    async def test_append_duplicate_event_id_fails(self, event_store):
        """Appending the same event_id twice raises an error."""
        event = make_tree_created_envelope()
        await event_store.append(event)
        with pytest.raises(Exception):  # IntegrityError
            await event_store.append(event)

    async def test_event_payload_preserved_as_json(self, event_store):
        """Complex nested payload (SamplingParams inside TreeCreated) round-trips."""
        from qivis.models import SamplingParams, TreeCreatedPayload

        payload = TreeCreatedPayload(
            title="Complex",
            default_sampling_params=SamplingParams(temperature=0.7, top_k=40),
            metadata={"nested": {"key": "value"}},
        )
        event = make_tree_created_envelope()
        # Override the payload with our complex one
        event = event.model_copy(update={"payload": payload.model_dump()})

        await event_store.append(event)
        events = await event_store.get_events(event.tree_id)

        assert events[0].payload["title"] == "Complex"
        assert events[0].payload["default_sampling_params"]["temperature"] == 0.7
        assert events[0].payload["metadata"]["nested"]["key"] == "value"


class TestEventStoreQueries:
    async def test_get_events_filters_by_tree_id(self, event_store):
        """Events for different trees are properly separated."""
        event_a = make_tree_created_envelope(title="Tree A")
        event_b = make_tree_created_envelope(title="Tree B")

        await event_store.append(event_a)
        await event_store.append(event_b)

        events_a = await event_store.get_events(event_a.tree_id)
        events_b = await event_store.get_events(event_b.tree_id)

        assert len(events_a) == 1
        assert events_a[0].payload["title"] == "Tree A"
        assert len(events_b) == 1
        assert events_b[0].payload["title"] == "Tree B"

    async def test_get_events_since_filters_by_sequence(self, event_store):
        """get_events_since returns only events after the given sequence_num."""
        e1 = make_tree_created_envelope(title="First")
        e2 = make_tree_created_envelope(title="Second")
        e3 = make_tree_created_envelope(title="Third")

        seq1 = await event_store.append(e1)
        await event_store.append(e2)
        await event_store.append(e3)

        # Events since seq1 should include seq2 and seq3
        events = await event_store.get_events_since(seq1)
        assert len(events) == 2
        assert events[0].payload["title"] == "Second"
        assert events[1].payload["title"] == "Third"

    async def test_events_ordered_by_sequence_num(self, event_store):
        """Events are returned in insertion order."""
        tree_id = "fixed-tree-id"
        events_in = []
        for i in range(5):
            e = make_tree_created_envelope(tree_id=tree_id, title=f"Event {i}")
            # Each needs a unique event_id but same tree_id
            events_in.append(e)

        for e in events_in:
            await event_store.append(e)

        events_out = await event_store.get_events(tree_id)
        assert len(events_out) == 5
        for i, e in enumerate(events_out):
            assert e.payload["title"] == f"Event {i}"

    async def test_get_events_empty_for_unknown_tree(self, event_store):
        """Querying a nonexistent tree returns empty list."""
        events = await event_store.get_events("nonexistent-tree-id")
        assert events == []
