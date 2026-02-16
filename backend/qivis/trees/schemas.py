"""Request and response schemas for tree and node endpoints."""

from typing import Literal

from pydantic import BaseModel, Field

from qivis.models import SamplingParams

# -- Requests --


class CreateTreeRequest(BaseModel):
    title: str | None = None
    default_system_prompt: str | None = None
    default_model: str | None = None
    default_provider: str | None = None
    default_sampling_params: SamplingParams | None = None


class PatchTreeRequest(BaseModel):
    """Fields to update on a tree. Only fields present in the request body are changed."""

    title: str | None = None
    default_model: str | None = None
    default_provider: str | None = None
    default_system_prompt: str | None = None
    default_sampling_params: SamplingParams | None = None


class CreateNodeRequest(BaseModel):
    content: str
    role: Literal["system", "user", "assistant", "tool", "researcher_note"] = "user"
    parent_id: str | None = None


class GenerateRequest(BaseModel):
    """Request body for POST /api/trees/{tree_id}/nodes/{node_id}/generate."""

    provider: str = "anthropic"
    model: str | None = None
    system_prompt: str | None = None
    sampling_params: SamplingParams | None = None
    stream: bool = False
    n: int = Field(default=1, ge=1, le=10)


# -- Responses --


class NodeResponse(BaseModel):
    node_id: str
    tree_id: str
    parent_id: str | None = None
    role: str
    content: str
    model: str | None = None
    provider: str | None = None
    system_prompt: str | None = None
    sampling_params: dict | None = None
    mode: str | None = None
    usage: dict | None = None
    latency_ms: int | None = None
    finish_reason: str | None = None
    logprobs: dict | None = None
    context_usage: dict | None = None
    participant_id: str | None = None
    participant_name: str | None = None
    created_at: str
    archived: int = 0
    sibling_count: int = 1
    sibling_index: int = 0


class TreeSummary(BaseModel):
    tree_id: str
    title: str | None = None
    conversation_mode: str = "single"
    created_at: str
    updated_at: str


class TreeDetailResponse(BaseModel):
    tree_id: str
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
