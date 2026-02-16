"""Tests for Phase 3.2: Thinking Tokens.

Covers data model extensions, provider thinking extraction, SSE protocol,
projector round-trip, context builder thinking inclusion, and schema migration.
"""

import json
import math
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from qivis.models import (
    EventEnvelope,
    NodeCreatedPayload,
    SamplingParams,
)
from qivis.providers.base import GenerationResult, StreamChunk


# ---------------------------------------------------------------------------
# Step 1: Data model field existence and defaults
# ---------------------------------------------------------------------------


class TestSamplingParamsThinking:
    def test_extended_thinking_default_false(self):
        sp = SamplingParams()
        assert sp.extended_thinking is False

    def test_thinking_budget_default_none(self):
        sp = SamplingParams()
        assert sp.thinking_budget is None

    def test_extended_thinking_roundtrip(self):
        sp = SamplingParams(extended_thinking=True, thinking_budget=8000)
        data = sp.model_dump()
        restored = SamplingParams.model_validate(data)
        assert restored.extended_thinking is True
        assert restored.thinking_budget == 8000


class TestGenerationResultThinking:
    def test_thinking_content_default_none(self):
        result = GenerationResult(content="hello", model="test")
        assert result.thinking_content is None

    def test_thinking_content_set(self):
        result = GenerationResult(
            content="answer",
            model="test",
            thinking_content="I need to think about this...",
        )
        assert result.thinking_content == "I need to think about this..."

    def test_thinking_content_roundtrip(self):
        result = GenerationResult(
            content="answer", model="test",
            thinking_content="reasoning here",
        )
        data = result.model_dump()
        restored = GenerationResult.model_validate(data)
        assert restored.thinking_content == "reasoning here"


class TestStreamChunkThinking:
    def test_thinking_default_empty(self):
        chunk = StreamChunk(type="text_delta", text="hello")
        assert chunk.thinking == ""

    def test_thinking_delta_chunk(self):
        chunk = StreamChunk(type="thinking_delta", thinking="Let me think...")
        assert chunk.type == "thinking_delta"
        assert chunk.thinking == "Let me think..."
        assert chunk.text == ""


class TestNodeCreatedPayloadThinking:
    def test_thinking_content_default_none(self):
        payload = NodeCreatedPayload(
            node_id="n1", role="assistant", content="hello",
        )
        assert payload.thinking_content is None

    def test_thinking_content_set(self):
        payload = NodeCreatedPayload(
            node_id="n1", role="assistant", content="hello",
            thinking_content="I reasoned about this...",
        )
        assert payload.thinking_content == "I reasoned about this..."


# ---------------------------------------------------------------------------
# Step 2: Projector round-trip
# ---------------------------------------------------------------------------


@pytest.fixture
async def db():
    """In-memory database for testing."""
    from qivis.db.connection import Database
    database = await Database.connect(":memory:")
    yield database
    await database.close()


@pytest.fixture
async def projector(db):
    """State projector backed by in-memory DB."""
    from qivis.events.projector import StateProjector
    return StateProjector(db)


class TestProjectorThinkingContent:
    @pytest.mark.asyncio
    async def test_node_created_with_thinking_content_stores_and_retrieves(
        self, db, projector,
    ):
        """thinking_content should survive the projector round-trip."""
        tree_id = str(uuid4())
        # Create tree first
        from qivis.models import TreeCreatedPayload
        tree_event = EventEnvelope(
            event_id=str(uuid4()), tree_id=tree_id,
            timestamp=datetime.now(UTC), device_id="local",
            event_type="TreeCreated",
            payload=TreeCreatedPayload(title="test").model_dump(),
        )
        await projector.project([tree_event])

        # Create node with thinking_content
        node_id = str(uuid4())
        thinking = "Step 1: Analyze the question. Step 2: Form response."
        payload = NodeCreatedPayload(
            node_id=node_id, role="assistant", content="My response",
            thinking_content=thinking,
        )
        event = EventEnvelope(
            event_id=str(uuid4()), tree_id=tree_id,
            timestamp=datetime.now(UTC), device_id="local",
            event_type="NodeCreated",
            payload=payload.model_dump(),
        )
        await projector.project([event])

        # Read back
        nodes = await projector.get_nodes(tree_id)
        assert len(nodes) == 1
        assert nodes[0]["thinking_content"] == thinking

    @pytest.mark.asyncio
    async def test_node_created_without_thinking_content(self, db, projector):
        """Nodes without thinking_content should have None."""
        tree_id = str(uuid4())
        from qivis.models import TreeCreatedPayload
        tree_event = EventEnvelope(
            event_id=str(uuid4()), tree_id=tree_id,
            timestamp=datetime.now(UTC), device_id="local",
            event_type="TreeCreated",
            payload=TreeCreatedPayload(title="test").model_dump(),
        )
        await projector.project([tree_event])

        node_id = str(uuid4())
        payload = NodeCreatedPayload(
            node_id=node_id, role="user", content="Hello",
        )
        event = EventEnvelope(
            event_id=str(uuid4()), tree_id=tree_id,
            timestamp=datetime.now(UTC), device_id="local",
            event_type="NodeCreated",
            payload=payload.model_dump(),
        )
        await projector.project([event])

        nodes = await projector.get_nodes(tree_id)
        assert nodes[0]["thinking_content"] is None


