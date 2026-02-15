"""State projector: projects events into materialized tables.

The read side of the CQRS pattern. Currently handles TreeCreated and
NodeCreated events. New handlers are added as their subphases arrive.
"""

import json
from collections.abc import Awaitable, Callable

from qivis.db.connection import Database
from qivis.models import EventEnvelope, NodeCreatedPayload, TreeCreatedPayload


class StateProjector:
    """Projects events into materialized SQL tables (trees, nodes)."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._handlers: dict[str, Callable[[EventEnvelope], Awaitable[None]]] = {
            "TreeCreated": self._handle_tree_created,
            "NodeCreated": self._handle_node_created,
        }

    async def project(self, events: list[EventEnvelope]) -> None:
        """Project a batch of events into materialized tables."""
        for event in events:
            handler = self._handlers.get(event.event_type)
            if handler:
                await handler(event)

    async def get_tree(self, tree_id: str) -> dict | None:
        """Read projected tree state. Returns None if not found."""
        row = await self._db.fetchone(
            "SELECT * FROM trees WHERE tree_id = ?", (tree_id,)
        )
        if row is None:
            return None
        return dict(row)

    async def get_nodes(self, tree_id: str) -> list[dict]:
        """Read projected nodes for a tree, ordered by creation time."""
        rows = await self._db.fetchall(
            "SELECT * FROM nodes WHERE tree_id = ? ORDER BY created_at",
            (tree_id,),
        )
        return [dict(row) for row in rows]

    async def _handle_tree_created(self, event: EventEnvelope) -> None:
        """Project a TreeCreated event into the trees table."""
        payload = TreeCreatedPayload.model_validate(event.payload)
        await self._db.execute(
            """
            INSERT OR REPLACE INTO trees
                (tree_id, title, metadata, default_model, default_provider,
                 default_system_prompt, default_sampling_params, conversation_mode,
                 created_at, updated_at, archived)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                event.tree_id,
                payload.title,
                json.dumps(payload.metadata),
                payload.default_model,
                payload.default_provider,
                payload.default_system_prompt,
                json.dumps(payload.default_sampling_params.model_dump())
                if payload.default_sampling_params
                else None,
                payload.conversation_mode,
                event.timestamp.isoformat()
                if hasattr(event.timestamp, "isoformat")
                else str(event.timestamp),
                event.timestamp.isoformat()
                if hasattr(event.timestamp, "isoformat")
                else str(event.timestamp),
            ),
        )

    async def _handle_node_created(self, event: EventEnvelope) -> None:
        """Project a NodeCreated event into the nodes table."""
        payload = NodeCreatedPayload.model_validate(event.payload)
        await self._db.execute(
            """
            INSERT OR REPLACE INTO nodes
                (node_id, tree_id, parent_id, role, content, model, provider,
                 system_prompt, sampling_params, mode, usage, latency_ms,
                 finish_reason, logprobs, context_usage, participant_id,
                 participant_name, created_at, archived)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                payload.node_id,
                event.tree_id,
                payload.parent_id,
                payload.role,
                payload.content,
                payload.model,
                payload.provider,
                payload.system_prompt,
                json.dumps(payload.sampling_params.model_dump())
                if payload.sampling_params
                else None,
                payload.mode,
                json.dumps(payload.usage) if payload.usage else None,
                payload.latency_ms,
                payload.finish_reason,
                json.dumps(payload.logprobs.model_dump())
                if payload.logprobs
                else None,
                json.dumps(payload.context_usage.model_dump())
                if payload.context_usage
                else None,
                payload.participant_id,
                payload.participant_name,
                event.timestamp.isoformat()
                if hasattr(event.timestamp, "isoformat")
                else str(event.timestamp),
            ),
        )
