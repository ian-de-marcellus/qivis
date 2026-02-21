"""Tests for manual summarization (Phase 7.3).

Three sections:
1. Contract tests -- projector handles SummaryGenerated/Removed events
2. Integration tests -- API endpoints with mocked LLM
3. Service tests -- algorithm verification (transcript building, scope logic)
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.trees.schemas import CreateSummaryRequest
from qivis.trees.service import TreeService
from tests.fixtures import (
    create_test_tree,
    create_tree_with_messages,
    make_node_created_envelope,
    make_summary_generated_envelope,
    make_summary_removed_envelope,
    make_tree_created_envelope,
)


# ---------------------------------------------------------------------------
# Contract tests: event -> store -> projector -> verify state
# ---------------------------------------------------------------------------


class TestSummaryProjection:
    """SummaryGenerated/Removed events project into the summaries table."""

    async def test_summary_generated_projects(self, event_store, projector, db):
        """SummaryGenerated inserts a row into the summaries table."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(tree_id=tree_ev.tree_id, content="Hello")

        for e in [tree_ev, node_ev]:
            await event_store.append(e)
        await projector.project([tree_ev, node_ev])

        node_id = node_ev.payload["node_id"]
        summary_ev = make_summary_generated_envelope(
            tree_id=tree_ev.tree_id,
            anchor_node_id=node_id,
            scope="branch",
            summary_type="concise",
            summary="The user greeted the assistant.",
            node_ids=[node_id],
        )
        await event_store.append(summary_ev)
        await projector.project([summary_ev])

        row = await db.fetchone(
            "SELECT * FROM summaries WHERE summary_id = ?",
            (summary_ev.payload["summary_id"],),
        )
        assert row is not None
        assert row["summary"] == "The user greeted the assistant."
        assert row["anchor_node_id"] == node_id
        assert row["tree_id"] == tree_ev.tree_id
        assert row["scope"] == "branch"
        assert row["summary_type"] == "concise"
        assert json.loads(row["node_ids"]) == [node_id]

    async def test_summary_removed_deletes_row(self, event_store, projector, db):
        """SummaryRemoved deletes the summary from the table."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(tree_id=tree_ev.tree_id, content="Hello")

        for e in [tree_ev, node_ev]:
            await event_store.append(e)
        await projector.project([tree_ev, node_ev])

        node_id = node_ev.payload["node_id"]
        summary_ev = make_summary_generated_envelope(
            tree_id=tree_ev.tree_id,
            anchor_node_id=node_id,
        )
        await event_store.append(summary_ev)
        await projector.project([summary_ev])

        summary_id = summary_ev.payload["summary_id"]
        remove_ev = make_summary_removed_envelope(
            tree_id=tree_ev.tree_id,
            summary_id=summary_id,
        )
        await event_store.append(remove_ev)
        await projector.project([remove_ev])

        row = await db.fetchone(
            "SELECT * FROM summaries WHERE summary_id = ?",
            (summary_id,),
        )
        assert row is None

    async def test_multiple_summaries_per_anchor_node(self, event_store, projector, db):
        """Multiple summaries can exist for the same anchor node."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(tree_id=tree_ev.tree_id, content="Hello")

        for e in [tree_ev, node_ev]:
            await event_store.append(e)
        await projector.project([tree_ev, node_ev])

        node_id = node_ev.payload["node_id"]

        summary1 = make_summary_generated_envelope(
            tree_id=tree_ev.tree_id,
            anchor_node_id=node_id,
            summary_type="concise",
            summary="Short version.",
        )
        summary2 = make_summary_generated_envelope(
            tree_id=tree_ev.tree_id,
            anchor_node_id=node_id,
            summary_type="detailed",
            summary="Long detailed version with more context.",
        )
        for e in [summary1, summary2]:
            await event_store.append(e)
            await projector.project([e])

        rows = await db.fetchall(
            "SELECT * FROM summaries WHERE anchor_node_id = ?",
            (node_id,),
        )
        assert len(rows) == 2
        types = {r["summary_type"] for r in rows}
        assert types == {"concise", "detailed"}


# ---------------------------------------------------------------------------
# Helper: create a TreeService with a mock summary client
# ---------------------------------------------------------------------------

