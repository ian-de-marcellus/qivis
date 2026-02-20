"""Tests for Phase 7.1: FTS5 full-text search across conversation nodes."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.main import app
from qivis.search.router import get_search_service
from qivis.search.service import SearchService
from qivis.trees.router import get_tree_service
from qivis.trees.service import TreeService

from tests.fixtures import (
    make_annotation_added_envelope,
    make_node_created_envelope,
    make_tree_created_envelope,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_tree(
    event_store: EventStore,
    projector: StateProjector,
    *,
    tree_id: str | None = None,
    title: str = "Test Tree",
    nodes: list[dict] | None = None,
) -> dict:
    """Create a tree with nodes. Returns {tree_id, node_ids}."""
    tree_ev = make_tree_created_envelope(tree_id=tree_id, title=title)
    await event_store.append(tree_ev)
    await projector.project([tree_ev])

    node_ids = []
    parent_id = None
    for node_spec in (nodes or []):
        node_ev = make_node_created_envelope(
            tree_id=tree_ev.tree_id,
            parent_id=parent_id,
            **node_spec,
        )
        await event_store.append(node_ev)
        await projector.project([node_ev])
        node_ids.append(node_ev.payload["node_id"])
        parent_id = node_ev.payload["node_id"]

    return {"tree_id": tree_ev.tree_id, "node_ids": node_ids}


async def _seed_annotation(
    event_store: EventStore,
    projector: StateProjector,
    tree_id: str,
    node_id: str,
    tag: str,
    value: str | None = None,
) -> None:
    """Add an annotation to a node."""
    ann_ev = make_annotation_added_envelope(
        tree_id=tree_id, node_id=node_id, tag=tag, value=value,
    )
    await event_store.append(ann_ev)
    await projector.project([ann_ev])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def db():
    database = await Database.connect(":memory:")
    yield database
    await database.close()


@pytest.fixture
async def event_store(db):
    return EventStore(db)


@pytest.fixture
async def projector(db):
    return StateProjector(db)


@pytest.fixture
async def search_service(db):
    return SearchService(db)


@pytest.fixture
async def client(db):
    tree_service = TreeService(db)
    search_service = SearchService(db)
    app.dependency_overrides[get_tree_service] = lambda: tree_service
    app.dependency_overrides[get_search_service] = lambda: search_service
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Contract tests — FTS5 infrastructure
# ---------------------------------------------------------------------------

class TestFTS5Infrastructure:
    """FTS5 virtual table, triggers, and backfill work correctly."""

    async def test_fts_table_created_by_migration(self, db):
        """After Database.connect(), nodes_fts virtual table exists."""
        rows = await db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='nodes_fts'"
        )
        assert len(rows) == 1

    async def test_fts_insert_trigger_fires(self, db, event_store, projector):
        """When a node is created via the projector, it appears in FTS search."""
        data = await _seed_tree(event_store, projector, nodes=[
            {"role": "user", "content": "The quick brown fox jumps over the lazy dog"},
        ])
        rows = await db.fetchall(
            "SELECT * FROM nodes_fts WHERE nodes_fts MATCH ?", ('"quick brown fox"',)
        )
        assert len(rows) == 1

    async def test_fts_delete_trigger_fires(self, db, event_store, projector):
        """When a node is deleted from the nodes table, it disappears from FTS."""
        data = await _seed_tree(event_store, projector, nodes=[
            {"role": "user", "content": "ephemeral message"},
        ])
        node_id = data["node_ids"][0]
        # Direct delete (not a normal operation, but tests the trigger)
        await db.execute("DELETE FROM nodes WHERE node_id = ?", (node_id,))
        rows = await db.fetchall(
            "SELECT * FROM nodes_fts WHERE nodes_fts MATCH ?", ('"ephemeral"',)
        )
        assert len(rows) == 0

    async def test_fts_backfill_indexes_existing_nodes(self, db):
        """The FTS rebuild command re-indexes all nodes from the content table."""
        now = datetime.now(UTC).isoformat()
        # Create a tree first (foreign key constraint)
        await db.execute(
            "INSERT INTO trees (tree_id, title, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("tree-1", "Test", now, now),
        )
        # Insert a node (trigger will auto-index it)
        await db.execute(
            "INSERT INTO nodes (node_id, tree_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("backfill-test", "tree-1", "user", "backfill canary text", now),
        )
        # Rebuild should not duplicate — still exactly one match
        await db.execute("INSERT INTO nodes_fts(nodes_fts) VALUES('rebuild')")
        rows = await db.fetchall(
            "SELECT * FROM nodes_fts WHERE nodes_fts MATCH ?", ('"backfill canary"',)
        )
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# Service tests — SearchService
# ---------------------------------------------------------------------------

class TestSearchService:
    """SearchService query building, filtering, and result mapping."""

    async def test_search_returns_matching_nodes(
        self, db, event_store, projector, search_service,
    ):
        """Basic keyword search returns nodes with matching content."""
        await _seed_tree(event_store, projector, nodes=[
            {"role": "user", "content": "Tell me about photosynthesis"},
            {"role": "assistant", "content": "Photosynthesis is the process by which plants convert sunlight"},
        ])
        result = await search_service.search("photosynthesis")
        assert result.total >= 2
        node_ids = {r.node_id for r in result.results}
        assert len(node_ids) >= 2

    async def test_search_returns_snippet_with_highlighting(
        self, db, event_store, projector, search_service,
    ):
        """Results include snippets with [[mark]]/[[/mark]] delimiters."""
        await _seed_tree(event_store, projector, nodes=[
            {"role": "user", "content": "Tell me about quantum entanglement"},
        ])
        result = await search_service.search("quantum")
        assert result.total >= 1
        snippet = result.results[0].snippet
        assert "[[mark]]" in snippet
        assert "[[/mark]]" in snippet

    async def test_search_sanitizes_fts_operators(
        self, db, event_store, projector, search_service,
    ):
        """FTS5 operators like AND, OR, NOT are treated as literal words."""
        await _seed_tree(event_store, projector, nodes=[
            {"role": "user", "content": "This AND that OR something NOT nothing"},
        ])
        # Should not crash — operators are quoted as literal words
        result = await search_service.search("AND OR NOT")
        # The content contains all three words, so it should match
        assert result.total >= 1

    async def test_search_multi_word_implicit_and(
        self, db, event_store, projector, search_service,
    ):
        """Multi-word search requires all terms present (implicit AND)."""
        await _seed_tree(event_store, projector, nodes=[
            {"role": "user", "content": "The cat sat on the mat"},
            {"role": "user", "content": "The dog ran in the park"},
        ])
        result = await search_service.search("cat mat")
        assert result.total == 1
        assert "cat" in result.results[0].content.lower()

    async def test_search_system_prompt_matches(
        self, db, event_store, projector, search_service,
    ):
        """Nodes with matching system_prompt are returned."""
        await _seed_tree(event_store, projector, nodes=[
            {
                "role": "assistant",
                "content": "Hello there!",
                "system_prompt": "You are a marine biologist specializing in cephalopods",
                "model": "test-model",
                "provider": "test-provider",
            },
        ])
        result = await search_service.search("cephalopods")
        assert result.total >= 1

    async def test_search_filter_tree_ids(
        self, db, event_store, projector, search_service,
    ):
        """tree_ids filter limits results to specified trees."""
        data1 = await _seed_tree(event_store, projector, title="Tree A", nodes=[
            {"role": "user", "content": "universal search term here"},
        ])
        data2 = await _seed_tree(event_store, projector, title="Tree B", nodes=[
            {"role": "user", "content": "universal search term here"},
        ])
        result = await search_service.search(
            "universal", tree_ids=[data1["tree_id"]],
        )
        assert result.total == 1
        assert result.results[0].tree_id == data1["tree_id"]

    async def test_search_filter_model(
        self, db, event_store, projector, search_service,
    ):
        """models filter limits results to specified models."""
        await _seed_tree(event_store, projector, nodes=[
            {"role": "assistant", "content": "Response from sonnet", "model": "claude-sonnet", "provider": "anthropic"},
            {"role": "assistant", "content": "Response from haiku", "model": "claude-haiku", "provider": "anthropic"},
        ])
        result = await search_service.search("response", models=["claude-sonnet"])
        assert result.total == 1
        assert result.results[0].model == "claude-sonnet"

    async def test_search_filter_role(
        self, db, event_store, projector, search_service,
    ):
        """roles filter limits results to specified roles."""
        await _seed_tree(event_store, projector, nodes=[
            {"role": "user", "content": "a unique filterword in conversation"},
            {"role": "assistant", "content": "a unique filterword in response", "model": "m", "provider": "p"},
        ])
        result = await search_service.search("filterword", roles=["assistant"])
        assert result.total == 1
        assert result.results[0].role == "assistant"

    async def test_search_filter_annotation_tag(
        self, db, event_store, projector, search_service,
    ):
        """tags filter returns only nodes with matching annotations."""
        data = await _seed_tree(event_store, projector, nodes=[
            {"role": "user", "content": "annotated node content here"},
            {"role": "user", "content": "unannotated node content here"},
        ])
        await _seed_annotation(
            event_store, projector,
            tree_id=data["tree_id"],
            node_id=data["node_ids"][0],
            tag="sycophancy",
        )
        result = await search_service.search("content", tags=["sycophancy"])
        assert result.total == 1
        assert result.results[0].node_id == data["node_ids"][0]

    async def test_search_filter_date_range(
        self, db, event_store, projector, search_service,
    ):
        """date_from and date_to filter by node creation date."""
        # Create two nodes with known timestamps
        tree_ev = make_tree_created_envelope(title="Date test")
        await event_store.append(tree_ev)
        await projector.project([tree_ev])

        old_node = make_node_created_envelope(
            tree_id=tree_ev.tree_id, role="user", content="old datetest message",
        )
        old_node.timestamp = datetime(2025, 1, 15, tzinfo=UTC)
        await event_store.append(old_node)
        await projector.project([old_node])

        new_node = make_node_created_envelope(
            tree_id=tree_ev.tree_id, role="user", content="new datetest message",
            parent_id=old_node.payload["node_id"],
        )
        new_node.timestamp = datetime(2026, 2, 15, tzinfo=UTC)
        await event_store.append(new_node)
        await projector.project([new_node])

        result = await search_service.search(
            "datetest", date_from="2026-01-01",
        )
        assert result.total == 1
        assert result.results[0].node_id == new_node.payload["node_id"]

    async def test_search_excludes_archived(
        self, db, event_store, projector, search_service,
    ):
        """Archived nodes are excluded from search results."""
        data = await _seed_tree(event_store, projector, nodes=[
            {"role": "user", "content": "archived test content"},
        ])
        # Archive the node directly
        await db.execute(
            "UPDATE nodes SET archived = 1 WHERE node_id = ?",
            (data["node_ids"][0],),
        )
        result = await search_service.search("archived test")
        assert result.total == 0

    async def test_search_empty_query_returns_empty(self, search_service):
        """Whitespace-only or empty query returns no results."""
        result = await search_service.search("   ")
        assert result.total == 0
        assert result.results == []

    async def test_search_respects_limit(
        self, db, event_store, projector, search_service,
    ):
        """limit parameter caps the number of results."""
        await _seed_tree(event_store, projector, nodes=[
            {"role": "user", "content": f"limitword message number {i}"}
            for i in range(10)
        ])
        result = await search_service.search("limitword", limit=3)
        assert len(result.results) == 3
        assert result.total == 3

    async def test_search_ordered_by_relevance(
        self, db, event_store, projector, search_service,
    ):
        """Results are ordered by BM25 relevance, not insertion order."""
        await _seed_tree(event_store, projector, nodes=[
            {"role": "user", "content": "The weather is nice today"},
            {"role": "user", "content": "Relevance relevance relevance — this node is very relevant to relevance"},
            {"role": "user", "content": "Tangentially mentioning relevance once"},
        ])
        result = await search_service.search("relevance")
        assert result.total >= 2
        # The node with more occurrences of "relevance" should rank higher
        assert "very relevant" in result.results[0].content


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------

class TestSearchAPI:
    """GET /api/search endpoint."""

    async def test_search_endpoint_returns_200(
        self, db, event_store, projector, client,
    ):
        """GET /api/search?q=keyword returns 200 with correct shape."""
        await _seed_tree(event_store, projector, nodes=[
            {"role": "user", "content": "searchable endpoint content"},
        ])
        resp = await client.get("/api/search", params={"q": "searchable"})
        assert resp.status_code == 200
        body = resp.json()
        assert "query" in body
        assert "results" in body
        assert "total" in body
        assert body["query"] == "searchable"
        assert len(body["results"]) >= 1
        item = body["results"][0]
        assert "node_id" in item
        assert "tree_id" in item
        assert "snippet" in item

    async def test_search_endpoint_requires_query(self, client):
        """GET /api/search without q parameter returns 422."""
        resp = await client.get("/api/search")
        assert resp.status_code == 422
