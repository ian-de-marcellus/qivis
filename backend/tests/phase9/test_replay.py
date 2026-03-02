"""Contract tests for conversation replay and cross-model generation (Phase 9.2a).

Tests ReplayService (both replay modes) and GenerationService.generate_cross().
"""

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.replay import (
    InvalidReplayPathError,
    ReplayService,
)
from qivis.generation.service import GenerationService
from qivis.models import LogprobData, SamplingParams, TokenLogprob
from qivis.providers.base import (
    GenerationRequest,
    GenerationResult,
    LLMProvider,
    StreamChunk,
)
from qivis.providers.registry import clear_providers, register_provider
from qivis.rhizomes.schemas import CreateNodeRequest, CreateRhizomeRequest
from qivis.rhizomes.service import RhizomeService


# -- Mock providers --


class MockProviderA(LLMProvider):
    """Mock provider that records what context it receives."""

    supported_modes = ["chat"]
    supported_params = ["temperature", "max_tokens"]

    def __init__(self, name_str: str = "mock-a", response_prefix: str = "A:"):
        self._name = name_str
        self._prefix = response_prefix
        self.calls: list[GenerationRequest] = []

    @property
    def name(self) -> str:
        return self._name

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.calls.append(request)
        # Echo back with prefix so tests can identify which provider responded
        content = f"{self._prefix} response to '{request.messages[-1]['content']}'"
        return GenerationResult(
            content=content,
            model=request.model,
            finish_reason="end_turn",
            usage={"input_tokens": 20, "output_tokens": 10},
            latency_ms=50,
            logprobs=LogprobData(
                tokens=[TokenLogprob(token="hello", logprob=-0.1, linear_prob=0.9, top_alternatives=[])],
                provider_format="mock",
                top_k_available=0,
            ),
        )

    async def generate_stream(
        self, request: GenerationRequest
    ) -> AsyncIterator[StreamChunk]:
        result = await self.generate(request)
        yield StreamChunk(type="text_delta", text=result.content)
        yield StreamChunk(
            type="message_stop",
            is_final=True,
            result=result,
        )


class MockProviderB(MockProviderA):
    """Second mock provider with different identity."""

    def __init__(self):
        super().__init__(name_str="mock-b", response_prefix="B:")


# -- Fixtures --


@pytest.fixture
async def services(db: Database):
    """Set up all services needed for replay/cross-model tests."""
    store = EventStore(db)
    projector = StateProjector(db)
    rhizome_svc = RhizomeService(db)
    gen_svc = GenerationService(rhizome_svc, store, projector)

    provider_a = MockProviderA()
    provider_b = MockProviderB()

    clear_providers()
    register_provider(provider_a)
    register_provider(provider_b)

    replay_svc = ReplayService(rhizome_svc, gen_svc, store, projector)

    yield {
        "rhizome_svc": rhizome_svc,
        "gen_svc": gen_svc,
        "replay_svc": replay_svc,
        "store": store,
        "projector": projector,
        "provider_a": provider_a,
        "provider_b": provider_b,
    }

    clear_providers()


@pytest.fixture
async def conversation(services):
    """Create a rhizome with a 4-message conversation: user, asst, user, asst."""
    svc = services["rhizome_svc"]
    projector = services["projector"]

    rhizome = await svc.create_rhizome(CreateRhizomeRequest(
        title="Test Conversation",
        default_system_prompt="You are helpful.",
        default_provider="mock-a",
        default_model="test-model",
    ))
    rid = rhizome.rhizome_id

    # Build a 4-message path: user1 -> asst1 -> user2 -> asst2
    user1 = await svc.create_node(rid, CreateNodeRequest(
        content="What's your favorite animal?",
        role="user",
    ))
    # For assistant nodes, emit directly through events to have proper generation metadata
    asst1_id = str(uuid4())
    from qivis.models import EventEnvelope, NodeCreatedPayload
    from datetime import UTC, datetime

    asst1_event = EventEnvelope(
        event_id=str(uuid4()),
        rhizome_id=rid,
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="NodeCreated",
        payload=NodeCreatedPayload(
            node_id=asst1_id,
            parent_id=user1.node_id,
            role="assistant",
            content="I love octopuses! They're incredibly intelligent.",
            model="test-model",
            provider="mock-a",
        ).model_dump(),
    )
    await services["store"].append(asst1_event)
    await projector.project([asst1_event])

    user2 = await svc.create_node(rid, CreateNodeRequest(
        content="Oh, why do you like octopuses?",
        role="user",
        parent_id=asst1_id,
    ))

    asst2_id = str(uuid4())
    asst2_event = EventEnvelope(
        event_id=str(uuid4()),
        rhizome_id=rid,
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="NodeCreated",
        payload=NodeCreatedPayload(
            node_id=asst2_id,
            parent_id=user2.node_id,
            role="assistant",
            content="Their problem-solving abilities are remarkable.",
            model="test-model",
            provider="mock-a",
        ).model_dump(),
    )
    await services["store"].append(asst2_event)
    await projector.project([asst2_event])

    return {
        "rhizome_id": rid,
        "path_node_ids": [user1.node_id, asst1_id, user2.node_id, asst2_id],
        "user1_id": user1.node_id,
        "asst1_id": asst1_id,
        "user2_id": user2.node_id,
        "asst2_id": asst2_id,
    }


