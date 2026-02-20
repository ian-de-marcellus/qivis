"""Intermediate representation for imported conversations.

All parsers produce ImportedTree/ImportedNode, which ImportService consumes
to emit events. This decouples format-specific parsing from event emission.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ImportedNode:
    """A single message from an external conversation."""

    temp_id: str
    parent_temp_id: str | None
    role: str  # "user" | "assistant" | "system"
    content: str
    model: str | None = None
    provider: str | None = None
    timestamp: float | None = None  # Unix epoch seconds
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImportedTree:
    """A complete parsed conversation, ready for import."""

    title: str | None
    source_format: str  # "chatgpt" | "claude" | "linear"
    source_id: str | None = None
    default_system_prompt: str | None = None
    default_model: str | None = None
    default_provider: str | None = None
    nodes: list[ImportedNode] = field(default_factory=list)
    root_temp_ids: list[str] = field(default_factory=list)
    created_at: float | None = None
    warnings: list[str] = field(default_factory=list)
