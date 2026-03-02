"""Request and response schemas for rhizome and node endpoints."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from qivis.models import SamplingParams

# -- Requests --


class CreateRhizomeRequest(BaseModel):
    title: str | None = None
    default_system_prompt: str | None = None
    default_model: str | None = None
    default_provider: str | None = None
    default_sampling_params: SamplingParams | None = None


class PatchRhizomeRequest(BaseModel):
    """Fields to update on a rhizome. Only fields present in the request body are changed."""

    title: str | None = None
    metadata: dict | None = None
    default_model: str | None = None
    default_provider: str | None = None
    default_system_prompt: str | None = None
    default_sampling_params: SamplingParams | None = None


class CreateNodeRequest(BaseModel):
    content: str
    role: Literal["system", "user", "assistant", "tool", "researcher_note"] = "user"
    parent_id: str | None = None
    mode: Literal["chat", "completion", "manual"] = "chat"


class PatchNodeContentRequest(BaseModel):
    """Request body for PATCH /api/rhizomes/{rhizome_id}/nodes/{node_id}/content."""

    edited_content: str | None


class GenerateRequest(BaseModel):
    """Request body for POST /api/rhizomes/{rhizome_id}/nodes/{node_id}/generate."""

    provider: str = "anthropic"
    model: str | None = None
    system_prompt: str | None = None
    sampling_params: SamplingParams | None = None
    stream: bool = False
    n: int = Field(default=1, ge=1, le=10)
    prefill_content: str | None = None


class ReplayRequest(BaseModel):
    """Request body for POST /api/rhizomes/{rhizome_id}/replay."""

    path_node_ids: list[str]
    provider: str
    model: str | None = None
    mode: Literal["context_faithful", "trajectory"] = "context_faithful"
    system_prompt: str | None = None
    sampling_params: SamplingParams | None = None
    stream: bool = False


class CrossModelTarget(BaseModel):
    """A single target for cross-model generation."""

    provider: str
    model: str


class CrossModelGenerateRequest(BaseModel):
    """Request body for POST /api/rhizomes/{rhizome_id}/nodes/{node_id}/generate-cross."""

    targets: list[CrossModelTarget] = Field(min_length=1, max_length=10)
    system_prompt: str | None = None
    sampling_params: SamplingParams | None = None
    stream: bool = False


class PerturbationConfig(BaseModel):
    """Single perturbation to apply during an experiment."""

    type: Literal["digression_toggle", "node_exclusion", "system_prompt", "intervention_toggle"]
    # digression_toggle
    group_id: str | None = None
    include: bool | None = None
    # node_exclusion
    node_id: str | None = None
    exclude: bool | None = None
    # system_prompt
    system_prompt: str | None = None
    # intervention_toggle
    intervention_index: int | None = None
    enabled: bool | None = None
    # Human-readable label (auto-generated if omitted)
    label: str | None = None


class PerturbationRequest(BaseModel):
    """Request body for POST /api/rhizomes/{rhizome_id}/nodes/{node_id}/perturb."""

    perturbations: list[PerturbationConfig] = Field(min_length=1, max_length=20)
    provider: str
    model: str | None = None
    sampling_params: SamplingParams | None = None
    include_control: bool = True
    stream: bool = False


class PerturbationStepResponse(BaseModel):
    """A single step result in a perturbation report."""

    label: str
    type: str
    config: dict | None = None
    content: str
    node_id: str
    latency_ms: int | None = None
    usage: dict | None = None


class DivergenceMetrics(BaseModel):
    """Divergence metrics for a perturbation vs control."""

    step_index: int
    label: str
    word_diff_ratio: float
    edit_distance: float
    certainty_delta: float | None = None
    length_ratio: float


class PerturbationReportResponse(BaseModel):
    """Full perturbation experiment report."""

    report_id: str
    rhizome_id: str
    experiment_id: str
    node_id: str
    provider: str
    model: str
    include_control: bool
    steps: list[PerturbationStepResponse]
    divergence: list[DivergenceMetrics]
    created_at: str


# -- Responses --


class NodeResponse(BaseModel):
    node_id: str
    rhizome_id: str
    parent_id: str | None = None
    role: str
    content: str
    model: str | None = None
    provider: str | None = None
    system_prompt: str | None = None
    sampling_params: dict | None = None
    mode: str | None = None
    prefill_content: str | None = None
    prompt_text: str | None = None
    usage: dict | None = None
    latency_ms: int | None = None
    finish_reason: str | None = None
    logprobs: dict | None = None
    context_usage: dict | None = None
    participant_id: str | None = None
    participant_name: str | None = None
    thinking_content: str | None = None
    edited_content: str | None = None
    include_thinking_in_context: bool = False
    include_timestamps: bool = False
    active_interventions: list[dict] | None = None
    created_at: str
    archived: int = 0
    sibling_count: int = 1
    sibling_index: int = 0
    annotation_count: int = 0
    note_count: int = 0
    is_bookmarked: bool = False
    edit_count: int = 0
    is_excluded: bool = False
    is_anchored: bool = False


class EditHistoryEntry(BaseModel):
    event_id: str
    sequence_num: int
    timestamp: str
    new_content: str | None  # None = restore to original


class EditHistoryResponse(BaseModel):
    node_id: str
    original_content: str
    current_content: str
    entries: list[EditHistoryEntry]


class InterventionEntry(BaseModel):
    event_id: str
    sequence_num: int
    timestamp: str
    intervention_type: str  # "node_edited" | "system_prompt_changed"
    node_id: str | None = None
    original_content: str | None = None
    new_content: str | None = None
    old_value: str | None = None
    new_value: str | None = None


class InterventionTimelineResponse(BaseModel):
    rhizome_id: str
    interventions: list[InterventionEntry]


class RhizomeSummary(BaseModel):
    rhizome_id: str
    title: str | None = None
    conversation_mode: str = "single"
    created_at: str
    updated_at: str
    folders: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    archived: int = 0


class AddAnnotationRequest(BaseModel):
    tag: str
    value: Any = None
    notes: str | None = None


class AnnotationResponse(BaseModel):
    annotation_id: str
    rhizome_id: str
    node_id: str
    tag: str
    value: Any = None
    notes: str | None = None
    created_at: str


class TaxonomyResponse(BaseModel):
    base_tags: list[str]
    used_tags: list[str]


class CreateNoteRequest(BaseModel):
    content: str


class NoteResponse(BaseModel):
    note_id: str
    rhizome_id: str
    node_id: str
    content: str
    created_at: str


class CreateBookmarkRequest(BaseModel):
    label: str
    notes: str | None = None


class BookmarkResponse(BaseModel):
    bookmark_id: str
    rhizome_id: str
    node_id: str
    label: str
    notes: str | None = None
    summary: str | None = None
    summary_model: str | None = None
    summarized_node_ids: list[str] | None = None
    created_at: str


class ExcludeNodeRequest(BaseModel):
    scope_node_id: str
    reason: str | None = None


class IncludeNodeRequest(BaseModel):
    scope_node_id: str


class NodeExclusionResponse(BaseModel):
    rhizome_id: str
    node_id: str
    scope_node_id: str
    reason: str | None = None
    created_at: str


class CreateDigressionGroupRequest(BaseModel):
    node_ids: list[str]
    label: str
    excluded_by_default: bool = False


class ToggleDigressionGroupRequest(BaseModel):
    included: bool


class BulkAnchorRequest(BaseModel):
    node_ids: list[str]
    anchor: bool


class DigressionGroupResponse(BaseModel):
    group_id: str
    rhizome_id: str
    label: str
    node_ids: list[str]
    included: bool
    created_at: str


class CreateSummaryRequest(BaseModel):
    scope: Literal["branch", "subtree"] = "branch"
    summary_type: Literal["concise", "detailed", "key_points", "custom"] = "concise"
    custom_prompt: str | None = None


class SummaryResponse(BaseModel):
    summary_id: str
    rhizome_id: str
    anchor_node_id: str
    scope: str
    summary_type: str
    summary: str
    model: str
    node_ids: list[str]
    prompt_used: str | None = None
    created_at: str


class RhizomeDetailResponse(BaseModel):
    rhizome_id: str
    title: str | None = None
    metadata: dict = Field(default_factory=dict)
    default_model: str | None = None
    default_provider: str | None = None
    default_system_prompt: str | None = None
    default_sampling_params: dict | None = None
    conversation_mode: str = "single"
    created_at: str
    updated_at: str
    archived: int = 0
    nodes: list[NodeResponse] = Field(default_factory=list)
