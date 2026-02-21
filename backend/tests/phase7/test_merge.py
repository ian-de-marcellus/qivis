"""Tests for Phase 7.2b: Merge imported conversations into existing trees."""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.importer.merge import MergePlan, _compute_merge_plan
from qivis.importer.models import ImportedNode, ImportedTree
from qivis.main import app
from qivis.trees.router import get_tree_service
from qivis.trees.service import TreeService


# ---------------------------------------------------------------------------
# Helpers for building fixture data
# ---------------------------------------------------------------------------


def _imported_node(
    temp_id: str,
    parent: str | None,
    role: str,
    content: str,
    *,
    model: str | None = None,
    provider: str | None = None,
    timestamp: float | None = None,
) -> ImportedNode:
    return ImportedNode(
        temp_id=temp_id,
        parent_temp_id=parent,
        role=role,
        content=content,
        model=model,
        provider=provider,
        timestamp=timestamp,
    )


def _imported_tree(nodes: list[ImportedNode]) -> ImportedTree:
    roots = [n.temp_id for n in nodes if n.parent_temp_id is None]
    return ImportedTree(
        title="Test Import",
        source_format="linear",
        nodes=nodes,
        root_temp_ids=roots,
    )


def _existing_node(
    node_id: str,
    parent_id: str | None,
    role: str,
    content: str,
    *,
    edited_content: str | None = None,
) -> dict:
    return {
        "node_id": node_id,
        "parent_id": parent_id,
        "role": role,
        "content": content,
        "edited_content": edited_content,
    }


# ---------------------------------------------------------------------------
# Contract tests: _compute_merge_plan
# ---------------------------------------------------------------------------