def _mock_summary_client(text: str = "Mock summary.", model: str = "claude-haiku-4-5-20251001"):
    """Create a mock Anthropic client that returns a fixed summary."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=text)]
    mock_response.model = model
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    return mock_client


# ---------------------------------------------------------------------------
# Integration tests: API round-trips with mocked LLM
# ---------------------------------------------------------------------------


class TestSummaryAPI:
    """API endpoints for manual summarization."""

    async def test_branch_summary(self, client, db):
        """POST /summarize with branch scope returns summary."""
        data = await create_tree_with_messages(client, n_messages=4)
        tree_id = data["tree_id"]
        last_node = data["node_ids"][-1]

        mock_client = _mock_summary_client("Branch concise summary.")
        service = TreeService(db, summary_client=mock_client)

        result = await service.generate_summary(
            tree_id, last_node,
            CreateSummaryRequest(scope="branch", summary_type="concise"),
        )
        assert result.summary == "Branch concise summary."
        assert result.scope == "branch"
        assert result.summary_type == "concise"
        assert result.anchor_node_id == last_node
        assert last_node in result.node_ids
        assert len(result.node_ids) == 4  # All 4 nodes in the branch

    async def test_subtree_summary(self, client, db):
        """POST /summarize with subtree scope returns summary covering descendants."""
        data = await create_tree_with_messages(client, n_messages=4)
        tree_id = data["tree_id"]
        root_node = data["node_ids"][0]

        mock_client = _mock_summary_client("Subtree summary.")
        service = TreeService(db, summary_client=mock_client)

        result = await service.generate_summary(
            tree_id, root_node,
            CreateSummaryRequest(scope="subtree", summary_type="detailed"),
        )
        assert result.summary == "Subtree summary."
        assert result.scope == "subtree"
        assert result.summary_type == "detailed"
        assert result.anchor_node_id == root_node
        assert len(result.node_ids) == 4  # Root + 3 descendants

    async def test_custom_prompt(self, client, db):
        """POST /summarize with custom prompt passes it through."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][-1]

        mock_client = _mock_summary_client("Custom result.")
        service = TreeService(db, summary_client=mock_client)

        result = await service.generate_summary(
            tree_id, node_id,
            CreateSummaryRequest(
                scope="branch",
                summary_type="custom",
                custom_prompt="Analyze the emotional dynamics.",
            ),
        )
        assert result.summary == "Custom result."
        assert result.prompt_used == "Analyze the emotional dynamics."
        assert result.summary_type == "custom"

        # Verify the custom prompt was used as the system prompt
        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs["system"] == "Analyze the emotional dynamics."

    async def test_list_summaries(self, client, db):
        """GET /summaries returns all summaries for tree."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][-1]

        mock_client = _mock_summary_client()
        service = TreeService(db, summary_client=mock_client)

        # Generate two summaries
        await service.generate_summary(
            tree_id, node_id,
            CreateSummaryRequest(scope="branch", summary_type="concise"),
        )
        await service.generate_summary(
            tree_id, node_id,
            CreateSummaryRequest(scope="branch", summary_type="detailed"),
        )

        summaries = await service.list_summaries(tree_id)
        assert len(summaries) == 2
        types = {s.summary_type for s in summaries}
        assert types == {"concise", "detailed"}

    async def test_remove_summary(self, client, db):
        """DELETE /summaries/{id} removes summary."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][-1]

        mock_client = _mock_summary_client()
        service = TreeService(db, summary_client=mock_client)

        result = await service.generate_summary(
            tree_id, node_id,
            CreateSummaryRequest(scope="branch", summary_type="concise"),
        )

        await service.remove_summary(tree_id, result.summary_id)

        summaries = await service.list_summaries(tree_id)
        assert len(summaries) == 0

    async def test_tree_not_found_404(self, client, db):
        """Summarize on non-existent tree raises TreeNotFoundError."""
        from qivis.trees.service import TreeNotFoundError

        mock_client = _mock_summary_client()
        service = TreeService(db, summary_client=mock_client)

        with pytest.raises(TreeNotFoundError):
            await service.generate_summary(
                "nonexistent", "nope",
                CreateSummaryRequest(),
            )

    async def test_node_not_found_404(self, client, db):
        """Summarize on non-existent node raises NodeNotFoundError."""
        from qivis.trees.service import NodeNotFoundError

        data = await create_tree_with_messages(client, n_messages=1)
        tree_id = data["tree_id"]

        mock_client = _mock_summary_client()
        service = TreeService(db, summary_client=mock_client)

        with pytest.raises(NodeNotFoundError):
            await service.generate_summary(
                tree_id, "nonexistent-node",
                CreateSummaryRequest(),
            )

    async def test_no_summary_client_503(self, client, db):
        """Summarize without summary client raises SummaryClientNotConfiguredError."""
        from qivis.trees.service import SummaryClientNotConfiguredError

        data = await create_tree_with_messages(client, n_messages=1)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        service = TreeService(db, summary_client=None)

        with pytest.raises(SummaryClientNotConfiguredError):
            await service.generate_summary(
                tree_id, node_id,
                CreateSummaryRequest(),
            )

    async def test_remove_nonexistent_summary_404(self, client, db):
        """Remove non-existent summary raises SummaryNotFoundError."""
        from qivis.trees.service import SummaryNotFoundError

        data = await create_tree_with_messages(client, n_messages=1)
        tree_id = data["tree_id"]

        service = TreeService(db, summary_client=None)

        with pytest.raises(SummaryNotFoundError):
            await service.remove_summary(tree_id, "nonexistent")