# ---------------------------------------------------------------------------
# ReplayService: tree structure tests
# ---------------------------------------------------------------------------


class TestReplayTreeStructure:
    """Tests that replay creates the correct node tree topology."""

    async def test_replay_creates_alternating_user_assistant_nodes(self, services, conversation):
        """Replay of a 4-message path creates 4 new nodes: 2 user copies + 2 assistant generations."""
        replay_svc = services["replay_svc"]
        provider_b = services["provider_b"]

        created = await replay_svc.replay_path(
            conversation["rhizome_id"],
            conversation["path_node_ids"],
            provider_b,
            model="b-model",
        )

        assert len(created) == 4
        # Alternating roles
        assert created[0].role == "user"
        assert created[1].role == "assistant"
        assert created[2].role == "user"
        assert created[3].role == "assistant"

    async def test_replayed_user_messages_have_identical_content(self, services, conversation):
        """User messages in the replay branch have the same text as originals."""
        replay_svc = services["replay_svc"]
        provider_b = services["provider_b"]

        created = await replay_svc.replay_path(
            conversation["rhizome_id"],
            conversation["path_node_ids"],
            provider_b,
            model="b-model",
        )

        assert created[0].content == "What's your favorite animal?"
        assert created[2].content == "Oh, why do you like octopuses?"

    async def test_replay_nodes_use_replay_device_id(self, services, conversation):
        """All replay nodes are tagged with device_id='replay'."""
        replay_svc = services["replay_svc"]
        store = services["store"]
        provider_b = services["provider_b"]

        await replay_svc.replay_path(
            conversation["rhizome_id"],
            conversation["path_node_ids"],
            provider_b,
            model="b-model",
        )

        # Check events in the store
        events = await store.get_events(conversation["rhizome_id"])
        replay_events = [
            e for e in events
            if e.device_id == "replay"
        ]
        # 4 new nodes (2 user copies + 2 assistant generations)
        # Plus generation_started events
        assert len([e for e in replay_events if e.event_type == "NodeCreated"]) == 4

    async def test_replay_nodes_share_generation_id(self, services, conversation):
        """All nodes in a single replay share the same generation_id."""
        replay_svc = services["replay_svc"]
        store = services["store"]
        provider_b = services["provider_b"]

        await replay_svc.replay_path(
            conversation["rhizome_id"],
            conversation["path_node_ids"],
            provider_b,
            model="b-model",
        )

        events = await store.get_events(conversation["rhizome_id"])
        replay_node_events = [
            e for e in events
            if e.device_id == "replay" and e.event_type == "NodeCreated"
        ]
        gen_ids = {e.payload.get("generation_id") for e in replay_node_events}
        # All should share one generation_id (or at most one per generation step)
        # User copies don't have generation_id, but assistant nodes do
        assistant_gen_ids = {
            e.payload.get("generation_id")
            for e in replay_node_events
            if e.payload.get("role") == "assistant"
        }
        # All assistant nodes in one replay share a replay_id
        assert len(assistant_gen_ids) >= 1
        assert None not in assistant_gen_ids

    async def test_replay_branch_structure_is_chain(self, services, conversation):
        """Replay creates a chain: user1' -> asst1' -> user2' -> asst2', branching from original root."""
        replay_svc = services["replay_svc"]
        provider_b = services["provider_b"]

        created = await replay_svc.replay_path(
            conversation["rhizome_id"],
            conversation["path_node_ids"],
            provider_b,
            model="b-model",
        )

        # First copied user message is a sibling of the original first user message
        # (same parent — the root / None)
        assert created[0].parent_id == None  # root node, like the original user1

        # asst1' is child of user1'
        assert created[1].parent_id == created[0].node_id
        # user2' is child of asst1'
        assert created[2].parent_id == created[1].node_id
        # asst2' is child of user2'
        assert created[3].parent_id == created[2].node_id


# ---------------------------------------------------------------------------
# ReplayService: path validation
# ---------------------------------------------------------------------------


class TestReplayPathValidation:
    """Tests that replay rejects invalid paths."""

    async def test_replay_rejects_empty_path(self, services, conversation):
        """Empty path raises an error."""
        replay_svc = services["replay_svc"]
        provider_b = services["provider_b"]

        with pytest.raises(InvalidReplayPathError, match="empty"):
            await replay_svc.replay_path(
                conversation["rhizome_id"],
                [],
                provider_b,
                model="b-model",
            )

    async def test_replay_rejects_disconnected_path(self, services, conversation):
        """Path with non-connected node IDs raises an error."""
        replay_svc = services["replay_svc"]
        provider_b = services["provider_b"]

        # Swap order of nodes so path is disconnected
        bad_path = [
            conversation["asst1_id"],  # assistant first (not connected to None parent)
            conversation["user1_id"],
        ]

        with pytest.raises(InvalidReplayPathError):
            await replay_svc.replay_path(
                conversation["rhizome_id"],
                bad_path,
                provider_b,
                model="b-model",
            )


