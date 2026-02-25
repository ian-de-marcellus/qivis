"""Tests for the context intervention pipeline (Phase 9.1a).

Tests the extensible architecture for context interventions:
- InterventionContext data structure
- ContextIntervention ABC and concrete implementations
- InterventionPipeline ordering and execution
- InterventionRegistry lookup and instantiation
- InterventionConfig validation
- ContextBuilder split: build_messages + count_and_evict
- NodeCreatedPayload.active_interventions snapshotting
- GenerationService integration with intervention pipeline
"""

import pytest

from qivis.generation.context import ContextBuilder
from qivis.generation.interventions import (
    ContextIntervention,
    InterventionConfig,
    InterventionContext,
    InterventionPipeline,
    InterventionRegistry,
)
from qivis.models import NodeCreatedPayload, SamplingParams


# ---------------------------------------------------------------------------
# Dummy interventions for testing
# ---------------------------------------------------------------------------


class _UppercaseIntervention(ContextIntervention):
    """Test intervention that uppercases all message content."""

    type_name = "test_uppercase"
    phase = "pre_eviction"

    def apply(self, ctx: InterventionContext) -> InterventionContext:
        for msg in ctx.messages:
            msg["content"] = msg["content"].upper()
        return ctx

    @classmethod
    def config_schema(cls) -> type | None:
        return None


class _PrefixIntervention(ContextIntervention):
    """Test intervention that prepends a prefix to all messages."""

    type_name = "test_prefix"
    phase = "post_eviction"

    def __init__(self, prefix: str = ">>>"):
        self._prefix = prefix

    def apply(self, ctx: InterventionContext) -> InterventionContext:
        for msg in ctx.messages:
            msg["content"] = f"{self._prefix} {msg['content']}"
        return ctx

    @classmethod
    def config_schema(cls) -> type | None:
        return None


class _SystemPromptNullerIntervention(ContextIntervention):
    """Test intervention that moves system prompt into first message."""

    type_name = "test_sysprompt_null"
    phase = "pre_eviction"

    def apply(self, ctx: InterventionContext) -> InterventionContext:
        if ctx.system_prompt and ctx.messages:
            ctx.messages[0]["content"] = (
                f"[SYSTEM: {ctx.system_prompt}]\n{ctx.messages[0]['content']}"
            )
            ctx.system_prompt = None
        return ctx

    @classmethod
    def config_schema(cls) -> type | None:
        return None


# ---------------------------------------------------------------------------
# InterventionContext tests
# ---------------------------------------------------------------------------


class TestInterventionContext:
    """Contract tests for InterventionContext data structure."""

    def test_construction_with_required_fields(self):
        ctx = InterventionContext(
            messages=[{"role": "user", "content": "Hello"}],
            system_prompt="Be helpful",
            node_ids=["node-1"],
            model="claude-sonnet-4-5-20250929",
            metadata={},
            mode="chat",
        )
        assert len(ctx.messages) == 1
        assert ctx.system_prompt == "Be helpful"
        assert ctx.node_ids == ["node-1"]
        assert ctx.model == "claude-sonnet-4-5-20250929"
        assert ctx.mode == "chat"

    def test_messages_and_node_ids_parallel(self):
        ctx = InterventionContext(
            messages=[
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hey"},
            ],
            system_prompt=None,
            node_ids=["n1", "n2"],
            model="gpt-4o",
            metadata={},
            mode="chat",
        )
        assert len(ctx.messages) == len(ctx.node_ids)

    def test_system_prompt_can_be_none(self):
        ctx = InterventionContext(
            messages=[], system_prompt=None, node_ids=[],
            model="test", metadata={}, mode="chat",
        )
        assert ctx.system_prompt is None

    def test_metadata_is_accessible(self):
        ctx = InterventionContext(
            messages=[], system_prompt=None, node_ids=[],
            model="test", metadata={"include_timestamps": True}, mode="chat",
        )
        assert ctx.metadata["include_timestamps"] is True


# ---------------------------------------------------------------------------
# InterventionConfig tests
# ---------------------------------------------------------------------------


