"""State projector: projects events into materialized tables.

The read side of the CQRS pattern. Currently handles RhizomeCreated and
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
    PerturbationReportGeneratedPayload,
    PerturbationReportRemovedPayload,
    RhizomeArchivedPayload,
    RhizomeCreatedPayload,
    RhizomeMetadataUpdatedPayload,
    RhizomeUnarchivedPayload,
    SummaryGeneratedPayload,
    SummaryRemovedPayload,
)

logger = logging.getLogger(__name__)


class StateProjector:
    """Projects events into materialized SQL tables (rhizomes, nodes)."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._handlers: dict[str, Callable[[EventEnvelope], Awaitable[None]]] = {
            # Current event type names
            "RhizomeCreated": self._handle_rhizome_created,
            "RhizomeMetadataUpdated": self._handle_rhizome_metadata_updated,
            "RhizomeArchived": self._handle_rhizome_archived,
            "RhizomeUnarchived": self._handle_rhizome_unarchived,
            # Backward compat: old event type names
            "TreeCreated": self._handle_rhizome_created,
            "TreeMetadataUpdated": self._handle_rhizome_metadata_updated,
            "TreeArchived": self._handle_rhizome_archived,
            "TreeUnarchived": self._handle_rhizome_unarchived,
            # Non-rhizome event types
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
            "PerturbationReportGenerated": self._handle_perturbation_report_generated,
            "PerturbationReportRemoved": self._handle_perturbation_report_removed,
        }

    async def project(self, events: list[EventEnvelope]) -> None:
        """Project a batch of events into materialized tables."""
        for event in events:
            handler = self._handlers.get(event.event_type)
            if handler:
                await handler(event)

    async def get_rhizome(self, rhizome_id: str) -> dict | None:
        """Read projected rhizome state. Returns None if not found."""
        row = await self._db.fetchone(
            "SELECT * FROM rhizomes WHERE rhizome_id = ?", (rhizome_id,)
        )
        if row is None:
            return None
        return dict(row)

    async def get_nodes(self, rhizome_id: str) -> list[dict]:
        """Read projected nodes for a rhizome, ordered by creation time."""
        rows = await self._db.fetchall(
            "SELECT * FROM nodes WHERE rhizome_id = ? ORDER BY created_at",
            (rhizome_id,),
        )
        return [dict(row) for row in rows]

    async def _handle_rhizome_created(self, event: EventEnvelope) -> None:
        """Project a RhizomeCreated event into the rhizomes table."""
        payload = RhizomeCreatedPayload.model_validate(event.payload)
        await self._db.execute(
            """
            INSERT OR REPLACE INTO rhizomes
                (rhizome_id, title, metadata, default_model, default_provider,
                 default_system_prompt, default_sampling_params, conversation_mode,
                 created_at, updated_at, archived)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                event.rhizome_id,
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

    _UPDATABLE_RHIZOME_FIELDS = {
        "title",
        "metadata",
        "default_model",
        "default_provider",
        "default_system_prompt",
        "default_sampling_params",
    }

    async def _handle_rhizome_metadata_updated(self, event: EventEnvelope) -> None:
        """Project a RhizomeMetadataUpdated event: update a single rhizome column."""
        payload = RhizomeMetadataUpdatedPayload.model_validate(event.payload)

        if payload.field not in self._UPDATABLE_RHIZOME_FIELDS:
            logger.warning(
                "RhizomeMetadataUpdated: unknown field %r, skipping", payload.field
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
            f"UPDATE rhizomes SET {payload.field} = ?, updated_at = ? WHERE rhizome_id = ?",
            (value, timestamp, event.rhizome_id),
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
                (annotation_id, rhizome_id, node_id, tag, value, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.annotation_id,
                event.rhizome_id,
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
                (bookmark_id, rhizome_id, node_id, label, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                payload.bookmark_id,
                event.rhizome_id,
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

    async def get_node_exclusions(self, rhizome_id: str) -> list[dict]:
        """Read all node exclusions for a rhizome."""
        rows = await self._db.fetchall(
            "SELECT * FROM node_exclusions WHERE rhizome_id = ?",
            (rhizome_id,),
        )
        return [dict(row) for row in rows]

    async def get_digression_groups(self, rhizome_id: str) -> list[dict]:
        """Read all digression groups for a rhizome, with member node_ids."""
        group_rows = await self._db.fetchall(
            "SELECT * FROM digression_groups WHERE rhizome_id = ?",
            (rhizome_id,),
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
                (rhizome_id, node_id, scope_node_id, reason, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                event.rhizome_id,
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
            "DELETE FROM node_exclusions WHERE rhizome_id = ? AND node_id = ? AND scope_node_id = ?",
            (event.rhizome_id, payload.node_id, payload.scope_node_id),
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
                (group_id, rhizome_id, label, included, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (payload.group_id, event.rhizome_id, payload.label, included, timestamp),
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
                (rhizome_id, node_id, created_at)
            VALUES (?, ?, ?)
            """,
            (event.rhizome_id, payload.node_id, timestamp),
        )

    async def _handle_node_unanchored(self, event: EventEnvelope) -> None:
        """Project a NodeUnanchored event: delete from node_anchors table."""
        payload = NodeUnanchoredPayload.model_validate(event.payload)
        await self._db.execute(
            "DELETE FROM node_anchors WHERE rhizome_id = ? AND node_id = ?",
            (event.rhizome_id, payload.node_id),
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
                (note_id, rhizome_id, node_id, content, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                payload.note_id,
                event.rhizome_id,
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
                (summary_id, rhizome_id, anchor_node_id, scope, summary_type,
                 summary, model, node_ids, prompt_used, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.summary_id,
                event.rhizome_id,
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

    async def _handle_rhizome_archived(self, event: EventEnvelope) -> None:
        """Project a RhizomeArchived event: set archived = 1."""
        RhizomeArchivedPayload.model_validate(event.payload)
        timestamp = (
            event.timestamp.isoformat()
            if hasattr(event.timestamp, "isoformat")
            else str(event.timestamp)
        )
        await self._db.execute(
            "UPDATE rhizomes SET archived = 1, updated_at = ? WHERE rhizome_id = ?",
            (timestamp, event.rhizome_id),
        )

    async def _handle_rhizome_unarchived(self, event: EventEnvelope) -> None:
        """Project a RhizomeUnarchived event: set archived = 0."""
        RhizomeUnarchivedPayload.model_validate(event.payload)
        timestamp = (
            event.timestamp.isoformat()
            if hasattr(event.timestamp, "isoformat")
            else str(event.timestamp)
        )
        await self._db.execute(
            "UPDATE rhizomes SET archived = 0, updated_at = ? WHERE rhizome_id = ?",
            (timestamp, event.rhizome_id),
        )

    async def _handle_node_created(self, event: EventEnvelope) -> None:
        """Project a NodeCreated event into the nodes table."""
        payload = NodeCreatedPayload.model_validate(event.payload)
        await self._db.execute(
            """
            INSERT OR REPLACE INTO nodes
                (node_id, rhizome_id, parent_id, role, content, model, provider,
                 system_prompt, sampling_params, mode, usage, latency_ms,
                 finish_reason, logprobs, context_usage, participant_id,
                 participant_name, thinking_content,
                 include_thinking_in_context, include_timestamps,
                 prefill_content, prompt_text, active_interventions,
                 created_at, archived)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                payload.node_id,
                event.rhizome_id,
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
                payload.prefill_content,
                payload.prompt_text,
                json.dumps(payload.active_interventions)
                if payload.active_interventions
                else None,
                event.timestamp.isoformat()
                if hasattr(event.timestamp, "isoformat")
                else str(event.timestamp),
            ),
        )

    # -- Perturbation reports --

    async def _handle_perturbation_report_generated(self, event: EventEnvelope) -> None:
        """Project a PerturbationReportGenerated event into perturbation_reports."""
        payload = PerturbationReportGeneratedPayload.model_validate(event.payload)
        timestamp = (
            event.timestamp.isoformat()
            if hasattr(event.timestamp, "isoformat")
            else str(event.timestamp)
        )
        await self._db.execute(
            """
            INSERT OR REPLACE INTO perturbation_reports
                (report_id, rhizome_id, experiment_id, node_id,
                 provider, model, include_control, steps, divergence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.report_id,
                event.rhizome_id,
                payload.experiment_id,
                payload.node_id,
                payload.provider,
                payload.model,
                1 if payload.include_control else 0,
                json.dumps(payload.steps),
                json.dumps(payload.divergence),
                timestamp,
            ),
        )

    async def _handle_perturbation_report_removed(self, event: EventEnvelope) -> None:
        """Project a PerturbationReportRemoved event: delete from perturbation_reports."""
        payload = PerturbationReportRemovedPayload.model_validate(event.payload)
        await self._db.execute(
            "DELETE FROM perturbation_reports WHERE report_id = ?",
            (payload.report_id,),
        )

    async def get_perturbation_reports(self, rhizome_id: str) -> list[dict]:
        """Read all perturbation reports for a rhizome."""
        rows = await self._db.fetchall(
            "SELECT * FROM perturbation_reports WHERE rhizome_id = ? ORDER BY created_at DESC",
            (rhizome_id,),
        )
        return [dict(row) for row in rows]

    async def get_perturbation_report(self, report_id: str) -> dict | None:
        """Read a single perturbation report by ID."""
        row = await self._db.fetchone(
            "SELECT * FROM perturbation_reports WHERE report_id = ?",
            (report_id,),
        )
        return dict(row) if row else None