# ---------------------------------------------------------------------------
# Service tests: algorithm verification
# ---------------------------------------------------------------------------


class TestSummaryAlgorithm:
    """Verify transcript building, scope logic, and prompt selection."""

    async def test_branch_walks_parent_chain(self, client, db):
        """Branch scope walks the correct parent chain from leaf to root."""
        data = await create_tree_with_messages(client, n_messages=5)
        tree_id = data["tree_id"]
        leaf = data["node_ids"][-1]

        mock_client = _mock_summary_client()
        service = TreeService(db, summary_client=mock_client)

        result = await service.generate_summary(
            tree_id, leaf,
            CreateSummaryRequest(scope="branch"),
        )
        # Branch from leaf to root should include all 5 nodes in order
        assert result.node_ids == data["node_ids"]

    async def test_subtree_collects_all_descendants(self, client, db):
        """Subtree scope collects all descendants including branches."""
        # Create tree: root -> A, root -> B (two children of root)
        tree = await create_test_tree(client, title="Branching")
        tree_id = tree["tree_id"]

        # Root node
        resp = await client.post(
            f"/api/trees/{tree_id}/nodes",
            json={"content": "Root", "role": "user"},
        )
        root_id = resp.json()["node_id"]

        # Two children
        resp = await client.post(
            f"/api/trees/{tree_id}/nodes",
            json={"content": "Child A", "role": "assistant", "parent_id": root_id},
        )
        child_a = resp.json()["node_id"]

        resp = await client.post(
            f"/api/trees/{tree_id}/nodes",
            json={"content": "Child B", "role": "assistant", "parent_id": root_id},
        )
        child_b = resp.json()["node_id"]

        mock_client = _mock_summary_client()
        service = TreeService(db, summary_client=mock_client)

        result = await service.generate_summary(
            tree_id, root_id,
            CreateSummaryRequest(scope="subtree"),
        )
        assert len(result.node_ids) == 3
        assert root_id in result.node_ids
        assert child_a in result.node_ids
        assert child_b in result.node_ids

    async def test_summary_type_selects_prompt(self, client, db):
        """Different summary types use different system prompts and max_tokens."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][-1]

        mock_client = _mock_summary_client()
        service = TreeService(db, summary_client=mock_client)

        # Concise
        await service.generate_summary(
            tree_id, node_id,
            CreateSummaryRequest(summary_type="concise"),
        )
        call = mock_client.messages.create.call_args
        assert call.kwargs["max_tokens"] == 300
        assert "terse" in call.kwargs["system"].lower()
        assert "30-50 words" in call.kwargs["system"]

        mock_client.messages.create.reset_mock()

        # Key points
        await service.generate_summary(
            tree_id, node_id,
            CreateSummaryRequest(summary_type="key_points"),
        )
        call = mock_client.messages.create.call_args
        assert call.kwargs["max_tokens"] == 1024
        assert "key points" in call.kwargs["system"].lower()

    async def test_edited_content_used_in_transcript(self, client, db):
        """Transcript uses edited_content when present."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]

        # Edit the first node
        await client.patch(
            f"/api/trees/{tree_id}/nodes/{node_id}/content",
            json={"edited_content": "Edited hello"},
        )

        mock_client = _mock_summary_client()
        service = TreeService(db, summary_client=mock_client)

        await service.generate_summary(
            tree_id, data["node_ids"][-1],
            CreateSummaryRequest(scope="branch"),
        )

        # Check the transcript passed to the mock
        call = mock_client.messages.create.call_args
        user_message = call.kwargs["messages"][0]["content"]
        assert "Edited hello" in user_message

    async def test_summaries_survive_replay(self, event_store, projector, db):
        """Summaries survive full event replay from scratch."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(tree_id=tree_ev.tree_id, content="Hello")
        summary_ev = make_summary_generated_envelope(
            tree_id=tree_ev.tree_id,
            anchor_node_id=node_ev.payload["node_id"],
            summary="Replayed summary.",
        )

        all_events = [tree_ev, node_ev, summary_ev]
        for e in all_events:
            await event_store.append(e)

        # Clear tables and replay
        await db.execute("DELETE FROM summaries")
        await db.execute("DELETE FROM nodes")
        await db.execute("DELETE FROM trees")

        fresh_projector = StateProjector(db)
        await fresh_projector.project(all_events)

        row = await db.fetchone(
            "SELECT * FROM summaries WHERE summary_id = ?",
            (summary_ev.payload["summary_id"],),
        )
        assert row is not None
        assert row["summary"] == "Replayed summary."
