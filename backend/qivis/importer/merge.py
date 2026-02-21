"""MergeService: merges imported conversations into existing trees."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.importer.models import ImportedNode, ImportedTree
from qivis.importer.parsers.detection import ImportFormatError
from qivis.importer.service import ImportService
from qivis.models import EventEnvelope, NodeCreatedPayload


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class GraftPoint(BaseModel):
    parent_node_id: str | None
    parent_content_preview: str | None
    new_node_count: int


class MergePreviewResponse(BaseModel):
    source_format: str
    source_title: str | None
    conversation_count: int
    total_imported: int
    matched_count: int
    new_count: int
    graft_points: list[GraftPoint]
    warnings: list[str]


class MergeResult(BaseModel):
    created_count: int
    matched_count: int
    node_ids: list[str]


# ---------------------------------------------------------------------------
# Internal plan dataclass
# ---------------------------------------------------------------------------


@dataclass
class MergePlan:
    """Result of matching imported nodes against existing tree nodes."""

    matched: dict[str, str] = field(default_factory=dict)
    """imported temp_id -> existing node_id"""

    new_nodes: list[ImportedNode] = field(default_factory=list)
    """Nodes to create, in topological order."""

    graft_map: dict[str, str | None] = field(default_factory=dict)
    """imported temp_id -> parent real node_id (for new nodes only)"""

    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Matching algorithm
# ---------------------------------------------------------------------------


def _effective_content(node: dict) -> str:
    """Get the content the researcher sees: edited_content if set, else content."""
    return (node.get("edited_content") or node["content"]).strip()


def _compute_merge_plan(
    imported: ImportedTree, existing_nodes: list[dict]
) -> MergePlan:
    """Match imported nodes against existing tree nodes.

    Pure function — no I/O. Builds an index of existing nodes by
    (parent_id, role, normalized_content), then walks imported nodes
    in topological order looking for structural matches.
    """
    # Index existing nodes: (parent_id, role, content) -> node_id
    # For duplicate keys (same content siblings), first one wins.
    existing_index: dict[tuple[str | None, str, str], str] = {}
    for node in existing_nodes:
        key = (node["parent_id"], node["role"], _effective_content(node))
        if key not in existing_index:
            existing_index[key] = node["node_id"]

    sorted_nodes = ImportService._topological_sort(imported)

    plan = MergePlan()

    for node in sorted_nodes:
        if node.parent_temp_id is None:
            # Root node — match against existing roots
            lookup_parent = None
        elif node.parent_temp_id in plan.matched:
            # Parent was matched — look among children of matched parent
            lookup_parent = plan.matched[node.parent_temp_id]
        else:
            # Parent was new (not matched) — this node is also new
            # Its parent should already be in graft_map or is also new
            parent_real_id = plan.graft_map.get(node.parent_temp_id)
            plan.new_nodes.append(node)
            plan.graft_map[node.temp_id] = parent_real_id
            continue

        # Try to match
        key = (lookup_parent, node.role, node.content.strip())
        if key in existing_index:
            plan.matched[node.temp_id] = existing_index[key]
        else:
            # No match — this is a new node grafted onto the matched parent
            plan.new_nodes.append(node)
            plan.graft_map[node.temp_id] = lookup_parent

    return plan


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class MergeService:
    def __init__(
        self, db: Database, store: EventStore, projector: StateProjector
    ) -> None:
        self._db = db
        self._store = store
        self._projector = projector

    async def preview_merge(
        self, tree_id: str, content: bytes, filename: str
    ) -> MergePreviewResponse:
        """Parse file and return merge preview without creating anything."""
        # Verify tree exists
        tree = await self._projector.get_tree(tree_id)
        if tree is None:
            raise TreeNotFoundError(tree_id)

        data = ImportService._load_json(content)
        fmt = detect_format_safe(data)
        trees = ImportService._parse(fmt, data)

        if not trees:
            return MergePreviewResponse(
                source_format=fmt,
                source_title=None,
                conversation_count=0,
                total_imported=0,
                matched_count=0,
                new_count=0,
                graft_points=[],
                warnings=["No conversations found in file"],
            )

        # Use first conversation for preview
        imported = trees[0]
        existing_nodes = await self._projector.get_nodes(tree_id)
        plan = _compute_merge_plan(imported, existing_nodes)

        # Build graft points summary
        graft_counts: dict[str | None, int] = defaultdict(int)
        for node in plan.new_nodes:
            graft_parent = plan.graft_map[node.temp_id]
            # Only count direct graft points (first new node at each point)
            if node.parent_temp_id is None or node.parent_temp_id in plan.matched:
                graft_counts[graft_parent] += 1
            graft_counts[graft_parent]  # ensure key exists even if 0 increment

        # Build node lookup for content previews
        node_content: dict[str, str] = {
            n["node_id"]: _effective_content(n) for n in existing_nodes
        }

        # Count new nodes per graft point (including descendants)
        graft_new_counts: dict[str | None, int] = defaultdict(int)
        for node in plan.new_nodes:
            # Walk up to find the graft point (first ancestor in graft_map
            # whose parent is a matched node or None)
            graft_parent = plan.graft_map[node.temp_id]
            graft_new_counts[graft_parent] += 1

        # Deduplicate: a graft point's descendants that are also new
        # count toward the same graft point. We need unique graft points.
        # A graft point is defined as a matched parent that has new children.
        unique_graft_parents: set[str | None] = set()
        for node in plan.new_nodes:
            if node.parent_temp_id is None or node.parent_temp_id in plan.matched:
                unique_graft_parents.add(plan.graft_map[node.temp_id])

        graft_points = []
        for parent_id in unique_graft_parents:
            preview = node_content.get(parent_id, "")[:100] if parent_id else None
            # Count all new nodes in subtree from this graft point
            count = sum(
                1 for n in plan.new_nodes
                if self._graft_root(n, plan) == parent_id
            )
            graft_points.append(GraftPoint(
                parent_node_id=parent_id,
                parent_content_preview=preview,
                new_node_count=count,
            ))

        return MergePreviewResponse(
            source_format=fmt,
            source_title=imported.title,
            conversation_count=len(trees),
            total_imported=len(imported.nodes),
            matched_count=len(plan.matched),
            new_count=len(plan.new_nodes),
            graft_points=graft_points,
            warnings=imported.warnings + plan.warnings,
        )

    async def execute_merge(
        self,
        tree_id: str,
        content: bytes,
        filename: str,
        *,
        conversation_index: int = 0,
    ) -> MergeResult:
        """Parse file, match against tree, create new nodes."""
        tree = await self._projector.get_tree(tree_id)
        if tree is None:
            raise TreeNotFoundError(tree_id)

        data = ImportService._load_json(content)
        fmt = detect_format_safe(data)
        trees = ImportService._parse(fmt, data)

        if conversation_index >= len(trees):
            raise ImportFormatError(
                f"Conversation index {conversation_index} out of range "
                f"(file has {len(trees)} conversations)"
            )

        imported = trees[conversation_index]
        existing_nodes = await self._projector.get_nodes(tree_id)
        plan = _compute_merge_plan(imported, existing_nodes)

        if not plan.new_nodes:
            return MergeResult(
                created_count=0,
                matched_count=len(plan.matched),
                node_ids=[],
            )

        # Create new nodes — map temp IDs to real IDs
        temp_to_real: dict[str, str] = {}
        node_ids: list[str] = []

        for node in plan.new_nodes:
            real_id = str(uuid4())
            temp_to_real[node.temp_id] = real_id
            node_ids.append(real_id)

            # Resolve parent: either a matched existing node or a just-created new node
            graft_parent = plan.graft_map[node.temp_id]
            if node.parent_temp_id and node.parent_temp_id not in plan.matched:
                # Parent is also a new node — use its real ID
                parent_real_id = temp_to_real.get(node.parent_temp_id)
            else:
                # Parent is a matched node (or None for root)
                parent_real_id = graft_parent

            node_timestamp = (
                datetime.fromtimestamp(node.timestamp, tz=UTC)
                if node.timestamp
                else datetime.now(UTC)
            )

            node_payload = NodeCreatedPayload(
                node_id=real_id,
                parent_id=parent_real_id,
                role=node.role,
                content=node.content,
                model=node.model,
                provider=node.provider,
                system_prompt=node.metadata.get("system_prompt"),
                mode="chat",
            )
            node_event = EventEnvelope(
                event_id=str(uuid4()),
                tree_id=tree_id,
                timestamp=node_timestamp,
                device_id="merge",
                event_type="NodeCreated",
                payload=node_payload.model_dump(),
            )
            await self._store.append(node_event)
            await self._projector.project([node_event])

        return MergeResult(
            created_count=len(node_ids),
            matched_count=len(plan.matched),
            node_ids=node_ids,
        )

    @staticmethod
    def _graft_root(
        node: ImportedNode, plan: MergePlan
    ) -> str | None:
        """Find the matched parent that a new node ultimately grafts onto."""
        current = node
        while current.parent_temp_id and current.parent_temp_id not in plan.matched:
            # Walk up through new nodes
            parent = next(
                (n for n in plan.new_nodes if n.temp_id == current.parent_temp_id),
                None,
            )
            if parent is None:
                break
            current = parent
        return plan.graft_map.get(current.temp_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TreeNotFoundError(Exception):
    def __init__(self, tree_id: str) -> None:
        self.tree_id = tree_id
        super().__init__(f"Tree not found: {tree_id}")


def detect_format_safe(data: dict | list) -> str:
    """Detect format, wrapping ImportFormatError for clarity."""
    from qivis.importer.parsers.detection import detect_format

    return detect_format(data)
