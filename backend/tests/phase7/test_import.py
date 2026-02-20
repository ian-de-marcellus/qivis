"""Tests for Phase 7.2: Conversation import (ChatGPT, Claude.ai, ShareGPT, generic linear)."""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.main import app
from qivis.trees.router import get_tree_service
from qivis.trees.service import TreeService


# ---------------------------------------------------------------------------
# ChatGPT fixture data
# ---------------------------------------------------------------------------

def _chatgpt_node(
    node_id: str,
    parent: str | None,
    children: list[str],
    role: str = "user",
    content: str = "Hello",
    model_slug: str | None = None,
    create_time: float | None = 1700000000.0,
) -> dict:
    """Build a single ChatGPT mapping node."""
    msg = {
        "id": f"msg-{node_id}",
        "author": {"role": role},
        "create_time": create_time,
        "content": {"content_type": "text", "parts": [content]},
        "metadata": {},
    }
    if model_slug:
        msg["metadata"]["model_slug"] = model_slug
    return {
        "id": node_id,
        "message": msg,
        "parent": parent,
        "children": children,
    }


def _chatgpt_structural_node(node_id: str, parent: str | None, children: list[str]) -> dict:
    """Build a structural ChatGPT node (message=null)."""
    return {
        "id": node_id,
        "message": None,
        "parent": parent,
        "children": children,
    }


def make_chatgpt_conversation(
    *,
    conv_id: str = "conv-1",
    title: str = "Test Conversation",
    mapping: dict | None = None,
) -> dict:
    """Build a complete ChatGPT conversation object."""
    if mapping is None:
        mapping = {
            "root": _chatgpt_structural_node("root", None, ["sys"]),
            "sys": _chatgpt_node("sys", "root", ["u1"], role="system",
                                 content="You are a helpful assistant."),
            "u1": _chatgpt_node("u1", "sys", ["a1"], role="user",
                                content="What is Python?"),
            "a1": _chatgpt_node("a1", "u1", ["u2"], role="assistant",
                                content="Python is a programming language.",
                                model_slug="gpt-4-turbo"),
            "u2": _chatgpt_node("u2", "a1", ["a2"], role="user",
                                content="Tell me more."),
            "a2": _chatgpt_node("a2", "u2", [], role="assistant",
                                content="It was created by Guido van Rossum.",
                                model_slug="gpt-4-turbo"),
        }
    return {
        "id": conv_id,
        "title": title,
        "create_time": 1700000000.0,
        "update_time": 1700001000.0,
        "current_node": "a2",
        "mapping": mapping,
    }


def make_chatgpt_branching_conversation() -> dict:
    """ChatGPT conversation with a fork: u1 has two assistant children."""
    mapping = {
        "root": _chatgpt_structural_node("root", None, ["u1"]),
        "u1": _chatgpt_node("u1", "root", ["a1", "a2"], role="user",
                            content="What is 2+2?"),
        "a1": _chatgpt_node("a1", "u1", [], role="assistant",
                            content="The answer is 4.",
                            model_slug="gpt-4"),
        "a2": _chatgpt_node("a2", "u1", [], role="assistant",
                            content="2+2 equals 4, of course!",
                            model_slug="gpt-4-turbo"),
    }
    return make_chatgpt_conversation(title="Branching Test", mapping=mapping)


# ---------------------------------------------------------------------------
# Linear / ShareGPT fixture data
# ---------------------------------------------------------------------------

SHAREGPT_DATA = [
    {"from": "system", "value": "You are a helpful assistant."},
    {"from": "human", "value": "Hello!"},
    {"from": "gpt", "value": "Hi there! How can I help?"},
    {"from": "human", "value": "What time is it?"},
    {"from": "gpt", "value": "I don't have access to the current time."},
]

GENERIC_LINEAR_DATA = [
    {"role": "system", "content": "Be helpful."},
    {"role": "user", "content": "Hello!"},
    {"role": "assistant", "content": "Hi! How can I help?"},
]


# ---------------------------------------------------------------------------
# Claude.ai fixture data
# ---------------------------------------------------------------------------

_CLAUDE_ROOT_SENTINEL = "00000000-0000-4000-8000-000000000000"


