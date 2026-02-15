"""Contract and integration tests for branching data model (Phase 1.1).

Tests that NodeResponse includes sibling_count and sibling_index,
computed at query time. Validates branching tree topologies.
"""

from tests.fixtures import create_branching_tree, create_test_tree


class TestSiblingMetadata:
    """Verify sibling_count and sibling_index on NodeResponse."""

    async def test_single_child_has_sibling_count_one_index_zero(self, client):
        """A lone root node is sibling 0 of 1."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        resp = await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "Only child",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["sibling_count"] == 1
        assert data["sibling_index"] == 0

    async def test_two_siblings_have_correct_count_and_indices(self, client):
        """Two children of the same parent get index 0 and 1, both count 2."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        # Parent node
        parent = await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "Parent",
        })
        parent_id = parent.json()["node_id"]

        # First child
        await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "Child B",
            "role": "assistant",
            "parent_id": parent_id,
        })

        # Second child (sibling of B)
        await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "Child C",
            "role": "assistant",
            "parent_id": parent_id,
        })

        # GET tree to see computed sibling info
        tree_resp = await client.get(f"/api/trees/{tree_id}")
        nodes = tree_resp.json()["nodes"]
        children = [n for n in nodes if n["parent_id"] == parent_id]
        children.sort(key=lambda n: n["sibling_index"])

        assert len(children) == 2
        assert children[0]["sibling_index"] == 0
        assert children[0]["sibling_count"] == 2
        assert children[1]["sibling_index"] == 1
        assert children[1]["sibling_count"] == 2

    async def test_three_siblings_ordering_by_created_at(self, client):
        """Three children ordered by creation time get indices 0, 1, 2."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        parent = await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "Parent",
        })
        parent_id = parent.json()["node_id"]

        for i in range(3):
            await client.post(f"/api/trees/{tree_id}/nodes", json={
                "content": f"Child {i}",
                "role": "assistant",
                "parent_id": parent_id,
            })

        tree_resp = await client.get(f"/api/trees/{tree_id}")
        nodes = tree_resp.json()["nodes"]
        children = [n for n in nodes if n["parent_id"] == parent_id]
        children.sort(key=lambda n: n["sibling_index"])

        assert len(children) == 3
        for i, child in enumerate(children):
            assert child["sibling_index"] == i
            assert child["sibling_count"] == 3

    async def test_siblings_at_different_depths_independent(self, client):
        """Sibling counts at different tree depths are independent."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        # Root has 2 children (depth 1 siblings)
        root = await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "Root",
        })
        root_id = root.json()["node_id"]

        child_a = await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "A",
            "role": "assistant",
            "parent_id": root_id,
        })
        a_id = child_a.json()["node_id"]

        await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "B",
            "role": "assistant",
            "parent_id": root_id,
        })

        # A has 3 children (depth 2 siblings)
        for i in range(3):
            await client.post(f"/api/trees/{tree_id}/nodes", json={
                "content": f"A-child-{i}",
                "parent_id": a_id,
            })

        tree_resp = await client.get(f"/api/trees/{tree_id}")
        nodes = tree_resp.json()["nodes"]

        depth1 = [n for n in nodes if n["parent_id"] == root_id]
        depth2 = [n for n in nodes if n["parent_id"] == a_id]

        assert all(n["sibling_count"] == 2 for n in depth1)
        assert all(n["sibling_count"] == 3 for n in depth2)

    async def test_create_node_response_includes_sibling_fields(self, client):
        """POST /api/trees/{id}/nodes response has sibling_count and sibling_index."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        resp = await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "Hello",
        })
        data = resp.json()
        assert "sibling_count" in data
        assert "sibling_index" in data

    async def test_tree_detail_nodes_include_sibling_fields(self, client):
        """GET /api/trees/{id} nodes all have sibling_count and sibling_index."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        await client.post(f"/api/trees/{tree_id}/nodes", json={"content": "A"})
        await client.post(f"/api/trees/{tree_id}/nodes", json={"content": "B"})

        tree_resp = await client.get(f"/api/trees/{tree_id}")
        for node in tree_resp.json()["nodes"]:
            assert "sibling_count" in node
            assert "sibling_index" in node


