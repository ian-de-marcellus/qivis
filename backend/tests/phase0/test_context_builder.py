"""Contract tests for ContextBuilder (Phase 0.5)."""

import pytest

from qivis.generation.context import ContextBuilder
from qivis.models import ContextUsage, EvictionReport


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


class TestMessageAssembly:
    """ContextBuilder.build() — message assembly."""

    def test_linear_path_chronological_order(self, builder: ContextBuilder):
        """Walking from n4 back to root produces messages in chronological order."""
        nodes = _make_nodes()
        messages, usage, report = builder.build(
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

    def test_system_prompt_excluded_from_messages(self, builder: ContextBuilder):
        """System prompt is passed via API param, not in messages array."""
        nodes = _make_nodes()
        messages, _, _ = builder.build(
            nodes=nodes,
            target_node_id="n4",
            system_prompt="Be helpful.",
            model_context_limit=200_000,
        )
        roles = {m["role"] for m in messages}
        assert "system" not in roles

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

    def test_single_node_path(self, builder: ContextBuilder):
        """A single root node produces a single-element array."""
        nodes = [{"node_id": "n1", "parent_id": None, "role": "user", "content": "Hi"}]
        messages, _, _ = builder.build(
            nodes=nodes,
            target_node_id="n1",
            system_prompt=None,
            model_context_limit=200_000,
        )
        assert messages == [{"role": "user", "content": "Hi"}]

    def test_empty_path_system_only(self, builder: ContextBuilder):
        """If the target is a system node, messages array is empty."""
        nodes = [
            {"node_id": "n1", "parent_id": None, "role": "system", "content": "System prompt"},
        ]
        messages, _, _ = builder.build(
            nodes=nodes,
            target_node_id="n1",
            system_prompt="System prompt",
            model_context_limit=200_000,
        )
        assert messages == []

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

    def test_node_not_found_raises(self, builder: ContextBuilder):
        with pytest.raises(ValueError, match="Node not found"):
            builder.build(
                nodes=[],
                target_node_id="nonexistent",
                system_prompt=None,
                model_context_limit=200_000,
            )

    def test_broken_chain_raises(self, builder: ContextBuilder):
        nodes = [{"node_id": "n2", "parent_id": "n1", "role": "user", "content": "Hi"}]
        with pytest.raises(ValueError, match="Broken chain"):
            builder.build(
                nodes=nodes,
                target_node_id="n2",
                system_prompt=None,
                model_context_limit=200_000,
            )


class TestContextUsageComputation:
    """ContextBuilder.build() — ContextUsage output."""

    def test_returns_context_usage(self, builder: ContextBuilder):
        """build() returns a ContextUsage as the second element."""
        nodes = _make_nodes()
        _, usage, _ = builder.build(
            nodes=nodes,
            target_node_id="n4",
            system_prompt="Be helpful.",
            model_context_limit=200_000,
        )
        assert isinstance(usage, ContextUsage)

    def test_total_tokens_positive(self, builder: ContextBuilder):
        """total_tokens reflects actual content."""
        nodes = _make_nodes()
        _, usage, _ = builder.build(
            nodes=nodes,
            target_node_id="n4",
            system_prompt="Be helpful.",
            model_context_limit=200_000,
        )
        assert usage.total_tokens > 0

    def test_breakdown_has_role_keys(self, builder: ContextBuilder):
        """breakdown dict has system, user, and assistant keys."""
        nodes = _make_nodes()
        _, usage, _ = builder.build(
            nodes=nodes,
            target_node_id="n4",
            system_prompt="Be helpful.",
            model_context_limit=200_000,
        )
        assert "system" in usage.breakdown
        assert "user" in usage.breakdown
        assert "assistant" in usage.breakdown

    def test_breakdown_sums_to_total(self, builder: ContextBuilder):
        """Sum of breakdown values equals total_tokens."""
        nodes = _make_nodes()
        _, usage, _ = builder.build(
            nodes=nodes,
            target_node_id="n4",
            system_prompt="Be helpful.",
            model_context_limit=200_000,
        )
        assert sum(usage.breakdown.values()) == usage.total_tokens

    def test_max_tokens_matches_model_limit(self, builder: ContextBuilder):
        """max_tokens is the model context limit we passed in."""
        nodes = _make_nodes()
        _, usage, _ = builder.build(
            nodes=nodes,
            target_node_id="n4",
            system_prompt="Be helpful.",
            model_context_limit=100_000,
        )
        assert usage.max_tokens == 100_000

    def test_excluded_zero_in_phase05(self, builder: ContextBuilder):
        """In Phase 0.5, excluded_tokens and excluded_count are always 0."""
        nodes = _make_nodes()
        _, usage, _ = builder.build(
            nodes=nodes,
            target_node_id="n4",
            system_prompt="Be helpful.",
            model_context_limit=200_000,
        )
        assert usage.excluded_tokens == 0
        assert usage.excluded_count == 0


class TestSystemPromptHandling:
    """ContextBuilder.build() — system prompt handling."""

    def test_system_prompt_tokens_in_breakdown(self, builder: ContextBuilder):
        """System prompt tokens are counted in breakdown['system']."""
        nodes = [{"node_id": "n1", "parent_id": None, "role": "user", "content": "Hi"}]
        _, usage, _ = builder.build(
            nodes=nodes,
            target_node_id="n1",
            system_prompt="You are a helpful assistant.",
            model_context_limit=200_000,
        )
        assert usage.breakdown["system"] > 0

    def test_null_system_prompt_zero_system_tokens(self, builder: ContextBuilder):
        """When system_prompt is None, breakdown['system'] is 0."""
        nodes = [{"node_id": "n1", "parent_id": None, "role": "user", "content": "Hi"}]
        _, usage, _ = builder.build(
            nodes=nodes,
            target_node_id="n1",
            system_prompt=None,
            model_context_limit=200_000,
        )
        assert usage.breakdown["system"] == 0


class TestBoundarySafeTruncation:
    """ContextBuilder.build() — boundary-safe truncation when exceeding context limit."""

    def test_no_truncation_when_under_limit(self, builder: ContextBuilder):
        """When total tokens are under the limit, no eviction happens."""
        nodes = _make_nodes()
        _, _, report = builder.build(
            nodes=nodes,
            target_node_id="n4",
            system_prompt="Be helpful.",
            model_context_limit=200_000,
        )
        assert isinstance(report, EvictionReport)
        assert report.eviction_applied is False
        assert report.evicted_node_ids == []
        assert report.tokens_freed == 0

    def test_oldest_messages_dropped_first(self, builder: ContextBuilder):
        """When over limit, the oldest messages (earliest in conversation) are dropped."""
        # Create nodes with enough content to exceed a tiny limit
        nodes = [
            {"node_id": "n1", "parent_id": None, "role": "user", "content": "A" * 100},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant", "content": "B" * 100},
            {"node_id": "n3", "parent_id": "n2", "role": "user", "content": "C" * 100},
            {"node_id": "n4", "parent_id": "n3", "role": "assistant", "content": "D" * 100},
        ]
        # Set limit so only ~2 messages fit (each is ~25 tokens at len//4)
        messages, _, report = builder.build(
            nodes=nodes,
            target_node_id="n4",
            system_prompt=None,
            model_context_limit=55,
        )
        assert report.eviction_applied is True
        # The oldest messages should have been dropped
        assert len(messages) < 4
        # The last message should always be present
        assert messages[-1]["content"] == "D" * 100

    def test_system_prompt_never_lost(self, builder: ContextBuilder):
        """System prompt tokens are always preserved, even under tight limits."""
        nodes = [
            {"node_id": "n1", "parent_id": None, "role": "user", "content": "A" * 100},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant", "content": "B" * 100},
        ]
        # Limit is tight but should still account for system prompt
        _, usage, _ = builder.build(
            nodes=nodes,
            target_node_id="n2",
            system_prompt="Important system instructions.",
            model_context_limit=60,
        )
        # System prompt should always be counted
        assert usage.breakdown["system"] > 0

    def test_whole_messages_only(self, builder: ContextBuilder):
        """Messages are never cut mid-message — only whole messages are dropped."""
        nodes = [
            {"node_id": "n1", "parent_id": None, "role": "user", "content": "Hello world"},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant", "content": "Hi there friend"},
            {"node_id": "n3", "parent_id": "n2", "role": "user", "content": "Last message"},
        ]
        messages, _, _ = builder.build(
            nodes=nodes,
            target_node_id="n3",
            system_prompt=None,
            model_context_limit=15,  # Very tight
        )
        # Each surviving message should have its full content
        for msg in messages:
            assert msg["content"] in ("Hello world", "Hi there friend", "Last message")

    def test_eviction_report_reflects_dropped(self, builder: ContextBuilder):
        """EvictionReport tracks what was evicted."""
        nodes = [
            {"node_id": "n1", "parent_id": None, "role": "user", "content": "A" * 100},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant", "content": "B" * 100},
            {"node_id": "n3", "parent_id": "n2", "role": "user", "content": "C" * 100},
        ]
        _, _, report = builder.build(
            nodes=nodes,
            target_node_id="n3",
            system_prompt=None,
            model_context_limit=30,  # Only ~1 message fits
        )
        assert report.eviction_applied is True
        assert report.tokens_freed > 0
        assert len(report.evicted_node_ids) > 0
        assert report.final_token_count > 0
