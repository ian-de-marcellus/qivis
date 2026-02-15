"""Contract tests for the StateProjector.

test_projection_roundtrip_tree is THE OTHER CANARY — events in,
projected state out. Must never break.
"""

from datetime import UTC

from tests.fixtures import (
    make_full_node_created_envelope,
    make_node_created_envelope,
    make_tree_created_envelope,
)


class TestProjectorCanary:
    """THE OTHER CANARY TESTS. Must never break."""

    async def test_projection_roundtrip_tree(self, event_store, projector):
        """Append TreeCreated, project, get_tree returns tree with matching fields."""
        event = make_tree_created_envelope(title="Canary Tree")

        await event_store.append(event)
        await projector.project([event])

        tree = await projector.get_tree(event.tree_id)
        assert tree is not None
        assert tree["title"] == "Canary Tree"
        assert tree["tree_id"] == event.tree_id

    async def test_projection_roundtrip_node(self, event_store, projector):
        """Append TreeCreated + NodeCreated, project, get_nodes returns the node."""
        tree_event = make_tree_created_envelope()
        node_event = make_node_created_envelope(
            tree_id=tree_event.tree_id, content="Hello!",
        )

        await event_store.append(tree_event)
        await event_store.append(node_event)
        await projector.project([tree_event, node_event])

        nodes = await projector.get_nodes(tree_event.tree_id)
        assert len(nodes) == 1
        assert nodes[0]["content"] == "Hello!"


class TestProjectorTreeFields:
    async def test_tree_fields_match_payload(self, event_store, projector):
        """TreeCreated with all fields -> projected tree has all matching fields."""
        from qivis.models import SamplingParams

        event = make_tree_created_envelope(
            title="Full Tree",
            default_model="claude-sonnet-4-5-20250929",
            default_provider="anthropic",
            default_system_prompt="Be helpful.",
            default_sampling_params=SamplingParams(temperature=0.5),
            metadata={"tag": "test"},
            conversation_mode="single",
        )

        await event_store.append(event)
        await projector.project([event])

        tree = await projector.get_tree(event.tree_id)
        assert tree["title"] == "Full Tree"
        assert tree["default_model"] == "claude-sonnet-4-5-20250929"
        assert tree["default_provider"] == "anthropic"
        assert tree["default_system_prompt"] == "Be helpful."
        assert tree["conversation_mode"] == "single"
        assert tree["archived"] == 0

    async def test_tree_not_found_returns_none(self, projector):
        """get_tree with nonexistent ID returns None."""
        tree = await projector.get_tree("nonexistent-id")
        assert tree is None


class TestProjectorNodeFields:
    async def test_node_fields_match_payload(self, event_store, projector):
        """NodeCreated with all generation fields -> projected node matches."""
        tree_event = make_tree_created_envelope()
        node_event = make_full_node_created_envelope(tree_id=tree_event.tree_id)

        await event_store.append(tree_event)
        await event_store.append(node_event)
        await projector.project([tree_event, node_event])

        nodes = await projector.get_nodes(tree_event.tree_id)
        assert len(nodes) == 1
        node = nodes[0]

        assert node["role"] == "assistant"
        assert node["content"] == "Hello! How can I help you?"
        assert node["model"] == "claude-sonnet-4-5-20250929"
        assert node["provider"] == "anthropic"
        assert node["latency_ms"] == 450
        assert node["finish_reason"] == "end_turn"

    async def test_nodes_empty_for_new_tree(self, event_store, projector):
        """After only TreeCreated, get_nodes returns empty list."""
        event = make_tree_created_envelope()
        await event_store.append(event)
        await projector.project([event])

        nodes = await projector.get_nodes(event.tree_id)
        assert nodes == []

    async def test_multiple_nodes_projected(self, event_store, projector):
        """Three NodeCreated events produce three projected nodes."""
        tree_event = make_tree_created_envelope()
        node_events = [
            make_node_created_envelope(
                tree_id=tree_event.tree_id, content=f"Message {i}",
            )
            for i in range(3)
        ]

        all_events = [tree_event] + node_events
        for e in all_events:
            await event_store.append(e)
        await projector.project(all_events)

        nodes = await projector.get_nodes(tree_event.tree_id)
        assert len(nodes) == 3


class TestProjectorEdgeCases:
    async def test_unknown_event_type_does_not_crash(self, event_store, projector):
        """An unknown event_type is silently skipped by the projector."""
        from datetime import datetime

        from qivis.models import EventEnvelope

        event = EventEnvelope(
            event_id="unknown-1", tree_id="t1",
            timestamp=datetime.now(UTC),
            device_id="test", event_type="FutureEventType",
            payload={"some": "data"},
        )
        # Should not raise
        await projector.project([event])

    async def test_projection_idempotent(self, event_store, projector):
        """Projecting the same events twice does not create duplicate rows."""
        tree_event = make_tree_created_envelope()
        node_event = make_node_created_envelope(
            tree_id=tree_event.tree_id, content="Hello",
        )

        all_events = [tree_event, node_event]
        for e in all_events:
            await event_store.append(e)

        # Project twice
        await projector.project(all_events)
        await projector.project(all_events)

        tree = await projector.get_tree(tree_event.tree_id)
        assert tree is not None

        nodes = await projector.get_nodes(tree_event.tree_id)
        assert len(nodes) == 1  # not 2
