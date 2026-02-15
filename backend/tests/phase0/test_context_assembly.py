"""Contract tests for ContextBuilder path-walking (originally Phase 0.4).

These tests validate the core path-walking behavior that was in assemble_messages()
and is now in ContextBuilder._walk_path() + build(). They test the same contracts
through the public build() API.
"""

import pytest

from qivis.generation.context import ContextBuilder


def _make_nodes() -> list[dict]:
    """Create a sample linear tree: system → user → assistant → user."""
    return [
        {"node_id": "n1", "parent_id": None, "role": "system", "content": "Be helpful."},
        {"node_id": "n2", "parent_id": "n1", "role": "user", "content": "Hello"},
        {"node_id": "n3", "parent_id": "n2", "role": "assistant", "content": "Hi there!"},
        {"node_id": "n4", "parent_id": "n3", "role": "user", "content": "How are you?"},
    ]


@pytest.fixture
def builder() -> ContextBuilder:
    return ContextBuilder()


class TestContextAssemblyLegacy:
    """Tests from Phase 0.4, adapted to use ContextBuilder.build()."""

    def test_linear_chain_chronological_order(self, builder: ContextBuilder):
        """Walking from n4 back to root produces messages in chronological order."""
        nodes = _make_nodes()
        messages, _, _ = builder.build(
            nodes=nodes,
            target_node_id="n4",
            system_prompt="Be helpful.",
            model_context_limit=200_000,
        )
        assert messages == [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
        ]

    def test_system_nodes_excluded(self, builder: ContextBuilder):
        """System-role nodes are not included in the messages array."""
        nodes = _make_nodes()
        messages, _, _ = builder.build(
            nodes=nodes,
            target_node_id="n2",
            system_prompt="Be helpful.",
            model_context_limit=200_000,
        )
        assert messages == [{"role": "user", "content": "Hello"}]

    def test_researcher_note_excluded(self, builder: ContextBuilder):
        """Researcher notes are not included in the messages array."""
        nodes = [
            {"node_id": "n1", "parent_id": None, "role": "user", "content": "Hello"},
            {
                "node_id": "n2",
                "parent_id": "n1",
                "role": "researcher_note",
                "content": "Interesting response",
            },
            {"node_id": "n3", "parent_id": "n2", "role": "assistant", "content": "Hi!"},
        ]
        messages, _, _ = builder.build(
            nodes=nodes,
            target_node_id="n3",
            system_prompt=None,
            model_context_limit=200_000,
        )
        assert messages == [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]

    def test_single_node_no_parent(self, builder: ContextBuilder):
        """A single root node produces a single-element array."""
        nodes = [{"node_id": "n1", "parent_id": None, "role": "user", "content": "Hi"}]
        messages, _, _ = builder.build(
            nodes=nodes,
            target_node_id="n1",
            system_prompt=None,
            model_context_limit=200_000,
        )
        assert messages == [{"role": "user", "content": "Hi"}]

    def test_node_not_found_raises(self, builder: ContextBuilder):
        with pytest.raises(ValueError, match="Node not found"):
            builder.build(
                nodes=[],
                target_node_id="nonexistent",
                system_prompt=None,
                model_context_limit=200_000,
            )

    def test_broken_chain_raises(self, builder: ContextBuilder):
        """If parent_id references a node not in the list, raise ValueError."""
        nodes = [{"node_id": "n2", "parent_id": "n1", "role": "user", "content": "Hi"}]
        with pytest.raises(ValueError, match="Broken chain"):
            builder.build(
                nodes=nodes,
                target_node_id="n2",
                system_prompt=None,
                model_context_limit=200_000,
            )

    def test_branching_only_follows_target_path(self, builder: ContextBuilder):
        """When tree has branches, only the path to the target is included."""
        nodes = [
            {"node_id": "n1", "parent_id": None, "role": "user", "content": "Root"},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant", "content": "Branch A"},
            {"node_id": "n3", "parent_id": "n1", "role": "assistant", "content": "Branch B"},
        ]
        messages, _, _ = builder.build(
            nodes=nodes,
            target_node_id="n2",
            system_prompt=None,
            model_context_limit=200_000,
        )
        assert messages == [
            {"role": "user", "content": "Root"},
            {"role": "assistant", "content": "Branch A"},
        ]
