"""Contract tests for Pydantic models.

Verifies that data structures and event payloads match the architecture spec,
serialize/deserialize correctly, and the EVENT_TYPES registry is complete.
"""

from datetime import UTC, datetime

from qivis.models import (
    EVENT_TYPES,
    AlternativeToken,
    AnnotationAddedPayload,
    AnnotationRemovedPayload,
    BookmarkCreatedPayload,
    BookmarkRemovedPayload,
    BookmarkSummaryGeneratedPayload,
    ContextUsage,
    DigressionGroupCreatedPayload,
    DigressionGroupToggledPayload,
    EventEnvelope,
    EvictionReport,
    EvictionStrategy,
    GarbageCollectedPayload,
    GarbagePurgedPayload,
    GenerationStartedPayload,
    LogprobData,
    NodeArchivedPayload,
    NodeContextExcludedPayload,
    NodeContextIncludedPayload,
    NodeCreatedPayload,
    NodeUnarchivedPayload,
    Participant,
    SamplingParams,
    SummaryGeneratedPayload,
    TokenLogprob,
    TreeArchivedPayload,
    TreeCreatedPayload,
    TreeMetadataUpdatedPayload,
    TreeUnarchivedPayload,
)

# -- Canonical data structures --


class TestSamplingParams:
    def test_defaults(self):
        p = SamplingParams()
        assert p.max_tokens == 2048
        assert p.logprobs is True
        assert p.top_logprobs == 5
        assert p.temperature is None

    def test_roundtrip(self):
        p = SamplingParams(temperature=0.7, top_k=40)
        data = p.model_dump()
        p2 = SamplingParams.model_validate(data)
        assert p2.temperature == 0.7
        assert p2.top_k == 40


class TestLogprobData:
    def test_nested_structure(self):
        alt = AlternativeToken(token="world", logprob=-1.5, linear_prob=0.22)
        tok = TokenLogprob(
            token="hello", logprob=-0.1, linear_prob=0.90,
            top_alternatives=[alt],
        )
        data = LogprobData(
            tokens=[tok], provider_format="openai",
            top_k_available=5,
        )
        assert data.tokens[0].top_alternatives[0].token == "world"
        assert data.full_vocab_available is False

    def test_roundtrip(self):
        data = LogprobData(
            tokens=[], provider_format="anthropic",
            top_k_available=0, full_vocab_available=True,
        )
        dumped = data.model_dump()
        restored = LogprobData.model_validate(dumped)
        assert restored.full_vocab_available is True


class TestContextUsage:
    def test_structure(self):
        cu = ContextUsage(
            total_tokens=1000, max_tokens=200000,
            breakdown={"system": 100, "user": 400, "assistant": 500},
            excluded_tokens=50, excluded_count=2,
        )
        dumped = cu.model_dump()
        restored = ContextUsage.model_validate(dumped)
        assert restored.total_tokens == 1000
        assert restored.breakdown["user"] == 400


class TestEvictionStrategy:
    def test_defaults(self):
        es = EvictionStrategy()
        assert es.mode == "smart"
        assert es.recent_turns_to_keep == 4
        assert es.keep_first_turns == 2
        assert es.warn_threshold == 0.85


class TestEvictionReport:
    def test_defaults(self):
        er = EvictionReport()
        assert er.eviction_applied is False
        assert er.evicted_node_ids == []
        assert er.warning is None


class TestParticipant:
    def test_with_nested_sampling_params(self):
        p = Participant(
            participant_id="p1", display_name="Claude",
            model="claude-sonnet-4-5-20250929", provider="anthropic",
            system_prompt="You are Claude.",
            sampling_params=SamplingParams(temperature=0.5),
        )
        dumped = p.model_dump()
        restored = Participant.model_validate(dumped)
        assert restored.sampling_params.temperature == 0.5
        assert restored.context_window_strategy == "full"


# -- Event payloads --


class TestTreeCreatedPayload:
    def test_minimal(self):
        p = TreeCreatedPayload()
        assert p.title is None
        assert p.conversation_mode == "single"
        assert p.metadata == {}

    def test_full(self):
        p = TreeCreatedPayload(
            title="My Tree",
            default_model="claude-sonnet-4-5-20250929",
            default_provider="anthropic",
            default_system_prompt="Be helpful.",
            default_sampling_params=SamplingParams(temperature=0.5),
            metadata={"tag": "test"},
            conversation_mode="multi_agent",
        )
        dumped = p.model_dump()
        restored = TreeCreatedPayload.model_validate(dumped)
        assert restored.title == "My Tree"
        assert restored.default_sampling_params is not None
        assert restored.default_sampling_params.temperature == 0.5


