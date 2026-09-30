"""Canonical data structures and event types for Qivis.

Defined once here, referenced everywhere else. Data structures match the
architecture doc specifications. Event payloads represent the type-specific
content of each event; the EventEnvelope wraps them with metadata.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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
    # Token id -> additive logit bias (providers that support it, e.g. llama.cpp)
    logit_bias: dict[int, float] | None = None
    # A GBNF grammar the output must match (llama.cpp), e.g. HEALED_SPACE
    grammar: str | None = None


class AlternativeToken(BaseModel):
    token: str
    logprob: float
    linear_prob: float


class TokenLogprob(BaseModel):
    token: str
    logprob: float  # ALWAYS natural log (base e)
    linear_prob: float  # exp(logprob), precomputed for UI
    top_alternatives: list[AlternativeToken]
    # Steered generation: who picked this token. "model" when it flowed
    # through on its own (above the auto-advance threshold), "researcher"
    # when steered to or typed. None for ordinary sampling.
    chosen_by: Literal["model", "researcher"] | None = None
    token_id: int | None = None


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
    keep_first_turns: int = 0
    summary_model: str = "claude-haiku-4-5-20251001"


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


class RhizomeCreatedPayload(BaseModel):
    title: str | None = None
    default_system_prompt: str | None = None
    default_model: str | None = None
    default_provider: str | None = None
    default_sampling_params: SamplingParams | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    conversation_mode: Literal["single", "multi_agent"] = "single"
    participants: list[Participant] | None = None


class RhizomeMetadataUpdatedPayload(BaseModel):
    field: str
    old_value: Any = None
    new_value: Any = None


class RhizomeArchivedPayload(BaseModel):
    reason: str | None = None


class RhizomeUnarchivedPayload(BaseModel):
    pass


class GenerationStartedPayload(BaseModel):
    generation_id: str
    parent_node_id: str | None = None
    model: str
    provider: str
    system_prompt: str | None = None
    sampling_params: SamplingParams = Field(default_factory=SamplingParams)
    mode: Literal["chat", "completion", "prefill", "steered"] = "chat"
    prefill_content: str | None = None
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
    mode: Literal["chat", "completion", "manual", "prefill", "steered"] = "chat"
    prompt_text: str | None = None
    prefill_content: str | None = None

    # Response metadata
    usage: dict[str, int] | None = None  # {input_tokens, output_tokens}
    latency_ms: int | None = None
    finish_reason: str | None = None
    logprobs: LogprobData | None = None
    context_usage: ContextUsage | None = None

    # Thinking / reasoning
    thinking_content: str | None = None

    # Context flags — snapshot of rhizome-level settings at generation time
    include_thinking_in_context: bool = False
    include_timestamps: bool = False

    # Context interventions — snapshot of active interventions at generation time
    active_interventions: list[dict[str, Any]] | None = None

    # Multi-agent identity
    participant_id: str | None = None
    participant_name: str | None = None
    visible_to: list[str] | None = None

    raw_response: dict[str, Any] | None = None

    # A reply the researcher cut short to branch from: the node it was cut from
    cut_from: str | None = None
    # A probe's sample the researcher continued from: the probe it came from
    from_probe: str | None = None
    # A new version of a reply branched at one of its tokens: {node_id, keep}
    branched_from: dict[str, Any] | None = None


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


class DigressionGroupDeletedPayload(BaseModel):
    group_id: str


class SummaryGeneratedPayload(BaseModel):
    summary_id: str
    anchor_node_id: str
    scope: Literal["branch", "subtree", "selection"]
    node_ids: list[str]
    summary: str
    model: str
    summary_type: Literal["concise", "detailed", "key_points", "custom"]
    prompt_used: str | None = None


class SummaryRemovedPayload(BaseModel):
    summary_id: str
    reason: str | None = None


class GarbageCollectedPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    deleted_node_ids: list[str]
    deleted_rhizome_ids: list[str] = Field(alias="deleted_tree_ids")
    reason: str = "manual_gc"
    recoverable_until: str  # ISO-8601


class NoteAddedPayload(BaseModel):
    note_id: str
    node_id: str
    content: str


class NoteRemovedPayload(BaseModel):
    note_id: str
    reason: str | None = None


class NodeContentEditedPayload(BaseModel):
    node_id: str
    original_content: str  # matches node.content; for event log readability
    new_content: str | None  # edited content, or None to restore


class GarbagePurgedPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    purged_node_ids: list[str]
    purged_rhizome_ids: list[str] = Field(alias="purged_tree_ids")


class PerturbationReportGeneratedPayload(BaseModel):
    report_id: str
    experiment_id: str
    node_id: str  # anchor node
    provider: str
    model: str
    include_control: bool
    steps: list[dict]
    divergence: list[dict]


class PerturbationReportRemovedPayload(BaseModel):
    report_id: str


class ProbeRecordedPayload(BaseModel):
    """Short samples of what a model would say next at one point, and what each answers.

    Each sample is stored as the node it would become (its text and exactly
    what produced it), so continuing from one records it as any reply.
    """

    probe_id: str
    node_id: str | None  # the point probed (None: the rhizome's beginning)
    provider: str
    model: str
    samples: list[dict]  # NodeCreatedPayload dumps, not yet nodes
    asked: int | None = None  # samples asked for (fewer come back if some fail)
    # The answer each sample gives, as a judge model named it (None: not judged)
    judge: dict | None = None


class NameStudyCreatedPayload(BaseModel):
    """A name study: which names models give a mind described one way, against a
    human described the same way and no description at all."""

    study_id: str
    title: str
    spec: dict  # models, pronouns, descriptions, subjects, frames, top, extra names
    rules: str  # what counted as a name (the engine's rules, as run)


class NameStudyCellPayload(BaseModel):
    """One cell's results: a model, pronoun set, frame and condition (model,
    human, bare); its exact prompt, top names, and scores for the study's names."""

    study_id: str
    key: str
    model: str
    pronoun: str
    frame: str
    condition: str
    prompt: str
    top: dict[str, float] | None = None  # the cell's own top names
    capital_mass: float | None = None
    scores: dict[str, float] | None = None  # the study's names, scored here
    # Per study name, its first token here: {"p": probability, "t": token, "n": tokens
    # in the name}, so a name's lean can be split from its first token's (" Mind"+"y")
    firsts: dict[str, dict] | None = None
    queries: int = 0