class TestBranchingTreeStructure:
    """Integration tests for branching tree topologies."""

    async def test_create_branch_from_non_leaf_node(self, client):
        """Fork from a non-leaf node creates a sibling branch."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        # Linear: A -> B -> C
        a = await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "A",
        })
        a_id = a.json()["node_id"]

        b = await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "B",
            "role": "assistant",
            "parent_id": a_id,
        })
        b_id = b.json()["node_id"]

        await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "C",
            "parent_id": b_id,
        })

        # Fork: D is a new child of A (sibling of B)
        d = await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "D (fork)",
            "role": "assistant",
            "parent_id": a_id,
        })
        assert d.status_code == 201

        tree_resp = await client.get(f"/api/trees/{tree_id}")
        nodes = tree_resp.json()["nodes"]
        assert len(nodes) == 4

        # B and D are siblings (both children of A)
        children_of_a = [n for n in nodes if n["parent_id"] == a_id]
        assert len(children_of_a) == 2
        assert all(n["sibling_count"] == 2 for n in children_of_a)

    async def test_deep_branching_tree_sibling_counts(self, client):
        """Verify topology from create_branching_tree fixture."""
        result = await create_branching_tree(client)
        tree_id = result["tree_id"]
        ids = result["node_ids"]

        tree_resp = await client.get(f"/api/trees/{tree_id}")
        nodes = tree_resp.json()["nodes"]
        by_id = {n["node_id"]: n for n in nodes}

        # root and A are each lone children at their level
        # (root has parent_id=None, A has parent_id=root)
        assert by_id[ids["root"]]["sibling_count"] == 1
        assert by_id[ids["A"]]["sibling_count"] == 1

        # B and C are siblings (both children of A)
        assert by_id[ids["B"]]["sibling_count"] == 2
        assert by_id[ids["C"]]["sibling_count"] == 2
        assert by_id[ids["B"]]["sibling_index"] == 0
        assert by_id[ids["C"]]["sibling_index"] == 1

    async def test_adding_sibling_updates_existing_counts(self, client):
        """Query-time computation means adding a sibling updates all counts."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        parent = await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "Parent",
        })
        parent_id = parent.json()["node_id"]

        # First child — alone
        b = await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "B",
            "role": "assistant",
            "parent_id": parent_id,
        })
        b_id = b.json()["node_id"]

        # Before adding sibling: B has count=1
        tree_resp = await client.get(f"/api/trees/{tree_id}")
        nodes = tree_resp.json()["nodes"]
        b_node = next(n for n in nodes if n["node_id"] == b_id)
        assert b_node["sibling_count"] == 1

        # Add sibling C
        await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "C",
            "role": "assistant",
            "parent_id": parent_id,
        })

        # After: both B and C have count=2
        tree_resp = await client.get(f"/api/trees/{tree_id}")
        nodes = tree_resp.json()["nodes"]
        children = [n for n in nodes if n["parent_id"] == parent_id]
        assert all(n["sibling_count"] == 2 for n in children)


class TestBranchingEdgeCases:
    """Edge cases for branching metadata."""

    async def test_empty_tree_no_nodes(self, client):
        """A tree with zero nodes returns empty list, no error."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        tree_resp = await client.get(f"/api/trees/{tree_id}")
        assert tree_resp.json()["nodes"] == []

    async def test_single_root_node(self, client):
        """A single root node is sibling 0 of 1."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "Only root",
        })

        tree_resp = await client.get(f"/api/trees/{tree_id}")
        nodes = tree_resp.json()["nodes"]
        assert len(nodes) == 1
        assert nodes[0]["sibling_count"] == 1
        assert nodes[0]["sibling_index"] == 0

    async def test_many_siblings(self, client):
        """A node with 10 children: all have count=10, indices 0-9."""
        tree = await create_test_tree(client)
        tree_id = tree["tree_id"]

        parent = await client.post(f"/api/trees/{tree_id}/nodes", json={
            "content": "Parent",
        })
        parent_id = parent.json()["node_id"]

        for i in range(10):
            await client.post(f"/api/trees/{tree_id}/nodes", json={
                "content": f"Child {i}",
                "role": "assistant",
                "parent_id": parent_id,
            })

        tree_resp = await client.get(f"/api/trees/{tree_id}")
        nodes = tree_resp.json()["nodes"]
        children = [n for n in nodes if n["parent_id"] == parent_id]
        children.sort(key=lambda n: n["sibling_index"])

        assert len(children) == 10
        for i, child in enumerate(children):
            assert child["sibling_index"] == i
            assert child["sibling_count"] == 10
