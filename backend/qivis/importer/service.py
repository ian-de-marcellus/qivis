"""ImportService: parses external conversation files, emits events."""

import json
from collections import defaultdict
from datetime import UTC, datetime
from uuid import uuid4

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.importer.models import ImportedNode, ImportedTree
from qivis.importer.parsers.chatgpt import parse_chatgpt
from qivis.importer.parsers.claude import parse_claude
from qivis.importer.parsers.detection import ImportFormatError, detect_format
from qivis.importer.parsers.linear import parse_linear
from qivis.importer.schemas import (
    ConversationPreview,
    ImportPreviewResponse,
    ImportResponse,
    ImportResult,
    MessagePreview,
)
from qivis.models import EventEnvelope, NodeCreatedPayload, RhizomeCreatedPayload


class ImportService:
    def __init__(
        self, db: Database, store: EventStore, projector: StateProjector
    ) -> None:
        self._db = db
        self._store = store
        self._projector = projector

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def preview(self, content: bytes, filename: str) -> ImportPreviewResponse:
        """Parse file and return preview without creating anything."""
        data = self._load_json(content)
        fmt = detect_format(data)
        rhizomes = self._parse(fmt, data)

        conversations = []
        for i, rhizome in enumerate(rhizomes):
            # Count fork points (nodes with multiple children)
            children_count: dict[str | None, int] = defaultdict(int)
            for node in rhizome.nodes:
                children_count[node.parent_temp_id] += 1
            branch_count = sum(1 for c in children_count.values() if c > 1)

            # Unique models
            model_names = sorted({
                n.model for n in rhizome.nodes if n.model
            })

            # First few messages
            first_messages = [
                MessagePreview(
                    role=n.role,
                    content_preview=n.content[:200],
                )
                for n in rhizome.nodes[:5]
            ]

            conversations.append(ConversationPreview(
                index=i,
                title=rhizome.title,
                message_count=len(rhizome.nodes),
                has_branches=branch_count > 0,
                branch_count=branch_count,
                model_names=model_names,
                system_prompt_preview=(
                    rhizome.default_system_prompt[:200]
                    if rhizome.default_system_prompt else None
                ),
                first_messages=first_messages,
                warnings=rhizome.warnings,
            ))

        return ImportPreviewResponse(
            format_detected=fmt,
            conversations=conversations,
            total_conversations=len(rhizomes),
        )

    async def import_rhizomes(
        self,
        content: bytes,
        filename: str,
        *,
        format_hint: str | None = None,
        selected_indices: list[int] | None = None,
    ) -> list[ImportResult]:
        """Parse and import conversations, returning results."""
        data = self._load_json(content)
        fmt = format_hint or detect_format(data)
        rhizomes = self._parse(fmt, data)

        if selected_indices is not None:
            rhizomes = [rhizomes[i] for i in selected_indices if i < len(rhizomes)]

        results = []
        for rhizome in rhizomes:
            result = await self._import_single(rhizome)
            results.append(result)
        return results

    # Keep old name as alias for backward compatibility
    import_trees = import_rhizomes

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _load_json(content: bytes) -> dict | list:
        """Parse raw bytes as JSON."""
        try:
            return json.loads(content)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ImportFormatError(f"Invalid JSON: {e}") from e

    @staticmethod
    def _parse(fmt: str, data: dict | list) -> list[ImportedTree]:
        """Route to the correct parser."""
        if fmt == "chatgpt":
            return parse_chatgpt(data)
        if fmt == "claude":
            return parse_claude(data)
        if fmt == "linear":
            if not isinstance(data, list):
                raise ImportFormatError("Linear format requires a JSON array")
            return [parse_linear(data)]
        raise ImportFormatError(f"Unknown format: {fmt}")

    @staticmethod
    def _topological_sort(imported: ImportedTree) -> list[ImportedNode]:
        """Sort nodes so that parents come before children."""
        by_id = {n.temp_id: n for n in imported.nodes}
        children_of: dict[str | None, list[str]] = defaultdict(list)
        for n in imported.nodes:
            children_of[n.parent_temp_id].append(n.temp_id)

        result: list[ImportedNode] = []
        visited: set[str] = set()

        def visit(temp_id: str) -> None:
            if temp_id in visited:
                return
            visited.add(temp_id)
            result.append(by_id[temp_id])
            for child_id in children_of.get(temp_id, []):
                visit(child_id)

        # Start from roots (parent_temp_id is None)
        for root_id in children_of.get(None, []):
            visit(root_id)

        # Also visit any orphans not reachable from roots
        for n in imported.nodes:
            if n.temp_id not in visited:
                visit(n.temp_id)

        return result

    async def _import_single(self, imported: ImportedTree) -> ImportResult:
        """Emit RhizomeCreated + NodeCreated events for one conversation."""
        rhizome_id = str(uuid4())

        rhizome_timestamp = (
            datetime.fromtimestamp(imported.created_at, tz=UTC)
            if imported.created_at
            else datetime.now(UTC)
        )

        # 1. Emit RhizomeCreated
        rhizome_payload = RhizomeCreatedPayload(
            title=imported.title or "Imported Conversation",
            default_system_prompt=imported.default_system_prompt,
            default_model=imported.default_model,
            default_provider=imported.default_provider,
            metadata={
                "imported": True,
                "import_source": imported.source_format,
                "original_id": imported.source_id,
                "import_warnings": imported.warnings,
            },
        )
        rhizome_event = EventEnvelope(
            event_id=str(uuid4()),
            rhizome_id=rhizome_id,
            timestamp=rhizome_timestamp,
            device_id="import",
            event_type="RhizomeCreated",
            payload=rhizome_payload.model_dump(),
        )
        await self._store.append(rhizome_event)
        await self._projector.project([rhizome_event])

        # 2. Topological sort + emit NodeCreated events
        sorted_nodes = self._topological_sort(imported)
        temp_to_real: dict[str, str] = {}

        for node in sorted_nodes:
            real_id = str(uuid4())
            temp_to_real[node.temp_id] = real_id

            parent_real_id = (
                temp_to_real.get(node.parent_temp_id)
                if node.parent_temp_id
                else None
            )

            node_timestamp = (
                datetime.fromtimestamp(node.timestamp, tz=UTC)
                if node.timestamp
                else rhizome_timestamp
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
                rhizome_id=rhizome_id,
                timestamp=node_timestamp,
                device_id="import",
                event_type="NodeCreated",
                payload=node_payload.model_dump(),
            )
            await self._store.append(node_event)
            await self._projector.project([node_event])

        return ImportResult(
            rhizome_id=rhizome_id,
            title=imported.title,
            node_count=len(sorted_nodes),
            warnings=imported.warnings,
        )