class TestNodeResponseThinking:
    def test_thinking_content_field_exists(self):
        from qivis.trees.schemas import NodeResponse
        resp = NodeResponse(
            node_id="n1", tree_id="t1", role="assistant",
            content="hi", created_at="2026-02-16T00:00:00",
            thinking_content="thought process",
        )
        assert resp.thinking_content == "thought process"

    def test_thinking_content_default_none(self):
        from qivis.trees.schemas import NodeResponse
        resp = NodeResponse(
            node_id="n1", tree_id="t1", role="assistant",
            content="hi", created_at="2026-02-16T00:00:00",
        )
        assert resp.thinking_content is None


class TestTreeServiceNodeFromRow:
    def test_maps_thinking_content_from_row(self):
        from qivis.trees.service import TreeService
        row = {
            "node_id": "n1", "tree_id": "t1", "parent_id": None,
            "role": "assistant", "content": "response",
            "model": "claude", "provider": "anthropic",
            "system_prompt": None, "sampling_params": None,
            "mode": "chat", "usage": None, "latency_ms": 100,
            "finish_reason": "end_turn", "logprobs": None,
            "context_usage": None, "participant_id": None,
            "participant_name": None, "created_at": "2026-02-16T00:00:00",
            "archived": 0, "thinking_content": "I thought about it",
        }
        node = TreeService._node_from_row(row)
        assert node.thinking_content == "I thought about it"

    def test_maps_null_thinking_content(self):
        from qivis.trees.service import TreeService
        row = {
            "node_id": "n1", "tree_id": "t1", "parent_id": None,
            "role": "user", "content": "hello",
            "model": None, "provider": None,
            "system_prompt": None, "sampling_params": None,
            "mode": "chat", "usage": None, "latency_ms": None,
            "finish_reason": None, "logprobs": None,
            "context_usage": None, "participant_id": None,
            "participant_name": None, "created_at": "2026-02-16T00:00:00",
            "archived": 0, "thinking_content": None,
        }
        node = TreeService._node_from_row(row)
        assert node.thinking_content is None


# ---------------------------------------------------------------------------
# Step 3: Anthropic provider _build_params
# ---------------------------------------------------------------------------


class TestAnthropicBuildParamsThinking:
    def test_thinking_enabled_adds_thinking_param(self):
        from qivis.providers.anthropic import AnthropicProvider
        from qivis.providers.base import GenerationRequest

        sp = SamplingParams(extended_thinking=True, thinking_budget=8000)
        request = GenerationRequest(
            model="claude-sonnet-4-5", messages=[{"role": "user", "content": "hi"}],
            sampling_params=sp,
        )
        params = AnthropicProvider._build_params(request)
        assert "thinking" in params
        assert params["thinking"]["type"] == "enabled"
        assert params["thinking"]["budget_tokens"] == 8000

    def test_thinking_enabled_forces_temperature_1(self):
        from qivis.providers.anthropic import AnthropicProvider
        from qivis.providers.base import GenerationRequest

        sp = SamplingParams(extended_thinking=True, temperature=0.5)
        request = GenerationRequest(
            model="claude-sonnet-4-5", messages=[{"role": "user", "content": "hi"}],
            sampling_params=sp,
        )
        params = AnthropicProvider._build_params(request)
        assert params["temperature"] == 1

    def test_thinking_disabled_no_thinking_param(self):
        from qivis.providers.anthropic import AnthropicProvider
        from qivis.providers.base import GenerationRequest

        sp = SamplingParams(extended_thinking=False)
        request = GenerationRequest(
            model="claude-sonnet-4-5", messages=[{"role": "user", "content": "hi"}],
            sampling_params=sp,
        )
        params = AnthropicProvider._build_params(request)
        assert "thinking" not in params

    def test_thinking_budget_default_when_none(self):
        from qivis.providers.anthropic import AnthropicProvider
        from qivis.providers.base import GenerationRequest

        sp = SamplingParams(extended_thinking=True, thinking_budget=None)
        request = GenerationRequest(
            model="claude-sonnet-4-5", messages=[{"role": "user", "content": "hi"}],
            sampling_params=sp,
        )
        params = AnthropicProvider._build_params(request)
        assert params["thinking"]["budget_tokens"] == 10000

    def test_max_tokens_bumped_when_too_small(self):
        from qivis.providers.anthropic import AnthropicProvider
        from qivis.providers.base import GenerationRequest

        sp = SamplingParams(
            extended_thinking=True, thinking_budget=5000, max_tokens=2048,
        )
        request = GenerationRequest(
            model="claude-sonnet-4-5", messages=[{"role": "user", "content": "hi"}],
            sampling_params=sp,
        )
        params = AnthropicProvider._build_params(request)
        # max_tokens should be bumped to at least budget + 2048
        assert params["max_tokens"] >= 5000 + 2048


