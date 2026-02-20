"""Tests for the smart eviction algorithm (Phase 6.4b).

Tests ContextBuilder's smart eviction mode: protected ranges (first N, last N,
anchored nodes), warning threshold, mode dispatch, and combined exclusion + eviction.
Also tests token counter interface and eviction report metadata (Interlude).
"""

import pytest

from qivis.generation.context import ContextBuilder
from qivis.generation.tokens import ApproximateTokenCounter, TokenCounter
from qivis.models import EvictionReport, EvictionStrategy


def _make_long_conversation(n: int = 10, content_len: int = 100) -> list[dict]:
    """Create a linear conversation with n user/assistant pairs.

    Each message is content_len characters long (~content_len//4 tokens).
    Returns 2*n nodes (no system node).
    """
    nodes: list[dict] = []
    for i in range(n):
        user_id = f"u{i}"
        asst_id = f"a{i}"
        parent = nodes[-1]["node_id"] if nodes else None
        nodes.append({
            "node_id": user_id,
            "parent_id": parent,
            "role": "user",
            "content": f"User message {i}. " + "x" * content_len,
        })
        nodes.append({
            "node_id": asst_id,
            "parent_id": user_id,
            "role": "assistant",
            "content": f"Assistant reply {i}. " + "y" * content_len,
        })
    return nodes


@pytest.fixture
def builder() -> ContextBuilder:
    return ContextBuilder()


class TestSmartEvictionProtection:
    """Smart eviction protects first turns, recent turns, and anchored nodes."""

    def test_protects_first_n_turns(self, builder: ContextBuilder):
        """First keep_first_turns messages are never evicted."""
        nodes = _make_long_conversation(8, content_len=100)
        target = nodes[-1]["node_id"]
        strategy = EvictionStrategy(
            mode="smart",
            keep_first_turns=4,
            recent_turns_to_keep=2,
        )
        # Tight limit forces eviction
        messages, usage, report = builder.build(
            nodes=nodes,
            target_node_id=target,
            system_prompt=None,
            model_context_limit=300,
            eviction=strategy,
        )
        assert report.eviction_applied is True
        # First 4 messages should survive (keep_first_turns=4)
        first_four_contents = [n["content"] for n in nodes[:4] if n["role"] in ("user", "assistant")]
        surviving_contents = [m["content"] for m in messages]
        for content in first_four_contents[:4]:
            assert content in surviving_contents, f"First-turn protected message was evicted"

    def test_protects_recent_n_turns(self, builder: ContextBuilder):
        """Last recent_turns_to_keep messages are never evicted."""
        nodes = _make_long_conversation(8, content_len=100)
        target = nodes[-1]["node_id"]
        strategy = EvictionStrategy(
            mode="smart",
            keep_first_turns=2,
            recent_turns_to_keep=4,
        )
        messages, usage, report = builder.build(
            nodes=nodes,
            target_node_id=target,
            system_prompt=None,
            model_context_limit=300,
            eviction=strategy,
        )
        assert report.eviction_applied is True
        # Last 4 messages should survive
        last_four = [n for n in nodes if n["role"] in ("user", "assistant")][-4:]
        surviving_contents = [m["content"] for m in messages]
        for n in last_four:
            assert n["content"] in surviving_contents, "Recent-turn protected message was evicted"

    def test_protects_anchored_nodes(self, builder: ContextBuilder):
        """Anchored node IDs are never evicted."""
        nodes = _make_long_conversation(8, content_len=100)
        target = nodes[-1]["node_id"]
        # Anchor a middle message
        anchored_id = "u3"  # 7th message (0-indexed user 3)
        strategy = EvictionStrategy(
            mode="smart",
            keep_first_turns=2,
            recent_turns_to_keep=2,
            keep_anchored=True,
        )
        messages, usage, report = builder.build(
            nodes=nodes,
            target_node_id=target,
            system_prompt=None,
            model_context_limit=300,
            anchored_ids={anchored_id},
            eviction=strategy,
        )
        assert report.eviction_applied is True
        surviving_contents = [m["content"] for m in messages]
        anchored_content = next(n["content"] for n in nodes if n["node_id"] == anchored_id)
        assert anchored_content in surviving_contents, "Anchored message was evicted"

    def test_evicts_middle_messages_oldest_first(self, builder: ContextBuilder):
        """Unprotected middle messages are evicted oldest-first."""
        nodes = _make_long_conversation(8, content_len=100)
        target = nodes[-1]["node_id"]
        strategy = EvictionStrategy(
            mode="smart",
            keep_first_turns=2,
            recent_turns_to_keep=2,
        )
        messages, usage, report = builder.build(
            nodes=nodes,
            target_node_id=target,
            system_prompt=None,
            model_context_limit=300,
            eviction=strategy,
        )
        assert report.eviction_applied is True
        assert len(report.evicted_node_ids) > 0
        # Evicted IDs should be from the middle, not first or last
        sendable = [n for n in nodes if n["role"] in ("user", "assistant")]
        first_ids = {n["node_id"] for n in sendable[:2]}
        last_ids = {n["node_id"] for n in sendable[-2:]}
        for eid in report.evicted_node_ids:
            assert eid not in first_ids, "First-turn message was evicted"
            assert eid not in last_ids, "Recent-turn message was evicted"


