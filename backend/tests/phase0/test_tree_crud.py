"""Contract and integration tests for rhizome and node CRUD (Phase 0.3).

Tests the API endpoints end-to-end: create rhizomes, add messages, retrieve.
"""


class TestCreateRhizome:
    async def test_create_rhizome_returns_correct_fields(self, client):
        """POST /api/rhizomes returns a rhizome with the provided title."""
        resp = await client.post("/api/rhizomes", json={"title": "My Rhizome"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "My Rhizome"
        assert data["rhizome_id"] is not None
        assert data["nodes"] == []
        assert data["conversation_mode"] == "single"
        assert data["archived"] == 0

    async def test_create_rhizome_with_all_fields(self, client):
        """POST /api/rhizomes with all optional fields."""
        resp = await client.post("/api/rhizomes", json={
            "title": "Full Rhizome",
            "default_system_prompt": "You are helpful.",
            "default_model": "claude-sonnet-4-5-20250929",
            "default_provider": "anthropic",
            "default_sampling_params": {"temperature": 0.7, "max_tokens": 1024},
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Full Rhizome"
        assert data["default_system_prompt"] == "You are helpful."
        assert data["default_model"] == "claude-sonnet-4-5-20250929"
        assert data["default_provider"] == "anthropic"
        assert data["default_sampling_params"]["temperature"] == 0.7

    async def test_create_rhizome_minimal(self, client):
        """POST /api/rhizomes with empty body works (all fields optional)."""
        resp = await client.post("/api/rhizomes", json={})
        assert resp.status_code == 201
        data = resp.json()
        assert data["rhizome_id"] is not None
        assert data["title"] is None


class TestListRhizomes:
    async def test_list_rhizomes_empty(self, client):
        """GET /api/rhizomes returns empty list when no rhizomes exist."""
        resp = await client.get("/api/rhizomes")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_rhizomes_returns_created(self, client):
        """GET /api/rhizomes returns rhizomes that were created."""
        await client.post("/api/rhizomes", json={"title": "Rhizome A"})
        await client.post("/api/rhizomes", json={"title": "Rhizome B"})

        resp = await client.get("/api/rhizomes")
        assert resp.status_code == 200
        rhizomes = resp.json()
        assert len(rhizomes) == 2
        titles = {t["title"] for t in rhizomes}
        assert titles == {"Rhizome A", "Rhizome B"}


class TestGetRhizome:
    async def test_get_rhizome_returns_detail(self, client):
        """GET /api/rhizomes/{id} returns the full rhizome with nodes."""
        create_resp = await client.post("/api/rhizomes", json={"title": "Detail Rhizome"})
        rhizome_id = create_resp.json()["rhizome_id"]

        resp = await client.get(f"/api/rhizomes/{rhizome_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["rhizome_id"] == rhizome_id
        assert data["title"] == "Detail Rhizome"

    async def test_get_rhizome_not_found(self, client):
        """GET /api/rhizomes/{id} returns 404 for nonexistent rhizome."""
        resp = await client.get("/api/rhizomes/nonexistent-id")
        assert resp.status_code == 404

    async def test_get_rhizome_includes_nodes(self, client):
        """GET /api/rhizomes/{id} includes nodes that were added."""
        create_resp = await client.post("/api/rhizomes", json={"title": "With Nodes"})
        rhizome_id = create_resp.json()["rhizome_id"]

        await client.post(f"/api/rhizomes/{rhizome_id}/nodes", json={
            "content": "First message",
        })
        await client.post(f"/api/rhizomes/{rhizome_id}/nodes", json={
            "content": "Second message",
        })

        resp = await client.get(f"/api/rhizomes/{rhizome_id}")
        data = resp.json()
        assert len(data["nodes"]) == 2
        contents = [n["content"] for n in data["nodes"]]
        assert "First message" in contents
        assert "Second message" in contents


class TestCreateNode:
    async def test_create_node_basic(self, client):
        """POST /api/rhizomes/{id}/nodes creates a user message."""
        create_resp = await client.post("/api/rhizomes", json={"title": "Node Test"})
        rhizome_id = create_resp.json()["rhizome_id"]

        resp = await client.post(f"/api/rhizomes/{rhizome_id}/nodes", json={
            "content": "Hello world",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["content"] == "Hello world"
        assert data["role"] == "user"
        assert data["rhizome_id"] == rhizome_id
        assert data["node_id"] is not None

    async def test_create_node_with_parent(self, client):
        """POST /api/rhizomes/{id}/nodes with parent_id links to parent."""
        create_resp = await client.post("/api/rhizomes", json={"title": "Parent Test"})
        rhizome_id = create_resp.json()["rhizome_id"]

        node1_resp = await client.post(f"/api/rhizomes/{rhizome_id}/nodes", json={
            "content": "First",
        })
        node1_id = node1_resp.json()["node_id"]

        node2_resp = await client.post(f"/api/rhizomes/{rhizome_id}/nodes", json={
            "content": "Second",
            "parent_id": node1_id,
        })
        assert node2_resp.status_code == 201
        assert node2_resp.json()["parent_id"] == node1_id

    async def test_create_node_nonexistent_rhizome(self, client):
        """POST /api/rhizomes/{id}/nodes on nonexistent rhizome returns 404."""
        resp = await client.post("/api/rhizomes/nonexistent/nodes", json={
            "content": "Hello",
        })
        assert resp.status_code == 404

    async def test_create_node_invalid_parent(self, client):
        """POST /api/rhizomes/{id}/nodes with invalid parent_id returns 400."""
        create_resp = await client.post("/api/rhizomes", json={"title": "Bad Parent"})
        rhizome_id = create_resp.json()["rhizome_id"]

        resp = await client.post(f"/api/rhizomes/{rhizome_id}/nodes", json={
            "content": "Hello",
            "parent_id": "nonexistent-node-id",
        })
        assert resp.status_code == 400


class TestFullWorkflow:
    async def test_create_rhizome_add_messages_retrieve(self, client):
        """Integration: create rhizome, add messages, retrieve with all messages."""
        # Create rhizome
        rhizome_resp = await client.post("/api/rhizomes", json={
            "title": "Workflow Test",
            "default_system_prompt": "You are helpful.",
        })
        assert rhizome_resp.status_code == 201
        rhizome_id = rhizome_resp.json()["rhizome_id"]

        # Add messages
        msg1 = await client.post(f"/api/rhizomes/{rhizome_id}/nodes", json={
            "content": "What is 2+2?",
        })
        assert msg1.status_code == 201

        msg2 = await client.post(f"/api/rhizomes/{rhizome_id}/nodes", json={
            "content": "The answer is 4.",
            "parent_id": msg1.json()["node_id"],
        })
        assert msg2.status_code == 201

        # Retrieve
        detail = await client.get(f"/api/rhizomes/{rhizome_id}")
        data = detail.json()
        assert data["title"] == "Workflow Test"
        assert len(data["nodes"]) == 2

    async def test_multiple_rhizomes_independent(self, client):
        """Nodes added to one rhizome don't appear in another."""
        rhizome_a = await client.post("/api/rhizomes", json={"title": "Rhizome A"})
        rhizome_b = await client.post("/api/rhizomes", json={"title": "Rhizome B"})
        rhizome_a_id = rhizome_a.json()["rhizome_id"]
        rhizome_b_id = rhizome_b.json()["rhizome_id"]

        await client.post(f"/api/rhizomes/{rhizome_a_id}/nodes", json={"content": "A msg"})
        await client.post(f"/api/rhizomes/{rhizome_b_id}/nodes", json={"content": "B msg"})

        data_a = (await client.get(f"/api/rhizomes/{rhizome_a_id}")).json()
        data_b = (await client.get(f"/api/rhizomes/{rhizome_b_id}")).json()

        assert len(data_a["nodes"]) == 1
        assert data_a["nodes"][0]["content"] == "A msg"
        assert len(data_b["nodes"]) == 1
        assert data_b["nodes"][0]["content"] == "B msg"