class TestAnthropicExtractThinking:
    def test_extracts_thinking_blocks(self):
        from qivis.providers.anthropic import AnthropicProvider

        block1 = MagicMock()
        block1.type = "thinking"
        block1.thinking = "First I consider..."
        block2 = MagicMock()
        block2.type = "text"
        block2.text = "Here is my answer"

        response = MagicMock()
        response.content = [block1, block2]

        thinking = AnthropicProvider._extract_thinking(response)
        assert thinking == "First I consider..."

    def test_returns_none_when_no_thinking_blocks(self):
        from qivis.providers.anthropic import AnthropicProvider

        block = MagicMock()
        block.type = "text"
        block.text = "Just text"

        response = MagicMock()
        response.content = [block]

        thinking = AnthropicProvider._extract_thinking(response)
        assert thinking is None

    def test_joins_multiple_thinking_blocks(self):
        from qivis.providers.anthropic import AnthropicProvider

        block1 = MagicMock()
        block1.type = "thinking"
        block1.thinking = "Part one."
        block2 = MagicMock()
        block2.type = "thinking"
        block2.thinking = "Part two."
        block3 = MagicMock()
        block3.type = "text"
        block3.text = "Answer"

        response = MagicMock()
        response.content = [block1, block2, block3]

        thinking = AnthropicProvider._extract_thinking(response)
        assert "Part one." in thinking
        assert "Part two." in thinking


# ---------------------------------------------------------------------------
# Step 4: OpenAI reasoning tokens
# ---------------------------------------------------------------------------


class TestOpenAIReasoningTokens:
    def test_reasoning_tokens_extracted_from_usage(self):
        """When completion_tokens_details has reasoning_tokens, include in usage dict."""
        from qivis.providers.openai_compat import OpenAICompatibleProvider

        details = MagicMock(spec=["reasoning_tokens"])
        details.reasoning_tokens = 150

        usage = MagicMock(spec=["prompt_tokens", "completion_tokens", "completion_tokens_details"])
        usage.prompt_tokens = 100
        usage.completion_tokens = 200
        usage.completion_tokens_details = details

        result = OpenAICompatibleProvider._extract_reasoning_tokens(usage)
        assert result == 150

    def test_reasoning_tokens_none_when_no_details(self):
        """When completion_tokens_details is absent, reasoning_tokens stays None."""
        from qivis.providers.openai_compat import OpenAICompatibleProvider

        usage = MagicMock(spec=["prompt_tokens", "completion_tokens"])
        usage.prompt_tokens = 100
        usage.completion_tokens = 200

        result = OpenAICompatibleProvider._extract_reasoning_tokens(usage)
        assert result is None

    def test_reasoning_tokens_none_when_details_none(self):
        """When completion_tokens_details is None, reasoning_tokens stays None."""
        from qivis.providers.openai_compat import OpenAICompatibleProvider

        usage = MagicMock(spec=["prompt_tokens", "completion_tokens", "completion_tokens_details"])
        usage.completion_tokens_details = None

        result = OpenAICompatibleProvider._extract_reasoning_tokens(usage)
        assert result is None


# ---------------------------------------------------------------------------
# Step 5: SSE protocol
# ---------------------------------------------------------------------------


class TestSSEThinkingEvents:
    def test_thinking_delta_event_format(self):
        """thinking_delta SSE event should have correct format."""
        thinking_text = "Let me reason about this..."
        data = {"type": "thinking_delta", "thinking": thinking_text}
        line = f"event: thinking_delta\ndata: {json.dumps(data)}\n\n"
        assert "event: thinking_delta" in line
        parsed = json.loads(line.split("data: ")[1].strip())
        assert parsed["thinking"] == thinking_text

    def test_message_stop_includes_thinking_content(self):
        """message_stop SSE event should include thinking_content field."""
        data = {
            "type": "message_stop",
            "content": "response text",
            "thinking_content": "full reasoning trace",
            "finish_reason": "end_turn",
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "latency_ms": 1500,
            "node_id": "n1",
        }
        line = f"event: message_stop\ndata: {json.dumps(data)}\n\n"
        parsed = json.loads(line.split("data: ")[1].strip())
        assert parsed["thinking_content"] == "full reasoning trace"