class TestComputeMergePlan:
    """Test the pure matching algorithm without I/O."""

    def test_linear_extend(self):
        """Existing A->B->C->D, import A'->B'->C'->D'->E->F.
        Should match 4 and create 2 new (E, F)."""
        existing = [
            _existing_node("n1", None, "user", "Hello"),
            _existing_node("n2", "n1", "assistant", "Hi there"),
            _existing_node("n3", "n2", "user", "How are you?"),
            _existing_node("n4", "n3", "assistant", "I'm doing well"),
        ]
        imported = _imported_tree([
            _imported_node("a", None, "user", "Hello"),
            _imported_node("b", "a", "assistant", "Hi there"),
            _imported_node("c", "b", "user", "How are you?"),
            _imported_node("d", "c", "assistant", "I'm doing well"),
            _imported_node("e", "d", "user", "What's new?"),
            _imported_node("f", "e", "assistant", "Not much!"),
        ])

        plan = _compute_merge_plan(imported, existing)

        assert len(plan.matched) == 4
        assert plan.matched["a"] == "n1"
        assert plan.matched["b"] == "n2"
        assert plan.matched["c"] == "n3"
        assert plan.matched["d"] == "n4"
        assert len(plan.new_nodes) == 2
        assert [n.temp_id for n in plan.new_nodes] == ["e", "f"]
        # E should be grafted onto n4 (the matched parent of D)
        assert plan.graft_map["e"] == "n4"
        # F's parent (E) is new, so F's graft_map entry should be None
        # (its parent_temp_id is "e" which is not in matched)
        # Actually F's parent is E which is new, so graft_map["f"] should
        # point to E's graft parent, which we set to None when parent is new.
        # Let me re-check the algorithm: when parent is new, we set
        # graft_map[temp_id] = graft_map of parent. But parent's graft_map
        # is "n4". Hmm no — the algorithm says:
        #   parent_real_id = plan.graft_map.get(node.parent_temp_id)
        # For F: parent_temp_id="e", "e" not in matched, so we look at
        # graft_map["e"] = "n4" -> graft_map["f"] = "n4"
        # But that's wrong for graft_map semantics. Let me check.
        # Actually graft_map is just for tracking, execute_merge resolves
        # the real parent via temp_to_real for new-to-new relationships.
        # The graft_map value for F doesn't matter much since F's parent
        # is another new node (E). What matters is the graft_map["e"] = "n4".

    def test_diverge_creates_branch(self):
        """Existing A->B->C->D, import A'->B'->X->Y.
        Should match 2 (A, B), create 2 new (X, Y) branching from B."""
        existing = [
            _existing_node("n1", None, "user", "Hello"),
            _existing_node("n2", "n1", "assistant", "Hi there"),
            _existing_node("n3", "n2", "user", "How are you?"),
            _existing_node("n4", "n3", "assistant", "I'm doing well"),
        ]
        imported = _imported_tree([
            _imported_node("a", None, "user", "Hello"),
            _imported_node("b", "a", "assistant", "Hi there"),
            _imported_node("x", "b", "user", "Something different"),
            _imported_node("y", "x", "assistant", "Different response"),
        ])

        plan = _compute_merge_plan(imported, existing)

        assert len(plan.matched) == 2
        assert plan.matched["a"] == "n1"
        assert plan.matched["b"] == "n2"
        assert len(plan.new_nodes) == 2
        assert [n.temp_id for n in plan.new_nodes] == ["x", "y"]
        # X grafts onto n2 (B's matched ID)
        assert plan.graft_map["x"] == "n2"

    def test_no_overlap_creates_new_root(self):
        """Completely different content. All nodes new as new root(s)."""
        existing = [
            _existing_node("n1", None, "user", "Hello"),
            _existing_node("n2", "n1", "assistant", "Hi there"),
        ]
        imported = _imported_tree([
            _imported_node("a", None, "user", "Completely different"),
            _imported_node("b", "a", "assistant", "Also different"),
        ])

        plan = _compute_merge_plan(imported, existing)

        assert len(plan.matched) == 0
        assert len(plan.new_nodes) == 2
        # A is a new root: graft_map["a"] = None
        assert plan.graft_map["a"] is None

    def test_full_overlap_nothing_to_merge(self):
        """All imported nodes match existing ones. Nothing new."""
        existing = [
            _existing_node("n1", None, "user", "Hello"),
            _existing_node("n2", "n1", "assistant", "Hi there"),
            _existing_node("n3", "n2", "user", "Goodbye"),
        ]
        imported = _imported_tree([
            _imported_node("a", None, "user", "Hello"),
            _imported_node("b", "a", "assistant", "Hi there"),
            _imported_node("c", "b", "user", "Goodbye"),
        ])

        plan = _compute_merge_plan(imported, existing)

        assert len(plan.matched) == 3
        assert len(plan.new_nodes) == 0

    def test_branching_import_partial_overlap(self):
        """Import has a fork: A->B->C and A->B->X.
        Existing has A->B->C. Should match A, B, C and create X."""
        existing = [
            _existing_node("n1", None, "user", "Hello"),
            _existing_node("n2", "n1", "assistant", "Hi"),
            _existing_node("n3", "n2", "user", "Path C"),
        ]
        imported = _imported_tree([
            _imported_node("a", None, "user", "Hello"),
            _imported_node("b", "a", "assistant", "Hi"),
            _imported_node("c", "b", "user", "Path C"),
            _imported_node("x", "b", "user", "Path X"),
        ])

        plan = _compute_merge_plan(imported, existing)

        assert len(plan.matched) == 3
        assert plan.matched["c"] == "n3"
        assert len(plan.new_nodes) == 1
        assert plan.new_nodes[0].temp_id == "x"
        # X grafts onto n2 (B's matched parent)
        assert plan.graft_map["x"] == "n2"

    def test_whitespace_normalization(self):
        """Content with leading/trailing whitespace should still match."""
        existing = [
            _existing_node("n1", None, "user", "Hello"),
            _existing_node("n2", "n1", "assistant", "Hi there"),
        ]
        imported = _imported_tree([
            _imported_node("a", None, "user", "  Hello  "),
            _imported_node("b", "a", "assistant", "Hi there\n"),
        ])

        plan = _compute_merge_plan(imported, existing)

        assert len(plan.matched) == 2
        assert len(plan.new_nodes) == 0

    def test_match_against_edited_content(self):
        """When edited_content is set, match against that instead of content."""
        existing = [
            _existing_node(
                "n1", None, "user", "Original text",
                edited_content="Edited text",
            ),
            _existing_node("n2", "n1", "assistant", "Response"),
        ]
        # Import with the edited version should match
        imported_match = _imported_tree([
            _imported_node("a", None, "user", "Edited text"),
            _imported_node("b", "a", "assistant", "Response"),
        ])
        plan = _compute_merge_plan(imported_match, existing)
        assert len(plan.matched) == 2

        # Import with the original version should NOT match
        imported_no_match = _imported_tree([
            _imported_node("a", None, "user", "Original text"),
            _imported_node("b", "a", "assistant", "Response"),
        ])
        plan2 = _compute_merge_plan(imported_no_match, existing)
        assert len(plan2.matched) == 0

    def test_role_mismatch_does_not_match(self):
        """Same content but different role should not match."""
        existing = [
            _existing_node("n1", None, "user", "Hello"),
        ]
        imported = _imported_tree([
            _imported_node("a", None, "assistant", "Hello"),
        ])

        plan = _compute_merge_plan(imported, existing)

        assert len(plan.matched) == 0
        assert len(plan.new_nodes) == 1


