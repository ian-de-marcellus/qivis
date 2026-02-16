"""State projector: projects events into materialized tables.

The read side of the CQRS pattern. Currently handles TreeCreated and
NodeCreated events. New handlers are added as their subphases arrive.
"""

import json
import logging
from collections.abc import Awaitable, Callable

from qivis.db.connection import Database
from qivis.models import (
    EventEnvelope,
    NodeContentEditedPayload,
    NodeCreatedPayload,
    TreeCreatedPayload,
    TreeMetadataUpdatedPayload,
)

logger = logging.getLogger(__name__)


class StateProjector:
    """Projects events into materialized SQL tables (trees, nodes)."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._handlers: dict[str, Callable[[EventEnvelope], Awaitable[None]]] = {
            "TreeCreated": self._handle_tree_created,
            "TreeMetadataUpdated": self._handle_tree_metadata_updated,
            "NodeCreated": self._handle_node_created,
            "NodeContentEdited": self._handle_node_content_edited,
            "GenerationStarted": self._handle_generation_started,
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

    _UPDATABLE_TREE_FIELDS = {
        "title",
        "metadata",
        "default_model",
        "default_provider",
        "default_system_prompt",
        "default_sampling_params",
    }

    async def _handle_tree_metadata_updated(self, event: EventEnvelope) -> None:
        """Project a TreeMetadataUpdated event: update a single tree column."""
        payload = TreeMetadataUpdatedPayload.model_validate(event.payload)

        if payload.field not in self._UPDATABLE_TREE_FIELDS:
            logger.warning(
                "TreeMetadataUpdated: unknown field %r, skipping", payload.field
            )
            return

        value = payload.new_value
        if payload.field in ("default_sampling_params", "metadata") and value is not None:
            value = json.dumps(value)

        timestamp = (
            event.timestamp.isoformat()
            if hasattr(event.timestamp, "isoformat")
            else str(event.timestamp)
        )

        await self._db.execute(
            f"UPDATE trees SET {payload.field} = ?, updated_at = ? WHERE tree_id = ?",
            (value, timestamp, event.tree_id),
        )

    async def _handle_node_content_edited(self, event: EventEnvelope) -> None:
        """Project a NodeContentEdited event: set/clear edited_content on a node."""
        payload = NodeContentEditedPayload.model_validate(event.payload)
        await self._db.execute(
            "UPDATE nodes SET edited_content = ? WHERE node_id = ?",
            (payload.new_content, payload.node_id),
        )

    async def _handle_generation_started(self, event: EventEnvelope) -> None:
        """GenerationStarted is recorded in the event log but does not project
        to any materialized table. Registered for explicitness."""

    async def _handle_node_created(self, event: EventEnvelope) -> None:
        """Project a NodeCreated event into the nodes table."""
        payload = NodeCreatedPayload.model_validate(event.payload)
        await self._db.execute(
            """
            INSERT OR REPLACE INTO nodes
                (node_id, tree_id, parent_id, role, content, model, provider,
                 system_prompt, sampling_params, mode, usage, latency_ms,
                 finish_reason, logprobs, context_usage, participant_id,
                 participant_name, thinking_content, created_at, archived)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
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
                payload.thinking_content,
                event.timestamp.isoformat()
                if hasattr(event.timestamp, "isoformat")
                else str(event.timestamp),
            ),
        )