def _claude_message(
    uuid: str,
    sender: str,
    text: str,
    parent_uuid: str = _CLAUDE_ROOT_SENTINEL,
    index: int = 0,
    created_at: str = "2026-02-18T03:23:11.721912Z",
    stop_reason: str | None = None,
    content_blocks: list[dict] | None = None,
) -> dict:
    """Build a single Claude.ai chat message."""
    if content_blocks is None:
        content_blocks = [{
            "start_timestamp": created_at,
            "stop_timestamp": created_at,
            "type": "text",
            "text": text,
            "citations": [],
        }]
    msg = {
        "uuid": uuid,
        "text": "",
        "content": content_blocks,
        "sender": sender,
        "index": index,
        "created_at": created_at,
        "updated_at": created_at,
        "truncated": False,
        "attachments": [],
        "files": [],
        "files_v2": [],
        "sync_sources": [],
        "parent_message_uuid": parent_uuid,
    }
    if stop_reason:
        msg["stop_reason"] = stop_reason
    return msg


def make_claude_conversation(
    *,
    uuid: str = "conv-claude-1",
    name: str = "Test Claude Conversation",
    model: str = "claude-sonnet-4-6",
    messages: list[dict] | None = None,
) -> dict:
    """Build a complete Claude.ai conversation export."""
    if messages is None:
        messages = [
            _claude_message("m1", "human", "Hello!", index=0),
            _claude_message("m2", "assistant", "Hi there!", parent_uuid="m1",
                           index=1, stop_reason="stop_sequence"),
            _claude_message("m3", "human", "How are you?", parent_uuid="m2", index=2),
            _claude_message("m4", "assistant", "I'm doing well!", parent_uuid="m3",
                           index=3, stop_reason="stop_sequence"),
        ]
    return {
        "uuid": uuid,
        "name": name,
        "model": model,
        "created_at": "2026-02-18T03:23:09.848343Z",
        "updated_at": "2026-02-18T05:39:56.754588Z",
        "settings": {},
        "is_starred": False,
        "platform": "CLAUDE_AI",
        "current_leaf_message_uuid": messages[-1]["uuid"] if messages else "",
        "chat_messages": messages,
    }


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
async def import_service(db, event_store, projector):
    from qivis.importer.service import ImportService
    return ImportService(db, event_store, projector)


@pytest.fixture
async def client(db, event_store, projector):
    from qivis.importer.router import get_import_service
    from qivis.importer.service import ImportService

    tree_service = TreeService(db)
    import_svc = ImportService(db, event_store, projector)
    app.dependency_overrides[get_tree_service] = lambda: tree_service
    app.dependency_overrides[get_import_service] = lambda: import_svc
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Contract tests — Parsers
# ---------------------------------------------------------------------------