class TestEvictionReport:
    """EvictionReport is correctly populated."""

    def test_report_populated(self, builder: ContextBuilder):
        """EvictionReport has evicted_node_ids, tokens_freed."""
        nodes = _make_long_conversation(8, content_len=100)
        target = nodes[-1]["node_id"]
        strategy = EvictionStrategy(mode="smart", keep_first_turns=2, recent_turns_to_keep=2)
        _, _, report = builder.build(
            nodes=nodes,
            target_node_id=target,
            system_prompt=None,
            model_context_limit=300,
            eviction=strategy,
        )
        assert isinstance(report, EvictionReport)
        assert report.eviction_applied is True
        assert len(report.evicted_node_ids) > 0
        assert report.tokens_freed > 0
        assert report.final_token_count > 0

    def test_evicted_content_collected_when_summarize(self, builder: ContextBuilder):
        """When summarize_evicted=True, evicted_content is populated."""
        nodes = _make_long_conversation(8, content_len=100)
        target = nodes[-1]["node_id"]
        strategy = EvictionStrategy(
            mode="smart", keep_first_turns=2, recent_turns_to_keep=2,
            summarize_evicted=True,
        )
        _, _, report = builder.build(
            nodes=nodes,
            target_node_id=target,
            system_prompt=None,
            model_context_limit=300,
            eviction=strategy,
        )
        assert report.eviction_applied is True
        assert len(report.evicted_content) > 0
        assert report.summary_needed is True

    def test_no_summary_when_summarize_false(self, builder: ContextBuilder):
        """When summarize_evicted=False, summary_needed is False."""
        nodes = _make_long_conversation(8, content_len=100)
        target = nodes[-1]["node_id"]
        strategy = EvictionStrategy(
            mode="smart", keep_first_turns=2, recent_turns_to_keep=2,
            summarize_evicted=False,
        )
        _, _, report = builder.build(
            nodes=nodes,
            target_node_id=target,
            system_prompt=None,
            model_context_limit=300,
            eviction=strategy,
        )
        assert report.eviction_applied is True
        assert report.summary_needed is False


