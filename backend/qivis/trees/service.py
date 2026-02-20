"""Tree service: coordinates EventStore and StateProjector for tree/node operations."""

from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
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
    TreeCreatedPayload,
    TreeMetadataUpdatedPayload,
)
from qivis.trees.schemas import (
    AddAnnotationRequest,
    AnnotationResponse,
    BookmarkResponse,
    CreateBookmarkRequest,
    CreateDigressionGroupRequest,
    CreateNodeRequest,
    CreateTreeRequest,
    DigressionGroupResponse,
    EditHistoryEntry,
    EditHistoryResponse,
    ExcludeNodeRequest,
    InterventionEntry,
    InterventionTimelineResponse,
    NodeExclusionResponse,
    NodeResponse,
    PatchNodeContentRequest,
    PatchTreeRequest,
    TaxonomyResponse,
    TreeDetailResponse,
    TreeSummary,
)
from qivis.utils.json import parse_json_field, parse_json_or_none

_TAXONOMY_PATH = Path(__file__).parent.parent / "annotation_taxonomy.yml"


class TreeService:
    """Coordinates event store and projector for tree/node CRUD."""

    def __init__(self, db: Database, summary_client: object | None = None) -> None:
        self._store = EventStore(db)
        self._projector = StateProjector(db)
        self._db = db
        self._summary_client = summary_client

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
            "metadata": parse_json_field(tree["metadata"]) or {},
            "default_model": tree["default_model"],
            "default_provider": tree["default_provider"],
            "default_system_prompt": tree["default_system_prompt"],
            "default_sampling_params": parse_json_field(tree["default_sampling_params"]),
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

        # Annotation counts per node
        ann_rows = await self._db.fetchall(
            "SELECT node_id, COUNT(*) as cnt FROM annotations WHERE tree_id = ? GROUP BY node_id",
            (tree_id,),
        )
        annotation_counts = {r["node_id"]: r["cnt"] for r in ann_rows}

        # Bookmarked node IDs
        bm_rows = await self._db.fetchall(
            "SELECT DISTINCT node_id FROM bookmarks WHERE tree_id = ?",
            (tree_id,),
        )
        bookmark_node_ids = {r["node_id"] for r in bm_rows}

        # Excluded node IDs (any node with at least one exclusion record)
        excl_rows = await self._db.fetchall(
            "SELECT DISTINCT node_id FROM node_exclusions WHERE tree_id = ?",
            (tree_id,),
        )
        excluded_node_ids = {r["node_id"] for r in excl_rows}

        # Anchored node IDs
        anchor_rows = await self._db.fetchall(
            "SELECT DISTINCT node_id FROM node_anchors WHERE tree_id = ?",
            (tree_id,),
        )
        anchored_node_ids = {r["node_id"] for r in anchor_rows}

        # Edit counts per node (from event log)
        edit_rows = await self._db.fetchall(
            "SELECT json_extract(payload, '$.node_id') as node_id, COUNT(*) as cnt "
            "FROM events WHERE tree_id = ? AND event_type = 'NodeContentEdited' "
            "GROUP BY json_extract(payload, '$.node_id')",
            (tree_id,),
        )
        edit_counts = {r["node_id"]: r["cnt"] for r in edit_rows}

        return self._tree_detail_from_row(
            tree, nodes,
            annotation_counts=annotation_counts,
            bookmark_node_ids=bookmark_node_ids,
            excluded_node_ids=excluded_node_ids,
            anchored_node_ids=anchored_node_ids,
            edit_counts=edit_counts,
        )

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

    async def get_intervention_timeline(
        self, tree_id: str,
    ) -> InterventionTimelineResponse:
        """Get all interventions (edits + system prompt changes) for a tree."""
        tree = await self._projector.get_tree(tree_id)
        if tree is None:
            raise TreeNotFoundError(tree_id)

        # Fetch edit events
        edit_events = await self._store.get_events_by_type(tree_id, "NodeContentEdited")

        # Fetch metadata events, filter for system prompt only
        metadata_events = await self._store.get_events_by_type(tree_id, "TreeMetadataUpdated")
        system_prompt_events = [
            ev for ev in metadata_events
            if ev.payload.get("field") == "default_system_prompt"
        ]

        # Build entries from edit events
        entries: list[InterventionEntry] = []
        for ev in edit_events:
            entries.append(InterventionEntry(
                event_id=ev.event_id,
                sequence_num=ev.sequence_num,
                timestamp=ev.timestamp.isoformat() if hasattr(ev.timestamp, "isoformat") else str(ev.timestamp),
                intervention_type="node_edited",
                node_id=ev.payload["node_id"],
                original_content=ev.payload.get("original_content"),
                new_content=ev.payload.get("new_content"),
            ))

        # Build entries from system prompt events
        for ev in system_prompt_events:
            entries.append(InterventionEntry(
                event_id=ev.event_id,
                sequence_num=ev.sequence_num,
                timestamp=ev.timestamp.isoformat() if hasattr(ev.timestamp, "isoformat") else str(ev.timestamp),
                intervention_type="system_prompt_changed",
                old_value=ev.payload.get("old_value"),
                new_value=ev.payload.get("new_value"),
            ))

        # Sort by sequence_num
        entries.sort(key=lambda e: e.sequence_num)

        return InterventionTimelineResponse(tree_id=tree_id, interventions=entries)

    # -- Annotation methods --

    async def add_annotation(
        self, tree_id: str, node_id: str, request: AddAnnotationRequest,
    ) -> AnnotationResponse:
        """Add an annotation to a node. Emits AnnotationAdded, projects, returns it."""
        tree = await self._projector.get_tree(tree_id)
        if tree is None:
            raise TreeNotFoundError(tree_id)

        nodes = await self._projector.get_nodes(tree_id)
        if not any(n["node_id"] == node_id for n in nodes):
            raise NodeNotFoundError(node_id)

        annotation_id = str(uuid4())
        now = datetime.now(UTC)

        payload = AnnotationAddedPayload(
            annotation_id=annotation_id,
            node_id=node_id,
            tag=request.tag,
            value=request.value,
            notes=request.notes,
        )
        event = EventEnvelope(
            event_id=str(uuid4()),
            tree_id=tree_id,
            timestamp=now,
            device_id="local",
            event_type="AnnotationAdded",
            payload=payload.model_dump(),
        )

        await self._store.append(event)
        await self._projector.project([event])

        row = await self._db.fetchone(
            "SELECT * FROM annotations WHERE annotation_id = ?",
            (annotation_id,),
        )
        assert row is not None
        return self._annotation_from_row(row)

    async def remove_annotation(
        self, tree_id: str, annotation_id: str, reason: str | None = None,
    ) -> None:
        """Remove an annotation. Emits AnnotationRemoved, projects."""
        row = await self._db.fetchone(
            "SELECT * FROM annotations WHERE annotation_id = ? AND tree_id = ?",
            (annotation_id, tree_id),
        )
        if row is None:
            raise AnnotationNotFoundError(annotation_id)

        now = datetime.now(UTC)
        payload = AnnotationRemovedPayload(
            annotation_id=annotation_id,
            reason=reason,
        )
        event = EventEnvelope(
            event_id=str(uuid4()),
            tree_id=tree_id,
            timestamp=now,
            device_id="local",
            event_type="AnnotationRemoved",
            payload=payload.model_dump(),
        )

        await self._store.append(event)
        await self._projector.project([event])

    async def get_node_annotations(
        self, tree_id: str, node_id: str,
    ) -> list[AnnotationResponse]:
        """Get all annotations for a node, sorted by created_at."""
        rows = await self._db.fetchall(
            "SELECT * FROM annotations WHERE node_id = ? AND tree_id = ? ORDER BY created_at",
            (node_id, tree_id),
        )
        return [self._annotation_from_row(r) for r in rows]

    async def get_tree_taxonomy(self, tree_id: str) -> TaxonomyResponse:
        """Get base tags + used tags for a tree."""
        tree = await self._projector.get_tree(tree_id)
        if tree is None:
            raise TreeNotFoundError(tree_id)

        # Load base tags
        base_tags: list[str] = []
        if _TAXONOMY_PATH.exists():
            with open(_TAXONOMY_PATH) as f:
                data = yaml.safe_load(f)
            base_tags = data.get("tags", [])

        # Get used tags
        rows = await self._db.fetchall(
            "SELECT DISTINCT tag FROM annotations WHERE tree_id = ?",
            (tree_id,),
        )
        used_tags = [r["tag"] for r in rows]

        return TaxonomyResponse(base_tags=base_tags, used_tags=used_tags)

    # -- Bookmark methods --

    async def add_bookmark(
        self, tree_id: str, node_id: str, request: CreateBookmarkRequest,
    ) -> BookmarkResponse:
        """Add a bookmark to a node. Emits BookmarkCreated, projects, returns it."""
        tree = await self._projector.get_tree(tree_id)
        if tree is None:
            raise TreeNotFoundError(tree_id)

        nodes = await self._projector.get_nodes(tree_id)
        if not any(n["node_id"] == node_id for n in nodes):
            raise NodeNotFoundError(node_id)

        bookmark_id = str(uuid4())
        now = datetime.now(UTC)

        payload = BookmarkCreatedPayload(
            bookmark_id=bookmark_id,
            node_id=node_id,
            label=request.label,
            notes=request.notes,
        )
        event = EventEnvelope(
            event_id=str(uuid4()),
            tree_id=tree_id,
            timestamp=now,
            device_id="local",
            event_type="BookmarkCreated",
            payload=payload.model_dump(),
        )

        await self._store.append(event)
        await self._projector.project([event])

        row = await self._db.fetchone(
            "SELECT * FROM bookmarks WHERE bookmark_id = ?",
            (bookmark_id,),
        )
        assert row is not None
        return self._bookmark_from_row(row)

    async def remove_bookmark(
        self, tree_id: str, bookmark_id: str,
    ) -> None:
        """Remove a bookmark. Emits BookmarkRemoved, projects."""
        row = await self._db.fetchone(
            "SELECT * FROM bookmarks WHERE bookmark_id = ? AND tree_id = ?",
            (bookmark_id, tree_id),
        )
        if row is None:
            raise BookmarkNotFoundError(bookmark_id)

        now = datetime.now(UTC)
        payload = BookmarkRemovedPayload(bookmark_id=bookmark_id)
        event = EventEnvelope(
            event_id=str(uuid4()),
            tree_id=tree_id,
            timestamp=now,
            device_id="local",
            event_type="BookmarkRemoved",
            payload=payload.model_dump(),
        )

        await self._store.append(event)
        await self._projector.project([event])

    async def get_tree_bookmarks(
        self, tree_id: str, query: str | None = None,
    ) -> list[BookmarkResponse]:
        """Get bookmarks for a tree, optionally filtered by search query."""
        if query:
            like = f"%{query}%"
            rows = await self._db.fetchall(
                """
                SELECT * FROM bookmarks
                WHERE tree_id = ? AND (label LIKE ? OR summary LIKE ? OR notes LIKE ?)
                ORDER BY created_at
                """,
                (tree_id, like, like, like),
            )
        else:
            rows = await self._db.fetchall(
                "SELECT * FROM bookmarks WHERE tree_id = ? ORDER BY created_at",
                (tree_id,),
            )
        return [self._bookmark_from_row(r) for r in rows]

    async def generate_bookmark_summary(
        self, tree_id: str, bookmark_id: str,
    ) -> BookmarkResponse:
        """Generate a summary for a bookmark's branch (root -> bookmarked node)."""
        if self._summary_client is None:
            raise SummaryClientNotConfiguredError()

        tree = await self._projector.get_tree(tree_id)
        if tree is None:
            raise TreeNotFoundError(tree_id)

        # Resolve summary model from tree's eviction strategy
        metadata = parse_json_field(tree.get("metadata")) or {}
        eviction_raw = metadata.get("eviction_strategy")
        summary_model = "claude-haiku-4-5-20251001"
        if isinstance(eviction_raw, dict) and "summary_model" in eviction_raw:
            summary_model = eviction_raw["summary_model"]

        bm_row = await self._db.fetchone(
            "SELECT * FROM bookmarks WHERE bookmark_id = ? AND tree_id = ?",
            (bookmark_id, tree_id),
        )
        if bm_row is None:
            raise BookmarkNotFoundError(bookmark_id)

        # Get all nodes and walk parent chain from bookmarked node to root
        nodes = await self._projector.get_nodes(tree_id)
        node_map = {n["node_id"]: n for n in nodes}

        path: list[dict] = []
        current = node_map.get(bm_row["node_id"])
        while current:
            path.append(current)
            current = node_map.get(current["parent_id"]) if current["parent_id"] else None
        path.reverse()  # root -> bookmarked node

        # Build conversation transcript for the prompt
        transcript_lines = []
        for n in path:
            content = n.get("edited_content") or n["content"]
            role = n["role"].capitalize()
            transcript_lines.append(f"{role}: {content}")
        transcript = "\n".join(transcript_lines)

        summarized_node_ids = [n["node_id"] for n in path]

        # Call the dedicated summary client
        response = await self._summary_client.messages.create(
            model=summary_model,
            max_tokens=100,
            system=(
                "You write terse research bookmark notes — like a post-it flag "
                "in a margin. One to two plain sentences, no markdown, no bullets, "
                "no headers. Third person. Emphasize the end of the branch — "
                "that's where it diverges. Finish your thought — never stop mid-sentence."
            ),
            messages=[
                {
                    "role": "user",
                    "content": f"Summarize this conversation branch:\n\n{transcript}",
                },
                {
                    "role": "assistant",
                    "content": "Branch note:",
                },
            ],
        )
        summary_text = response.content[0].text

        summary_text = response.content[0].text
        model_used = response.model

        # Emit BookmarkSummaryGenerated event
        now = datetime.now(UTC)
        payload = BookmarkSummaryGeneratedPayload(
            bookmark_id=bookmark_id,
            summary=summary_text,
            model=model_used,
            summarized_node_ids=summarized_node_ids,
        )
        event = EventEnvelope(
            event_id=str(uuid4()),
            tree_id=tree_id,
            timestamp=now,
            device_id="local",
            event_type="BookmarkSummaryGenerated",
            payload=payload.model_dump(),
        )

        await self._store.append(event)
        await self._projector.project([event])

        # Read back updated bookmark
        updated_row = await self._db.fetchone(
            "SELECT * FROM bookmarks WHERE bookmark_id = ?",
            (bookmark_id,),
        )
        assert updated_row is not None
        return self._bookmark_from_row(updated_row)

    async def generate_eviction_summary(
        self,
        evicted_content: list[str],
        *,
        model: str = "claude-haiku-4-5-20251001",
    ) -> str | None:
        """Generate a concise recap of evicted messages for context continuity.

        Returns the summary text, or None if no summary client is configured.
        """
        if self._summary_client is None:
            return None
        if not evicted_content:
            return None

        transcript = "\n".join(evicted_content)

        response = await self._summary_client.messages.create(
            model=model,
            max_tokens=200,
            system=(
                "You write concise conversation recaps for context continuity. "
                "Summarize the key points, decisions, and any important details "
                "from the evicted messages in 2-3 sentences. No markdown, no bullets. "
                "Write as a neutral observer."
            ),
            messages=[
                {
                    "role": "user",
                    "content": (
                        "These messages were removed from context due to length limits. "
                        f"Summarize them:\n\n{transcript}"
                    ),
                },
                {
                    "role": "assistant",
                    "content": "Summary:",
                },
            ],
        )
        return response.content[0].text

    # -- Context exclusion methods --

    async def exclude_node(
        self, tree_id: str, node_id: str, request: ExcludeNodeRequest,
    ) -> NodeExclusionResponse:
        """Exclude a node from context on a specific branch path."""
        tree = await self._projector.get_tree(tree_id)
        if tree is None:
            raise TreeNotFoundError(tree_id)

        nodes = await self._projector.get_nodes(tree_id)
        node_ids = {n["node_id"] for n in nodes}
        if node_id not in node_ids:
            raise NodeNotFoundError(node_id)
        if request.scope_node_id not in node_ids:
            raise NodeNotFoundError(request.scope_node_id)

        now = datetime.now(UTC)
        payload = NodeContextExcludedPayload(
            node_id=node_id,
            scope_node_id=request.scope_node_id,
            reason=request.reason,
        )
        event = EventEnvelope(
            event_id=str(uuid4()),
            tree_id=tree_id,
            timestamp=now,
            device_id="local",
            event_type="NodeContextExcluded",
            payload=payload.model_dump(),
        )

        await self._store.append(event)
        await self._projector.project([event])

        return NodeExclusionResponse(
            tree_id=tree_id,
            node_id=node_id,
            scope_node_id=request.scope_node_id,
            reason=request.reason,
            created_at=now.isoformat(),
        )

    async def include_node(
        self, tree_id: str, node_id: str, scope_node_id: str,
    ) -> None:
        """Re-include a previously excluded node (idempotent)."""
        now = datetime.now(UTC)
        payload = NodeContextIncludedPayload(
            node_id=node_id,
            scope_node_id=scope_node_id,
        )
        event = EventEnvelope(
            event_id=str(uuid4()),
            tree_id=tree_id,
            timestamp=now,
            device_id="local",
            event_type="NodeContextIncluded",
            payload=payload.model_dump(),
        )

        await self._store.append(event)
        await self._projector.project([event])

    async def get_tree_exclusions(
        self, tree_id: str,
    ) -> list[NodeExclusionResponse]:
        """Get all exclusions for a tree."""
        rows = await self._db.fetchall(
            "SELECT * FROM node_exclusions WHERE tree_id = ?",
            (tree_id,),
        )
        return [
            NodeExclusionResponse(
                tree_id=r["tree_id"],
                node_id=r["node_id"],
                scope_node_id=r["scope_node_id"],
                reason=r["reason"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    # -- Anchor methods --

    async def anchor_node(self, tree_id: str, node_id: str) -> bool:
        """Toggle anchor on a node. Returns True if now anchored, False if unanchored."""
        tree = await self._projector.get_tree(tree_id)
        if tree is None:
            raise TreeNotFoundError(tree_id)

        nodes = await self._projector.get_nodes(tree_id)
        node_ids = {n["node_id"] for n in nodes}
        if node_id not in node_ids:
            raise NodeNotFoundError(node_id)

        # Check current state
        row = await self._db.fetchone(
            "SELECT * FROM node_anchors WHERE tree_id = ? AND node_id = ?",
            (tree_id, node_id),
        )
        now = datetime.now(UTC)

        if row is not None:
            # Unanchor
            payload = NodeUnanchoredPayload(node_id=node_id)
            event = EventEnvelope(
                event_id=str(uuid4()),
                tree_id=tree_id,
                timestamp=now,
                device_id="local",
                event_type="NodeUnanchored",
                payload=payload.model_dump(),
            )
            await self._store.append(event)
            await self._projector.project([event])
            return False
        else:
            # Anchor
            payload = NodeAnchoredPayload(node_id=node_id)
            event = EventEnvelope(
                event_id=str(uuid4()),
                tree_id=tree_id,
                timestamp=now,
                device_id="local",
                event_type="NodeAnchored",
                payload=payload.model_dump(),
            )
            await self._store.append(event)
            await self._projector.project([event])
            return True

    async def bulk_anchor(
        self, tree_id: str, node_ids: list[str], anchor: bool,
    ) -> int:
        """Anchor or unanchor multiple nodes. Returns count of nodes that changed state."""
        tree = await self._projector.get_tree(tree_id)
        if tree is None:
            raise TreeNotFoundError(tree_id)

        nodes = await self._projector.get_nodes(tree_id)
        valid_ids = {n["node_id"] for n in nodes}

        # Get current anchor state for all requested nodes
        anchor_rows = await self._db.fetchall(
            "SELECT DISTINCT node_id FROM node_anchors WHERE tree_id = ?",
            (tree_id,),
        )
        currently_anchored = {r["node_id"] for r in anchor_rows}

        events: list[EventEnvelope] = []
        now = datetime.now(UTC)

        for nid in node_ids:
            if nid not in valid_ids:
                continue
            is_anchored = nid in currently_anchored
            if anchor and not is_anchored:
                payload = NodeAnchoredPayload(node_id=nid)
                events.append(EventEnvelope(
                    event_id=str(uuid4()),
                    tree_id=tree_id,
                    timestamp=now,
                    device_id="local",
                    event_type="NodeAnchored",
                    payload=payload.model_dump(),
                ))
            elif not anchor and is_anchored:
                payload = NodeUnanchoredPayload(node_id=nid)
                events.append(EventEnvelope(
                    event_id=str(uuid4()),
                    tree_id=tree_id,
                    timestamp=now,
                    device_id="local",
                    event_type="NodeUnanchored",
                    payload=payload.model_dump(),
                ))

        for event in events:
            await self._store.append(event)
        if events:
            await self._projector.project(events)

        return len(events)

    # -- Digression group methods --

    async def create_digression_group(
        self, tree_id: str, request: CreateDigressionGroupRequest,
    ) -> DigressionGroupResponse:
        """Create a digression group. Validates nodes exist and are contiguous."""
        tree = await self._projector.get_tree(tree_id)
        if tree is None:
            raise TreeNotFoundError(tree_id)

        nodes = await self._projector.get_nodes(tree_id)
        node_map = {n["node_id"]: n for n in nodes}

        # Validate all nodes exist in this tree
        for nid in request.node_ids:
            if nid not in node_map:
                raise NodeNotFoundError(nid)

        # Validate contiguity: nodes must form a contiguous segment of a parent chain
        if len(request.node_ids) > 1:
            # Build a quick child-of lookup
            ordered = request.node_ids
            for i in range(1, len(ordered)):
                child = node_map[ordered[i]]
                if child["parent_id"] != ordered[i - 1]:
                    raise NonContiguousGroupError(request.node_ids)

        group_id = str(uuid4())
        now = datetime.now(UTC)

        payload = DigressionGroupCreatedPayload(
            group_id=group_id,
            node_ids=request.node_ids,
            label=request.label,
            excluded_by_default=request.excluded_by_default,
        )
        event = EventEnvelope(
            event_id=str(uuid4()),
            tree_id=tree_id,
            timestamp=now,
            device_id="local",
            event_type="DigressionGroupCreated",
            payload=payload.model_dump(),
        )

        await self._store.append(event)
        await self._projector.project([event])

        return DigressionGroupResponse(
            group_id=group_id,
            tree_id=tree_id,
            label=request.label,
            node_ids=request.node_ids,
            included=not request.excluded_by_default,
            created_at=now.isoformat(),
        )

    async def get_digression_groups(
        self, tree_id: str,
    ) -> list[DigressionGroupResponse]:
        """Get all digression groups for a tree."""
        groups = await self._projector.get_digression_groups(tree_id)
        return [
            DigressionGroupResponse(
                group_id=g["group_id"],
                tree_id=g["tree_id"],
                label=g["label"],
                node_ids=g["node_ids"],
                included=bool(g["included"]),
                created_at=g["created_at"],
            )
            for g in groups
        ]

    async def toggle_digression_group(
        self, tree_id: str, group_id: str, included: bool,
    ) -> DigressionGroupResponse:
        """Toggle a digression group's included state."""
        row = await self._db.fetchone(
            "SELECT * FROM digression_groups WHERE group_id = ? AND tree_id = ?",
            (group_id, tree_id),
        )
        if row is None:
            raise DigressionGroupNotFoundError(group_id)

        now = datetime.now(UTC)
        payload = DigressionGroupToggledPayload(
            group_id=group_id,
            included=included,
        )
        event = EventEnvelope(
            event_id=str(uuid4()),
            tree_id=tree_id,
            timestamp=now,
            device_id="local",
            event_type="DigressionGroupToggled",
            payload=payload.model_dump(),
        )

        await self._store.append(event)
        await self._projector.project([event])

        # Read back with member nodes
        groups = await self._projector.get_digression_groups(tree_id)
        group = next(g for g in groups if g["group_id"] == group_id)
        return DigressionGroupResponse(
            group_id=group["group_id"],
            tree_id=group["tree_id"],
            label=group["label"],
            node_ids=group["node_ids"],
            included=bool(group["included"]),
            created_at=group["created_at"],
        )

    async def delete_digression_group(
        self, tree_id: str, group_id: str,
    ) -> None:
        """Delete a digression group. Direct projection deletion (no event)."""
        row = await self._db.fetchone(
            "SELECT * FROM digression_groups WHERE group_id = ? AND tree_id = ?",
            (group_id, tree_id),
        )
        if row is None:
            raise DigressionGroupNotFoundError(group_id)

        await self._db.execute(
            "DELETE FROM digression_group_nodes WHERE group_id = ?",
            (group_id,),
        )
        await self._db.execute(
            "DELETE FROM digression_groups WHERE group_id = ?",
            (group_id,),
        )

    @staticmethod
    def _bookmark_from_row(row: dict) -> BookmarkResponse:
        """Convert a projected bookmark row to a response."""
        summarized = parse_json_or_none(row["summarized_node_ids"])
        return BookmarkResponse(
            bookmark_id=row["bookmark_id"],
            tree_id=row["tree_id"],
            node_id=row["node_id"],
            label=row["label"],
            notes=row["notes"],
            summary=row["summary"],
            summary_model=row["summary_model"],
            summarized_node_ids=summarized,
            created_at=row["created_at"],
        )

    @staticmethod
    def _annotation_from_row(row: dict) -> AnnotationResponse:
        """Convert a projected annotation row to a response."""
        value = parse_json_or_none(row["value"])
        return AnnotationResponse(
            annotation_id=row["annotation_id"],
            tree_id=row["tree_id"],
            node_id=row["node_id"],
            tag=row["tag"],
            value=value,
            notes=row["notes"],
            created_at=row["created_at"],
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
    def _tree_detail_from_row(
        row: dict,
        node_rows: list[dict],
        *,
        annotation_counts: dict[str, int] | None = None,
        bookmark_node_ids: set[str] | None = None,
        excluded_node_ids: set[str] | None = None,
        anchored_node_ids: set[str] | None = None,
        edit_counts: dict[str, int] | None = None,
    ) -> TreeDetailResponse:
        """Convert a projected tree row + node rows to a response."""
        sibling_info = TreeService._compute_sibling_info(node_rows)
        return TreeDetailResponse(
            tree_id=row["tree_id"],
            title=row["title"],
            metadata=parse_json_field(row["metadata"]) or {},
            default_model=row["default_model"],
            default_provider=row["default_provider"],
            default_system_prompt=row["default_system_prompt"],
            default_sampling_params=parse_json_field(row["default_sampling_params"]),
            conversation_mode=row["conversation_mode"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            archived=row["archived"],
            nodes=[
                TreeService._node_from_row(
                    n,
                    sibling_info=sibling_info,
                    annotation_counts=annotation_counts,
                    bookmark_node_ids=bookmark_node_ids,
                    excluded_node_ids=excluded_node_ids,
                    anchored_node_ids=anchored_node_ids,
                    edit_counts=edit_counts,
                )
                for n in node_rows
            ],
        )

    @staticmethod
    def _node_from_row(
        row: dict,
        *,
        sibling_info: dict[str, tuple[int, int]] | None = None,
        annotation_counts: dict[str, int] | None = None,
        bookmark_node_ids: set[str] | None = None,
        excluded_node_ids: set[str] | None = None,
        anchored_node_ids: set[str] | None = None,
        edit_counts: dict[str, int] | None = None,
    ) -> NodeResponse:
        """Convert a projected node row to a response."""
        si, sc = (0, 1)
        if sibling_info is not None and row["node_id"] in sibling_info:
            si, sc = sibling_info[row["node_id"]]

        ac = 0
        if annotation_counts is not None:
            ac = annotation_counts.get(row["node_id"], 0)

        ib = False
        if bookmark_node_ids is not None:
            ib = row["node_id"] in bookmark_node_ids

        ie = False
        if excluded_node_ids is not None:
            ie = row["node_id"] in excluded_node_ids

        ia = False
        if anchored_node_ids is not None:
            ia = row["node_id"] in anchored_node_ids

        ec = 0
        if edit_counts is not None:
            ec = edit_counts.get(row["node_id"], 0)

        return NodeResponse(
            node_id=row["node_id"],
            tree_id=row["tree_id"],
            parent_id=row["parent_id"],
            role=row["role"],
            content=row["content"],
            model=row["model"],
            provider=row["provider"],
            system_prompt=row["system_prompt"],
            sampling_params=parse_json_or_none(row["sampling_params"]),
            mode=row["mode"],
            usage=parse_json_or_none(row["usage"]),
            latency_ms=row["latency_ms"],
            finish_reason=row["finish_reason"],
            logprobs=parse_json_or_none(row["logprobs"]),
            context_usage=parse_json_or_none(row["context_usage"]),
            participant_id=row["participant_id"],
            participant_name=row["participant_name"],
            thinking_content=row.get("thinking_content"),
            edited_content=row.get("edited_content"),
            include_thinking_in_context=bool(row.get("include_thinking_in_context", 0)),
            include_timestamps=bool(row.get("include_timestamps", 0)),
            created_at=row["created_at"],
            archived=row["archived"],
            sibling_index=si,
            sibling_count=sc,
            annotation_count=ac,
            edit_count=ec,
            is_bookmarked=ib,
            is_excluded=ie,
            is_anchored=ia,
        )


class TreeNotFoundError(Exception):
    def __init__(self, tree_id: str) -> None:
        self.tree_id = tree_id
        super().__init__(f"Tree not found: {tree_id}")


class NodeNotFoundError(Exception):
    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        super().__init__(f"Node not found: {node_id}")


class AnnotationNotFoundError(Exception):
    def __init__(self, annotation_id: str) -> None:
        self.annotation_id = annotation_id
        super().__init__(f"Annotation not found: {annotation_id}")


class BookmarkNotFoundError(Exception):
    def __init__(self, bookmark_id: str) -> None:
        self.bookmark_id = bookmark_id
        super().__init__(f"Bookmark not found: {bookmark_id}")


class SummaryClientNotConfiguredError(Exception):
    def __init__(self) -> None:
        super().__init__("Summary API key not configured")


class InvalidParentError(Exception):
    def __init__(self, parent_id: str) -> None:
        self.parent_id = parent_id
        super().__init__(f"Invalid parent node: {parent_id}")


class DigressionGroupNotFoundError(Exception):
    def __init__(self, group_id: str) -> None:
        self.group_id = group_id
        super().__init__(f"Digression group not found: {group_id}")


class NonContiguousGroupError(Exception):
    def __init__(self, node_ids: list[str]) -> None:
        self.node_ids = node_ids
        super().__init__(f"Nodes are not contiguous: {node_ids}")