class TestChatGPTParser:
    """ChatGPT conversations.json parser."""

    def test_chatgpt_linear_conversation(self):
        """Basic linear conversation produces correct chain."""
        from qivis.importer.parsers.chatgpt import parse_chatgpt

        conv = make_chatgpt_conversation()
        trees = parse_chatgpt(conv)
        assert len(trees) == 1
        tree = trees[0]
        assert tree.title == "Test Conversation"
        assert tree.source_format == "chatgpt"
        assert tree.source_id == "conv-1"
        # 4 real messages (u1, a1, u2, a2 — system and structural skipped)
        assert len(tree.nodes) == 4
        roles = [n.role for n in tree.nodes]
        assert roles == ["user", "assistant", "user", "assistant"]

    def test_chatgpt_branching_preserved(self):
        """Fork with 2 children produces correct tree structure."""
        from qivis.importer.parsers.chatgpt import parse_chatgpt

        conv = make_chatgpt_branching_conversation()
        trees = parse_chatgpt(conv)
        tree = trees[0]
        # 3 nodes: u1, a1, a2
        assert len(tree.nodes) == 3
        # Both assistant nodes should have u1 as parent
        user_node = tree.nodes[0]
        assert user_node.role == "user"
        assistant_parents = [n.parent_temp_id for n in tree.nodes if n.role == "assistant"]
        assert all(p == user_node.temp_id for p in assistant_parents)

    def test_chatgpt_null_message_nodes_skipped(self):
        """Structural nodes (message=null) are skipped, children reparented."""
        from qivis.importer.parsers.chatgpt import parse_chatgpt

        conv = make_chatgpt_conversation()
        trees = parse_chatgpt(conv)
        tree = trees[0]
        # The structural "root" node should not appear
        temp_ids = {n.temp_id for n in tree.nodes}
        assert "root" not in temp_ids
        # First real node should have no parent (it's the new root)
        assert tree.nodes[0].parent_temp_id is None

    def test_chatgpt_system_message_extracted(self):
        """System message becomes default_system_prompt, not a node."""
        from qivis.importer.parsers.chatgpt import parse_chatgpt

        conv = make_chatgpt_conversation()
        trees = parse_chatgpt(conv)
        tree = trees[0]
        assert tree.default_system_prompt == "You are a helpful assistant."
        # No node with role "system"
        assert not any(n.role == "system" for n in tree.nodes)

    def test_chatgpt_model_provider_inference(self):
        """model_slug maps to correct provider."""
        from qivis.importer.parsers.chatgpt import parse_chatgpt

        conv = make_chatgpt_conversation()
        trees = parse_chatgpt(conv)
        tree = trees[0]
        assistant_nodes = [n for n in tree.nodes if n.role == "assistant"]
        for node in assistant_nodes:
            assert node.model == "gpt-4-turbo"
            assert node.provider == "openai"

    def test_chatgpt_multi_conversation_file(self):
        """Array of conversations produces multiple ImportedTrees."""
        from qivis.importer.parsers.chatgpt import parse_chatgpt

        data = [
            make_chatgpt_conversation(conv_id="c1", title="First"),
            make_chatgpt_conversation(conv_id="c2", title="Second"),
        ]
        trees = parse_chatgpt(data)
        assert len(trees) == 2
        assert trees[0].title == "First"
        assert trees[1].title == "Second"

    def test_chatgpt_timestamps_preserved(self):
        """Unix epoch values preserved on imported nodes."""
        from qivis.importer.parsers.chatgpt import parse_chatgpt

        conv = make_chatgpt_conversation()
        trees = parse_chatgpt(conv)
        tree = trees[0]
        for node in tree.nodes:
            assert node.timestamp == 1700000000.0

    def test_chatgpt_content_parts_joined(self):
        """content.parts array with multiple elements joined with newline."""
        from qivis.importer.parsers.chatgpt import parse_chatgpt

        mapping = {
            "root": _chatgpt_structural_node("root", None, ["u1"]),
            "u1": {
                "id": "u1",
                "message": {
                    "id": "msg-u1",
                    "author": {"role": "user"},
                    "create_time": 1700000000.0,
                    "content": {
                        "content_type": "text",
                        "parts": ["Part one.", "Part two.", "Part three."],
                    },
                    "metadata": {},
                },
                "parent": "root",
                "children": [],
            },
        }
        conv = make_chatgpt_conversation(mapping=mapping)
        trees = parse_chatgpt(conv)
        assert trees[0].nodes[0].content == "Part one.\nPart two.\nPart three."


class TestLinearParser:
    """ShareGPT and generic linear format parser."""

    def test_linear_sharegpt_format(self):
        """ShareGPT {from, value} role mapping works."""
        from qivis.importer.parsers.linear import parse_linear

        tree = parse_linear(SHAREGPT_DATA)
        assert tree.source_format == "linear"
        # System message extracted, 4 remaining nodes
        assert len(tree.nodes) == 4
        assert tree.default_system_prompt == "You are a helpful assistant."
        roles = [n.role for n in tree.nodes]
        assert roles == ["user", "assistant", "user", "assistant"]

    def test_linear_generic_format(self):
        """Generic {role, content} parsed correctly."""
        from qivis.importer.parsers.linear import parse_linear

        tree = parse_linear(GENERIC_LINEAR_DATA)
        assert len(tree.nodes) == 2  # system extracted
        assert tree.default_system_prompt == "Be helpful."
        assert tree.nodes[0].role == "user"
        assert tree.nodes[1].role == "assistant"


