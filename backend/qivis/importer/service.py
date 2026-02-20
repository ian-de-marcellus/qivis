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
from qivis.models import EventEnvelope, NodeCreatedPayload, TreeCreatedPayload


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
        trees = self._parse(fmt, data)

        conversations = []
        for i, tree in enumerate(trees):
            # Count fork points (nodes with multiple children)
            children_count: dict[str | None, int] = defaultdict(int)
            for node in tree.nodes:
                children_count[node.parent_temp_id] += 1
            branch_count = sum(1 for c in children_count.values() if c > 1)

            # Unique models
            model_names = sorted({
                n.model for n in tree.nodes if n.model
            })

            # First few messages
            first_messages = [
                MessagePreview(
                    role=n.role,
                    content_preview=n.content[:200],
                )
                for n in tree.nodes[:5]
            ]

            conversations.append(ConversationPreview(
                index=i,
                title=tree.title,
                message_count=len(tree.nodes),
                has_branches=branch_count > 0,
                branch_count=branch_count,
                model_names=model_names,
                system_prompt_preview=(
                    tree.default_system_prompt[:200]
                    if tree.default_system_prompt else None
                ),
                first_messages=first_messages,
                warnings=tree.warnings,
            ))

        return ImportPreviewResponse(
            format_detected=fmt,
            conversations=conversations,
            total_conversations=len(trees),
        )

    async def import_trees(
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
        trees = self._parse(fmt, data)

        if selected_indices is not None:
            trees = [trees[i] for i in selected_indices if i < len(trees)]

        results = []
        for tree in trees:
            result = await self._import_single(tree)
            results.append(result)
        return results

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
    def _topological_sort(tree: ImportedTree) -> list[ImportedNode]:
        """Sort nodes so that parents come before children."""
        by_id = {n.temp_id: n for n in tree.nodes}
        children_of: dict[str | None, list[str]] = defaultdict(list)
        for n in tree.nodes:
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
        for n in tree.nodes:
            if n.temp_id not in visited:
                visit(n.temp_id)

        return result

    async def _import_single(self, imported: ImportedTree) -> ImportResult:
        """Emit TreeCreated + NodeCreated events for one conversation."""
        tree_id = str(uuid4())

        tree_timestamp = (
            datetime.fromtimestamp(imported.created_at, tz=UTC)
            if imported.created_at
            else datetime.now(UTC)
        )

        # 1. Emit TreeCreated
        tree_payload = TreeCreatedPayload(
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
        tree_event = EventEnvelope(
            event_id=str(uuid4()),
            tree_id=tree_id,
            timestamp=tree_timestamp,
            device_id="import",
            event_type="TreeCreated",
            payload=tree_payload.model_dump(),
        )
        await self._store.append(tree_event)
        await self._projector.project([tree_event])

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
                else tree_timestamp
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
                device_id="import",
                event_type="NodeCreated",
                payload=node_payload.model_dump(),
            )
            await self._store.append(node_event)
            await self._projector.project([node_event])

        return ImportResult(
            tree_id=tree_id,
            title=imported.title,
            node_count=len(sorted_nodes),
            warnings=imported.warnings,
        )