class TestInterventionConfig:
    """Contract tests for InterventionConfig Pydantic model."""

    def test_valid_config(self):
        config = InterventionConfig(
            type="system_prompt_reposition",
            enabled=True,
            config={"placement": "first_user_message"},
        )
        assert config.type == "system_prompt_reposition"
        assert config.enabled is True
        assert config.config["placement"] == "first_user_message"

    def test_disabled_config(self):
        config = InterventionConfig(
            type="reminder_injection",
            enabled=False,
            config={"content": "Remember..."},
        )
        assert config.enabled is False

    def test_empty_config_dict(self):
        config = InterventionConfig(
            type="test_type", enabled=True, config={},
        )
        assert config.config == {}

    def test_config_from_dict(self):
        raw = {"type": "message_wrapper", "enabled": True, "config": {"template": "<msg>{content}</msg>"}}
        config = InterventionConfig.model_validate(raw)
        assert config.type == "message_wrapper"
        assert config.config["template"] == "<msg>{content}</msg>"


# ---------------------------------------------------------------------------
# ContextIntervention ABC tests
# ---------------------------------------------------------------------------


class TestContextInterventionABC:
    """Tests for the ContextIntervention abstract base class."""

    def test_dummy_intervention_has_type_name(self):
        intervention = _UppercaseIntervention()
        assert intervention.type_name == "test_uppercase"

    def test_dummy_intervention_has_phase(self):
        intervention = _UppercaseIntervention()
        assert intervention.phase == "pre_eviction"

    def test_apply_modifies_context(self):
        ctx = InterventionContext(
            messages=[{"role": "user", "content": "hello world"}],
            system_prompt=None, node_ids=["n1"],
            model="test", metadata={}, mode="chat",
        )
        result = _UppercaseIntervention().apply(ctx)
        assert result.messages[0]["content"] == "HELLO WORLD"

    def test_apply_can_modify_system_prompt(self):
        ctx = InterventionContext(
            messages=[{"role": "user", "content": "hello"}],
            system_prompt="Be helpful",
            node_ids=["n1"],
            model="test", metadata={}, mode="chat",
        )
        result = _SystemPromptNullerIntervention().apply(ctx)
        assert result.system_prompt is None
        assert "[SYSTEM: Be helpful]" in result.messages[0]["content"]


# ---------------------------------------------------------------------------
# InterventionPipeline tests
# ---------------------------------------------------------------------------


class TestInterventionPipeline:
    """Tests for the InterventionPipeline execution engine."""

    def test_empty_pipeline_is_noop(self):
        pipeline = InterventionPipeline([])
        ctx = InterventionContext(
            messages=[{"role": "user", "content": "hello"}],
            system_prompt="Be helpful", node_ids=["n1"],
            model="test", metadata={}, mode="chat",
        )
        result = pipeline.run_pre_eviction(ctx)
        assert result.messages[0]["content"] == "hello"
        assert result.system_prompt == "Be helpful"

        result = pipeline.run_post_eviction(result)
        assert result.messages[0]["content"] == "hello"

    def test_pre_eviction_runs_only_pre_interventions(self):
        pipeline = InterventionPipeline([
            _UppercaseIntervention(),   # pre_eviction
            _PrefixIntervention(),      # post_eviction
        ])
        ctx = InterventionContext(
            messages=[{"role": "user", "content": "hello"}],
            system_prompt=None, node_ids=["n1"],
            model="test", metadata={}, mode="chat",
        )
        result = pipeline.run_pre_eviction(ctx)
        # Uppercase applied, prefix not yet
        assert result.messages[0]["content"] == "HELLO"

    def test_post_eviction_runs_only_post_interventions(self):
        pipeline = InterventionPipeline([
            _UppercaseIntervention(),   # pre_eviction
            _PrefixIntervention(),      # post_eviction
        ])
        ctx = InterventionContext(
            messages=[{"role": "user", "content": "hello"}],
            system_prompt=None, node_ids=["n1"],
            model="test", metadata={}, mode="chat",
        )
        result = pipeline.run_post_eviction(ctx)
        # Only prefix applied, uppercase not (it's pre_eviction)
        assert result.messages[0]["content"] == ">>> hello"

    def test_full_pipeline_pre_then_post(self):
        pipeline = InterventionPipeline([
            _UppercaseIntervention(),   # pre_eviction
            _PrefixIntervention(),      # post_eviction
        ])
        ctx = InterventionContext(
            messages=[{"role": "user", "content": "hello"}],
            system_prompt=None, node_ids=["n1"],
            model="test", metadata={}, mode="chat",
        )
        ctx = pipeline.run_pre_eviction(ctx)
        ctx = pipeline.run_post_eviction(ctx)
        assert ctx.messages[0]["content"] == ">>> HELLO"

    def test_multiple_pre_eviction_run_in_order(self):
        pipeline = InterventionPipeline([
            _SystemPromptNullerIntervention(),  # pre_eviction
            _UppercaseIntervention(),            # pre_eviction
        ])
        ctx = InterventionContext(
            messages=[{"role": "user", "content": "hello"}],
            system_prompt="Be helpful", node_ids=["n1"],
            model="test", metadata={}, mode="chat",
        )
        result = pipeline.run_pre_eviction(ctx)
        # First: system prompt moved into message, then uppercased
        assert result.system_prompt is None
        assert "[SYSTEM: BE HELPFUL]" in result.messages[0]["content"]
        assert "HELLO" in result.messages[0]["content"]

    def test_pipeline_preserves_node_ids(self):
        pipeline = InterventionPipeline([_UppercaseIntervention()])
        ctx = InterventionContext(
            messages=[{"role": "user", "content": "hello"}],
            system_prompt=None, node_ids=["abc-123"],
            model="test", metadata={}, mode="chat",
        )
        result = pipeline.run_pre_eviction(ctx)
        assert result.node_ids == ["abc-123"]

    def test_get_active_configs_returns_all_interventions(self):
        pipeline = InterventionPipeline([
            _UppercaseIntervention(),
            _PrefixIntervention("!!!"),
        ])
        configs = pipeline.get_active_configs()
        assert len(configs) == 2
        assert configs[0]["type"] == "test_uppercase"
        assert configs[1]["type"] == "test_prefix"