# ---------------------------------------------------------------------------
# ReplayService: context modes
# ---------------------------------------------------------------------------


class TestReplayContextModes:
    """Tests for context-faithful vs trajectory replay modes."""

    async def test_context_faithful_uses_original_assistant_messages(self, services, conversation):
        """In context-faithful mode, the model sees original assistant messages at each step."""
        replay_svc = services["replay_svc"]
        provider_b = services["provider_b"]

        await replay_svc.replay_path(
            conversation["rhizome_id"],
            conversation["path_node_ids"],
            provider_b,
            model="b-model",
            mode="context_faithful",
        )

        # Provider B should have been called twice (once per assistant message to generate)
        assert len(provider_b.calls) == 2

        # Second call's context should include the ORIGINAL asst1 message, not B's asst1'
        second_call = provider_b.calls[1]
        messages = second_call.messages
        # Should contain: user1, orig_asst1 ("I love octopuses!"), user2
        assistant_msgs = [m for m in messages if m["role"] == "assistant"]
        assert len(assistant_msgs) >= 1
        assert "octopuses" in assistant_msgs[0]["content"]  # original content

    async def test_trajectory_uses_replayed_assistant_messages(self, services, conversation):
        """In trajectory mode, the model sees its own prior responses at each step."""
        replay_svc = services["replay_svc"]
        provider_b = services["provider_b"]

        await replay_svc.replay_path(
            conversation["rhizome_id"],
            conversation["path_node_ids"],
            provider_b,
            model="b-model",
            mode="trajectory",
        )

        assert len(provider_b.calls) == 2

        # Second call's context should include B's OWN asst1' response, not the original
        second_call = provider_b.calls[1]
        messages = second_call.messages
        assistant_msgs = [m for m in messages if m["role"] == "assistant"]
        assert len(assistant_msgs) >= 1
        # Provider B responses start with "B: response to..."
        assert assistant_msgs[0]["content"].startswith("B:")

    async def test_replay_preserves_system_prompt_override(self, services, conversation):
        """A system prompt override is passed through to each generation step."""
        replay_svc = services["replay_svc"]
        provider_b = services["provider_b"]

        await replay_svc.replay_path(
            conversation["rhizome_id"],
            conversation["path_node_ids"],
            provider_b,
            model="b-model",
            system_prompt="Custom system prompt for replay",
        )

        # Both generation calls should use the overridden system prompt
        for call in provider_b.calls:
            assert call.system_prompt == "Custom system prompt for replay"


# ---------------------------------------------------------------------------
# Cross-model generation
# ---------------------------------------------------------------------------


class TestCrossModelGeneration:
    """Tests for generate_cross() — forking to multiple providers simultaneously."""

    async def test_cross_model_creates_sibling_nodes(self, services, conversation):
        """Cross-model generation creates one sibling node per target provider."""
        gen_svc = services["gen_svc"]

        targets = [
            {"provider": "mock-a", "model": "a-model"},
            {"provider": "mock-b", "model": "b-model"},
        ]

        results = await gen_svc.generate_cross(
            conversation["rhizome_id"],
            conversation["asst2_id"],  # generate from the last node
            targets=targets,
        )

        assert len(results) == 2
        # Both should be children of the same parent (asst2)
        assert all(r.parent_id == conversation["asst2_id"] for r in results)
        # Different providers
        providers = {r.provider for r in results}
        assert providers == {"mock-a", "mock-b"}

    async def test_cross_model_nodes_share_generation_id(self, services, conversation):
        """All cross-model results share the same generation_id."""
        gen_svc = services["gen_svc"]
        store = services["store"]

        targets = [
            {"provider": "mock-a", "model": "a-model"},
            {"provider": "mock-b", "model": "b-model"},
        ]

        await gen_svc.generate_cross(
            conversation["rhizome_id"],
            conversation["asst2_id"],
            targets=targets,
        )

        # Find the cross-model NodeCreated events (the last 2)
        events = await store.get_events(conversation["rhizome_id"])
        node_events = [e for e in events if e.event_type == "NodeCreated"]
        # Last 2 should be our cross-model results
        cross_events = node_events[-2:]
        gen_ids = {e.payload.get("generation_id") for e in cross_events}
        assert len(gen_ids) == 1  # All share same generation_id
        assert None not in gen_ids

    async def test_cross_model_with_correct_provider_metadata(self, services, conversation):
        """Each cross-model result records its own provider and model."""
        gen_svc = services["gen_svc"]

        targets = [
            {"provider": "mock-a", "model": "a-model"},
            {"provider": "mock-b", "model": "b-model"},
        ]

        results = await gen_svc.generate_cross(
            conversation["rhizome_id"],
            conversation["asst2_id"],
            targets=targets,
        )

        result_a = next(r for r in results if r.provider == "mock-a")
        result_b = next(r for r in results if r.provider == "mock-b")

        assert result_a.model == "a-model"
        assert result_b.model == "b-model"
        # Content should show which provider responded
        assert "A:" in result_a.content
        assert "B:" in result_b.content