# ---------------------------------------------------------------------------
# Step 6: Context builder include_thinking
# ---------------------------------------------------------------------------


class TestContextBuilderThinking:
    def _make_nodes(self, thinking_content=None):
        """Helper to create a minimal node set for context builder tests."""
        return [
            {
                "node_id": "n1", "parent_id": None, "role": "user",
                "content": "What's 2+2?", "created_at": "2026-02-16T00:00:00",
                "thinking_content": None,
            },
            {
                "node_id": "n2", "parent_id": "n1", "role": "assistant",
                "content": "4", "created_at": "2026-02-16T00:01:00",
                "thinking_content": thinking_content,
            },
            {
                "node_id": "n3", "parent_id": "n2", "role": "user",
                "content": "Thanks!", "created_at": "2026-02-16T00:02:00",
                "thinking_content": None,
            },
        ]

    def test_include_thinking_false_no_prepend(self):
        from qivis.generation.context import ContextBuilder
        builder = ContextBuilder()
        nodes = self._make_nodes(thinking_content="I need to add 2+2")

        messages, usage, report = builder.build(
            nodes=nodes, target_node_id="n3",
            system_prompt=None, model_context_limit=200000,
            include_thinking=False,
        )

        # Assistant message should not contain thinking
        assistant_msg = next(m for m in messages if m["role"] == "assistant")
        assert "[Model thinking:" not in assistant_msg["content"]
        assert assistant_msg["content"] == "4"

    def test_include_thinking_true_prepends(self):
        from qivis.generation.context import ContextBuilder
        builder = ContextBuilder()
        nodes = self._make_nodes(thinking_content="I need to add 2+2")

        messages, usage, report = builder.build(
            nodes=nodes, target_node_id="n3",
            system_prompt=None, model_context_limit=200000,
            include_thinking=True,
        )

        assistant_msg = next(m for m in messages if m["role"] == "assistant")
        assert assistant_msg["content"].startswith("[Model thinking: I need to add 2+2]")
        assert "\n\n4" in assistant_msg["content"]

    def test_include_thinking_true_skips_nodes_without_thinking(self):
        from qivis.generation.context import ContextBuilder
        builder = ContextBuilder()
        nodes = self._make_nodes(thinking_content=None)

        messages, usage, report = builder.build(
            nodes=nodes, target_node_id="n3",
            system_prompt=None, model_context_limit=200000,
            include_thinking=True,
        )

        assistant_msg = next(m for m in messages if m["role"] == "assistant")
        assert "[Model thinking:" not in assistant_msg["content"]
        assert assistant_msg["content"] == "4"

    def test_include_thinking_true_counts_thinking_tokens(self):
        from qivis.generation.context import ContextBuilder
        builder = ContextBuilder()
        thinking = "A" * 400  # 100 tokens at len//4
        nodes = self._make_nodes(thinking_content=thinking)

        messages_without, usage_without, _ = builder.build(
            nodes=nodes, target_node_id="n3",
            system_prompt=None, model_context_limit=200000,
            include_thinking=False,
        )
        messages_with, usage_with, _ = builder.build(
            nodes=nodes, target_node_id="n3",
            system_prompt=None, model_context_limit=200000,
            include_thinking=True,
        )

        # With thinking should use more tokens than without
        assert usage_with.total_tokens > usage_without.total_tokens


# ---------------------------------------------------------------------------
# Schema migration
# ---------------------------------------------------------------------------


class TestSchemaMigration:
    @pytest.mark.asyncio
    async def test_migration_is_idempotent(self, db):
        """Running migration twice should not error (column already exists)."""
        from qivis.db.schema import run_migrations
        # First call happens during Database.connect (via _ensure_schema)
        # Second call should be safe
        await run_migrations(db)
        await run_migrations(db)

    @pytest.mark.asyncio
    async def test_thinking_content_column_exists(self, db):
        """The thinking_content column should exist after migration."""
        # Create tree first (FK constraint)
        await db.execute(
            "INSERT INTO trees (tree_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("test_t1", "test", "2026-02-16T00:00:00", "2026-02-16T00:00:00"),
        )
        await db.execute(
            "INSERT INTO nodes (node_id, tree_id, role, content, created_at, thinking_content) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("test_n1", "test_t1", "assistant", "hi", "2026-02-16T00:00:00", "thinking text"),
        )
        row = await db.fetchone("SELECT thinking_content FROM nodes WHERE node_id = ?", ("test_n1",))
        assert row is not None
        assert row["thinking_content"] == "thinking text"
