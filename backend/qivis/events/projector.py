"""State projector: projects events into materialized tables.

The read side of the CQRS pattern. Currently handles TreeCreated and
NodeCreated events. New handlers are added as their subphases arrive.
"""

import json
import logging
from collections.abc import Awaitable, Callable

from qivis.db.connection import Database
from qivis.models import (
    AnnotationAddedPayload,
    AnnotationRemovedPayload,
    BookmarkCreatedPayload,
    BookmarkRemovedPayload,
    BookmarkSummaryGeneratedPayload,
    DigressionGroupCreatedPayload,
    DigressionGroupToggledPayload,
    EventEnvelope,
    NodeAnchoredPayload,
    NodeContentEditedPayload,
    NodeContextExcludedPayload,
    NodeContextIncludedPayload,
    NodeCreatedPayload,
    NodeUnanchoredPayload,
    NoteAddedPayload,
    NoteRemovedPayload,
    SummaryGeneratedPayload,
    SummaryRemovedPayload,
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
            "AnnotationAdded": self._handle_annotation_added,
            "AnnotationRemoved": self._handle_annotation_removed,
            "BookmarkCreated": self._handle_bookmark_created,
            "BookmarkRemoved": self._handle_bookmark_removed,
            "BookmarkSummaryGenerated": self._handle_bookmark_summary_generated,
            "NodeContextExcluded": self._handle_node_context_excluded,
            "NodeContextIncluded": self._handle_node_context_included,
            "DigressionGroupCreated": self._handle_digression_group_created,
            "DigressionGroupToggled": self._handle_digression_group_toggled,
            "NodeAnchored": self._handle_node_anchored,
            "NodeUnanchored": self._handle_node_unanchored,
            "NoteAdded": self._handle_note_added,
            "NoteRemoved": self._handle_note_removed,
            "SummaryGenerated": self._handle_summary_generated,
            "SummaryRemoved": self._handle_summary_removed,
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

    async def _handle_annotation_added(self, event: EventEnvelope) -> None:
        """Project an AnnotationAdded event into the annotations table."""
        payload = AnnotationAddedPayload.model_validate(event.payload)
        timestamp = (
            event.timestamp.isoformat()
            if hasattr(event.timestamp, "isoformat")
            else str(event.timestamp)
        )
        value_json = json.dumps(payload.value) if payload.value is not None else None
        await self._db.execute(
            """
            INSERT OR REPLACE INTO annotations
                (annotation_id, tree_id, node_id, tag, value, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.annotation_id,
                event.tree_id,
                payload.node_id,
                payload.tag,
                value_json,
                payload.notes,
                timestamp,
            ),
        )

    async def _handle_annotation_removed(self, event: EventEnvelope) -> None:
        """Project an AnnotationRemoved event: delete from annotations table."""
        payload = AnnotationRemovedPayload.model_validate(event.payload)
        await self._db.execute(
            "DELETE FROM annotations WHERE annotation_id = ?",
            (payload.annotation_id,),
        )

    async def _handle_bookmark_created(self, event: EventEnvelope) -> None:
        """Project a BookmarkCreated event into the bookmarks table."""
        payload = BookmarkCreatedPayload.model_validate(event.payload)
        timestamp = (
            event.timestamp.isoformat()
            if hasattr(event.timestamp, "isoformat")
            else str(event.timestamp)
        )
        await self._db.execute(
            """
            INSERT OR REPLACE INTO bookmarks
                (bookmark_id, tree_id, node_id, label, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                payload.bookmark_id,
                event.tree_id,
                payload.node_id,
                payload.label,
                payload.notes,
                timestamp,
            ),
        )

    async def _handle_bookmark_removed(self, event: EventEnvelope) -> None:
        """Project a BookmarkRemoved event: delete from bookmarks table."""
        payload = BookmarkRemovedPayload.model_validate(event.payload)
        await self._db.execute(
            "DELETE FROM bookmarks WHERE bookmark_id = ?",
            (payload.bookmark_id,),
        )

    async def _handle_bookmark_summary_generated(self, event: EventEnvelope) -> None:
        """Project a BookmarkSummaryGenerated event: update summary fields."""
        payload = BookmarkSummaryGeneratedPayload.model_validate(event.payload)
        await self._db.execute(
            """
            UPDATE bookmarks
            SET summary = ?, summary_model = ?, summarized_node_ids = ?
            WHERE bookmark_id = ?
            """,
            (
                payload.summary,
                payload.model,
                json.dumps(payload.summarized_node_ids),
                payload.bookmark_id,
            ),
        )

    async def get_node_exclusions(self, tree_id: str) -> list[dict]:
        """Read all node exclusions for a tree."""
        rows = await self._db.fetchall(
            "SELECT * FROM node_exclusions WHERE tree_id = ?",
            (tree_id,),
        )
        return [dict(row) for row in rows]

    async def get_digression_groups(self, tree_id: str) -> list[dict]:
        """Read all digression groups for a tree, with member node_ids."""
        group_rows = await self._db.fetchall(
            "SELECT * FROM digression_groups WHERE tree_id = ?",
            (tree_id,),
        )
        groups = []
        for row in group_rows:
            member_rows = await self._db.fetchall(
                "SELECT node_id FROM digression_group_nodes WHERE group_id = ? ORDER BY sort_order",
                (row["group_id"],),
            )
            groups.append({
                **dict(row),
                "node_ids": [m["node_id"] for m in member_rows],
            })
        return groups

    async def _handle_node_context_excluded(self, event: EventEnvelope) -> None:
        """Project a NodeContextExcluded event into node_exclusions."""
        payload = NodeContextExcludedPayload.model_validate(event.payload)
        timestamp = (
            event.timestamp.isoformat()
            if hasattr(event.timestamp, "isoformat")
            else str(event.timestamp)
        )
        await self._db.execute(
            """
            INSERT OR REPLACE INTO node_exclusions
                (tree_id, node_id, scope_node_id, reason, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                event.tree_id,
                payload.node_id,
                payload.scope_node_id,
                payload.reason,
                timestamp,
            ),
        )

    async def _handle_node_context_included(self, event: EventEnvelope) -> None:
        """Project a NodeContextIncluded event: remove matching exclusion."""
        payload = NodeContextIncludedPayload.model_validate(event.payload)
        await self._db.execute(
            "DELETE FROM node_exclusions WHERE tree_id = ? AND node_id = ? AND scope_node_id = ?",
            (event.tree_id, payload.node_id, payload.scope_node_id),
        )

    async def _handle_digression_group_created(self, event: EventEnvelope) -> None:
        """Project a DigressionGroupCreated event into groups + membership."""
        payload = DigressionGroupCreatedPayload.model_validate(event.payload)
        timestamp = (
            event.timestamp.isoformat()
            if hasattr(event.timestamp, "isoformat")
            else str(event.timestamp)
        )
        included = 0 if payload.excluded_by_default else 1
        await self._db.execute(
            """
            INSERT OR REPLACE INTO digression_groups
                (group_id, tree_id, label, included, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (payload.group_id, event.tree_id, payload.label, included, timestamp),
        )
        for i, node_id in enumerate(payload.node_ids):
            await self._db.execute(
                """
                INSERT OR REPLACE INTO digression_group_nodes
                    (group_id, node_id, sort_order)
                VALUES (?, ?, ?)
                """,
                (payload.group_id, node_id, i),
            )

    async def _handle_digression_group_toggled(self, event: EventEnvelope) -> None:
        """Project a DigressionGroupToggled event: update included flag."""
        payload = DigressionGroupToggledPayload.model_validate(event.payload)
        await self._db.execute(
            "UPDATE digression_groups SET included = ? WHERE group_id = ?",
            (1 if payload.included else 0, payload.group_id),
        )

    async def _handle_node_anchored(self, event: EventEnvelope) -> None:
        """Project a NodeAnchored event into the node_anchors table."""
        payload = NodeAnchoredPayload.model_validate(event.payload)
        timestamp = (
            event.timestamp.isoformat()
            if hasattr(event.timestamp, "isoformat")
            else str(event.timestamp)
        )
        await self._db.execute(
            """
            INSERT OR REPLACE INTO node_anchors
                (tree_id, node_id, created_at)
            VALUES (?, ?, ?)
            """,
            (event.tree_id, payload.node_id, timestamp),
        )

    async def _handle_node_unanchored(self, event: EventEnvelope) -> None:
        """Project a NodeUnanchored event: delete from node_anchors table."""
        payload = NodeUnanchoredPayload.model_validate(event.payload)
        await self._db.execute(
            "DELETE FROM node_anchors WHERE tree_id = ? AND node_id = ?",
            (event.tree_id, payload.node_id),
        )

    async def _handle_note_added(self, event: EventEnvelope) -> None:
        """Project a NoteAdded event into the notes table."""
        payload = NoteAddedPayload.model_validate(event.payload)
        timestamp = (
            event.timestamp.isoformat()
            if hasattr(event.timestamp, "isoformat")
            else str(event.timestamp)
        )
        await self._db.execute(
            """
            INSERT OR REPLACE INTO notes
                (note_id, tree_id, node_id, content, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                payload.note_id,
                event.tree_id,
                payload.node_id,
                payload.content,
                timestamp,
            ),
        )

    async def _handle_note_removed(self, event: EventEnvelope) -> None:
        """Project a NoteRemoved event: delete from notes table."""
        payload = NoteRemovedPayload.model_validate(event.payload)
        await self._db.execute(
            "DELETE FROM notes WHERE note_id = ?",
            (payload.note_id,),
        )

    async def _handle_summary_generated(self, event: EventEnvelope) -> None:
        """Project a SummaryGenerated event into the summaries table."""
        payload = SummaryGeneratedPayload.model_validate(event.payload)
        timestamp = (
            event.timestamp.isoformat()
            if hasattr(event.timestamp, "isoformat")
            else str(event.timestamp)
        )
        await self._db.execute(
            """
            INSERT OR REPLACE INTO summaries
                (summary_id, tree_id, anchor_node_id, scope, summary_type,
                 summary, model, node_ids, prompt_used, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.summary_id,
                event.tree_id,
                payload.anchor_node_id,
                payload.scope,
                payload.summary_type,
                payload.summary,
                payload.model,
                json.dumps(payload.node_ids),
                payload.prompt_used,
                timestamp,
            ),
        )

    async def _handle_summary_removed(self, event: EventEnvelope) -> None:
        """Project a SummaryRemoved event: delete from summaries table."""
        payload = SummaryRemovedPayload.model_validate(event.payload)
        await self._db.execute(
            "DELETE FROM summaries WHERE summary_id = ?",
            (payload.summary_id,),
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
                 participant_name, thinking_content,
                 include_thinking_in_context, include_timestamps,
                 created_at, archived)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
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
                1 if payload.include_thinking_in_context else 0,
                1 if payload.include_timestamps else 0,
                event.timestamp.isoformat()
                if hasattr(event.timestamp, "isoformat")
                else str(event.timestamp),
            ),
        )
