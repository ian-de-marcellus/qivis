"""Walking the rhizome's tree of nodes (plain node dicts, as projected).

One place for the few ways Qivis reads a tree: up from a node to the root,
down from the root along the newest (or a chosen) child, a subtree, and
every root-to-leaf path. Siblings are always in creation order.
"""

from collections import defaultdict
from collections.abc import Iterable


def ancestry(
    by_id: dict[str, dict], node_id: str | None, *, strict: bool = False,
) -> list[dict]:
    """The chain from the root down to node_id (inclusive); [] for None.

    A missing node or parent ends the chain early, unless strict, where it's a
    ValueError. A cycle is always a ValueError.
    """
    chain: list[dict] = []
    seen: set[str] = set()
    current = node_id
    while current is not None:
        if current in seen:
            raise ValueError(f"Cycle detected at node: {current}")
        seen.add(current)
        node = by_id.get(current)
        if node is None:
            if not strict:
                break
            if current == node_id:
                raise ValueError(f"Node not found: {current}")
            raise ValueError(f"Broken chain: node {current} not found")
        chain.append(node)
        current = node.get("parent_id")
    chain.reverse()
    return chain


def children_of(nodes: Iterable[dict]) -> dict[str | None, list[dict]]:
    """Each parent's children (None: the roots), oldest first."""
    children: dict[str | None, list[dict]] = defaultdict(list)
    for n in nodes:
        children[n.get("parent_id")].append(n)
    for siblings in children.values():
        siblings.sort(key=lambda n: n.get("created_at") or "")
    return children


def current_path(
    nodes: Iterable[dict], choose: set[str] = frozenset(),
) -> list[tuple[dict, list[dict]]]:
    """From the root down: at each step the chosen sibling, else the newest.

    Returns (node, its siblings) pairs -- what a reader of the conversation's
    current line sees.
    """
    children = children_of(nodes)
    path: list[tuple[dict, list[dict]]] = []
    parent: str | None = None
    while children.get(parent):
        siblings = children[parent]
        pick = next((s for s in siblings if s["node_id"] in choose), siblings[-1])
        path.append((pick, siblings))
        parent = pick["node_id"]
    return path


def subtree(nodes: Iterable[dict], root_id: str) -> list[dict]:
    """root_id and all its descendants, breadth first."""
    nodes = list(nodes)
    children = children_of(nodes)
    queue = [n for n in nodes if n["node_id"] == root_id]
    collected: list[dict] = []
    while queue:
        node = queue.pop(0)
        collected.append(node)
        queue.extend(children.get(node["node_id"], []))
    return collected


def leaf_paths(nodes: Iterable[dict]) -> list[list[str]]:
    """Every root-to-leaf path, as node ids (iterative: conversations get deep)."""
    children = children_of(nodes)
    paths: list[list[str]] = []
    stack = [[root["node_id"]] for root in reversed(children.get(None, []))]
    while stack:
        path = stack.pop()
        kids = children.get(path[-1])
        if not kids:
            paths.append(path)
        for child in reversed(kids or []):
            stack.append([*path, child["node_id"]])
    return paths
