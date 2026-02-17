"""
One-shot migration: backfill excluded_node_ids on nodes whose context_usage
has excluded_count > 0 but no excluded_node_ids stored.

These nodes were generated before the code change that added per-ID tracking.
We reconstruct the exclusion state at generation time by replaying
NodeContextExcluded, NodeContextIncluded, DigressionGroupCreated, and
DigressionGroupToggled events in sequence order.

Usage:
    cd backend
    python scripts/backfill_excluded_node_ids.py
"""

import json
import sqlite3
import sys
from pathlib import Path


def get_db_path() -> Path:
    """Resolve the database path relative to the backend directory."""
    backend_dir = Path(__file__).resolve().parent.parent
    return backend_dir / "qivis.db"


def walk_path_to_root(nodes_by_id: dict, start_parent_id: str | None) -> set[str]:
    """Walk parent chain from start_parent_id to root, return set of node IDs."""
    path_ids: set[str] = set()
    current_id = start_parent_id
    while current_id is not None:
        path_ids.add(current_id)
        node = nodes_by_id.get(current_id)
        if node is None:
            break
        current_id = node["parent_id"]
    return path_ids


def backfill(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Find all distinct tree IDs that have nodes needing backfill:
    # assistant nodes with context_usage.excluded_count > 0
    candidates = conn.execute("""
        SELECT node_id, tree_id, parent_id, context_usage, created_at
        FROM nodes
        WHERE role = 'assistant'
          AND context_usage IS NOT NULL
          AND json_extract(context_usage, '$.excluded_count') > 0
    """).fetchall()

    if not candidates:
        print("No nodes need backfilling.")
        conn.close()
        return

    # Filter to those with empty or missing excluded_node_ids
    needs_backfill = []
    for row in candidates:
        cu = json.loads(row["context_usage"])
        existing_ids = cu.get("excluded_node_ids", [])
        if not existing_ids:
            needs_backfill.append(row)

    if not needs_backfill:
        print("All nodes already have excluded_node_ids populated.")
        conn.close()
        return

    print(f"Found {len(needs_backfill)} node(s) to backfill.")

    # Group by tree
    trees: dict[str, list] = {}
    for row in needs_backfill:
        trees.setdefault(row["tree_id"], []).append(row)

    total_updated = 0

    for tree_id, target_nodes in trees.items():
        print(f"\nTree {tree_id}: {len(target_nodes)} node(s)")

        # Load all nodes for this tree (for path walking)
        all_nodes = conn.execute(
            "SELECT node_id, parent_id, role FROM nodes WHERE tree_id = ?",
            (tree_id,),
        ).fetchall()
        nodes_by_id = {n["node_id"]: dict(n) for n in all_nodes}

        # Load relevant events for this tree, sorted by sequence_num
        events = conn.execute("""
            SELECT sequence_num, event_type, payload, timestamp
            FROM events
            WHERE tree_id = ?
              AND event_type IN (
                  'NodeContextExcluded', 'NodeContextIncluded',
                  'DigressionGroupCreated', 'DigressionGroupToggled',
                  'NodeCreated'
              )
            ORDER BY sequence_num
        """, (tree_id,)).fetchall()

        # Build a map: node_id -> sequence_num of its creation event
        node_creation_seq: dict[str, int] = {}
        for ev in events:
            if ev["event_type"] == "NodeCreated":
                payload = json.loads(ev["payload"])
                node_creation_seq[payload["node_id"]] = ev["sequence_num"]

        # Sort target nodes by their creation sequence number
        target_nodes_sorted = sorted(
            target_nodes,
            key=lambda n: node_creation_seq.get(n["node_id"], 0),
        )

        # Replay events to reconstruct exclusion state at each target node's creation time
        # State: active exclusions as (node_id, scope_node_id) pairs
        active_exclusions: dict[tuple[str, str], bool] = {}
        # Digression groups: group_id -> {node_ids, included}
        digression_groups: dict[str, dict] = {}

        event_idx = 0
        for target in target_nodes_sorted:
            target_seq = node_creation_seq.get(target["node_id"])
            if target_seq is None:
                print(f"  WARNING: No creation event found for {target['node_id']}, skipping")
                continue

            # Replay events up to (but not including) the target's creation
            while event_idx < len(events) and events[event_idx]["sequence_num"] < target_seq:
                ev = events[event_idx]
                payload = json.loads(ev["payload"])

                if ev["event_type"] == "NodeContextExcluded":
                    key = (payload["node_id"], payload["scope_node_id"])
                    active_exclusions[key] = True

                elif ev["event_type"] == "NodeContextIncluded":
                    key = (payload["node_id"], payload["scope_node_id"])
                    active_exclusions.pop(key, None)

                elif ev["event_type"] == "DigressionGroupCreated":
                    digression_groups[payload["group_id"]] = {
                        "node_ids": payload["node_ids"],
                        "included": not payload.get("excluded_by_default", False),
                    }

                elif ev["event_type"] == "DigressionGroupToggled":
                    gid = payload["group_id"]
                    if gid in digression_groups:
                        digression_groups[gid]["included"] = payload["included"]

                event_idx += 1

            # Compute the path from target's parent to root
            path_ids = walk_path_to_root(nodes_by_id, target["parent_id"])
            # Also include the target node itself in path_ids for scope matching
            path_ids.add(target["node_id"])

            # Compute effective excluded set:
            # 1. Individual exclusions where scope_node_id is on our path
            effective_excluded: set[str] = set()
            for (nid, scope), _ in active_exclusions.items():
                if scope in path_ids:
                    effective_excluded.add(nid)

            # 2. Digression group exclusions (groups that are not included)
            path_node_ids_for_groups = walk_path_to_root(nodes_by_id, target["parent_id"])
            for gid, group in digression_groups.items():
                if not group["included"]:
                    group_nids = group["node_ids"]
                    # Group applies if all its nodes are on the path
                    if group_nids and all(nid in path_node_ids_for_groups for nid in group_nids):
                        effective_excluded.update(group_nids)

            # Filter to only API-sendable roles on the path
            api_roles = {"user", "assistant", "tool"}
            excluded_on_path = []
            for nid in effective_excluded:
                node = nodes_by_id.get(nid)
                if node and node["role"] in api_roles and nid in path_ids:
                    excluded_on_path.append(nid)

            # Update context_usage
            cu = json.loads(target["context_usage"])
            cu["excluded_node_ids"] = excluded_on_path

            # Sanity check: our count should match the stored excluded_count
            stored_count = cu.get("excluded_count", 0)
            if len(excluded_on_path) != stored_count:
                print(
                    f"  NOTE: {target['node_id']}: reconstructed {len(excluded_on_path)} "
                    f"excluded IDs but stored excluded_count is {stored_count}"
                )

            conn.execute(
                "UPDATE nodes SET context_usage = ? WHERE node_id = ?",
                (json.dumps(cu), target["node_id"]),
            )
            total_updated += 1
            print(f"  Updated {target['node_id']}: {len(excluded_on_path)} excluded IDs")

    conn.commit()
    conn.close()
    print(f"\nDone. Updated {total_updated} node(s).")


if __name__ == "__main__":
    db_path = get_db_path()
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        sys.exit(1)
    print(f"Database: {db_path}")
    backfill(db_path)
