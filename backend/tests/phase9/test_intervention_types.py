"""Tests for built-in context intervention types (Phase 9.1b).

Tests SystemPromptReposition, ReminderInjection, and MessageWrapper
intervention types.
"""

import pytest

from qivis.generation.interventions import (
    InterventionConfig,
    InterventionContext,
    InterventionPipeline,
    InterventionRegistry,
    default_registry,
)
from qivis.generation.interventions.system_prompt_reposition import SystemPromptReposition
from qivis.generation.interventions.reminder_injection import ReminderInjection
from qivis.generation.interventions.message_wrapper import MessageWrapper


def _make_ctx(
    messages: list[dict[str, str]] | None = None,
    system_prompt: str | None = "You are helpful.",
    node_ids: list[str] | None = None,
) -> InterventionContext:
    """Helper to create InterventionContext with sensible defaults."""
    if messages is None:
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
            {"role": "assistant", "content": "I'm doing well."},
        ]
    if node_ids is None:
        node_ids = [f"n{i}" for i in range(len(messages))]
    return InterventionContext(
        messages=messages,
        system_prompt=system_prompt,
        node_ids=node_ids,
        model="claude-sonnet-4-5-20250929",
        metadata={},
        mode="chat",
    )


# ---------------------------------------------------------------------------
# SystemPromptReposition tests
# ---------------------------------------------------------------------------


class TestSystemPromptReposition:
    """Tests for the SystemPromptReposition intervention."""

    def test_type_name_and_phase(self):
        i = SystemPromptReposition()
        assert i.type_name == "system_prompt_reposition"
        assert i.phase == "pre_eviction"

    def test_default_placement_is_first_user_message(self):
        i = SystemPromptReposition()
        ctx = _make_ctx()
        result = i.apply(ctx)
        # System prompt should be in the first message now
        assert result.system_prompt is None
        assert "[System Instructions]" in result.messages[0]["content"]
        assert "You are helpful." in result.messages[0]["content"]
        assert "Hello" in result.messages[0]["content"]
        # Message count unchanged
        assert len(result.messages) == 4

    def test_standalone_preamble_placement(self):
        i = SystemPromptReposition(placement="standalone_preamble")
        ctx = _make_ctx()
        result = i.apply(ctx)
        assert result.system_prompt is None
        # A new user message is inserted at position 0
        assert len(result.messages) == 5
        assert "[System Instructions]" in result.messages[0]["content"]
        assert result.messages[0]["role"] == "user"
        # Original first message is now at index 1
        assert result.messages[1]["content"] == "Hello"

    def test_last_before_final_placement(self):
        i = SystemPromptReposition(placement="last_before_final")
        ctx = _make_ctx()
        result = i.apply(ctx)
        assert result.system_prompt is None
        # System prompt inserted as second-to-last
        assert len(result.messages) == 5
        assert "[System Instructions]" in result.messages[3]["content"]
        assert result.messages[4]["content"] == "I'm doing well."

    def test_custom_wrapper_template(self):
        i = SystemPromptReposition(
            placement="first_user_message",
            wrapper_template="<instructions>{content}</instructions>",
        )
        ctx = _make_ctx()
        result = i.apply(ctx)
        assert "<instructions>You are helpful.</instructions>" in result.messages[0]["content"]

    def test_no_system_prompt_is_noop(self):
        i = SystemPromptReposition()
        ctx = _make_ctx(system_prompt=None)
        original_messages = [m.copy() for m in ctx.messages]
        result = i.apply(ctx)
        assert result.messages == original_messages
        assert result.system_prompt is None

    def test_empty_messages_with_system_prompt(self):
        i = SystemPromptReposition()
        ctx = _make_ctx(messages=[], system_prompt="Be helpful")
        result = i.apply(ctx)
        # Can't reposition into empty messages — should be noop
        assert result.system_prompt == "Be helpful"
        assert len(result.messages) == 0

    def test_node_ids_updated_for_standalone_preamble(self):
        i = SystemPromptReposition(placement="standalone_preamble")
        ctx = _make_ctx()
        result = i.apply(ctx)
        # New preamble message gets a synthetic node_id
        assert len(result.node_ids) == 5
        assert result.node_ids[0] == "__intervention_system_prompt__"
        assert result.node_ids[1] == "n0"

    def test_node_ids_updated_for_last_before_final(self):
        i = SystemPromptReposition(placement="last_before_final")
        ctx = _make_ctx()
        result = i.apply(ctx)
        assert len(result.node_ids) == 5
        assert result.node_ids[3] == "__intervention_system_prompt__"

    def test_registered_in_default_registry(self):
        assert default_registry.get("system_prompt_reposition") is SystemPromptReposition


# ---------------------------------------------------------------------------
# ReminderInjection tests
# ---------------------------------------------------------------------------