# ---------------------------------------------------------------------------
# Integration tests: API endpoints
# ---------------------------------------------------------------------------


def _make_linear_json(messages: list[dict]) -> bytes:
    """Build a simple linear (ShareGPT) format JSON for testing."""
    return json.dumps(messages).encode()


@pytest.fixture
async def setup():
    """Create a fresh database and test client."""
    db = await Database.connect(":memory:")
    store = EventStore(db)
    projector = StateProjector(db)
    service = TreeService(db)
    app.dependency_overrides[get_tree_service] = lambda: service

    from qivis.importer.merge import MergeService
    from qivis.importer.merge_router import get_merge_service

    merge_svc = MergeService(db, store, projector)
    app.dependency_overrides[get_merge_service] = lambda: merge_svc

    from qivis.importer.service import ImportService
    from qivis.importer.router import get_import_service

    import_svc = ImportService(db, store, projector)
    app.dependency_overrides[get_import_service] = lambda: import_svc

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, service, store, db

    app.dependency_overrides.clear()
    await db.close()


async def _create_tree_with_messages(
    client: AsyncClient,
    messages: list[tuple[str, str]],
) -> tuple[str, list[str]]:
    """Helper: create a tree and add messages manually. Returns (tree_id, node_ids)."""
    resp = await client.post("/api/trees", json={"title": "Test Tree"})
    assert resp.status_code == 201
    tree_id = resp.json()["tree_id"]

    node_ids = []
    parent_id = None
    for role, content in messages:
        resp = await client.post(
            f"/api/trees/{tree_id}/nodes",
            json={"parent_id": parent_id, "role": role, "content": content},
        )
        assert resp.status_code == 201
        node_id = resp.json()["node_id"]
        node_ids.append(node_id)
        parent_id = node_id

    return tree_id, node_ids