class TestClaudeParser:
    """Claude.ai conversation export parser."""

    def test_claude_linear_conversation(self):
        """Basic linear conversation produces correct chain."""
        from qivis.importer.parsers.claude import parse_claude

        conv = make_claude_conversation()
        trees = parse_claude(conv)
        assert len(trees) == 1
        tree = trees[0]
        assert tree.title == "Test Claude Conversation"
        assert tree.source_format == "claude"
        assert tree.source_id == "conv-claude-1"
        assert len(tree.nodes) == 4
        roles = [n.role for n in tree.nodes]
        assert roles == ["user", "assistant", "user", "assistant"]
        # First message is a root
        assert tree.nodes[0].parent_temp_id is None
        # Second message chains to first
        assert tree.nodes[1].parent_temp_id == "m1"

    def test_claude_branching_preserved(self):
        """Multiple root messages create branches."""
        from qivis.importer.parsers.claude import parse_claude

        messages = [
            _claude_message("m1", "human", "First attempt", index=0),
            _claude_message("m2", "assistant", "Response to first", parent_uuid="m1", index=1),
            _claude_message("m3", "human", "Second attempt", index=2),  # root sentinel = branch
            _claude_message("m4", "assistant", "Response to second", parent_uuid="m3", index=3),
        ]
        conv = make_claude_conversation(messages=messages)
        trees = parse_claude(conv)
        tree = trees[0]
        # Two root messages
        assert len(tree.root_temp_ids) == 2
        assert "m1" in tree.root_temp_ids
        assert "m3" in tree.root_temp_ids
        # m2 parents to m1, m4 parents to m3
        by_id = {n.temp_id: n for n in tree.nodes}
        assert by_id["m2"].parent_temp_id == "m1"
        assert by_id["m4"].parent_temp_id == "m3"

    def test_claude_sender_role_mapping(self):
        """Sender 'human' maps to 'user', 'assistant' stays 'assistant'."""
        from qivis.importer.parsers.claude import parse_claude

        conv = make_claude_conversation()
        tree = parse_claude(conv)[0]
        assert tree.nodes[0].role == "user"
        assert tree.nodes[1].role == "assistant"

    def test_claude_model_and_provider(self):
        """Model from conversation-level, provider always 'anthropic'."""
        from qivis.importer.parsers.claude import parse_claude

        conv = make_claude_conversation(model="claude-sonnet-4-6")
        tree = parse_claude(conv)[0]
        assert tree.default_model == "claude-sonnet-4-6"
        assert tree.default_provider == "anthropic"
        # Assistant messages get the model, user messages don't
        assert tree.nodes[0].model is None  # user
        assert tree.nodes[1].model == "claude-sonnet-4-6"  # assistant

    def test_claude_system_prompt_placeholder_on_nodes(self):
        """Claude.ai platform gets placeholder on nodes, not tree default."""
        from qivis.importer.parsers.claude import parse_claude

        conv = make_claude_conversation()
        tree = parse_claude(conv)[0]
        # Tree default is empty — don't send placeholder with future generations
        assert tree.default_system_prompt is None
        # But each node records what was in effect
        for node in tree.nodes:
            assert "not included in export" in node.metadata["system_prompt"]

    def test_claude_timestamps_parsed(self):
        """ISO timestamps converted to Unix epoch."""
        from qivis.importer.parsers.claude import parse_claude

        conv = make_claude_conversation()
        tree = parse_claude(conv)[0]
        assert tree.created_at is not None
        assert isinstance(tree.created_at, float)
        # Node timestamps
        for node in tree.nodes:
            assert node.timestamp is not None
            assert isinstance(node.timestamp, float)

    def test_claude_multi_block_content(self):
        """Multi-block content joins text blocks, skips non-text."""
        from qivis.importer.parsers.claude import parse_claude

        blocks = [
            {"type": "text", "text": "Let me search for that.", "start_timestamp": "t", "stop_timestamp": "t"},
            {"type": "web_search", "search_results": [], "is_error": False},
            {"type": "text", "text": "Here's what I found.", "start_timestamp": "t", "stop_timestamp": "t"},
        ]
        messages = [
            _claude_message("m1", "human", "Search for X", index=0),
            _claude_message("m2", "assistant", "", parent_uuid="m1", index=1,
                           content_blocks=blocks),
        ]
        conv = make_claude_conversation(messages=messages)
        tree = parse_claude(conv)[0]
        assistant_node = tree.nodes[1]
        assert assistant_node.content == "Let me search for that.\nHere's what I found."

    def test_claude_empty_assistant_skipped(self):
        """Assistant messages with no text content are skipped with warning."""
        from qivis.importer.parsers.claude import parse_claude

        # Assistant message with only tool_use, no text
        blocks = [{"type": "tool_use", "id": "t1", "name": "web_search", "input": {}}]
        messages = [
            _claude_message("m1", "human", "Search", index=0),
            _claude_message("m2", "assistant", "", parent_uuid="m1", index=1,
                           content_blocks=blocks),
            _claude_message("m3", "assistant", "Found it!", parent_uuid="m1", index=2),
        ]
        conv = make_claude_conversation(messages=messages)
        tree = parse_claude(conv)[0]
        # m2 skipped, m1 and m3 remain
        assert len(tree.nodes) == 2
        assert any("Skipped empty" in w for w in tree.warnings)