class TestEvictionModes:
    """Mode dispatch: smart, truncate, none."""

    def test_truncate_mode_uses_old_behavior(self, builder: ContextBuilder):
        """mode='truncate' drops from front, no protection."""
        nodes = _make_long_conversation(6, content_len=100)
        target = nodes[-1]["node_id"]
        strategy = EvictionStrategy(mode="truncate", keep_first_turns=2, recent_turns_to_keep=2)
        messages, _, report = builder.build(
            nodes=nodes,
            target_node_id=target,
            system_prompt=None,
            model_context_limit=200,
            eviction=strategy,
        )
        assert report.eviction_applied is True
        # Truncate mode doesn't protect first turns — first message may be evicted
        surviving_contents = [m["content"] for m in messages]
        first_msg = next(n for n in nodes if n["role"] in ("user", "assistant"))
        if first_msg["content"] not in surviving_contents:
            # First message was evicted — that's fine for truncate mode
            assert "u0" in report.evicted_node_ids or len(report.evicted_node_ids) > 0

    def test_none_mode_no_eviction(self, builder: ContextBuilder):
        """mode='none' means no eviction even over limit."""
        nodes = _make_long_conversation(8, content_len=100)
        target = nodes[-1]["node_id"]
        strategy = EvictionStrategy(mode="none")
        messages, usage, report = builder.build(
            nodes=nodes,
            target_node_id=target,
            system_prompt=None,
            model_context_limit=100,  # Way too small
            eviction=strategy,
        )
        assert report.eviction_applied is False
        # All sendable messages should be present
        sendable_count = sum(1 for n in nodes if n["role"] in ("user", "assistant"))
        assert len(messages) == sendable_count


class TestWarningThreshold:
    """Warning when approaching context limit but not exceeding it."""

    def test_warning_at_threshold(self, builder: ContextBuilder):
        """When total/max >= warn_threshold but below limit, report has warning."""
        # Create enough content to be at ~90% of a carefully chosen limit
        nodes = [
            {"node_id": "n1", "parent_id": None, "role": "user", "content": "x" * 360},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant", "content": "y" * 360},
        ]
        # Each message is 360/4 = 90 tokens. Total = 180 tokens.
        # Set limit to 200 so 180/200 = 90% >= 85% threshold.
        strategy = EvictionStrategy(mode="smart", warn_threshold=0.85)
        _, usage, report = builder.build(
            nodes=nodes,
            target_node_id="n2",
            system_prompt=None,
            model_context_limit=200,
            eviction=strategy,
        )
        assert report.eviction_applied is False
        assert report.warning is not None
        assert "90%" in report.warning or "Context" in report.warning

    def test_no_warning_below_threshold(self, builder: ContextBuilder):
        """When total/max < warn_threshold, no warning."""
        nodes = [
            {"node_id": "n1", "parent_id": None, "role": "user", "content": "Hello"},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant", "content": "Hi"},
        ]
        strategy = EvictionStrategy(mode="smart", warn_threshold=0.85)
        _, _, report = builder.build(
            nodes=nodes,
            target_node_id="n2",
            system_prompt=None,
            model_context_limit=200_000,
            eviction=strategy,
        )
        assert report.warning is None


class TestCombinedExclusionAndEviction:
    """Exclusions happen first, then eviction acts on remaining messages."""

    def test_exclusion_then_eviction(self, builder: ContextBuilder):
        """Excluded nodes are removed before eviction, reducing what needs evicting."""
        nodes = _make_long_conversation(8, content_len=100)
        target = nodes[-1]["node_id"]
        # Exclude some middle messages
        excluded = {"u2", "a2", "u3", "a3"}
        strategy = EvictionStrategy(mode="smart", keep_first_turns=2, recent_turns_to_keep=2)
        messages, usage, report = builder.build(
            nodes=nodes,
            target_node_id=target,
            system_prompt=None,
            model_context_limit=250,
            excluded_ids=excluded,
            eviction=strategy,
        )
        # Excluded nodes should not be in messages
        surviving_contents = [m["content"] for m in messages]
        for nid in excluded:
            content = next(n["content"] for n in nodes if n["node_id"] == nid)
            assert content not in surviving_contents
        # Excluded tokens should be counted
        assert usage.excluded_tokens > 0
        assert usage.excluded_count == 4