class TestMergeAPI:
    """Integration tests through the HTTP API."""

    @pytest.mark.asyncio
    async def test_preview_returns_correct_counts(self, setup):
        client, *_ = setup
        tree_id, node_ids = await _create_tree_with_messages(client, [
            ("user", "Hello"),
            ("assistant", "Hi there"),
        ])

        # Import file extends the conversation
        file_data = _make_linear_json([
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "New message"},
            {"role": "assistant", "content": "New response"},
        ])

        resp = await client.post(
            f"/api/trees/{tree_id}/merge/preview",
            files={"file": ("test.json", file_data, "application/json")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["matched_count"] == 2
        assert data["new_count"] == 2
        assert data["total_imported"] == 4
        assert data["source_format"] == "linear"
        assert len(data["graft_points"]) == 1

    @pytest.mark.asyncio
    async def test_merge_creates_nodes_with_correct_parent(self, setup):
        client, *_ = setup
        tree_id, node_ids = await _create_tree_with_messages(client, [
            ("user", "Hello"),
            ("assistant", "Hi there"),
        ])

        file_data = _make_linear_json([
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "New question"},
        ])

        resp = await client.post(
            f"/api/trees/{tree_id}/merge",
            files={"file": ("test.json", file_data, "application/json")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["created_count"] == 1
        assert data["matched_count"] == 2
        assert len(data["node_ids"]) == 1

        # Verify the new node is in the tree with correct parent
        tree_resp = await client.get(f"/api/trees/{tree_id}")
        tree_data = tree_resp.json()
        new_node = next(
            n for n in tree_data["nodes"] if n["node_id"] == data["node_ids"][0]
        )
        assert new_node["parent_id"] == node_ids[-1]  # parented to last existing node
        assert new_node["role"] == "user"
        assert new_node["content"] == "New question"

    @pytest.mark.asyncio
    async def test_merge_preserves_metadata(self, setup):
        client, *_ = setup
        tree_id, _ = await _create_tree_with_messages(client, [
            ("user", "Hello"),
        ])

        # Import with model/provider info
        file_data = _make_linear_json([
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Response", "model": "gpt-4"},
        ])

        resp = await client.post(
            f"/api/trees/{tree_id}/merge",
            files={"file": ("test.json", file_data, "application/json")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["created_count"] == 1

        tree_resp = await client.get(f"/api/trees/{tree_id}")
        new_node = next(
            n for n in tree_resp.json()["nodes"]
            if n["node_id"] == data["node_ids"][0]
        )
        assert new_node["model"] == "gpt-4"

    @pytest.mark.asyncio
    async def test_merge_events_have_device_id_merge(self, setup):
        client, _, store, db = setup
        tree_id, _ = await _create_tree_with_messages(client, [
            ("user", "Hello"),
        ])

        file_data = _make_linear_json([
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "New response"},
        ])

        resp = await client.post(
            f"/api/trees/{tree_id}/merge",
            files={"file": ("test.json", file_data, "application/json")},
        )
        assert resp.status_code == 200

        # Check event log
        events = await store.get_events(tree_id)
        merge_events = [e for e in events if e.device_id == "merge"]
        assert len(merge_events) == 1
        assert merge_events[0].event_type == "NodeCreated"

    @pytest.mark.asyncio
    async def test_merge_tree_not_found_404(self, setup):
        client, *_ = setup

        file_data = _make_linear_json([
            {"role": "user", "content": "Hello"},
        ])

        resp = await client.post(
            "/api/trees/nonexistent-id/merge/preview",
            files={"file": ("test.json", file_data, "application/json")},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_full_overlap_returns_zero_created(self, setup):
        client, *_ = setup
        tree_id, _ = await _create_tree_with_messages(client, [
            ("user", "Hello"),
            ("assistant", "Hi there"),
        ])

        file_data = _make_linear_json([
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ])

        resp = await client.post(
            f"/api/trees/{tree_id}/merge",
            files={"file": ("test.json", file_data, "application/json")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["created_count"] == 0
        assert data["matched_count"] == 2
        assert data["node_ids"] == []

    @pytest.mark.asyncio
    async def test_existing_tree_unchanged_after_merge(self, setup):
        client, *_ = setup
        tree_id, original_ids = await _create_tree_with_messages(client, [
            ("user", "Hello"),
            ("assistant", "Hi there"),
        ])

        # Get original tree state
        orig_resp = await client.get(f"/api/trees/{tree_id}")
        orig_nodes = {
            n["node_id"]: n for n in orig_resp.json()["nodes"]
        }

        # Merge extending conversation
        file_data = _make_linear_json([
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "New message"},
        ])

        await client.post(
            f"/api/trees/{tree_id}/merge",
            files={"file": ("test.json", file_data, "application/json")},
        )

        # Verify original nodes unchanged
        new_resp = await client.get(f"/api/trees/{tree_id}")
        for node in new_resp.json()["nodes"]:
            if node["node_id"] in orig_nodes:
                orig = orig_nodes[node["node_id"]]
                assert node["content"] == orig["content"]
                assert node["parent_id"] == orig["parent_id"]
                assert node["role"] == orig["role"]