class TestReminderInjection:
    """Tests for the ReminderInjection intervention."""

    def test_type_name_and_phase(self):
        i = ReminderInjection(content="Remember!")
        assert i.type_name == "reminder_injection"
        assert i.phase == "post_eviction"

    def test_every_n_turns(self):
        # 6 messages with n=2 → reminders after positions 2 and 4
        messages = [
            {"role": "user", "content": f"msg{i}"}
            for i in range(6)
        ]
        i = ReminderInjection(content="Remember!", position="every_n_turns", n=2)
        ctx = _make_ctx(messages=messages, node_ids=[f"n{j}" for j in range(6)])
        result = i.apply(ctx)
        reminder_indices = [
            idx for idx, m in enumerate(result.messages)
            if m["content"] == "Remember!"
        ]
        assert len(reminder_indices) == 2

    def test_at_fraction(self):
        i = ReminderInjection(content="Halfway!", position="at_fraction", fraction=0.5)
        ctx = _make_ctx()  # 4 messages
        result = i.apply(ctx)
        # One reminder inserted at ~50%
        reminders = [m for m in result.messages if m["content"] == "Halfway!"]
        assert len(reminders) == 1
        # Should be roughly in the middle
        reminder_idx = next(
            idx for idx, m in enumerate(result.messages) if m["content"] == "Halfway!"
        )
        assert 1 <= reminder_idx <= 3

    def test_before_last(self):
        i = ReminderInjection(content="Final reminder!", position="before_last")
        ctx = _make_ctx()  # 4 messages, last is "I'm doing well."
        result = i.apply(ctx)
        assert len(result.messages) == 5
        assert result.messages[3]["content"] == "Final reminder!"
        assert result.messages[4]["content"] == "I'm doing well."

    def test_reminder_role_default_user(self):
        i = ReminderInjection(content="Remember!", position="before_last")
        ctx = _make_ctx()
        result = i.apply(ctx)
        reminder = next(m for m in result.messages if m["content"] == "Remember!")
        assert reminder["role"] == "user"

    def test_reminder_role_system(self):
        i = ReminderInjection(content="Remember!", position="before_last", role="system")
        ctx = _make_ctx()
        result = i.apply(ctx)
        reminder = next(m for m in result.messages if m["content"] == "Remember!")
        assert reminder["role"] == "system"

    def test_empty_messages_is_noop(self):
        i = ReminderInjection(content="Remember!", position="before_last")
        ctx = _make_ctx(messages=[])
        result = i.apply(ctx)
        assert len(result.messages) == 0

    def test_single_message_before_last(self):
        i = ReminderInjection(content="Note!", position="before_last")
        ctx = _make_ctx(
            messages=[{"role": "user", "content": "Hi"}],
            node_ids=["n0"],
        )
        result = i.apply(ctx)
        # Reminder inserted before the single message
        assert len(result.messages) == 2
        assert result.messages[0]["content"] == "Note!"
        assert result.messages[1]["content"] == "Hi"

    def test_node_ids_grow_with_injected_reminders(self):
        i = ReminderInjection(content="Remember!", position="before_last")
        ctx = _make_ctx()
        result = i.apply(ctx)
        assert len(result.node_ids) == len(result.messages)

    def test_every_n_turns_with_large_n(self):
        """When n is larger than message count, no reminders are inserted."""
        i = ReminderInjection(content="Remember!", position="every_n_turns", n=100)
        ctx = _make_ctx()  # 4 messages
        result = i.apply(ctx)
        reminders = [m for m in result.messages if m["content"] == "Remember!"]
        assert len(reminders) == 0

    def test_registered_in_default_registry(self):
        assert default_registry.get("reminder_injection") is ReminderInjection


# ---------------------------------------------------------------------------
# MessageWrapper tests
# ---------------------------------------------------------------------------