class TestAllProtectedGraceful:
    """When all messages are protected, no eviction occurs even over limit."""

    def test_all_protected_no_eviction(self, builder: ContextBuilder):
        """If all messages are in protected ranges, no eviction happens."""
        # 4 messages total, keep_first=2, recent=2 — all protected
        nodes = _make_long_conversation(2, content_len=100)
        target = nodes[-1]["node_id"]
        strategy = EvictionStrategy(
            mode="smart",
            keep_first_turns=2,
            recent_turns_to_keep=2,
        )
        messages, _, report = builder.build(
            nodes=nodes,
            target_node_id=target,
            system_prompt=None,
            model_context_limit=10,  # Way too small, but all protected
            eviction=strategy,
        )
        # All 4 messages present (all protected)
        assert len(messages) == 4
        assert report.eviction_applied is False


class TestNoEvictionStrategyFallback:
    """When eviction is None, old truncate behavior is used."""

    def test_none_eviction_uses_truncate(self, builder: ContextBuilder):
        """When eviction=None, the old _truncate_to_fit is used."""
        nodes = _make_long_conversation(6, content_len=100)
        target = nodes[-1]["node_id"]
        messages, _, report = builder.build(
            nodes=nodes,
            target_node_id=target,
            system_prompt=None,
            model_context_limit=200,
            eviction=None,
        )
        assert report.eviction_applied is True
        assert len(report.evicted_node_ids) > 0


class TestEvictionStrategyRoundtrip:
    """Eviction strategy stored in tree metadata survives roundtrip."""

    def test_strategy_serialization(self):
        """EvictionStrategy can be serialized and deserialized from dict."""
        strategy = EvictionStrategy(
            mode="smart",
            keep_first_turns=3,
            recent_turns_to_keep=5,
            keep_anchored=True,
            summarize_evicted=False,
            warn_threshold=0.9,
        )
        as_dict = strategy.model_dump()
        restored = EvictionStrategy.model_validate(as_dict)
        assert restored.mode == "smart"
        assert restored.keep_first_turns == 3
        assert restored.recent_turns_to_keep == 5
        assert restored.keep_anchored is True
        assert restored.summarize_evicted is False
        assert restored.warn_threshold == 0.9

    def test_strategy_defaults(self):
        """EvictionStrategy has sensible defaults."""
        strategy = EvictionStrategy()
        assert strategy.mode == "smart"
        assert strategy.keep_first_turns == 2
        assert strategy.recent_turns_to_keep == 4
        assert strategy.keep_anchored is True
        assert strategy.summarize_evicted is True
        assert strategy.warn_threshold == 0.85


class TestContextUsageEvictedTokens:
    """ContextUsage reports evicted_node_ids after smart eviction."""

    def test_context_usage_has_evicted_ids(self, builder: ContextBuilder):
        """After smart eviction, ContextUsage.evicted_node_ids is populated."""
        nodes = _make_long_conversation(8, content_len=100)
        target = nodes[-1]["node_id"]
        strategy = EvictionStrategy(mode="smart", keep_first_turns=2, recent_turns_to_keep=2)
        _, usage, report = builder.build(
            nodes=nodes,
            target_node_id=target,
            system_prompt=None,
            model_context_limit=300,
            eviction=strategy,
        )
        assert report.eviction_applied is True
        assert len(usage.evicted_node_ids) > 0
        assert usage.evicted_node_ids == report.evicted_node_ids


# ---- Token counter interface (Interlude) ----


class FixedTokenCounter(TokenCounter):
    """Test counter that returns a fixed value per call."""

    def __init__(self, tokens_per_call: int) -> None:
        self._tpc = tokens_per_call

    def count(self, text: str) -> int:
        return self._tpc