# ---------------------------------------------------------------------------
# InterventionRegistry tests
# ---------------------------------------------------------------------------


class TestInterventionRegistry:
    """Tests for the InterventionRegistry type lookup and instantiation."""

    def test_register_and_lookup(self):
        registry = InterventionRegistry()
        registry.register(_UppercaseIntervention)
        assert registry.get("test_uppercase") is _UppercaseIntervention

    def test_lookup_unknown_returns_none(self):
        registry = InterventionRegistry()
        assert registry.get("nonexistent") is None

    def test_create_from_config(self):
        registry = InterventionRegistry()
        registry.register(_UppercaseIntervention)
        config = InterventionConfig(type="test_uppercase", enabled=True, config={})
        intervention = registry.create(config)
        assert isinstance(intervention, _UppercaseIntervention)

    def test_create_disabled_returns_none(self):
        registry = InterventionRegistry()
        registry.register(_UppercaseIntervention)
        config = InterventionConfig(type="test_uppercase", enabled=False, config={})
        intervention = registry.create(config)
        assert intervention is None

    def test_create_unknown_type_returns_none(self):
        registry = InterventionRegistry()
        config = InterventionConfig(type="nonexistent", enabled=True, config={})
        intervention = registry.create(config)
        assert intervention is None

    def test_available_types(self):
        registry = InterventionRegistry()
        registry.register(_UppercaseIntervention)
        registry.register(_PrefixIntervention)
        types = registry.available_types()
        assert len(types) == 2
        type_names = {t["type_name"] for t in types}
        assert "test_uppercase" in type_names
        assert "test_prefix" in type_names

    def test_create_pipeline_from_configs(self):
        registry = InterventionRegistry()
        registry.register(_UppercaseIntervention)
        registry.register(_PrefixIntervention)
        configs = [
            InterventionConfig(type="test_uppercase", enabled=True, config={}),
            InterventionConfig(type="test_prefix", enabled=False, config={}),
        ]
        pipeline = registry.create_pipeline(configs)
        # Only enabled intervention is in the pipeline
        assert len(pipeline._interventions) == 1


# ---------------------------------------------------------------------------
# ContextBuilder split tests
# ---------------------------------------------------------------------------


