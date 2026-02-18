"""Canonical data structures and event types for Qivis.

Defined once here, referenced everywhere else. Data structures match the
architecture doc specifications. Event payloads represent the type-specific
content of each event; the EventEnvelope wraps them with metadata.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Canonical data structures
# ---------------------------------------------------------------------------


class SamplingParams(BaseModel):
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    max_tokens: int = 2048
    stop_sequences: list[str] | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    logprobs: bool = True
    top_logprobs: int | None = 5
    extended_thinking: bool = False
    thinking_budget: int | None = None


class AlternativeToken(BaseModel):
    token: str
    logprob: float
    linear_prob: float


class TokenLogprob(BaseModel):
    token: str
    logprob: float  # ALWAYS natural log (base e)
    linear_prob: float  # exp(logprob), precomputed for UI
    top_alternatives: list[AlternativeToken]


class LogprobData(BaseModel):
    tokens: list[TokenLogprob]
    provider_format: str  # "openai", "llamacpp", "anthropic"
    top_k_available: int
    full_vocab_available: bool = False


class ContextUsage(BaseModel):
    total_tokens: int
    max_tokens: int
    breakdown: dict[str, int]  # by role: system, user, assistant, tool
    excluded_tokens: int
    excluded_count: int
    excluded_node_ids: list[str] = Field(default_factory=list)
    evicted_node_ids: list[str] = Field(default_factory=list)


class EvictionStrategy(BaseModel):
    mode: str = "smart"  # "smart" | "truncate" | "none"
    recent_turns_to_keep: int = 4
    keep_first_turns: int = 2
    keep_anchored: bool = True
    summarize_evicted: bool = True
    summary_model: str = "claude-haiku-4-5-20251001"
    warn_threshold: float = 0.85


class EvictionReport(BaseModel):
    eviction_applied: bool = False
    evicted_node_ids: list[str] = Field(default_factory=list)
    tokens_freed: int = 0
    summary_inserted: bool = False
    summary_needed: bool = False
    evicted_content: list[str] = Field(default_factory=list)
    final_token_count: int = 0
    warning: str | None = None


class Participant(BaseModel):
    participant_id: str
    display_name: str
    model: str
    provider: str
    system_prompt: str
    sampling_params: SamplingParams = Field(default_factory=SamplingParams)
    context_window_strategy: str = "full"  # "full", "sliding_window", "summary"
    max_context_tokens: int | None = None


# ---------------------------------------------------------------------------
# Event payloads — one per event type
# ---------------------------------------------------------------------------


class TreeCreatedPayload(BaseModel):
    title: str | None = None
    default_system_prompt: str | None = None
    default_model: str | None = None
    default_provider: str | None = None
    default_sampling_params: SamplingParams | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    conversation_mode: Literal["single", "multi_agent"] = "single"
    participants: list[Participant] | None = None


class TreeMetadataUpdatedPayload(BaseModel):
    field: str
    old_value: Any = None
    new_value: Any = None


class TreeArchivedPayload(BaseModel):
    reason: str | None = None


class TreeUnarchivedPayload(BaseModel):
    pass


class GenerationStartedPayload(BaseModel):
    generation_id: str
    parent_node_id: str
    model: str
    provider: str
    system_prompt: str | None = None
    sampling_params: SamplingParams = Field(default_factory=SamplingParams)
    mode: Literal["chat", "completion"] = "chat"
    n: int = 1
    participant_id: str | None = None


class NodeCreatedPayload(BaseModel):
    node_id: str
    generation_id: str | None = None
    parent_id: str | None = None
    role: Literal["system", "user", "assistant", "tool", "researcher_note"]
    content: str

    # Generation metadata (null for user/note messages)
    model: str | None = None
    provider: str | None = None
    system_prompt: str | None = None
    sampling_params: SamplingParams | None = None
    mode: Literal["chat", "completion", "manual"] = "chat"
    prompt_text: str | None = None

    # Response metadata
    usage: dict[str, int] | None = None  # {input_tokens, output_tokens}
    latency_ms: int | None = None
    finish_reason: str | None = None
    logprobs: LogprobData | None = None
    context_usage: ContextUsage | None = None

    # Thinking / reasoning
    thinking_content: str | None = None

    # Context flags — snapshot of tree-level settings at generation time
    include_thinking_in_context: bool = False
    include_timestamps: bool = False

    # Multi-agent identity
    participant_id: str | None = None
    participant_name: str | None = None
    visible_to: list[str] | None = None

    raw_response: dict[str, Any] | None = None


class NodeAnchoredPayload(BaseModel):
    node_id: str


class NodeUnanchoredPayload(BaseModel):
    node_id: str


class NodeArchivedPayload(BaseModel):
    node_id: str
    reason: str | None = None


class NodeUnarchivedPayload(BaseModel):
    node_id: str


class AnnotationAddedPayload(BaseModel):
    annotation_id: str
    node_id: str
    tag: str
    value: Any = None
    notes: str | None = None


class AnnotationRemovedPayload(BaseModel):
    annotation_id: str
    reason: str | None = None


class BookmarkCreatedPayload(BaseModel):
    bookmark_id: str
    node_id: str
    label: str
    notes: str | None = None


class BookmarkRemovedPayload(BaseModel):
    bookmark_id: str


class BookmarkSummaryGeneratedPayload(BaseModel):
    bookmark_id: str
    summary: str
    model: str
    summarized_node_ids: list[str]


class NodeContextExcludedPayload(BaseModel):
    node_id: str
    scope_node_id: str  # leaf of active path at exclusion time
    reason: str | None = None


class NodeContextIncludedPayload(BaseModel):
    node_id: str
    scope_node_id: str


class DigressionGroupCreatedPayload(BaseModel):
    group_id: str
    node_ids: list[str]
    label: str
    excluded_by_default: bool = False


class DigressionGroupToggledPayload(BaseModel):
    group_id: str
    included: bool


class SummaryGeneratedPayload(BaseModel):
    summary_id: str
    scope: Literal["branch", "subtree", "selection"]
    node_ids: list[str]
    summary: str
    model: str
    summary_type: Literal["concise", "detailed", "key_points", "custom"]
    prompt_used: str | None = None


class GarbageCollectedPayload(BaseModel):
    deleted_node_ids: list[str]
    deleted_tree_ids: list[str]
    reason: str = "manual_gc"
    recoverable_until: str  # ISO-8601


class NodeContentEditedPayload(BaseModel):
    node_id: str
    original_content: str  # matches node.content; for event log readability
    new_content: str | None  # edited content, or None to restore


class GarbagePurgedPayload(BaseModel):
    purged_node_ids: list[str]
    purged_tree_ids: list[str]


# ---------------------------------------------------------------------------
# Event type registry
# ---------------------------------------------------------------------------

EVENT_TYPES: dict[str, type[BaseModel]] = {
    "TreeCreated": TreeCreatedPayload,
    "TreeMetadataUpdated": TreeMetadataUpdatedPayload,
    "TreeArchived": TreeArchivedPayload,
    "TreeUnarchived": TreeUnarchivedPayload,
    "GenerationStarted": GenerationStartedPayload,
    "NodeCreated": NodeCreatedPayload,
    "NodeContentEdited": NodeContentEditedPayload,
    "NodeArchived": NodeArchivedPayload,
    "NodeUnarchived": NodeUnarchivedPayload,
    "AnnotationAdded": AnnotationAddedPayload,
    "AnnotationRemoved": AnnotationRemovedPayload,
    "BookmarkCreated": BookmarkCreatedPayload,
    "BookmarkRemoved": BookmarkRemovedPayload,
    "BookmarkSummaryGenerated": BookmarkSummaryGeneratedPayload,
    "NodeContextExcluded": NodeContextExcludedPayload,
    "NodeContextIncluded": NodeContextIncludedPayload,
    "DigressionGroupCreated": DigressionGroupCreatedPayload,
    "DigressionGroupToggled": DigressionGroupToggledPayload,
    "SummaryGenerated": SummaryGeneratedPayload,
    "GarbageCollected": GarbageCollectedPayload,
    "GarbagePurged": GarbagePurgedPayload,
}


# ---------------------------------------------------------------------------
# Event envelope
# ---------------------------------------------------------------------------


class EventEnvelope(BaseModel):
    """Wraps every event with metadata. Stored in the events table."""

    event_id: str
    tree_id: str
    timestamp: datetime
    device_id: str = "local"
    user_id: str | None = None
    event_type: str
    payload: dict[str, Any]
    sequence_num: int | None = None  # assigned by DB on insert

    def typed_payload(self) -> BaseModel:
        """Deserialize payload into the correct Pydantic model based on event_type."""
        payload_cls = EVENT_TYPES[self.event_type]
        return payload_cls.model_validate(self.payload)
