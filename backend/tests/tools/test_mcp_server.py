"""Qivis MCP server: other models talk to local ones; everything is recorded."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.service import GenerationService
from qivis.main import app
from qivis.mcp_server import QivisBridge, build_server
from qivis.model_catalog import ModelCatalog, get_catalog, set_catalog
from qivis.providers.base import GenerationRequest, GenerationResult, LLMProvider, StreamChunk
from qivis.providers.registry import clear_providers, register_provider
from qivis.rhizomes.router import get_generation_service, get_rhizome_service
from qivis.rhizomes.service import RhizomeService


class FakeSun(LLMProvider):
    supported_modes = ["completion"]
    suggested_models = ["sun.gguf", "other.gguf"]

    def __init__(self):
        self.n = 0
        self.fail = False

    @property
    def name(self) -> str:
        return "fakesun"

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        if self.fail:
            raise RuntimeError("model server unavailable")
        self.n += 1
        return GenerationResult(content=f"reply {self.n}", model="sun.gguf", finish_reason="stop")

    async def generate_stream(self, request) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(type="message_stop", is_final=True, result=await self.generate(request))


@pytest.fixture
async def env(db: Database):
    store, projector, service = EventStore(db), StateProjector(db), RhizomeService(db)
    gen = GenerationService(service, store, projector)
    provider = FakeSun()
    clear_providers()
    register_provider(provider)
    previous = get_catalog()
    set_catalog(ModelCatalog({"sun.gguf": {"label": "Sun 1.0.1", "provider": "fakesun",
                                           "generation_mode": "completion", "prompt_template": "llama3"}}))
    app.dependency_overrides[get_rhizome_service] = lambda: service
    app.dependency_overrides[get_generation_service] = lambda: gen
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://qivis") as client:
        yield {"client": client, "provider": provider,
               "fable": QivisBridge(client, "Fable"), "other": QivisBridge(client, "Echo")}
    app.dependency_overrides.clear()
    clear_providers()
    set_catalog(previous)


async def test_lists_profiled_models_only(env):
    models = await env["fable"].models()
    assert [m["label"] for m in models] == ["Sun 1.0.1"]


async def test_conversation_is_recorded_and_continues(env):
    fable, c = env["fable"], env["client"]
    first = await fable.send("Sun 1.0.1", "hello Sun")
    assert first["reply"] == "reply 1"
    second = await fable.send("sun 1.0.1", "how are you?")   # names are case-insensitive
    assert second["conversation_id"] == first["conversation_id"]

    rh = (await c.get(f"/api/rhizomes/{first['conversation_id']}")).json()
    meta = rh["metadata"]
    assert meta["folders"] == ["Connectome"] and "caller:fable" in meta["tags"]
    assert meta["prompt_template"] == "auto" and meta["generation_mode"] == "completion"
    users = [n for n in rh["nodes"] if n["role"] == "user"]
    assert {n["participant_name"] for n in users} == {"Fable"}
    assert await fable.read("Sun 1.0.1") == (
        "You: hello Sun\n\nSun 1.0.1: reply 1\n\nYou: how are you?\n\nSun 1.0.1: reply 2")
    assert await fable.read("Sun 1.0.1", last=1) == "Sun 1.0.1: reply 2"


async def test_new_conversation_and_resuming_by_id(env):
    fable = env["fable"]
    old = await fable.send("Sun 1.0.1", "first thread")
    await fable.new_conversation("Sun 1.0.1")
    new = await fable.send("Sun 1.0.1", "second thread")
    assert new["conversation_id"] != old["conversation_id"]
    back = await fable.send("Sun 1.0.1", "back to the first", conversation_id=old["conversation_id"])
    assert back["conversation_id"] == old["conversation_id"]
    listed = await fable.conversations("Sun 1.0.1")
    assert {c["conversation_id"] for c in listed} == {old["conversation_id"], new["conversation_id"]}


async def test_unknown_model_names_the_available_ones(env):
    with pytest.raises(ValueError, match="Available: Sun 1.0.1"):
        await env["fable"].send("Claude", "hi")


async def test_failed_reply_is_not_left_in_the_thread(env):
    fable, provider = env["fable"], env["provider"]
    await fable.send("Sun 1.0.1", "one")
    provider.fail = True
    with pytest.raises(RuntimeError, match="you can send it again"):
        await fable.send("Sun 1.0.1", "two (lost)")
    provider.fail = False
    await fable.send("Sun 1.0.1", "two")
    assert await fable.read("Sun 1.0.1") == (
        "You: one\n\nSun 1.0.1: reply 1\n\nYou: two\n\nSun 1.0.1: reply 2")


async def test_callers_are_isolated(env):
    mine = await env["fable"].send("Sun 1.0.1", "private-ish")
    other = env["other"]
    assert await other.conversations() == []
    assert await other.read("Sun 1.0.1") == "No conversation with Sun 1.0.1 yet."
    with pytest.raises(ValueError, match="No conversation"):
        await other.send("Sun 1.0.1", "hi", conversation_id=mine["conversation_id"])


async def test_empty_and_oversized_messages(env):
    with pytest.raises(ValueError, match="empty"):
        await env["fable"].send("Sun 1.0.1", "   ")
    with pytest.raises(ValueError, match="limit"):
        await env["fable"].send("Sun 1.0.1", "x" * 12_001)


async def test_tools_are_registered_like_the_computer_connector(env):
    server = build_server(env["fable"])
    names = {t.name for t in await server.list_tools()}
    assert names == {"models_list", "model_send", "model_read", "model_new_conversation", "model_conversations"}
