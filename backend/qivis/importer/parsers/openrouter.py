"""Parser for OpenRouter conversation export format (orpg.3.0).

OpenRouter exports as a single JSON object with:
- version: "orpg.3.0"
- characters: map of character configs (each has model, modelInfo)
- messages: map of message metadata (id, parentMessageId, type, characterId, createdAt)
- items: map of content (id, messageId, data.role, data.content blocks)

Thread structure is flat user->assistant pairs: user messages lack parentMessageId,
assistant messages point to their paired user message. We reconstruct the linear
chain by sorting chronologically and linking each user message to the previous
assistant message.
"""

from datetime import datetime, timezone

from qivis.importer.models import ImportedNode, ImportedTree


def _parse_timestamp(ts: str | None) -> float | None:
    """Parse ISO 8601 timestamp to Unix epoch seconds."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _extract_model_info(characters: dict) -> dict[str, tuple[str | None, str | None]]:
    """Build char_id -> (provider, model) map from character configs.

    The model slug is "provider/model" (e.g. "anthropic/claude-opus-4.6").
    """
    result: dict[str, tuple[str | None, str | None]] = {}
    for char_id, char in characters.items():
        slug = char.get("model", "")
        if "/" in slug:
            provider, model = slug.split("/", 1)
            result[char_id] = (provider, model)
        elif slug:
            result[char_id] = (None, slug)
        else:
            result[char_id] = (None, None)
    return result


def _extract_content(item_data: dict, warnings: list[str], item_id: str) -> str:
    """Extract text content from an item's data.content blocks.

    Handles input_text and output_text blocks. Skips input_image and input_file
    with warnings.
    """
    content_blocks = item_data.get("content", [])
    text_parts: list[str] = []

    if isinstance(content_blocks, str):
        return content_blocks

    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type", "")
        if block_type in ("input_text", "output_text"):
            text = block.get("text", "")
            if text:
                text_parts.append(text)
        elif block_type == "input_image":
            warnings.append(f"Skipped image attachment in {item_id}")
        elif block_type == "input_file":
            filename = block.get("filename", "file")
            warnings.append(f"Skipped file attachment '{filename}' in {item_id}")

    return "\n".join(text_parts).strip()


def parse_openrouter(data: dict) -> list[ImportedTree]:
    """Parse an OpenRouter export into a list of ImportedTrees.

    OpenRouter exports one conversation per file, so this always returns
    a single-element list.
    """
    warnings: list[str] = []

    characters = data.get("characters", {})
    messages = data.get("messages", {})
    items = data.get("items", {})
    title = data.get("title")

    char_models = _extract_model_info(characters)

    # Build item lookup: item_id -> item data
    item_lookup: dict[str, dict] = {}
    for item_id, item in items.items():
        item_lookup[item_id] = item

    # Sort messages chronologically
    sorted_msgs = sorted(
        messages.values(),
        key=lambda m: m.get("createdAt", ""),
    )

    # Build nodes and reconstruct the linear chain.
    # User messages have no parentMessageId in the export.
    # We chain: user_n's parent = assistant_(n-1)
    nodes: list[ImportedNode] = []
    root_ids: list[str] = []
    last_assistant_id: str | None = None

    for msg in sorted_msgs:
        msg_id = msg.get("id", "")
        msg_type = msg.get("type", "")
        char_id = msg.get("characterId", "")
        timestamp = _parse_timestamp(msg.get("createdAt"))

        # Resolve role
        if msg_type == "user" or char_id == "USER":
            role = "user"
        elif msg_type == "assistant":
            role = "assistant"
        else:
            warnings.append(f"Skipped message with unknown type '{msg_type}': {msg_id}")
            continue

        # Extract content from linked items
        msg_items = msg.get("items", [])
        text_parts: list[str] = []
        for item_ref in msg_items:
            item_id = item_ref.get("id", "") if isinstance(item_ref, dict) else str(item_ref)
            item = item_lookup.get(item_id)
            if item:
                item_data = item.get("data", {})
                text = _extract_content(item_data, warnings, item_id)
                if text:
                    text_parts.append(text)

        content = "\n".join(text_parts).strip()
        if not content and role == "assistant":
            warnings.append(f"Skipped empty assistant message {msg_id}")
            continue

        # Determine parent for tree structure
        if role == "user":
            # Chain to previous assistant, or root if first message
            parent_id = last_assistant_id
            if parent_id is None:
                root_ids.append(msg_id)
        else:
            # Assistant messages: use parentMessageId from export (points to user msg)
            parent_id = msg.get("parentMessageId")
            if not parent_id:
                # Fallback: orphan assistant
                warnings.append(f"Assistant message {msg_id} has no parentMessageId")

        # Model info from character — stored in metadata for provenance only.
        # OpenRouter slugs (e.g. "claude-opus-4.6") don't match provider API
        # model IDs (e.g. "claude-opus-4-6"), so we don't set model/provider
        # on nodes to avoid broken defaults for future generations.
        metadata: dict = {}
        if role == "assistant":
            or_provider, or_model = char_models.get(char_id, (None, None))
            if or_model:
                metadata["openrouter_model"] = or_model
            if or_provider:
                metadata["openrouter_provider"] = or_provider
        msg_meta = msg.get("metadata", {})
        if msg_meta.get("tokensCount"):
            metadata["tokens_count"] = msg_meta["tokensCount"]
        if msg_meta.get("cost"):
            metadata["cost"] = msg_meta["cost"]
        if msg_meta.get("generationId"):
            metadata["generation_id"] = msg_meta["generationId"]

        nodes.append(ImportedNode(
            temp_id=msg_id,
            parent_temp_id=parent_id,
            role=role,
            content=content,
            model=None,
            provider=None,
            timestamp=timestamp,
            metadata=metadata,
        ))

        if role == "assistant":
            last_assistant_id = msg_id

    # Don't set default_model/default_provider — OpenRouter model slugs
    # don't match provider API model IDs, so using them as defaults would
    # cause generation failures.
    created_at = _parse_timestamp(sorted_msgs[0].get("createdAt")) if sorted_msgs else None

    return [ImportedTree(
        title=title,
        source_format="openrouter",
        source_id=None,
        default_model=None,
        default_provider=None,
        nodes=nodes,
        root_temp_ids=root_ids,
        created_at=created_at,
        warnings=warnings,
    )]
