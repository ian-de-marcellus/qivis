"""Export service: JSON and CSV export, tree path enumeration."""

import csv
import io
from datetime import UTC, datetime

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.utils.json import json_str, parse_json_or_none


class ExportService:
    """Builds export artifacts from materialized state."""

    def __init__(
        self,
        db: Database,
        store: EventStore,
        projector: StateProjector,
    ) -> None:
        self._db = db
        self._store = store
        self._projector = projector

    async def export_json(
        self,
        tree_id: str,
        *,
        include_events: bool = False,
    ) -> dict | None:
        """Export tree as a rich JSON document.

        Returns None if tree not found.
        """
        tree = await self._projector.get_tree(tree_id)
        if tree is None:
            return None

        nodes = await self._projector.get_nodes(tree_id)

        # Annotations per node
        annotations_by_node: dict[str, list[dict]] = {}
        ann_rows = await self._db.fetchall(
            "SELECT * FROM annotations WHERE tree_id = ?", (tree_id,)
        )
        for row in ann_rows:
            r = _row_to_dict(row)
            nid = r["node_id"]
            annotations_by_node.setdefault(nid, []).append({
                "annotation_id": r["annotation_id"],
                "tag": r["tag"],
                "value": parse_json_or_none(r.get("value")),
                "notes": r.get("notes"),
            })

        # Bookmarks
        bm_rows = await self._db.fetchall(
            "SELECT * FROM bookmarks WHERE tree_id = ?", (tree_id,)
        )
        bookmarks = []
        for row in bm_rows:
            r = _row_to_dict(row)
            bookmarks.append({
                "bookmark_id": r["bookmark_id"],
                "node_id": r["node_id"],
                "label": r["label"],
                "notes": r.get("notes"),
                "summary": r.get("summary"),
                "created_at": r.get("created_at"),
            })

        # Exclusions
        excl_rows = await self._projector.get_node_exclusions(tree_id)
        exclusions = [
            {
                "node_id": r["node_id"],
                "scope_node_id": r["scope_node_id"],
                "reason": r.get("reason"),
            }
            for r in excl_rows
        ]

        # Digression groups
        dg_raw = await self._projector.get_digression_groups(tree_id)
        digression_groups = [
            {
                "group_id": g["group_id"],
                "label": g["label"],
                "node_ids": g["node_ids"],
                "included": g["included"],
            }
            for g in dg_raw
        ]

        # Anchored node IDs
        anchor_rows = await self._db.fetchall(
            "SELECT node_id FROM node_anchors WHERE tree_id = ?", (tree_id,)
        )
        anchored_ids = {r["node_id"] for r in anchor_rows}

        # Excluded node IDs (any scope)
        excluded_ids = {r["node_id"] for r in excl_rows}

        # Bookmarked node IDs
        bookmarked_ids = {r["node_id"] for r in bm_rows}

        # Build node list
        export_nodes = []
        for n in nodes:
            export_nodes.append({
                "node_id": n["node_id"],
                "parent_id": n.get("parent_id"),
                "role": n["role"],
                "content": n["content"],
                "edited_content": n.get("edited_content"),
                "model": n.get("model"),
                "provider": n.get("provider"),
                "system_prompt": n.get("system_prompt"),
                "sampling_params": parse_json_or_none(n.get("sampling_params")),
                "usage": parse_json_or_none(n.get("usage")),
                "latency_ms": n.get("latency_ms"),
                "finish_reason": n.get("finish_reason"),
                "logprobs": parse_json_or_none(n.get("logprobs")),
                "context_usage": parse_json_or_none(n.get("context_usage")),
                "thinking_content": n.get("thinking_content"),
                "created_at": n.get("created_at"),
                "annotations": annotations_by_node.get(n["node_id"], []),
                "is_bookmarked": n["node_id"] in bookmarked_ids,
                "is_anchored": n["node_id"] in anchored_ids,
                "is_excluded": n["node_id"] in excluded_ids,
            })

        metadata = parse_json_or_none(tree.get("metadata")) or {}

        result: dict = {
            "source": "qivis",
            "version": "1.0",
            "exported_at": datetime.now(UTC).isoformat(),
            "tree": {
                "tree_id": tree["tree_id"],
                "title": tree.get("title"),
                "created_at": tree.get("created_at"),
                "updated_at": tree.get("updated_at"),
                "default_model": tree.get("default_model"),
                "default_provider": tree.get("default_provider"),
                "default_system_prompt": tree.get("default_system_prompt"),
                "default_sampling_params": parse_json_or_none(
                    tree.get("default_sampling_params")
                ),
                "metadata": metadata,
            },
            "nodes": export_nodes,
            "bookmarks": bookmarks,
            "exclusions": exclusions,
            "digression_groups": digression_groups,
        }

        if include_events:
            events = await self._store.get_events(tree_id)
            result["events"] = [
                {
                    "event_id": e.event_id,
                    "tree_id": e.tree_id,
                    "timestamp": e.timestamp.isoformat()
                    if hasattr(e.timestamp, "isoformat")
                    else str(e.timestamp),
                    "event_type": e.event_type,
                    "payload": e.payload,
                    "sequence_num": e.sequence_num,
                }
                for e in events
            ]

        return result

    async def export_csv(self, tree_id: str) -> str | None:
        """Export tree as CSV (one row per node).

        Returns CSV string, or None if tree not found.
        """
        tree = await self._projector.get_tree(tree_id)
        if tree is None:
            return None

        nodes = await self._projector.get_nodes(tree_id)

        # Annotations per node (tags only for CSV)
        ann_rows = await self._db.fetchall(
            "SELECT node_id, tag FROM annotations WHERE tree_id = ?", (tree_id,)
        )
        tags_by_node: dict[str, list[str]] = {}
        for row in ann_rows:
            tags_by_node.setdefault(row["node_id"], []).append(row["tag"])

        # Bookmarked / anchored / excluded sets
        bm_rows = await self._db.fetchall(
            "SELECT node_id FROM bookmarks WHERE tree_id = ?", (tree_id,)
        )
        bookmarked_ids = {r["node_id"] for r in bm_rows}

        anchor_rows = await self._db.fetchall(
            "SELECT node_id FROM node_anchors WHERE tree_id = ?", (tree_id,)
        )
        anchored_ids = {r["node_id"] for r in anchor_rows}

        excl_rows = await self._projector.get_node_exclusions(tree_id)
        excluded_ids = {r["node_id"] for r in excl_rows}

        # Compute path depth for each node
        by_id = {n["node_id"]: n for n in nodes}
        depths: dict[str, int] = {}
        for n in nodes:
            depth = 0
            cur = n
            while cur.get("parent_id") and cur["parent_id"] in by_id:
                depth += 1
                cur = by_id[cur["parent_id"]]
            depths[n["node_id"]] = depth

        fieldnames = [
            "node_id", "parent_id", "role", "content", "edited_content",
            "model", "provider", "latency_ms", "finish_reason",
            "thinking_content", "created_at", "annotation_tags",
            "is_bookmarked", "is_anchored", "is_excluded", "path_depth",
            "sampling_params", "usage", "logprobs", "context_usage",
        ]

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()

        for n in nodes:
            nid = n["node_id"]
            writer.writerow({
                "node_id": nid,
                "parent_id": n.get("parent_id") or "",
                "role": n["role"],
                "content": n["content"],
                "edited_content": n.get("edited_content") or "",
                "model": n.get("model") or "",
                "provider": n.get("provider") or "",
                "latency_ms": n.get("latency_ms") or "",
                "finish_reason": n.get("finish_reason") or "",
                "thinking_content": n.get("thinking_content") or "",
                "created_at": n.get("created_at") or "",
                "annotation_tags": ",".join(tags_by_node.get(nid, [])),
                "is_bookmarked": str(nid in bookmarked_ids).lower(),
                "is_anchored": str(nid in anchored_ids).lower(),
                "is_excluded": str(nid in excluded_ids).lower(),
                "path_depth": depths.get(nid, 0),
                "sampling_params": json_str(n.get("sampling_params")),
                "usage": json_str(n.get("usage")),
                "logprobs": json_str(n.get("logprobs")),
                "context_usage": json_str(n.get("context_usage")),
            })

        return output.getvalue()

    async def get_paths(self, tree_id: str) -> list[list[str]] | None:
        """Enumerate all root-to-leaf paths in the tree.

        Returns list of paths (each path is a list of node_ids from root to leaf),
        or None if tree not found.
        """
        tree = await self._projector.get_tree(tree_id)
        if tree is None:
            return None

        nodes = await self._projector.get_nodes(tree_id)
        if not nodes:
            return []

        by_id = {n["node_id"]: n for n in nodes}
        children: dict[str | None, list[str]] = {}
        for n in nodes:
            pid = n.get("parent_id")
            children.setdefault(pid, []).append(n["node_id"])

        # Find roots (no parent or parent not in tree)
        roots = children.get(None, [])

        # DFS to enumerate paths
        paths: list[list[str]] = []

        def _dfs(node_id: str, path: list[str]) -> None:
            path.append(node_id)
            child_ids = children.get(node_id, [])
            if not child_ids:
                # Leaf node — record path
                paths.append(list(path))
            else:
                for cid in child_ids:
                    _dfs(cid, path)
            path.pop()

        for root_id in roots:
            _dfs(root_id, [])

        return paths


def _row_to_dict(row) -> dict:
    """Convert a sqlite3.Row or dict to a plain dict."""
    if isinstance(row, dict):
        return row
    return dict(row)


