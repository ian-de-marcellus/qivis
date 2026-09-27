"""Per-target generation mode in cross-model forks.

A Sun rhizome runs in completion mode (llama3 template). Forking it to a
chat model like GPT or Llama-Instruct must send chat messages, not the
rendered Llama 3 transcript -- while a base model on the same dual-mode
provider may want completion. So each target can set its own mode;
leaving it unset keeps the rhizome's behavior.
"""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.replay import ReplayService
from qivis.generation.service import GenerationService
from qivis.main import app
from qivis.providers.base import (
    GenerationRequest,
    GenerationResult,
    LLMProvider,
    StreamChunk,
)
from qivis.providers.registry import clear_providers, register_provider
from qivis.rhizomes.router import (
    get_generation_service,
    get_replay_service,
    get_rhizome_service,
)
from qivis.rhizomes.service import RhizomeService


class ModeRecordingProvider(LLMProvider):
    def __init__(self, name: str, modes: list[str]):
        self._name = name
        self.supported_modes = modes
        self.calls: list[GenerationRequest] = []

    @property
    def name(self) -> str:
        return self._name

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.calls.append(request)
        return GenerationResult(
            content=f"{self._name} says hi", model=request.model,
            finish_reason="stop", usage={}, latency_ms=1,
        )

    async def generate_stream(
        self, request: GenerationRequest,
    ) -> AsyncIterator[StreamChunk]:
        result = await self.generate(request)
        yield StreamChunk(type="text_delta", text=result.content)
        yield StreamChunk(type="message_stop", is_final=True, result=result)


@pytest.fixture
async def setup(db: Database):
    store = EventStore(db)
    projector = StateProjector(db)
    rhizome_svc = RhizomeService(db)
    gen_svc = GenerationService(rhizome_svc, store, projector)

    providers = {
        "dual": ModeRecordingProvider("dual", ["chat", "completion"]),
        "local": ModeRecordingProvider("local", ["completion"]),
        "chatonly": ModeRecordingProvider("chatonly", ["chat"]),
    }
    clear_providers()
    for p in providers.values():
        register_provider(p)

    app.dependency_overrides[get_rhizome_service] = lambda: rhizome_svc
    app.dependency_overrides[get_generation_service] = lambda: gen_svc
    replay_svc = ReplayService(rhizome_svc, gen_svc, store, projector)
    app.dependency_overrides[get_replay_service] = lambda: replay_svc

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        yield client, providers

    app.dependency_overrides.clear()
    clear_providers()


async def _rhizome_with_user_turn(client: AsyncClient, *, completion: bool) -> tuple[str, str]:
    # The rhizome's own model is "base": a completion rhizome's mode applies to it
    rid = (await client.post(
        "/api/rhizomes", json={"title": "t", "default_model": "base"},
    )).json()["rhizome_id"]
    if completion:
        await client.patch(f"/api/rhizomes/{rid}", json={"metadata": {
            "generation_mode": "completion", "prompt_template": "llama3",
        }})
    nid = (await client.post(
        f"/api/rhizomes/{rid}/nodes", json={"content": "hey Sun", "role": "user"},
    )).json()["node_id"]
    return rid, nid


async def _cross(client, rid, nid, targets, stream=False):
    return await client.post(
        f"/api/rhizomes/{rid}/nodes/{nid}/generate-cross",
        json={"targets": targets, "stream": stream},
    )


