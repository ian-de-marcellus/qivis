"""Tests for context exclusion and digression groups (Phase 6.3).

Five sections:
1. Contract tests -- projector handles exclusion/inclusion/group events
2. API integration tests -- node exclusion + digression group CRUD
3. ContextBuilder integration -- exclusions actually filter messages
4. is_excluded on NodeResponse
5. Event sourcing integrity -- exclusions + groups survive replay
"""

import pytest

from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.context import ContextBuilder
from tests.fixtures import (
    create_branching_tree,
    create_test_tree,
    create_tree_with_messages,
    make_digression_group_created_envelope,
    make_digression_group_toggled_envelope,
    make_node_context_excluded_envelope,
    make_node_context_included_envelope,
    make_node_created_envelope,
    make_tree_created_envelope,
)


# ---------------------------------------------------------------------------
# Contract tests: event -> store -> projector -> verify state
# ---------------------------------------------------------------------------


class TestExclusionProjection:
    """NodeContextExcluded/Included events project correctly."""

    async def test_node_context_excluded_projects(self, event_store, projector, db):
        """NodeContextExcluded inserts a row into node_exclusions table."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(tree_id=tree_ev.tree_id, content="Hello")
        scope_ev = make_node_created_envelope(
            tree_id=tree_ev.tree_id, parent_id=node_ev.payload["node_id"],
            role="assistant", content="Hi",
        )

        for e in [tree_ev, node_ev, scope_ev]:
            await event_store.append(e)
        await projector.project([tree_ev, node_ev, scope_ev])

        excl_ev = make_node_context_excluded_envelope(
            tree_id=tree_ev.tree_id,
            node_id=node_ev.payload["node_id"],
            scope_node_id=scope_ev.payload["node_id"],
            reason="Testing exclusion",
        )
        await event_store.append(excl_ev)
        await projector.project([excl_ev])

        row = await db.fetchone(
            "SELECT * FROM node_exclusions WHERE tree_id = ? AND node_id = ?",
            (tree_ev.tree_id, node_ev.payload["node_id"]),
        )
        assert row is not None
        assert row["scope_node_id"] == scope_ev.payload["node_id"]
        assert row["reason"] == "Testing exclusion"

    async def test_node_context_included_deletes_row(self, event_store, projector, db):
        """NodeContextIncluded removes the matching exclusion."""
        tree_ev = make_tree_created_envelope()
        node_ev = make_node_created_envelope(tree_id=tree_ev.tree_id, content="Hello")
        scope_ev = make_node_created_envelope(
            tree_id=tree_ev.tree_id, parent_id=node_ev.payload["node_id"],
            role="assistant", content="Hi",
        )

        for e in [tree_ev, node_ev, scope_ev]:
            await event_store.append(e)
        await projector.project([tree_ev, node_ev, scope_ev])

        node_id = node_ev.payload["node_id"]
        scope_node_id = scope_ev.payload["node_id"]

        excl_ev = make_node_context_excluded_envelope(
            tree_id=tree_ev.tree_id, node_id=node_id, scope_node_id=scope_node_id,
        )
        await event_store.append(excl_ev)
        await projector.project([excl_ev])

        incl_ev = make_node_context_included_envelope(
            tree_id=tree_ev.tree_id, node_id=node_id, scope_node_id=scope_node_id,
        )
        await event_store.append(incl_ev)
        await projector.project([incl_ev])

        row = await db.fetchone(
            "SELECT * FROM node_exclusions WHERE tree_id = ? AND node_id = ? AND scope_node_id = ?",
            (tree_ev.tree_id, node_id, scope_node_id),
        )
        assert row is None


class TestDigressionGroupProjection:
    """DigressionGroupCreated/Toggled events project correctly."""

    async def test_group_created_projects(self, event_store, projector, db):
        """DigressionGroupCreated inserts group + membership rows."""
        tree_ev = make_tree_created_envelope()
        n1 = make_node_created_envelope(tree_id=tree_ev.tree_id, content="Msg 1")
        n2 = make_node_created_envelope(
            tree_id=tree_ev.tree_id, parent_id=n1.payload["node_id"],
            role="assistant", content="Msg 2",
        )

        for e in [tree_ev, n1, n2]:
            await event_store.append(e)
        await projector.project([tree_ev, n1, n2])

        node_ids = [n1.payload["node_id"], n2.payload["node_id"]]
        group_ev = make_digression_group_created_envelope(
            tree_id=tree_ev.tree_id, node_ids=node_ids, label="Side topic",
        )
        await event_store.append(group_ev)
        await projector.project([group_ev])

        group_row = await db.fetchone(
            "SELECT * FROM digression_groups WHERE group_id = ?",
            (group_ev.payload["group_id"],),
        )
        assert group_row is not None
        assert group_row["label"] == "Side topic"
        assert group_row["included"] == 1

        member_rows = await db.fetchall(
            "SELECT * FROM digression_group_nodes WHERE group_id = ? ORDER BY sort_order",
            (group_ev.payload["group_id"],),
        )
        assert len(member_rows) == 2
        assert member_rows[0]["node_id"] == node_ids[0]
        assert member_rows[1]["node_id"] == node_ids[1]

    async def test_group_toggled_updates_state(self, event_store, projector, db):
        """DigressionGroupToggled updates the included flag."""
        tree_ev = make_tree_created_envelope()
        n1 = make_node_created_envelope(tree_id=tree_ev.tree_id, content="Msg")

        for e in [tree_ev, n1]:
            await event_store.append(e)
        await projector.project([tree_ev, n1])

        group_ev = make_digression_group_created_envelope(
            tree_id=tree_ev.tree_id,
            node_ids=[n1.payload["node_id"]],
            label="Aside",
        )
        await event_store.append(group_ev)
        await projector.project([group_ev])

        toggle_ev = make_digression_group_toggled_envelope(
            tree_id=tree_ev.tree_id,
            group_id=group_ev.payload["group_id"],
            included=False,
        )
        await event_store.append(toggle_ev)
        await projector.project([toggle_ev])

        row = await db.fetchone(
            "SELECT * FROM digression_groups WHERE group_id = ?",
            (group_ev.payload["group_id"],),
        )
        assert row["included"] == 0


# ---------------------------------------------------------------------------
# API integration tests: node exclusion CRUD
# ---------------------------------------------------------------------------


class TestNodeExclusionAPI:
    """POST exclude/include + GET exclusions endpoints."""

    async def test_exclude_node_returns_response(self, client):
        """POST exclude returns exclusion data."""
        data = await create_tree_with_messages(client, n_messages=4)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][1]  # exclude the assistant message
        scope_node_id = data["node_ids"][-1]  # leaf of current path

        resp = await client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/exclude",
            json={"scope_node_id": scope_node_id},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["node_id"] == node_id
        assert body["scope_node_id"] == scope_node_id
        assert body["tree_id"] == tree_id

    async def test_exclude_nonexistent_node_404(self, client):
        """POST exclude on nonexistent node returns 404."""
        tree = await create_test_tree(client)
        resp = await client.post(
            f"/api/trees/{tree['tree_id']}/nodes/no-such-node/exclude",
            json={"scope_node_id": "whatever"},
        )
        assert resp.status_code == 404

    async def test_get_exclusions_returns_list(self, client):
        """GET exclusions returns all exclusions for the tree."""
        data = await create_tree_with_messages(client, n_messages=4)
        tree_id = data["tree_id"]
        scope = data["node_ids"][-1]

        # Exclude two nodes
        await client.post(
            f"/api/trees/{tree_id}/nodes/{data['node_ids'][0]}/exclude",
            json={"scope_node_id": scope},
        )
        await client.post(
            f"/api/trees/{tree_id}/nodes/{data['node_ids'][1]}/exclude",
            json={"scope_node_id": scope, "reason": "Off-topic"},
        )

        resp = await client.get(f"/api/trees/{tree_id}/exclusions")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        reasons = {e["reason"] for e in body}
        assert "Off-topic" in reasons

    async def test_include_removes_exclusion(self, client):
        """POST include removes the matching exclusion."""
        data = await create_tree_with_messages(client, n_messages=4)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][1]
        scope = data["node_ids"][-1]

        await client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/exclude",
            json={"scope_node_id": scope},
        )

        resp = await client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/include",
            json={"scope_node_id": scope},
        )
        assert resp.status_code == 204

        excl_resp = await client.get(f"/api/trees/{tree_id}/exclusions")
        assert len(excl_resp.json()) == 0

    async def test_include_idempotent(self, client):
        """POST include on non-excluded node doesn't error."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][0]
        scope = data["node_ids"][-1]

        resp = await client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/include",
            json={"scope_node_id": scope},
        )
        assert resp.status_code == 204

    async def test_multiple_exclusions_different_scopes_coexist(self, client):
        """Same node excluded with different scope_node_ids creates separate records."""
        branching = await create_branching_tree(client)
        tree_id = branching["tree_id"]
        ids = branching["node_ids"]

        # Exclude root node from two different branches
        await client.post(
            f"/api/trees/{tree_id}/nodes/{ids['root']}/exclude",
            json={"scope_node_id": ids["B"]},
        )
        await client.post(
            f"/api/trees/{tree_id}/nodes/{ids['root']}/exclude",
            json={"scope_node_id": ids["C"]},
        )

        resp = await client.get(f"/api/trees/{tree_id}/exclusions")
        body = resp.json()
        assert len(body) == 2
        scopes = {e["scope_node_id"] for e in body}
        assert ids["B"] in scopes
        assert ids["C"] in scopes