class TestContextBuilderSplit:
    """Tests for the ContextBuilder.build_messages() and count_and_evict() split."""

    def test_build_messages_returns_messages_and_node_ids(self):
        builder = ContextBuilder()
        nodes = [
            {"node_id": "n1", "parent_id": None, "role": "user", "content": "Hello"},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant", "content": "Hi there"},
        ]
        messages, node_ids, created_ats, excluded_info = builder.build_messages(
            nodes=nodes,
            target_node_id="n2",
            include_timestamps=False,
            include_thinking=False,
        )
        assert len(messages) == 2
        assert len(node_ids) == 2
        assert len(created_ats) == 2
        assert messages[0] == {"role": "user", "content": "Hello"}
        assert messages[1] == {"role": "assistant", "content": "Hi there"}
        assert node_ids == ["n1", "n2"]

    def test_build_messages_respects_exclusions(self):
        builder = ContextBuilder()
        nodes = [
            {"node_id": "n1", "parent_id": None, "role": "user", "content": "Hello"},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant", "content": "Hi"},
            {"node_id": "n3", "parent_id": "n2", "role": "user", "content": "Bye"},
        ]
        messages, node_ids, _created_ats, _ = builder.build_messages(
            nodes=nodes,
            target_node_id="n3",
            excluded_ids={"n2"},
        )
        assert len(messages) == 2
        assert node_ids == ["n1", "n3"]

    def test_count_and_evict_within_limit(self):
        builder = ContextBuilder()
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        node_ids = ["n1", "n2"]
        result_msgs, usage, report = builder.count_and_evict(
            messages=messages,
            node_ids=node_ids,
            system_prompt="Be helpful",
            model_context_limit=200_000,
        )
        assert len(result_msgs) == 2
        assert usage.total_tokens > 0
        assert not report.eviction_applied

    def test_count_and_evict_triggers_eviction(self):
        builder = ContextBuilder()
        messages = [
            {"role": "user", "content": "A" * 400},
            {"role": "assistant", "content": "B" * 400},
            {"role": "user", "content": "C" * 400},
        ]
        node_ids = ["n1", "n2", "n3"]
        result_msgs, usage, report = builder.count_and_evict(
            messages=messages,
            node_ids=node_ids,
            system_prompt=None,
            model_context_limit=250,  # Very low limit to force eviction
        )
        assert report.eviction_applied
        assert len(result_msgs) < 3

    def test_build_and_split_produce_same_result_as_build(self):
        """Verify that build_messages + count_and_evict produces the same
        result as the monolithic build() for the same inputs."""
        builder = ContextBuilder()
        nodes = [
            {"node_id": "n1", "parent_id": None, "role": "user", "content": "Hello world"},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant", "content": "Hi there!"},
            {"node_id": "n3", "parent_id": "n2", "role": "user", "content": "How are you?"},
        ]

        # Monolithic build
        mono_msgs, mono_usage, mono_report = builder.build(
            nodes=nodes,
            target_node_id="n3",
            system_prompt="Be helpful",
            model_context_limit=200_000,
        )

        # Split build
        messages, node_ids, _created_ats, excluded_info = builder.build_messages(
            nodes=nodes,
            target_node_id="n3",
        )
        split_msgs, split_usage, split_report = builder.count_and_evict(
            messages=messages,
            node_ids=node_ids,
            system_prompt="Be helpful",
            model_context_limit=200_000,
            excluded_token_total=excluded_info["excluded_tokens"],
            excluded_node_count=excluded_info["excluded_count"],
            excluded_node_ids=excluded_info["excluded_node_ids"],
        )

        assert mono_msgs == split_msgs
        assert mono_usage.total_tokens == split_usage.total_tokens
        assert mono_usage.breakdown == split_usage.breakdown


# ---------------------------------------------------------------------------
# NodeCreatedPayload snapshotting tests
# ---------------------------------------------------------------------------


class TestNodeCreatedPayloadSnapshot:
    """Tests that NodeCreatedPayload can snapshot active interventions."""

    def test_active_interventions_default_none(self):
        payload = NodeCreatedPayload(
            node_id="n1", role="assistant", content="Hello",
        )
        assert payload.active_interventions is None

    def test_active_interventions_stores_list(self):
        interventions = [
            {"type": "system_prompt_reposition", "config": {"placement": "first_user_message"}},
            {"type": "reminder_injection", "config": {"content": "Remember", "position": "every_n_turns", "n": 5}},
        ]
        payload = NodeCreatedPayload(
            node_id="n1", role="assistant", content="Hello",
            active_interventions=interventions,
        )
        assert len(payload.active_interventions) == 2
        assert payload.active_interventions[0]["type"] == "system_prompt_reposition"

    def test_active_interventions_serializes(self):
        interventions = [{"type": "test", "config": {}}]
        payload = NodeCreatedPayload(
            node_id="n1", role="assistant", content="Hello",
            active_interventions=interventions,
        )
        data = payload.model_dump()
        assert data["active_interventions"] == interventions