class TestPerTargetMode:
    async def test_chat_override_in_completion_rhizome(self, setup):
        client, providers = setup
        rid, nid = await _rhizome_with_user_turn(client, completion=True)
        resp = await _cross(client, rid, nid, [
            {"provider": "local", "model": "sun"},
            {"provider": "dual", "model": "gpt", "mode": "chat"},
        ])
        assert resp.status_code == 200
        # The local model still gets the rendered llama3 prompt...
        assert providers["local"].calls[-1].prompt_text.startswith("<|begin_of_text|>")
        # ...but the chat target gets plain messages
        chat_req = providers["dual"].calls[-1]
        assert chat_req.prompt_text is None
        assert chat_req.messages == [{"role": "user", "content": "hey Sun"}]
        modes = {n["provider"]: n["mode"] for n in resp.json()}
        assert modes == {"local": "completion", "dual": "chat"}

    async def test_unset_mode_keeps_rhizome_behavior(self, setup):
        client, providers = setup
        rid, nid = await _rhizome_with_user_turn(client, completion=True)
        resp = await _cross(client, rid, nid, [{"provider": "dual", "model": "base"}])
        assert resp.status_code == 200
        assert providers["dual"].calls[-1].prompt_text.startswith("<|begin_of_text|>")

    async def test_completion_override_in_chat_rhizome(self, setup):
        client, providers = setup
        rid, nid = await _rhizome_with_user_turn(client, completion=False)
        resp = await _cross(client, rid, nid, [
            {"provider": "dual", "model": "base", "mode": "completion"},
        ])
        assert resp.status_code == 200
        assert providers["dual"].calls[-1].prompt_text is not None
        assert resp.json()[0]["mode"] == "completion"

    async def test_chat_override_streaming(self, setup):
        client, providers = setup
        rid, nid = await _rhizome_with_user_turn(client, completion=True)
        resp = await _cross(client, rid, nid, [
            {"provider": "dual", "model": "gpt", "mode": "chat"},
        ], stream=True)
        assert resp.status_code == 200
        assert "event: error" not in resp.text
        assert providers["dual"].calls[-1].prompt_text is None

    async def test_unsupported_mode_is_400(self, setup):
        client, _ = setup
        rid, nid = await _rhizome_with_user_turn(client, completion=True)
        resp = await _cross(client, rid, nid, [
            {"provider": "local", "model": "sun", "mode": "chat"},
        ])
        assert resp.status_code == 400
        resp = await _cross(client, rid, nid, [
            {"provider": "chatonly", "model": "claude", "mode": "completion"},
        ])
        assert resp.status_code == 400


class TestReplayGenerationMode:
    async def _path(self, client) -> tuple[str, list[str]]:
        rid, user = await _rhizome_with_user_turn(client, completion=True)
        asst = (await client.post(f"/api/rhizomes/{rid}/nodes", json={
            "content": "hi!", "role": "assistant", "parent_id": user, "mode": "manual",
        })).json()["node_id"]
        return rid, [user, asst]

    async def test_replay_chat_override_in_completion_rhizome(self, setup):
        client, providers = setup
        rid, path = await self._path(client)
        resp = await client.post(f"/api/rhizomes/{rid}/replay", json={
            "path_node_ids": path, "provider": "dual", "model": "gpt",
            "generation_mode": "chat",
        })
        assert resp.status_code == 200
        assert providers["dual"].calls[-1].prompt_text is None
        assert resp.json()[0]["mode"] == "chat"

    async def test_replay_unsupported_mode_is_400(self, setup):
        client, _ = setup
        rid, path = await self._path(client)
        resp = await client.post(f"/api/rhizomes/{rid}/replay", json={
            "path_node_ids": path, "provider": "local", "model": "sun",
            "generation_mode": "chat",
        })
        assert resp.status_code == 400


class TestGenerateMode:
    async def test_single_generate_chat_override(self, setup):
        """Regenerating with GPT inside a Sun rhizome: chat, not a llama3 transcript."""
        client, providers = setup
        rid, nid = await _rhizome_with_user_turn(client, completion=True)
        resp = await client.post(f"/api/rhizomes/{rid}/nodes/{nid}/generate", json={
            "provider": "dual", "model": "gpt", "mode": "chat",
        })
        assert resp.status_code == 201
        assert providers["dual"].calls[-1].prompt_text is None
        assert resp.json()["mode"] == "chat"

    async def test_single_generate_unsupported_mode_is_400(self, setup):
        client, _ = setup
        rid, nid = await _rhizome_with_user_turn(client, completion=True)
        resp = await client.post(f"/api/rhizomes/{rid}/nodes/{nid}/generate", json={
            "provider": "local", "model": "sun", "mode": "chat",
        })
        assert resp.status_code == 400
