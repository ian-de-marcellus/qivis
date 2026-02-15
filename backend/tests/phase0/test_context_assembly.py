"""Contract tests for minimal context assembly (Phase 0.4)."""

import pytest

from qivis.generation.context import assemble_messages


def _make_nodes() -> list[dict]:
    """Create a sample linear tree: system → user → assistant → user."""
    return [
        {"node_id": "n1", "parent_id": None, "role": "system", "content": "Be helpful."},
        {"node_id": "n2", "parent_id": "n1", "role": "user", "content": "Hello"},
        {"node_id": "n3", "parent_id": "n2", "role": "assistant", "content": "Hi there!"},
        {"node_id": "n4", "parent_id": "n3", "role": "user", "content": "How are you?"},
    ]


class TestAssembleMessages:
    def test_linear_chain_chronological_order(self):
        """Walking from n4 back to root produces messages in chronological order."""
        nodes = _make_nodes()
        result = assemble_messages(nodes, "n4")
        assert result == [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
        ]

    def test_system_nodes_excluded(self):
        """System-role nodes are not included in the messages array."""
        nodes = _make_nodes()
        result = assemble_messages(nodes, "n2")
        # n1 is system role, should be skipped
        assert result == [{"role": "user", "content": "Hello"}]

    def test_researcher_note_excluded(self):
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
        result = assemble_messages(nodes, "n3")
        assert result == [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]

    def test_single_node_no_parent(self):
        """A single root node produces a single-element array."""
        nodes = [{"node_id": "n1", "parent_id": None, "role": "user", "content": "Hi"}]
        result = assemble_messages(nodes, "n1")
        assert result == [{"role": "user", "content": "Hi"}]

    def test_node_not_found_raises(self):
        with pytest.raises(ValueError, match="Node not found"):
            assemble_messages([], "nonexistent")

    def test_broken_chain_raises(self):
        """If parent_id references a node not in the list, raise ValueError."""
        nodes = [{"node_id": "n2", "parent_id": "n1", "role": "user", "content": "Hi"}]
        with pytest.raises(ValueError, match="Broken chain"):
            assemble_messages(nodes, "n2")

    def test_branching_only_follows_target_path(self):
        """When tree has branches, only the path to the target is included."""
        nodes = [
            {"node_id": "n1", "parent_id": None, "role": "user", "content": "Root"},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant", "content": "Branch A"},
            {"node_id": "n3", "parent_id": "n1", "role": "assistant", "content": "Branch B"},
        ]
        result = assemble_messages(nodes, "n2")
        assert result == [
            {"role": "user", "content": "Root"},
            {"role": "assistant", "content": "Branch A"},
        ]
        # n3 (Branch B) is NOT included
