"""Parser for linear conversation formats (ShareGPT, generic {role, content}).

Produces a single-path ImportedTree (no branching). System messages are
extracted as the tree's default_system_prompt.
"""

from uuid import uuid4

from qivis.importer.models import ImportedNode, ImportedTree


# ShareGPT role mapping
_SHAREGPT_ROLES = {
    "human": "user",
    "gpt": "assistant",
    "system": "system",
    "user": "user",
    "assistant": "assistant",
}


def _is_sharegpt(messages: list[dict]) -> bool:
    """Detect ShareGPT format by checking for 'from' or 'value' keys."""
    if not messages:
        return False
    first = messages[0]
    return "from" in first or "value" in first


def _normalize_message(msg: dict, is_sharegpt: bool) -> tuple[str, str]:
    """Extract (role, content) from a message dict."""
    if is_sharegpt:
        raw_role = msg.get("from", "user")
        content = msg.get("value", "")
    else:
        raw_role = msg.get("role", "user")
        content = msg.get("content", "")

    role = _SHAREGPT_ROLES.get(raw_role, raw_role)
    return role, content


def parse_linear(data: list) -> ImportedTree:
    """Parse a linear array of messages into a single-path ImportedTree."""
    sharegpt = _is_sharegpt(data)
    system_prompt: str | None = None
    nodes: list[ImportedNode] = []
    prev_id: str | None = None

    for msg in data:
        role, content = _normalize_message(msg, sharegpt)

        if role == "system":
            if system_prompt is None:
                system_prompt = content
            continue

        if role not in ("user", "assistant"):
            continue

        node_id = str(uuid4())
        nodes.append(ImportedNode(
            temp_id=node_id,
            parent_temp_id=prev_id,
            role=role,
            content=content,
            model=msg.get("model"),
            provider=msg.get("provider"),
            timestamp=msg.get("create_time") or msg.get("timestamp"),
        ))
        prev_id = node_id

    root_ids = [nodes[0].temp_id] if nodes else []

    return ImportedTree(
        title=None,
        source_format="linear",
        default_system_prompt=system_prompt,
        nodes=nodes,
        root_temp_ids=root_ids,
    )