# ---------------------------------------------------------------------------
# API integration tests: digression group CRUD
# ---------------------------------------------------------------------------


class TestDigressionGroupAPI:
    """POST/GET/toggle/DELETE digression group endpoints."""

    async def test_create_group_returns_response(self, client):
        """POST create group returns DigressionGroupResponse."""
        data = await create_tree_with_messages(client, n_messages=4)
        tree_id = data["tree_id"]
        node_ids = data["node_ids"][:2]  # first two messages

        resp = await client.post(
            f"/api/trees/{tree_id}/digression-groups",
            json={"node_ids": node_ids, "label": "Side topic"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["label"] == "Side topic"
        assert body["node_ids"] == node_ids
        assert body["included"] is True
        assert "group_id" in body

    async def test_create_group_noncontiguous_400(self, client):
        """POST create group with non-contiguous nodes returns 400."""
        data = await create_tree_with_messages(client, n_messages=6)
        tree_id = data["tree_id"]
        # Skip a node to make it non-contiguous
        node_ids = [data["node_ids"][0], data["node_ids"][2]]

        resp = await client.post(
            f"/api/trees/{tree_id}/digression-groups",
            json={"node_ids": node_ids, "label": "Gaps"},
        )
        assert resp.status_code == 400

    async def test_get_groups_returns_all(self, client):
        """GET groups returns all groups with toggle state."""
        data = await create_tree_with_messages(client, n_messages=6)
        tree_id = data["tree_id"]

        await client.post(
            f"/api/trees/{tree_id}/digression-groups",
            json={"node_ids": data["node_ids"][:2], "label": "Group A"},
        )
        await client.post(
            f"/api/trees/{tree_id}/digression-groups",
            json={"node_ids": data["node_ids"][2:4], "label": "Group B"},
        )

        resp = await client.get(f"/api/trees/{tree_id}/digression-groups")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        labels = {g["label"] for g in body}
        assert labels == {"Group A", "Group B"}

    async def test_toggle_group_off(self, client):
        """POST toggle group off sets included=false."""
        data = await create_tree_with_messages(client, n_messages=4)
        tree_id = data["tree_id"]

        create_resp = await client.post(
            f"/api/trees/{tree_id}/digression-groups",
            json={"node_ids": data["node_ids"][:2], "label": "Test"},
        )
        group_id = create_resp.json()["group_id"]

        toggle_resp = await client.post(
            f"/api/trees/{tree_id}/digression-groups/{group_id}/toggle",
            json={"included": False},
        )
        assert toggle_resp.status_code == 200
        assert toggle_resp.json()["included"] is False

        # Verify via GET
        groups = (await client.get(f"/api/trees/{tree_id}/digression-groups")).json()
        group = next(g for g in groups if g["group_id"] == group_id)
        assert group["included"] is False

    async def test_toggle_group_on(self, client):
        """POST toggle group on restores included=true."""
        data = await create_tree_with_messages(client, n_messages=4)
        tree_id = data["tree_id"]

        create_resp = await client.post(
            f"/api/trees/{tree_id}/digression-groups",
            json={"node_ids": data["node_ids"][:2], "label": "Test"},
        )
        group_id = create_resp.json()["group_id"]

        # Toggle off then on
        await client.post(
            f"/api/trees/{tree_id}/digression-groups/{group_id}/toggle",
            json={"included": False},
        )
        toggle_resp = await client.post(
            f"/api/trees/{tree_id}/digression-groups/{group_id}/toggle",
            json={"included": True},
        )
        assert toggle_resp.status_code == 200
        assert toggle_resp.json()["included"] is True

    async def test_delete_group(self, client):
        """DELETE removes group; subsequent GET excludes it."""
        data = await create_tree_with_messages(client, n_messages=4)
        tree_id = data["tree_id"]

        create_resp = await client.post(
            f"/api/trees/{tree_id}/digression-groups",
            json={"node_ids": data["node_ids"][:2], "label": "Temp"},
        )
        group_id = create_resp.json()["group_id"]

        del_resp = await client.delete(
            f"/api/trees/{tree_id}/digression-groups/{group_id}",
        )
        assert del_resp.status_code == 204

        groups = (await client.get(f"/api/trees/{tree_id}/digression-groups")).json()
        assert len(groups) == 0


# ---------------------------------------------------------------------------
# ContextBuilder integration: exclusions filter messages
# ---------------------------------------------------------------------------


class TestContextBuilderExclusion:
    """ContextBuilder.build() respects excluded_ids and digression groups."""

    @pytest.fixture
    def builder(self) -> ContextBuilder:
        return ContextBuilder()

    def _make_chain(self) -> list[dict]:
        """user -> assistant -> user -> assistant -> user."""
        return [
            {"node_id": "u1", "parent_id": None, "role": "user", "content": "Hello"},
            {"node_id": "a1", "parent_id": "u1", "role": "assistant", "content": "Hi there"},
            {"node_id": "u2", "parent_id": "a1", "role": "user", "content": "Tell me about X"},
            {"node_id": "a2", "parent_id": "u2", "role": "assistant", "content": "X is interesting"},
            {"node_id": "u3", "parent_id": "a2", "role": "user", "content": "Thanks"},
        ]

    def test_excluded_node_omitted_from_messages(self, builder):
        """Excluding a node removes it from the built messages list."""
        nodes = self._make_chain()
        messages, usage, report = builder.build(
            nodes=nodes,
            target_node_id="u3",
            system_prompt=None,
            model_context_limit=200_000,
            excluded_ids={"a1"},
        )
        contents = [m["content"] for m in messages]
        assert "Hi there" not in contents
        assert "Hello" in contents
        assert "Thanks" in contents

    def test_excluded_tokens_counted_in_usage(self, builder):
        """Excluded nodes appear in excluded_tokens and excluded_count."""
        nodes = self._make_chain()
        messages, usage, report = builder.build(
            nodes=nodes,
            target_node_id="u3",
            system_prompt=None,
            model_context_limit=200_000,
            excluded_ids={"a1"},
        )
        assert usage.excluded_count == 1
        assert usage.excluded_tokens > 0

    def test_digression_group_excluded_nodes_omitted(self, builder):
        """Toggled-off group with all nodes on path excludes those nodes."""
        nodes = self._make_chain()
        messages, usage, report = builder.build(
            nodes=nodes,
            target_node_id="u3",
            system_prompt=None,
            model_context_limit=200_000,
            digression_groups={"g1": ["u2", "a2"]},
            excluded_group_ids={"g1"},
        )
        contents = [m["content"] for m in messages]
        assert "Tell me about X" not in contents
        assert "X is interesting" not in contents
        assert "Hello" in contents
        assert "Thanks" in contents

    def test_node_exclusion_overrides_group_inclusion(self, builder):
        """Node-level exclusion wins even if node is in an included group."""
        nodes = self._make_chain()
        # Group is included (not in excluded_group_ids), but node is individually excluded
        messages, usage, report = builder.build(
            nodes=nodes,
            target_node_id="u3",
            system_prompt=None,
            model_context_limit=200_000,
            excluded_ids={"a1"},
            digression_groups={"g1": ["a1", "u2"]},
            excluded_group_ids=set(),  # group is included
        )
        contents = [m["content"] for m in messages]
        assert "Hi there" not in contents  # individually excluded
        assert "Tell me about X" in contents  # group is included, not individually excluded


# ---------------------------------------------------------------------------
# is_excluded on NodeResponse
# ---------------------------------------------------------------------------


class TestIsExcluded:
    """is_excluded flag on NodeResponse."""

    async def test_is_excluded_true_when_excluded(self, client):
        """After excluding, node has is_excluded=True in tree response."""
        data = await create_tree_with_messages(client, n_messages=4)
        tree_id = data["tree_id"]
        node_id = data["node_ids"][1]
        scope = data["node_ids"][-1]

        await client.post(
            f"/api/trees/{tree_id}/nodes/{node_id}/exclude",
            json={"scope_node_id": scope},
        )

        resp = await client.get(f"/api/trees/{tree_id}")
        tree = resp.json()
        node = next(n for n in tree["nodes"] if n["node_id"] == node_id)
        assert node["is_excluded"] is True

    async def test_is_excluded_false_by_default(self, client):
        """Nodes without exclusions have is_excluded=False."""
        data = await create_tree_with_messages(client, n_messages=2)
        tree_id = data["tree_id"]

        resp = await client.get(f"/api/trees/{tree_id}")
        tree = resp.json()
        for node in tree["nodes"]:
            assert node["is_excluded"] is False


# ---------------------------------------------------------------------------
# Event sourcing integrity
# ---------------------------------------------------------------------------


class TestExclusionEventReplay:
    """Exclusions + groups survive full event replay."""

    async def test_exclusions_and_groups_survive_replay(self, event_store, projector, db):
        """Rebuild all projections from scratch -- exclusions and groups are consistent."""
        tree_ev = make_tree_created_envelope()
        n1 = make_node_created_envelope(tree_id=tree_ev.tree_id, content="Hello")
        n2 = make_node_created_envelope(
            tree_id=tree_ev.tree_id, parent_id=n1.payload["node_id"],
            role="assistant", content="Hi",
        )
        n3 = make_node_created_envelope(
            tree_id=tree_ev.tree_id, parent_id=n2.payload["node_id"],
            content="Question",
        )

        base_events = [tree_ev, n1, n2, n3]
        for e in base_events:
            await event_store.append(e)
        await projector.project(base_events)

        # Exclude n1, then re-include it, then exclude n2
        excl1 = make_node_context_excluded_envelope(
            tree_id=tree_ev.tree_id,
            node_id=n1.payload["node_id"],
            scope_node_id=n3.payload["node_id"],
            reason="Test",
        )
        incl1 = make_node_context_included_envelope(
            tree_id=tree_ev.tree_id,
            node_id=n1.payload["node_id"],
            scope_node_id=n3.payload["node_id"],
        )
        excl2 = make_node_context_excluded_envelope(
            tree_id=tree_ev.tree_id,
            node_id=n2.payload["node_id"],
            scope_node_id=n3.payload["node_id"],
        )

        # Create a group and toggle it off
        group_ev = make_digression_group_created_envelope(
            tree_id=tree_ev.tree_id,
            node_ids=[n1.payload["node_id"], n2.payload["node_id"]],
            label="Intro",
        )
        toggle_ev = make_digression_group_toggled_envelope(
            tree_id=tree_ev.tree_id,
            group_id=group_ev.payload["group_id"],
            included=False,
        )

        mutation_events = [excl1, incl1, excl2, group_ev, toggle_ev]
        for e in mutation_events:
            await event_store.append(e)
        await projector.project(mutation_events)

        # Wipe materialized tables and replay
        await db.execute("DELETE FROM node_exclusions")
        await db.execute("DELETE FROM digression_groups")
        await db.execute("DELETE FROM digression_group_nodes")
        await db.execute("DELETE FROM bookmarks")
        await db.execute("DELETE FROM annotations")
        await db.execute("DELETE FROM nodes")
        await db.execute("DELETE FROM trees")

        all_events = await event_store.get_events(tree_ev.tree_id)
        fresh_projector = StateProjector(db)
        await fresh_projector.project(all_events)

        # n1 was excluded then included -- should have no exclusion
        n1_excl = await db.fetchone(
            "SELECT * FROM node_exclusions WHERE node_id = ?",
            (n1.payload["node_id"],),
        )
        assert n1_excl is None

        # n2 should still be excluded
        n2_excl = await db.fetchone(
            "SELECT * FROM node_exclusions WHERE node_id = ?",
            (n2.payload["node_id"],),
        )
        assert n2_excl is not None

        # Group should exist and be toggled off
        group_row = await db.fetchone(
            "SELECT * FROM digression_groups WHERE group_id = ?",
            (group_ev.payload["group_id"],),
        )
        assert group_row is not None
        assert group_row["included"] == 0
        assert group_row["label"] == "Intro"

        # Group membership should be intact
        members = await db.fetchall(
            "SELECT * FROM digression_group_nodes WHERE group_id = ?",
            (group_ev.payload["group_id"],),
        )
        assert len(members) == 2