class TestMessageWrapper:
    """Tests for the MessageWrapper intervention."""

    def test_type_name_and_phase(self):
        i = MessageWrapper(template="<msg>{content}</msg>")
        assert i.type_name == "message_wrapper"
        assert i.phase == "pre_eviction"

    def test_basic_wrapping(self):
        i = MessageWrapper(template="<msg>{content}</msg>")
        ctx = _make_ctx(
            messages=[{"role": "user", "content": "Hello"}],
            node_ids=["n0"],
        )
        result = i.apply(ctx)
        assert result.messages[0]["content"] == "<msg>Hello</msg>"

    def test_template_with_role_and_index(self):
        i = MessageWrapper(
            template='<message role="{role}" index="{index}">\n{content}\n</message>'
        )
        ctx = _make_ctx(
            messages=[
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hey"},
            ],
            node_ids=["n0", "n1"],
        )
        result = i.apply(ctx)
        assert '<message role="user" index="0">' in result.messages[0]["content"]
        assert '<message role="assistant" index="1">' in result.messages[1]["content"]
        assert "Hi" in result.messages[0]["content"]
        assert "Hey" in result.messages[1]["content"]

    def test_apply_to_specific_roles(self):
        i = MessageWrapper(
            template="[{role}]: {content}",
            apply_to_roles=["user"],
        )
        ctx = _make_ctx(
            messages=[
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hey"},
            ],
            node_ids=["n0", "n1"],
        )
        result = i.apply(ctx)
        assert result.messages[0]["content"] == "[user]: Hi"
        # Assistant message unchanged
        assert result.messages[1]["content"] == "Hey"

    def test_separator_insertion(self):
        i = MessageWrapper(template="{content}", separator="---")
        ctx = _make_ctx(
            messages=[
                {"role": "user", "content": "A"},
                {"role": "assistant", "content": "B"},
                {"role": "user", "content": "C"},
            ],
            node_ids=["n0", "n1", "n2"],
        )
        result = i.apply(ctx)
        # Separators between messages: content gets separator prepended (except first)
        assert result.messages[0]["content"] == "A"
        assert result.messages[1]["content"] == "---\nB"
        assert result.messages[2]["content"] == "---\nC"

    def test_empty_messages_is_noop(self):
        i = MessageWrapper(template="<msg>{content}</msg>")
        ctx = _make_ctx(messages=[])
        result = i.apply(ctx)
        assert len(result.messages) == 0

    def test_node_ids_unchanged(self):
        i = MessageWrapper(template="<msg>{content}</msg>")
        ctx = _make_ctx()
        original_ids = list(ctx.node_ids)
        result = i.apply(ctx)
        assert result.node_ids == original_ids

    def test_timestamp_variable(self):
        i = MessageWrapper(template="[{timestamp}] {content}")
        ctx = _make_ctx(
            messages=[
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hey"},
            ],
            node_ids=["n0", "n1"],
        )
        ctx.created_ats = ["2026-01-15T14:30:00", "2026-01-15T14:31:00"]
        result = i.apply(ctx)
        assert result.messages[0]["content"] == "[2026-01-15 14:30] Hi"
        assert result.messages[1]["content"] == "[2026-01-15 14:31] Hey"

    def test_timestamp_variable_with_missing_created_at(self):
        i = MessageWrapper(template="[{timestamp}] {content}")
        ctx = _make_ctx(
            messages=[{"role": "user", "content": "Hi"}],
            node_ids=["n0"],
        )
        ctx.created_ats = [None]
        result = i.apply(ctx)
        assert result.messages[0]["content"] == "[] Hi"

    def test_timestamp_variable_with_empty_created_ats(self):
        i = MessageWrapper(template="[{timestamp}] {content}")
        ctx = _make_ctx(
            messages=[{"role": "user", "content": "Hi"}],
            node_ids=["n0"],
        )
        # No created_ats set — should default to empty string
        result = i.apply(ctx)
        assert result.messages[0]["content"] == "[] Hi"

    def test_registered_in_default_registry(self):
        assert default_registry.get("message_wrapper") is MessageWrapper


# ---------------------------------------------------------------------------
# Registry integration tests
# ---------------------------------------------------------------------------


class TestBuiltinRegistration:
    """Tests that all built-in types are registered in the default registry."""

    def test_all_builtin_types_available(self):
        types = default_registry.available_types()
        type_names = {t["type_name"] for t in types}
        assert "system_prompt_reposition" in type_names
        assert "reminder_injection" in type_names
        assert "message_wrapper" in type_names

    def test_create_pipeline_from_config_list(self):
        configs = [
            InterventionConfig(
                type="system_prompt_reposition",
                enabled=True,
                config={"placement": "standalone_preamble"},
            ),
            InterventionConfig(
                type="reminder_injection",
                enabled=True,
                config={"content": "Remember!", "position": "before_last"},
            ),
            InterventionConfig(
                type="message_wrapper",
                enabled=False,  # Disabled
                config={"template": "<msg>{content}</msg>"},
            ),
        ]
        pipeline = default_registry.create_pipeline(configs)
        # Only 2 enabled interventions
        assert len(pipeline._interventions) == 2

    def test_full_pipeline_execution(self):
        """Run all three intervention types in a full pipeline."""
        configs = [
            InterventionConfig(
                type="message_wrapper",
                enabled=True,
                config={"template": "[{role}] {content}"},
            ),
            InterventionConfig(
                type="system_prompt_reposition",
                enabled=True,
                config={"placement": "standalone_preamble"},
            ),
            InterventionConfig(
                type="reminder_injection",
                enabled=True,
                config={"content": "Stay focused!", "position": "before_last"},
            ),
        ]
        pipeline = default_registry.create_pipeline(configs)
        ctx = _make_ctx()

        # Pre-eviction: wrapper + system_prompt_reposition
        ctx = pipeline.run_pre_eviction(ctx)
        assert ctx.system_prompt is None
        # Message wrapper should have formatted messages
        assert "[user]" in ctx.messages[1]["content"] or "[System Instructions]" in ctx.messages[0]["content"]

        # Post-eviction: reminder_injection
        ctx = pipeline.run_post_eviction(ctx)
        reminders = [m for m in ctx.messages if m["content"] == "Stay focused!"]
        assert len(reminders) == 1