class TestFormatDetection:
    """Auto-detection of import format from data shape."""

    def test_format_detection(self):
        from qivis.importer.parsers.detection import detect_format

        # Single ChatGPT conversation
        assert detect_format(make_chatgpt_conversation()) == "chatgpt"

        # Array of ChatGPT conversations
        assert detect_format([make_chatgpt_conversation()]) == "chatgpt"

        # Single Claude.ai conversation
        assert detect_format(make_claude_conversation()) == "claude"

        # Array of Claude.ai conversations
        assert detect_format([make_claude_conversation()]) == "claude"

        # ShareGPT format
        assert detect_format(SHAREGPT_DATA) == "linear"

        # Generic linear
        assert detect_format(GENERIC_LINEAR_DATA) == "linear"


class TestTopologicalSort:
    """Nodes emitted parent-before-child even if input unordered."""

    def test_topological_sort(self):
        from qivis.importer.models import ImportedNode, ImportedTree
        from qivis.importer.service import ImportService

        # Nodes listed child-first (wrong order)
        nodes = [
            ImportedNode(temp_id="c", parent_temp_id="b", role="user", content="C"),
            ImportedNode(temp_id="a", parent_temp_id=None, role="user", content="A"),
            ImportedNode(temp_id="b", parent_temp_id="a", role="assistant", content="B"),
        ]
        tree = ImportedTree(
            title="Test",
            source_format="test",
            nodes=nodes,
            root_temp_ids=["a"],
        )
        sorted_nodes = ImportService._topological_sort(tree)
        sorted_ids = [n.temp_id for n in sorted_nodes]
        # a must come before b, b must come before c
        assert sorted_ids.index("a") < sorted_ids.index("b")
        assert sorted_ids.index("b") < sorted_ids.index("c")


# ---------------------------------------------------------------------------
# Integration tests — ImportService
# ---------------------------------------------------------------------------

