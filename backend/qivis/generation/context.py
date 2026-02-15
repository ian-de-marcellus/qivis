"""Minimal context assembly for Phase 0.4.

Walks the parent chain from target node to root, reverses to chronological
order, and returns a simple messages array. No eviction, no exclusion.
The full ContextBuilder with smart eviction comes in Phase 0.5.
"""


def assemble_messages(nodes: list[dict], target_node_id: str) -> list[dict[str, str]]:
    """Build messages array by walking from target_node_id to root.

    Args:
        nodes: All projected nodes for the tree (list of dicts from projector).
        target_node_id: The node to start walking from.

    Returns:
        List of {"role": str, "content": str} in chronological order (root first).
        System and researcher_note roles are excluded.

    Raises:
        ValueError: If target_node_id is not found or the chain is broken.
    """
    by_id = {n["node_id"]: n for n in nodes}
    if target_node_id not in by_id:
        raise ValueError(f"Node not found: {target_node_id}")

    chain: list[dict[str, str]] = []
    current_id: str | None = target_node_id
    visited: set[str] = set()

    while current_id is not None:
        if current_id in visited:
            raise ValueError(f"Cycle detected at node: {current_id}")
        visited.add(current_id)
        node = by_id.get(current_id)
        if node is None:
            raise ValueError(f"Broken chain: node {current_id} not found")
        if node["role"] in ("user", "assistant", "tool"):
            chain.append({"role": node["role"], "content": node["content"]})
        current_id = node.get("parent_id")

    chain.reverse()
    return chain
