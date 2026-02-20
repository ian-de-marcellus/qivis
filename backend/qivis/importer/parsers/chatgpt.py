"""Parser for ChatGPT conversations.json export format.

ChatGPT's export is tree-native: a `mapping` dict of nodes with parent/children
pointers. Structural nodes (message=null) are skipped and children reparented.
System messages are extracted as the tree's default_system_prompt.
"""

from collections import Counter

from qivis.importer.models import ImportedNode, ImportedTree


def _infer_provider(model_slug: str | None) -> str | None:
    """Infer provider name from ChatGPT model_slug."""
    if not model_slug:
        return None
    slug = model_slug.lower()
    if (
        slug.startswith("gpt-")
        or slug.startswith("o1")
        or slug.startswith("o3")
        or slug.startswith("o4")
        or slug.startswith("chatgpt-")
    ):
        return "openai"
    if slug.startswith("claude-"):
        return "anthropic"
    return None


def _extract_content(message: dict) -> str:
    """Extract text content from a ChatGPT message object."""
    content_obj = message.get("content", {})
    parts = content_obj.get("parts", [])
    # Filter to strings only (parts can contain non-string items for multimodal)
    text_parts = [p for p in parts if isinstance(p, str)]
    return "\n".join(text_parts)


def _parse_single(conv: dict) -> ImportedTree:
    """Parse a single ChatGPT conversation object into an ImportedTree."""
    mapping = conv.get("mapping", {})
    warnings: list[str] = []

    # Phase 1: Identify real nodes vs structural/system
    real_nodes: dict[str, dict] = {}  # node_id -> mapping entry
    system_prompt: str | None = None
    skipped_ids: set[str] = set()

    for node_id, entry in mapping.items():
        message = entry.get("message")
        if message is None:
            skipped_ids.add(node_id)
            continue

        role = message.get("author", {}).get("role", "")
        if role == "system":
            content = _extract_content(message)
            if content.strip():
                system_prompt = content
            skipped_ids.add(node_id)
            continue

        if role == "tool":
            skipped_ids.add(node_id)
            warnings.append(f"Skipped tool message {node_id}")
            continue

        if role not in ("user", "assistant"):
            skipped_ids.add(node_id)
            warnings.append(f"Skipped unknown role '{role}' on {node_id}")
            continue

        real_nodes[node_id] = entry

    # Phase 2: Reparent — if a node's parent was skipped, walk up to find real ancestor
    def find_real_parent(node_id: str) -> str | None:
        parent_id = mapping.get(node_id, {}).get("parent")
        visited = set()
        while parent_id is not None:
            if parent_id in visited:
                break
            visited.add(parent_id)
            if parent_id in real_nodes:
                return parent_id
            parent_id = mapping.get(parent_id, {}).get("parent")
        return None

    # Phase 3: Build ImportedNodes
    imported_nodes: list[ImportedNode] = []
    models_seen: list[str] = []
    root_ids: list[str] = []

    for node_id, entry in real_nodes.items():
        message = entry["message"]
        role = message["author"]["role"]
        content = _extract_content(message)
        model_slug = message.get("metadata", {}).get("model_slug")
        timestamp = message.get("create_time")

        if model_slug:
            models_seen.append(model_slug)

        parent = find_real_parent(node_id)
        if parent is None:
            root_ids.append(node_id)

        imported_nodes.append(ImportedNode(
            temp_id=node_id,
            parent_temp_id=parent,
            role=role,
            content=content,
            model=model_slug,
            provider=_infer_provider(model_slug),
            timestamp=timestamp,
        ))

    # Detect most common model for tree defaults
    default_model = None
    default_provider = None
    if models_seen:
        most_common = Counter(models_seen).most_common(1)[0][0]
        default_model = most_common
        default_provider = _infer_provider(most_common)

    return ImportedTree(
        title=conv.get("title"),
        source_format="chatgpt",
        source_id=conv.get("id"),
        default_system_prompt=system_prompt,
        default_model=default_model,
        default_provider=default_provider,
        nodes=imported_nodes,
        root_temp_ids=root_ids,
        created_at=conv.get("create_time"),
        warnings=warnings,
    )


def parse_chatgpt(data: dict | list) -> list[ImportedTree]:
    """Parse ChatGPT conversations.json (array or single conversation)."""
    if isinstance(data, list):
        return [_parse_single(conv) for conv in data]
    return [_parse_single(data)]
