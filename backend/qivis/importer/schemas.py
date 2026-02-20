"""Pydantic schemas for the import API."""

from pydantic import BaseModel


class MessagePreview(BaseModel):
    role: str
    content_preview: str


class ConversationPreview(BaseModel):
    index: int
    title: str | None
    message_count: int
    has_branches: bool
    branch_count: int
    model_names: list[str]
    system_prompt_preview: str | None
    first_messages: list[MessagePreview]
    warnings: list[str]


class ImportPreviewResponse(BaseModel):
    format_detected: str
    conversations: list[ConversationPreview]
    total_conversations: int


class ImportResult(BaseModel):
    tree_id: str
    title: str | None
    node_count: int
    warnings: list[str]


class ImportResponse(BaseModel):
    results: list[ImportResult]