class TestNodeCreatedPayload:
    def test_user_message(self):
        p = NodeCreatedPayload(node_id="n1", role="user", content="Hello")
        assert p.model is None
        assert p.logprobs is None
        assert p.generation_id is None

    def test_assistant_message(self):
        p = NodeCreatedPayload(
            node_id="n2", role="assistant", content="Hi there!",
            generation_id="g1", model="claude-sonnet-4-5-20250929",
            provider="anthropic", mode="chat",
            usage={"input_tokens": 10, "output_tokens": 5},
            latency_ms=200, finish_reason="end_turn",
        )
        assert p.model == "claude-sonnet-4-5-20250929"
        assert p.usage is not None
        assert p.usage["output_tokens"] == 5


# -- EventEnvelope --


class TestEventEnvelope:
    def test_typed_payload_tree_created(self):
        payload = TreeCreatedPayload(title="Test").model_dump()
        env = EventEnvelope(
            event_id="e1", tree_id="t1",
            timestamp=datetime(2026, 2, 15, tzinfo=UTC),
            device_id="local", event_type="TreeCreated",
            payload=payload,
        )
        typed = env.typed_payload()
        assert isinstance(typed, TreeCreatedPayload)
        assert typed.title == "Test"

    def test_typed_payload_unknown_type_raises(self):
        env = EventEnvelope(
            event_id="e1", tree_id="t1",
            timestamp=datetime(2026, 2, 15, tzinfo=UTC),
            device_id="local", event_type="NonexistentEvent",
            payload={},
        )
        try:
            env.typed_payload()
            assert False, "Should have raised KeyError"
        except KeyError:
            pass


# -- EVENT_TYPES registry --


class TestEventTypesRegistry:
    def test_all_event_types_registered(self):
        """Every payload class defined in the module should be in EVENT_TYPES."""
        expected_types = {
            "TreeCreated", "TreeMetadataUpdated", "TreeArchived", "TreeUnarchived",
            "GenerationStarted", "NodeCreated", "NodeContentEdited",
            "NodeArchived", "NodeUnarchived",
            "AnnotationAdded", "AnnotationRemoved",
            "BookmarkCreated", "BookmarkRemoved", "BookmarkSummaryGenerated",
            "NoteAdded", "NoteRemoved",
            "NodeContextExcluded", "NodeContextIncluded",
            "DigressionGroupCreated", "DigressionGroupToggled",
            "SummaryGenerated", "GarbageCollected", "GarbagePurged",
        }
        assert set(EVENT_TYPES.keys()) == expected_types

    def test_registry_maps_to_correct_classes(self):
        assert EVENT_TYPES["TreeCreated"] is TreeCreatedPayload
        assert EVENT_TYPES["NodeCreated"] is NodeCreatedPayload
        assert EVENT_TYPES["GenerationStarted"] is GenerationStartedPayload
        assert EVENT_TYPES["TreeMetadataUpdated"] is TreeMetadataUpdatedPayload
        assert EVENT_TYPES["TreeArchived"] is TreeArchivedPayload
        assert EVENT_TYPES["TreeUnarchived"] is TreeUnarchivedPayload
        assert EVENT_TYPES["NodeArchived"] is NodeArchivedPayload
        assert EVENT_TYPES["NodeUnarchived"] is NodeUnarchivedPayload
        assert EVENT_TYPES["AnnotationAdded"] is AnnotationAddedPayload
        assert EVENT_TYPES["AnnotationRemoved"] is AnnotationRemovedPayload
        assert EVENT_TYPES["BookmarkCreated"] is BookmarkCreatedPayload
        assert EVENT_TYPES["BookmarkRemoved"] is BookmarkRemovedPayload
        assert EVENT_TYPES["BookmarkSummaryGenerated"] is BookmarkSummaryGeneratedPayload
        assert EVENT_TYPES["NodeContextExcluded"] is NodeContextExcludedPayload
        assert EVENT_TYPES["NodeContextIncluded"] is NodeContextIncludedPayload
        assert EVENT_TYPES["DigressionGroupCreated"] is DigressionGroupCreatedPayload
        assert EVENT_TYPES["DigressionGroupToggled"] is DigressionGroupToggledPayload
        assert EVENT_TYPES["SummaryGenerated"] is SummaryGeneratedPayload
        assert EVENT_TYPES["GarbageCollected"] is GarbageCollectedPayload
        assert EVENT_TYPES["GarbagePurged"] is GarbagePurgedPayload