class TestTokenCounterInterface:
    """TokenCounter ABC and implementations."""

    def test_approximate_counter_matches_len_div_4(self):
        """ApproximateTokenCounter reproduces the len // 4 heuristic."""
        counter = ApproximateTokenCounter()
        assert counter.count("hello world") == len("hello world") // 4
        assert counter.count("") == 0
        assert counter.count("abc") == 0  # 3 // 4 = 0
        assert counter.count("abcd") == 1  # 4 // 4 = 1

    def test_custom_counter_changes_eviction_threshold(self, builder: ContextBuilder):
        """A custom counter that inflates token counts triggers eviction sooner."""
        nodes = _make_long_conversation(4, content_len=20)
        target = nodes[-1]["node_id"]
        strategy = EvictionStrategy(mode="smart", keep_first_turns=2, recent_turns_to_keep=2)

        # With approximate counter (small tokens), no eviction needed
        _, _, report_approx = builder.build(
            nodes=nodes,
            target_node_id=target,
            system_prompt=None,
            model_context_limit=1000,
            eviction=strategy,
        )
        assert report_approx.eviction_applied is False

        # With inflated counter (100 tokens per message), eviction triggers
        fat_counter = FixedTokenCounter(500)
        _, _, report_fat = builder.build(
            nodes=nodes,
            target_node_id=target,
            system_prompt=None,
            model_context_limit=1000,
            eviction=strategy,
            token_counter=fat_counter,
        )
        assert report_fat.eviction_applied is True

    def test_default_counter_when_none(self, builder: ContextBuilder):
        """When no token_counter is passed, build() uses ApproximateTokenCounter."""
        nodes = _make_long_conversation(3, content_len=40)
        target = nodes[-1]["node_id"]
        # Both calls should produce identical results
        _, usage_default, _ = builder.build(
            nodes=nodes,
            target_node_id=target,
            system_prompt="Be helpful.",
            model_context_limit=200_000,
        )
        _, usage_explicit, _ = builder.build(
            nodes=nodes,
            target_node_id=target,
            system_prompt="Be helpful.",
            model_context_limit=200_000,
            token_counter=ApproximateTokenCounter(),
        )
        assert usage_default.total_tokens == usage_explicit.total_tokens


# ---- EvictionReport metadata (Interlude) ----


class TestEvictionReportMetadata:
    """EvictionReport carries strategy metadata for downstream use."""

    def test_report_carries_keep_first_turns(self, builder: ContextBuilder):
        """After smart eviction, report.keep_first_turns reflects the strategy."""
        nodes = _make_long_conversation(8, content_len=100)
        target = nodes[-1]["node_id"]
        strategy = EvictionStrategy(mode="smart", keep_first_turns=5, recent_turns_to_keep=2)
        _, _, report = builder.build(
            nodes=nodes,
            target_node_id=target,
            system_prompt=None,
            model_context_limit=300,
            eviction=strategy,
        )
        assert report.eviction_applied is True
        assert report.keep_first_turns == 5

    def test_report_carries_summary_model(self, builder: ContextBuilder):
        """After smart eviction, report.summary_model reflects the strategy."""
        nodes = _make_long_conversation(8, content_len=100)
        target = nodes[-1]["node_id"]
        strategy = EvictionStrategy(
            mode="smart",
            keep_first_turns=2,
            recent_turns_to_keep=2,
            summary_model="gpt-4o-mini",
        )
        _, _, report = builder.build(
            nodes=nodes,
            target_node_id=target,
            system_prompt=None,
            model_context_limit=300,
            eviction=strategy,
        )
        assert report.eviction_applied is True
        assert report.summary_model == "gpt-4o-mini"

    def test_default_report_has_sensible_defaults(self):
        """Un-evicted report has default keep_first_turns=0 and default summary_model."""
        report = EvictionReport()
        assert report.keep_first_turns == 0
        assert report.summary_model == "claude-haiku-4-5-20251001"

    def test_report_defaults_when_no_eviction(self, builder: ContextBuilder):
        """When no eviction is needed, report still has field defaults."""
        nodes = _make_long_conversation(2, content_len=20)
        target = nodes[-1]["node_id"]
        _, _, report = builder.build(
            nodes=nodes,
            target_node_id=target,
            system_prompt=None,
            model_context_limit=200_000,
        )
        assert report.eviction_applied is False
        assert report.keep_first_turns == 0
        assert report.summary_model == "claude-haiku-4-5-20251001"