class NameStudyExtendedPayload(BaseModel):
    """More pronoun sets for a study (their descriptions and frames); the study
    goes on to fill in what they add."""

    study_id: str
    pronouns: list[str] = []
    descriptions: dict[str, str] = {}
    frames: dict[str, list[str]] = {}
    # Names to score in every cell, beside the study's own (e.g. found by discovery)
    extra_names: list[str] = []


class NameDiscoveryCreatedPayload(BaseModel):
    """A search for names by what they lean toward (qivis.names.discover)."""

    discovery_id: str
    title: str
    spec: dict  # model, pronoun, the studies it reads descriptions from, weights, search sizes
    prompts: dict  # every prompt it compares, by role, exactly as sent


class NameDiscoveryFinishedPayload(BaseModel):
    discovery_id: str
    status: str  # "done", "failed"
    results: list[dict] = []
    error: str | None = None
    queries: int = 0


class NameStudyStatusPayload(BaseModel):
    study_id: str
    status: str  # "queued", "running", "done", "failed", "stopped"
    error: str | None = None


class ProbeJudgedPayload(BaseModel):
    probe_id: str
    judge: dict


# ---------------------------------------------------------------------------
# Event type registry
# ---------------------------------------------------------------------------

EVENT_TYPES: dict[str, type[BaseModel]] = {
    # Current names
    "RhizomeCreated": RhizomeCreatedPayload,
    "RhizomeMetadataUpdated": RhizomeMetadataUpdatedPayload,
    "RhizomeArchived": RhizomeArchivedPayload,
    "RhizomeUnarchived": RhizomeUnarchivedPayload,
    "GenerationStarted": GenerationStartedPayload,
    "NodeCreated": NodeCreatedPayload,
    "NodeContentEdited": NodeContentEditedPayload,
    "NoteAdded": NoteAddedPayload,
    "NoteRemoved": NoteRemovedPayload,
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
    "DigressionGroupDeleted": DigressionGroupDeletedPayload,
    "NodeAnchored": NodeAnchoredPayload,
    "NodeUnanchored": NodeUnanchoredPayload,
    "SummaryGenerated": SummaryGeneratedPayload,
    "SummaryRemoved": SummaryRemovedPayload,
    "GarbageCollected": GarbageCollectedPayload,
    "GarbagePurged": GarbagePurgedPayload,
    "PerturbationReportGenerated": PerturbationReportGeneratedPayload,
    "PerturbationReportRemoved": PerturbationReportRemovedPayload,
    "ProbeRecorded": ProbeRecordedPayload,
    "ProbeJudged": ProbeJudgedPayload,
    "NameStudyCreated": NameStudyCreatedPayload,
    "NameStudyCellEnumerated": NameStudyCellPayload,
    "NameStudyCellScored": NameStudyCellPayload,
    "NameStudyStatus": NameStudyStatusPayload,
    "NameStudyExtended": NameStudyExtendedPayload,
    "NameStudyCellFirsts": NameStudyCellPayload,
    "NameDiscoveryCreated": NameDiscoveryCreatedPayload,
    "NameDiscoveryFinished": NameDiscoveryFinishedPayload,
    # Backward compat: old event type names from before the rename
    "TreeCreated": RhizomeCreatedPayload,
    "TreeMetadataUpdated": RhizomeMetadataUpdatedPayload,
    "TreeArchived": RhizomeArchivedPayload,
    "TreeUnarchived": RhizomeUnarchivedPayload,
}


# ---------------------------------------------------------------------------
# Event envelope
# ---------------------------------------------------------------------------


class EventEnvelope(BaseModel):
    """Wraps every event with metadata. Stored in the events table."""

    event_id: str
    rhizome_id: str
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
