"""Contract and integration tests for tree and node CRUD (Phase 0.3).

Tests the API endpoints end-to-end: create trees, add messages, retrieve.
"""


class TestCreateTree:
    async def test_create_tree_returns_correct_fields(self, client):
        """POST /api/trees returns a tree with the provided title."""
        resp = await client.post("/api/trees", json={"title": "My Tree"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "My Tree"
        assert data["tree_id"] is not None
        assert data["nodes"] == []
        assert data["conversation_mode"] == "single"
        assert data["archived"] == 0

    async def test_create_tree_with_all_fields(self, client):
        """POST /api/trees with all optional fields."""
        resp = await client.post("/api/trees", json={
            "title": "Full Tree",
            "default_system_prompt": "You are helpful.",
            "default_model": "claude-sonnet-4-5-20250929",
            "default_provider": "anthropic",
            "default_sampling_params": {"temperature": 0.7, "max_tokens": 1024},
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Full Tree"
        assert data["default_system_prompt"] == "You are helpful."
        assert data["default_model"] == "claude-sonnet-4-5-20250929"
        assert data["default_provider"] == "anthropic"
        assert data["default_sampling_params"]["temperature"] == 0.7

    async def test_create_tree_minimal(self, client):
        """POST /api/trees with empty body works (all fields optional)."""
        resp = await client.post("/api/trees", json={})
        assert resp.status_code == 201
        data = resp.json()
        assert data["tree_id"] is not None
        assert data["title"] is None


class TestListTrees:
    async def test_list_trees_empty(self, client):
        """GET /api/trees returns empty list when no trees exist."""
        resp = await client.get("/api/trees")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_trees_returns_created(self, client):
        """GET /api/trees returns trees that were created."""
        await client.post("/api/trees", json={"title": "Tree A"})
        await client.post("/api/trees", json={"title": "Tree B"})

        resp = await client.get("/api/trees")
        assert resp.status_code == 200
        trees = resp.json()
        assert len(trees) == 2
        titles = {t["title"] for t in trees}
        assert titles == {"Tree A", "Tree B"}


class TestGetTree:
    async def test_get_tree_returns_detail(self, client):
        """GET /api/trees/{id} returns the full tree with nodes."""
        create_resp = await client.post("/api/trees", json={"title": "Detail Tree"})
        tree_id = create_resp.json()["tree_id"]

        resp = await client.get(f"/api/trees/{tree_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tree_id"] == tree_id
        assert data["title"] == "Detail Tree"

    async def test_get_tree_not_found(self, client):
        """GET /api/trees/{id} returns 404 for nonexistent tree."""
        resp = await client.get("/api/trees/nonexistent-id")
        assert resp.status_code == 404

    async def test_get_tree_includes_nodes(self, client):
        """GET /api/trees/{id} includes nodes that were added."""
        create_resp = await client.post("/api/trees", json={"title": "With Nodes"})
        tree_id = create_resp.json()["tree_id"]

        await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "First message",
        })
        await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "Second message",
        })

        resp = await client.get(f"/api/trees/{tree_id}")
        data = resp.json()
        assert len(data["nodes"]) == 2
        contents = [n["content"] for n in data["nodes"]]
        assert "First message" in contents
        assert "Second message" in contents


class TestCreateNode:
    async def test_create_node_basic(self, client):
        """POST /api/trees/{id}/nodes creates a user message."""
        create_resp = await client.post("/api/trees", json={"title": "Node Test"})
        tree_id = create_resp.json()["tree_id"]

        resp = await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "Hello world",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["content"] == "Hello world"
        assert data["role"] == "user"
        assert data["tree_id"] == tree_id
        assert data["node_id"] is not None

    async def test_create_node_with_parent(self, client):
        """POST /api/trees/{id}/nodes with parent_id links to parent."""
        create_resp = await client.post("/api/trees", json={"title": "Parent Test"})
        tree_id = create_resp.json()["tree_id"]

        node1_resp = await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "First",
        })
        node1_id = node1_resp.json()["node_id"]

        node2_resp = await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "Second",
            "parent_id": node1_id,
        })
        assert node2_resp.status_code == 201
        assert node2_resp.json()["parent_id"] == node1_id

    async def test_create_node_nonexistent_tree(self, client):
        """POST /api/trees/{id}/nodes on nonexistent tree returns 404."""
        resp = await client.post("/api/trees/nonexistent/nodes", json={
            "content": "Hello",
        })
        assert resp.status_code == 404

    async def test_create_node_invalid_parent(self, client):
        """POST /api/trees/{id}/nodes with invalid parent_id returns 400."""
        create_resp = await client.post("/api/trees", json={"title": "Bad Parent"})
        tree_id = create_resp.json()["tree_id"]

        resp = await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "Hello",
            "parent_id": "nonexistent-node-id",
        })
        assert resp.status_code == 400


class TestFullWorkflow:
    async def test_create_tree_add_messages_retrieve(self, client):
        """Integration: create tree, add messages, retrieve with all messages."""
        # Create tree
        tree_resp = await client.post("/api/trees", json={
            "title": "Workflow Test",
            "default_system_prompt": "You are helpful.",
        })
        assert tree_resp.status_code == 201
        tree_id = tree_resp.json()["tree_id"]

        # Add messages
        msg1 = await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "What is 2+2?",
        })
        assert msg1.status_code == 201

        msg2 = await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "The answer is 4.",
            "parent_id": msg1.json()["node_id"],
        })
        assert msg2.status_code == 201

        # Retrieve
        tree = await client.get(f"/api/trees/{tree_id}")
        data = tree.json()
        assert data["title"] == "Workflow Test"
        assert len(data["nodes"]) == 2

    async def test_multiple_trees_independent(self, client):
        """Nodes added to one tree don't appear in another."""
        tree_a = await client.post("/api/trees", json={"title": "Tree A"})
        tree_b = await client.post("/api/trees", json={"title": "Tree B"})
        tree_a_id = tree_a.json()["tree_id"]
        tree_b_id = tree_b.json()["tree_id"]

        await client.post(f"/api/trees/{tree_a_id}/nodes", json={"content": "A msg"})
        await client.post(f"/api/trees/{tree_b_id}/nodes", json={"content": "B msg"})

        data_a = (await client.get(f"/api/trees/{tree_a_id}")).json()
        data_b = (await client.get(f"/api/trees/{tree_b_id}")).json()

        assert len(data_a["nodes"]) == 1
        assert data_a["nodes"][0]["content"] == "A msg"
        assert len(data_b["nodes"]) == 1
        assert data_b["nodes"][0]["content"] == "B msg"
