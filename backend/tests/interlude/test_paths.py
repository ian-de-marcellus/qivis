"""One set of tree walks, shared by generation, export, the guest portal and MCP."""

import pytest

from qivis.rhizomes.paths import ancestry, current_path, leaf_paths, subtree


def n(node_id, parent_id, t):
    return {"node_id": node_id, "parent_id": parent_id, "created_at": f"2026-01-01T00:00:{t:02d}"}


#   a ─ b ─ c
#     └ d ─ e     (d is newer than b)
NODES = [n("a", None, 0), n("b", "a", 1), n("c", "b", 2), n("d", "a", 3), n("e", "d", 4)]
BY_ID = {x["node_id"]: x for x in NODES}


def ids(nodes):
    return [x["node_id"] for x in nodes]


def test_ancestry_is_root_first():
    assert ids(ancestry(BY_ID, "c")) == ["a", "b", "c"]
    assert ancestry(BY_ID, None) == []


def test_ancestry_strictness():
    assert ids(ancestry({"c": n("c", "gone", 0)}, "c")) == ["c"]
    with pytest.raises(ValueError, match="Broken chain: node gone not found"):
        ancestry({"c": n("c", "gone", 0)}, "c", strict=True)
    with pytest.raises(ValueError, match="Node not found: zz"):
        ancestry(BY_ID, "zz", strict=True)
    with pytest.raises(ValueError, match="Cycle"):
        ancestry({"x": n("x", "y", 0), "y": n("y", "x", 1)}, "x")


def test_current_path_takes_newest_unless_chosen():
    assert [x["node_id"] for x, _ in current_path(NODES)] == ["a", "d", "e"]
    path = current_path(NODES, {"b"})
    assert [x["node_id"] for x, _ in path] == ["a", "b", "c"]
    assert ids(path[1][1]) == ["b", "d"]  # siblings, oldest first


def test_subtree_and_leaf_paths():
    assert ids(subtree(NODES, "a")) == ["a", "b", "d", "c", "e"]
    assert leaf_paths(NODES) == [["a", "b", "c"], ["a", "d", "e"]]


def test_deep_conversations_do_not_recurse():
    chain = [n("0", None, 0)] + [
        {"node_id": str(i), "parent_id": str(i - 1), "created_at": f"{i:06d}"} for i in range(1, 5000)
    ]
    assert len(leaf_paths(chain)[0]) == 5000
    assert len(ancestry({x["node_id"]: x for x in chain}, "4999")) == 5000
