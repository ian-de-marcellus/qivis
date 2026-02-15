"""Tree service: coordinates EventStore and StateProjector for tree/node operations."""

import json
from datetime import UTC, datetime
from uuid import uuid4

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.models import EventEnvelope, NodeCreatedPayload, TreeCreatedPayload
from qivis.trees.schemas import (
    CreateNodeRequest,
    CreateTreeRequest,
    NodeResponse,
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

        # Read back the projected node
        nodes = await self._projector.get_nodes(tree_id)
        node_row = next(n for n in nodes if n["node_id"] == node_id)
        return self._node_from_row(node_row)

    @staticmethod
    def _tree_detail_from_row(row: dict, node_rows: list[dict]) -> TreeDetailResponse:
        """Convert a projected tree row + node rows to a response."""
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
            nodes=[TreeService._node_from_row(n) for n in node_rows],
        )

    @staticmethod
    def _node_from_row(row: dict) -> NodeResponse:
        """Convert a projected node row to a response."""

        def maybe_json(val: object) -> dict | None:
            if val is None:
                return None
            if isinstance(val, str):
                return json.loads(val)
            return val  # type: ignore[return-value]

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
            created_at=row["created_at"],
            archived=row["archived"],
        )


class TreeNotFoundError(Exception):
    def __init__(self, tree_id: str) -> None:
        self.tree_id = tree_id
        super().__init__(f"Tree not found: {tree_id}")


class InvalidParentError(Exception):
    def __init__(self, parent_id: str) -> None:
        self.parent_id = parent_id
        super().__init__(f"Invalid parent node: {parent_id}")
