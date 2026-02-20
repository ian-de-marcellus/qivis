"""Parser for Claude.ai conversation export format.

Claude.ai's export is tree-native: `chat_messages` array with
`parent_message_uuid` pointers. Content is an array of typed blocks
(text, web_search, tool_use, tool_result). System messages aren't
present as messages — the conversation-level `model` field provides
the default model.
"""

from collections import Counter
from datetime import datetime, timezone

from qivis.importer.models import ImportedNode, ImportedTree

# The sentinel UUID that Claude.ai uses for root-level messages
_ROOT_SENTINEL = "00000000-0000-4000-8000-000000000000"


def _extract_content(message: dict) -> str:
    """Extract text content from a Claude.ai message's content blocks.

    Joins all text-type blocks. Skips tool_use, tool_result, web_search,
    and other non-text block types.
    """
    content_blocks = message.get("content", [])
    text_parts: list[str] = []

    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text = block.get("text", "")
            if text:
                text_parts.append(text)

    return "\n".join(text_parts).strip()


def _parse_timestamp(ts: str | None) -> float | None:
    """Parse ISO 8601 timestamp to Unix epoch seconds."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _parse_single(conv: dict) -> ImportedTree:
    """Parse a single Claude.ai conversation export into an ImportedTree."""
    messages = conv.get("chat_messages", [])
    warnings: list[str] = []

    nodes: list[ImportedNode] = []
    root_ids: list[str] = []
    models_seen: list[str] = []
    conv_model = conv.get("model")

    for msg in messages:
        sender = msg.get("sender", "")
        if sender == "human":
            role = "user"
        elif sender == "assistant":
            role = "assistant"
        else:
            warnings.append(f"Skipped unknown sender '{sender}' on {msg.get('uuid')}")
            continue

        content = _extract_content(msg)

        # Skip messages that have no text content (pure tool_use, etc.)
        if not content and role == "assistant":
            warnings.append(f"Skipped empty assistant message {msg.get('uuid')}")
            continue

        msg_uuid = msg.get("uuid", "")
        parent_uuid = msg.get("parent_message_uuid")

        # Root sentinel means no parent
        if parent_uuid == _ROOT_SENTINEL:
            parent_uuid = None
            root_ids.append(msg_uuid)

        # Model: assistant messages may have their own, else use conversation default
        model = conv_model if role == "assistant" else None
        if model:
            models_seen.append(model)

        timestamp = _parse_timestamp(msg.get("created_at"))

        nodes.append(ImportedNode(
            temp_id=msg_uuid,
            parent_temp_id=parent_uuid,
            role=role,
            content=content,
            model=model,
            provider="anthropic" if model else None,
            timestamp=timestamp,
        ))

    # Default model from most common
    default_model = None
    default_provider = None
    if models_seen:
        default_model = Counter(models_seen).most_common(1)[0][0]
        default_provider = "anthropic"

    created_at = _parse_timestamp(conv.get("created_at"))

    # Claude.ai always uses a system prompt but doesn't include it in exports.
    # Record a placeholder on each node so the researcher knows one was present,
    # but don't set it as the tree default (that would send the placeholder with
    # future generations).
    platform = conv.get("platform", "")
    if platform == "CLAUDE_AI":
        placeholder = "[Default Anthropic system prompt — not included in export]"
        for node in nodes:
            node.metadata["system_prompt"] = placeholder

    return ImportedTree(
        title=conv.get("name"),
        source_format="claude",
        source_id=conv.get("uuid"),
        default_model=default_model,
        default_provider=default_provider,
        nodes=nodes,
        root_temp_ids=root_ids,
        created_at=created_at,
        warnings=warnings,
    )


def parse_claude(data: dict | list) -> list[ImportedTree]:
    """Parse Claude.ai export (single conversation or array)."""
    if isinstance(data, list):
        return [_parse_single(conv) for conv in data]
    return [_parse_single(data)]