class TestImportService:
    """ImportService creates proper events and trees."""

    async def test_import_creates_tree_with_events(self, import_service, event_store):
        """Import emits TreeCreated + NodeCreated events."""
        data = json.dumps(make_chatgpt_conversation()).encode()
        results = await import_service.import_trees(data, "test.json")
        assert len(results) == 1
        result = results[0]
        assert result.node_count == 4

        events = await event_store.get_events(result.tree_id)
        event_types = [e.event_type for e in events]
        assert event_types[0] == "TreeCreated"
        assert event_types.count("NodeCreated") == 4

    async def test_imported_tree_fully_functional(self, import_service, projector):
        """Imported tree has correct parent-child relationships."""
        data = json.dumps(make_chatgpt_conversation()).encode()
        results = await import_service.import_trees(data, "test.json")
        tree_id = results[0].tree_id

        tree = await projector.get_tree(tree_id)
        assert tree is not None
        assert tree["title"] == "Test Conversation"

        nodes = await projector.get_nodes(tree_id)
        assert len(nodes) == 4

        # Verify chain: each node's parent is the previous node
        for i in range(1, len(nodes)):
            assert nodes[i]["parent_id"] == nodes[i - 1]["node_id"]
        # First node has no parent
        assert nodes[0]["parent_id"] is None

    async def test_imported_timestamps_preserved(self, import_service, event_store):
        """Event timestamps match source conversation timestamps."""
        data = json.dumps(make_chatgpt_conversation()).encode()
        results = await import_service.import_trees(data, "test.json")

        events = await event_store.get_events(results[0].tree_id)
        node_events = [e for e in events if e.event_type == "NodeCreated"]
        for event in node_events:
            # Timestamp should be from the source (1700000000.0 epoch)
            assert "2023-11-14" in event.timestamp.isoformat()

    async def test_imported_nodes_mode_is_chat(self, import_service, projector):
        """Imported nodes use mode='chat', NOT 'manual'."""
        data = json.dumps(make_chatgpt_conversation()).encode()
        results = await import_service.import_trees(data, "test.json")

        nodes = await projector.get_nodes(results[0].tree_id)
        for node in nodes:
            assert node["mode"] == "chat"

    async def test_import_metadata_on_tree(self, import_service, projector):
        """Tree metadata includes import provenance."""
        data = json.dumps(make_chatgpt_conversation()).encode()
        results = await import_service.import_trees(data, "test.json")

        tree = await projector.get_tree(results[0].tree_id)
        metadata = json.loads(tree["metadata"]) if isinstance(tree["metadata"], str) else tree["metadata"]
        assert metadata["imported"] is True
        assert metadata["import_source"] == "chatgpt"
        assert metadata["original_id"] == "conv-1"

    async def test_import_device_id(self, import_service, event_store):
        """All import events have device_id='import'."""
        data = json.dumps(make_chatgpt_conversation()).encode()
        results = await import_service.import_trees(data, "test.json")

        events = await event_store.get_events(results[0].tree_id)
        for event in events:
            assert event.device_id == "import"

    async def test_multi_conversation_selective_import(self, import_service):
        """Selecting specific indices imports only those conversations."""
        multi = [
            make_chatgpt_conversation(conv_id="c1", title="First"),
            make_chatgpt_conversation(conv_id="c2", title="Second"),
            make_chatgpt_conversation(conv_id="c3", title="Third"),
        ]
        data = json.dumps(multi).encode()
        results = await import_service.import_trees(
            data, "test.json", selected_indices=[1],
        )
        assert len(results) == 1
        assert results[0].title == "Second"

    async def test_import_with_branches(self, import_service, projector):
        """ChatGPT branching creates correct sibling structure."""
        data = json.dumps(make_chatgpt_branching_conversation()).encode()
        results = await import_service.import_trees(data, "test.json")
        tree_id = results[0].tree_id

        nodes = await projector.get_nodes(tree_id)
        assert len(nodes) == 3  # u1, a1, a2

        # Find the user node (root)
        user_nodes = [n for n in nodes if n["role"] == "user"]
        assert len(user_nodes) == 1
        user_id = user_nodes[0]["node_id"]

        # Both assistant nodes should be children of the user node
        assistant_nodes = [n for n in nodes if n["role"] == "assistant"]
        assert len(assistant_nodes) == 2
        for an in assistant_nodes:
            assert an["parent_id"] == user_id


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

class TestImportAPI:
    """Import API endpoints."""

    async def test_preview_endpoint_returns_summary(self, client):
        """Upload file, get preview with correct counts."""
        data = json.dumps(make_chatgpt_conversation())
        resp = await client.post(
            "/api/import/preview",
            files={"file": ("test.json", data.encode(), "application/json")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["format_detected"] == "chatgpt"
        assert body["total_conversations"] == 1
        assert body["conversations"][0]["message_count"] == 4
        assert body["conversations"][0]["title"] == "Test Conversation"

    async def test_import_endpoint_returns_results(self, client):
        """Upload file, get tree IDs back."""
        data = json.dumps(make_chatgpt_conversation())
        resp = await client.post(
            "/api/import",
            files={"file": ("test.json", data.encode(), "application/json")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["results"]) == 1
        assert "tree_id" in body["results"][0]
        assert body["results"][0]["node_count"] == 4

    async def test_invalid_json_returns_422(self, client):
        """Non-JSON content returns clear error."""
        resp = await client.post(
            "/api/import/preview",
            files={"file": ("test.json", b"not json at all", "application/json")},
        )
        assert resp.status_code == 422

    async def test_unrecognized_format_returns_422(self, client):
        """Valid JSON but unrecognized structure returns error."""
        data = json.dumps({"random": "data"})
        resp = await client.post(
            "/api/import/preview",
            files={"file": ("test.json", data.encode(), "application/json")},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestImportEdgeCases:
    """Edge cases and graceful degradation."""

    async def test_empty_conversation_handled(self, import_service):
        """Conversation with only structural nodes produces a tree with no nodes."""
        mapping = {
            "root": _chatgpt_structural_node("root", None, []),
        }
        conv = make_chatgpt_conversation(mapping=mapping)
        data = json.dumps(conv).encode()
        results = await import_service.import_trees(data, "test.json")
        assert len(results) == 1
        assert results[0].node_count == 0
