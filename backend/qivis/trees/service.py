"""Tree service: coordinates EventStore and StateProjector for tree/node operations."""

import json
from collections import defaultdict
from datetime import UTC, datetime
from uuid import uuid4

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.models import (
    EventEnvelope,
    NodeContentEditedPayload,
    NodeCreatedPayload,
    TreeCreatedPayload,
    TreeMetadataUpdatedPayload,
)
from qivis.trees.schemas import (
    CreateNodeRequest,
    CreateTreeRequest,
    EditHistoryEntry,
    EditHistoryResponse,
    NodeResponse,
    PatchNodeContentRequest,
    PatchTreeRequest,
    TreeDetailResponse,
    TreeSummary,
)


class TreeService:
    """Coordinates event store and projector for tree/node CRUD."""

    def __init__(self, db: Database) -> None:
        self._store = EventStore(db)
        self._projector = StateProjector(db)
        self._db = db

    async def create_tree(self, request: CreateTreeRequest) -> TreeDetailResponse:
        """Create a new tree. Emits TreeCreated, projects, returns the tree."""
        tree_id = str(uuid4())
        now = datetime.now(UTC)

        payload = TreeCreatedPayload(
            title=request.title,
            default_system_prompt=request.default_system_prompt,
            default_model=request.default_model,
            default_provider=request.default_provider,
            default_sampling_params=request.default_sampling_params,
        )

        event = EventEnvelope(
            event_id=str(uuid4()),
            tree_id=tree_id,
            timestamp=now,
            device_id="local",
            event_type="TreeCreated",
            payload=payload.model_dump(),
        )

        await self._store.append(event)
        await self._projector.project([event])

        tree = await self._projector.get_tree(tree_id)
        assert tree is not None
        return self._tree_detail_from_row(tree, [])

    async def update_tree(
        self, tree_id: str, request: PatchTreeRequest
    ) -> TreeDetailResponse:
        """Update tree metadata. Emits one TreeMetadataUpdated per changed field."""
        tree = await self._projector.get_tree(tree_id)
        if tree is None:
            raise TreeNotFoundError(tree_id)

        # Map PatchTreeRequest fields to their current projected values
        field_to_current = {
            "title": tree["title"],
            "metadata": (
                json.loads(tree["metadata"])
                if isinstance(tree["metadata"], str) and tree["metadata"]
                else tree["metadata"] or {}
            ),
            "default_model": tree["default_model"],
            "default_provider": tree["default_provider"],
            "default_system_prompt": tree["default_system_prompt"],
            "default_sampling_params": (
                json.loads(tree["default_sampling_params"])
                if isinstance(tree["default_sampling_params"], str)
                and tree["default_sampling_params"]
                else None
            ),
        }

        now = datetime.now(UTC)
        events: list[EventEnvelope] = []

        for field_name in request.model_fields_set:
            new_value = getattr(request, field_name)
            # Normalize SamplingParams to dict for comparison
            if hasattr(new_value, "model_dump"):
                new_value = new_value.model_dump()

            old_value = field_to_current.get(field_name)
            if new_value == old_value:
                continue

            payload = TreeMetadataUpdatedPayload(
                field=field_name,
                old_value=old_value,
                new_value=new_value,
            )
            event = EventEnvelope(
                event_id=str(uuid4()),
                tree_id=tree_id,
                timestamp=now,
                device_id="local",
                event_type="TreeMetadataUpdated",
                payload=payload.model_dump(),
            )
            events.append(event)

        for event in events:
            await self._store.append(event)
        if events:
            await self._projector.project(events)

        # Read back the full tree with nodes
        updated_tree = await self._projector.get_tree(tree_id)
        assert updated_tree is not None
        nodes = await self._projector.get_nodes(tree_id)
        return self._tree_detail_from_row(updated_tree, nodes)

    async def get_tree(self, tree_id: str) -> TreeDetailResponse | None:
        """Get a tree with all its nodes. Returns None if not found."""
        tree = await self._projector.get_tree(tree_id)
        if tree is None:
            return None
        nodes = await self._projector.get_nodes(tree_id)
        return self._tree_detail_from_row(tree, nodes)

    async def list_trees(self) -> list[TreeSummary]:
        """List all non-archived trees."""
        rows = await self._db.fetchall(
            "SELECT tree_id, title, conversation_mode, created_at, updated_at "
            "FROM trees WHERE archived = 0 ORDER BY created_at DESC"
        )
        return [
            TreeSummary(
                tree_id=row["tree_id"],
                title=row["title"],
                conversation_mode=row["conversation_mode"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    async def create_node(
        self, tree_id: str, request: CreateNodeRequest
    ) -> NodeResponse:
        """Add a user message to a tree. Validates tree exists and parent_id is valid."""
        tree = await self._projector.get_tree(tree_id)
        if tree is None:
            raise TreeNotFoundError(tree_id)

        if request.parent_id is not None:
            nodes = await self._projector.get_nodes(tree_id)
            node_ids = {n["node_id"] for n in nodes}
            if request.parent_id not in node_ids:
                raise InvalidParentError(request.parent_id)

        node_id = str(uuid4())
        now = datetime.now(UTC)

        payload = NodeCreatedPayload(
            node_id=node_id,
            parent_id=request.parent_id,
            role=request.role,
            content=request.content,
            mode=request.mode,
        )

        event = EventEnvelope(
            event_id=str(uuid4()),
            tree_id=tree_id,
            timestamp=now,
            device_id="local",
            event_type="NodeCreated",
            payload=payload.model_dump(),
        )

        await self._store.append(event)
        await self._projector.project([event])

        # Read back the projected node with sibling info
        nodes = await self._projector.get_nodes(tree_id)
        sibling_info = self._compute_sibling_info(nodes)
        node_row = next(n for n in nodes if n["node_id"] == node_id)
        return self._node_from_row(node_row, sibling_info=sibling_info)

    async def edit_node_content(
        self, tree_id: str, node_id: str, edited_content: str | None,
    ) -> NodeResponse:
        """Edit a node's content overlay. Emits NodeContentEdited event.

        Normalization: empty string -> None, same-as-original -> None.
        """
        tree = await self._projector.get_tree(tree_id)
        if tree is None:
            raise TreeNotFoundError(tree_id)

        nodes = await self._projector.get_nodes(tree_id)
        node_row = next((n for n in nodes if n["node_id"] == node_id), None)
        if node_row is None:
            raise NodeNotFoundError(node_id)

        # Normalize: empty string -> None, same-as-original -> None
        if edited_content is not None:
            edited_content = edited_content.strip() if edited_content else None
        if edited_content == node_row["content"]:
            edited_content = None
        if edited_content == "":
            edited_content = None

        now = datetime.now(UTC)
        payload = NodeContentEditedPayload(
            node_id=node_id,
            original_content=node_row["content"],
            new_content=edited_content,
        )
        event = EventEnvelope(
            event_id=str(uuid4()),
            tree_id=tree_id,
            timestamp=now,
            device_id="local",
            event_type="NodeContentEdited",
            payload=payload.model_dump(),
        )

        await self._store.append(event)
        await self._projector.project([event])

        # Read back with sibling info
        nodes = await self._projector.get_nodes(tree_id)
        sibling_info = self._compute_sibling_info(nodes)
        updated_row = next(n for n in nodes if n["node_id"] == node_id)
        return self._node_from_row(updated_row, sibling_info=sibling_info)

    async def get_edit_history(
        self, tree_id: str, node_id: str,
    ) -> EditHistoryResponse:
        """Get the edit history for a node from the event log."""
        tree = await self._projector.get_tree(tree_id)
        if tree is None:
            raise TreeNotFoundError(tree_id)

        nodes = await self._projector.get_nodes(tree_id)
        node_row = next((n for n in nodes if n["node_id"] == node_id), None)
        if node_row is None:
            raise NodeNotFoundError(node_id)

        events = await self._store.get_events_by_type(tree_id, "NodeContentEdited")
        entries = [
            EditHistoryEntry(
                event_id=ev.event_id,
                sequence_num=ev.sequence_num,
                timestamp=ev.timestamp.isoformat() if hasattr(ev.timestamp, 'isoformat') else str(ev.timestamp),
                new_content=ev.payload["new_content"],
            )
            for ev in events
            if ev.payload["node_id"] == node_id
        ]

        current_content = node_row.get("edited_content") or node_row["content"]

        return EditHistoryResponse(
            node_id=node_id,
            original_content=node_row["content"],
            current_content=current_content,
            entries=entries,
        )

    @staticmethod
    def _compute_sibling_info(
        node_rows: list[dict],
    ) -> dict[str, tuple[int, int]]:
        """Compute (sibling_index, sibling_count) for each node.

        Groups nodes by parent_id, orders by created_at (already guaranteed
        by the projector query), returns {node_id: (index, count)}.
        """
        parent_groups: dict[str | None, list[str]] = defaultdict(list)
        for row in node_rows:
            parent_groups[row["parent_id"]].append(row["node_id"])

        result: dict[str, tuple[int, int]] = {}
        for children in parent_groups.values():
            count = len(children)
            for idx, node_id in enumerate(children):
                result[node_id] = (idx, count)
        return result

    @staticmethod
    def _tree_detail_from_row(row: dict, node_rows: list[dict]) -> TreeDetailResponse:
        """Convert a projected tree row + node rows to a response."""
        sibling_info = TreeService._compute_sibling_info(node_rows)
        return TreeDetailResponse(
            tree_id=row["tree_id"],
            title=row["title"],
            metadata=(
                json.loads(row["metadata"])
                if isinstance(row["metadata"], str)
                else row["metadata"]
            ),
            default_model=row["default_model"],
            default_provider=row["default_provider"],
            default_system_prompt=row["default_system_prompt"],
            default_sampling_params=(
                json.loads(row["default_sampling_params"])
                if isinstance(row["default_sampling_params"], str)
                and row["default_sampling_params"]
                else None
            ),
            conversation_mode=row["conversation_mode"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            archived=row["archived"],
            nodes=[
                TreeService._node_from_row(n, sibling_info=sibling_info)
                for n in node_rows
            ],
        )

    @staticmethod
    def _node_from_row(
        row: dict,
        *,
        sibling_info: dict[str, tuple[int, int]] | None = None,
    ) -> NodeResponse:
        """Convert a projected node row to a response."""

        def maybe_json(val: object) -> dict | None:
            if val is None:
                return None
            if isinstance(val, str):
                return json.loads(val)
            return val  # type: ignore[return-value]

        si, sc = (0, 1)
        if sibling_info is not None and row["node_id"] in sibling_info:
            si, sc = sibling_info[row["node_id"]]

        return NodeResponse(
            node_id=row["node_id"],
            tree_id=row["tree_id"],
            parent_id=row["parent_id"],
            role=row["role"],
            content=row["content"],
            model=row["model"],
            provider=row["provider"],
            system_prompt=row["system_prompt"],
            sampling_params=maybe_json(row["sampling_params"]),
            mode=row["mode"],
            usage=maybe_json(row["usage"]),
            latency_ms=row["latency_ms"],
            finish_reason=row["finish_reason"],
            logprobs=maybe_json(row["logprobs"]),
            context_usage=maybe_json(row["context_usage"]),
            participant_id=row["participant_id"],
            participant_name=row["participant_name"],
            thinking_content=row.get("thinking_content"),
            edited_content=row.get("edited_content"),
            created_at=row["created_at"],
            archived=row["archived"],
            sibling_index=si,
            sibling_count=sc,
        )


class TreeNotFoundError(Exception):
    def __init__(self, tree_id: str) -> None:
        self.tree_id = tree_id
        super().__init__(f"Tree not found: {tree_id}")


class NodeNotFoundError(Exception):
    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        super().__init__(f"Node not found: {node_id}")


class InvalidParentError(Exception):
    def __init__(self, parent_id: str) -> None:
        self.parent_id = parent_id
        super().__init__(f"Invalid parent node: {parent_id}")
