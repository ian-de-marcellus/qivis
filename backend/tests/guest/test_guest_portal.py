"""Guest portal: auth, isolation, recording, chat flow, limits.

The real Qivis app runs in-process (ASGITransport) as the guest server's
backend, with a fake completion-mode provider standing in for llama.cpp.
"""

import json
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.service import GenerationService
from qivis.guest import auth
from qivis.guest.app import create_app
from qivis.guest.config import ConfigStore, Guest, GuestModel, Limits, new_config, save
from qivis.main import app as qivis_app
from qivis.models import LogprobData, TokenLogprob
from qivis.providers.base import GenerationRequest, GenerationResult, LLMProvider, StreamChunk
from qivis.providers.registry import clear_providers, register_provider
from qivis.rhizomes.router import get_generation_service, get_rhizome_service
from qivis.rhizomes.service import RhizomeService


class FakeSun(LLMProvider):
    supported_modes = ["completion"]

    def __init__(self):
        self.count = 0

    @property
    def name(self) -> str:
        return "fakesun"

    def _result(self) -> GenerationResult:
        self.count += 1
        text = f"Hello {self.count}."
        toks = [text[:5], text[5:]]
        return GenerationResult(
            content=text,
            model="sun.gguf",
            finish_reason="stop",
            logprobs=LogprobData(
                tokens=[
                    TokenLogprob(token=t, logprob=-0.1, linear_prob=0.9, top_alternatives=[])
                    for t in toks
                ],
                provider_format="llamacpp",
                top_k_available=5,
            ),
        )

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        return self._result()

    async def generate_stream(self, request: GenerationRequest) -> AsyncIterator[StreamChunk]:
        result = self._result()
        yield StreamChunk(type="text_delta", text=result.content)
        yield StreamChunk(type="message_stop", is_final=True, result=result)


TOKENS = {"alice": "alice-token-" + "a" * 30, "bob": "bob-token-" + "b" * 30}


@pytest.fixture
async def portal(db: Database, tmp_path):
    store, projector, service = EventStore(db), StateProjector(db), RhizomeService(db)
    gen = GenerationService(service, store, projector)
    clear_providers()
    register_provider(FakeSun())
    qivis_app.dependency_overrides[get_rhizome_service] = lambda: service
    qivis_app.dependency_overrides[get_generation_service] = lambda: gen

    cfg = new_config()
    cfg.qivis_url = "http://qivis.test"
    cfg.models = [
        GuestModel(
            id="sun",
            label="Sun",
            provider="fakesun",
            model="sun.gguf",
            generation_mode="completion",
            prompt_template="llama3",
        )
    ]
    cfg.guests = [
        Guest(id=gid, name=gid.title(), token_sha256=auth.hash_token(tok), created_at="2026-09-27")
        for gid, tok in TOKENS.items()
    ]
    cfg.limits = Limits(max_message_chars=200, messages_per_minute=5, max_conversations=3)
    path = tmp_path / "guest.json"
    save(cfg, path)

    guest_app = create_app(ConfigStore(path), qivis_transport=ASGITransport(app=qivis_app))
    clients = {}
    for gid in TOKENS:
        clients[gid] = AsyncClient(
            transport=ASGITransport(app=guest_app), base_url="https://guest.test"
        )
    raw_qivis = AsyncClient(transport=ASGITransport(app=qivis_app), base_url="http://qivis.test")
    yield {"clients": clients, "path": path, "cfg": cfg, "qivis": raw_qivis, "app": guest_app}
    for c in clients.values():
        await c.aclose()
    await raw_qivis.aclose()
    qivis_app.dependency_overrides.clear()
    clear_providers()


async def login(client: AsyncClient, gid: str) -> None:
    resp = await client.get(f"/i/{TOKENS[gid]}")
    assert resp.status_code == 303


def sse(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.split("\n\n"):
        ev, data = "", None
        for line in block.strip().split("\n"):
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if ev and data is not None:
            out.append((ev, data))
    return out


async def start(client: AsyncClient) -> str:
    resp = await client.post("/api/conversations", json={"model_id": "sun"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def say(
    client: AsyncClient, rid: str, text: str, parent: str | None
) -> list[tuple[str, dict]]:
    resp = await client.post(
        f"/api/conversations/{rid}/messages", json={"content": text, "parent_id": parent}
    )
    assert resp.status_code == 200, resp.text
    return sse(resp.text)


class TestAuth:
    async def test_no_cookie_gets_invite_page_and_401(self, portal):
        c = portal["clients"]["alice"]
        assert (await c.get("/")).status_code == 401
        assert (await c.get("/api/me")).status_code == 401

    async def test_bad_token_rejected(self, portal):
        c = portal["clients"]["alice"]
        assert (await c.get("/i/not-a-real-token")).status_code == 404
        assert (await c.get("/api/me")).status_code == 401

    async def test_invite_sets_cookie(self, portal):
        c = portal["clients"]["alice"]
        await login(c, "alice")
        assert (await c.get("/api/me")).json() == {"name": "Alice"}
        assert (await c.get("/")).status_code == 200

    async def test_tampered_cookie_rejected(self, portal):
        c = portal["clients"]["alice"]
        c.cookies.set(auth.COOKIE, "bob.deadbeef", domain="guest.test")
        assert (await c.get("/api/me")).status_code == 401

    async def test_revocation_is_immediate(self, portal):
        c = portal["clients"]["alice"]
        await login(c, "alice")
        cfg = portal["cfg"]
        cfg.guests[0].revoked = True
        save(cfg, portal["path"])
        import os

        os.utime(portal["path"], (1, 1))  # ensure the mtime changes within the same second
        assert (await c.get("/api/me")).status_code == 401

    async def test_no_docs_or_openapi(self, portal):
        c = portal["clients"]["alice"]
        for p in ("/docs", "/openapi.json", "/redoc"):
            assert (await c.get(p)).status_code == 404

    async def test_security_headers(self, portal):
        r = await portal["clients"]["alice"].get("/")
        assert "default-src 'self'" in r.headers["content-security-policy"]
        assert r.headers["x-frame-options"] == "DENY"


class TestFlowAndRecording:
    async def test_chat_regenerate_and_record(self, portal):
        c, q = portal["clients"]["alice"], portal["qivis"]
        await login(c, "alice")
        rid = await start(c)

        events = await say(c, rid, "hi Sun", None)
        kinds = [e for e, _ in events]
        assert kinds[0] == "user" and "delta" in kinds and kinds[-1] == "done"
        reply = events[-1][1]
        assert reply["author"] == "Sun" and reply["content"] == "Hello 1."
        assert [t["t"] for t in reply["tokens"]] == ["Hello", " 1."]

        # recorded in Qivis: tagged, in Guests, with the guest's name on the user turn
        rh = (await q.get(f"/api/rhizomes/{rid}")).json()
        assert rh["metadata"]["guest"]["name"] == "Alice"
        assert "guest:alice" in rh["metadata"]["tags"] and rh["metadata"]["folders"] == ["Guests"]
        user = next(n for n in rh["nodes"] if n["role"] == "user")
        assert user["participant_name"] == "Alice"

        # regenerate: a new sibling, displayed by default; the old one can be chosen
        r = await c.post(f"/api/conversations/{rid}/regenerate", json={"node_id": reply["id"]})
        again = sse(r.text)[-1][1]
        assert again["content"] == "Hello 2." and len(again["sibling_ids"]) == 2
        view = (await c.get(f"/api/conversations/{rid}")).json()
        assert view["nodes"][-1]["content"] == "Hello 2."
        view = (await c.get(f"/api/conversations/{rid}?choose={reply['id']}")).json()
        assert view["nodes"][-1]["content"] == "Hello 1."

        # continue from the displayed leaf
        events = await say(c, rid, "and now?", again["id"])
        assert events[-1][0] == "done"
        view = (await c.get(f"/api/conversations/{rid}")).json()
        assert [n["role"] for n in view["nodes"]] == ["user", "assistant", "user", "assistant"]

        convs = (await c.get("/api/conversations")).json()
        assert convs[0]["id"] == rid and convs[0]["preview"] == "hi Sun"

    async def test_models_listed_and_unknown_rejected(self, portal):
        c = portal["clients"]["alice"]
        await login(c, "alice")
        assert (await c.get("/api/models")).json() == [{"id": "sun", "label": "Sun"}]
        assert (await c.post("/api/conversations", json={"model_id": "claude"})).status_code == 400


class TestIsolation:
    async def test_guests_cannot_touch_each_others_conversations(self, portal):
        a, b = portal["clients"]["alice"], portal["clients"]["bob"]
        await login(a, "alice")
        await login(b, "bob")
        rid = await start(a)
        reply = (await say(a, rid, "secret", None))[-1][1]
        assert (await b.get("/api/conversations")).json() == []
        assert (await b.get(f"/api/conversations/{rid}")).status_code == 404
        r = await b.post(
            f"/api/conversations/{rid}/messages", json={"content": "x", "parent_id": reply["id"]}
        )
        assert r.status_code == 404
        r = await b.post(f"/api/conversations/{rid}/regenerate", json={"node_id": reply["id"]})
        assert r.status_code == 404

    async def test_non_guest_rhizomes_invisible(self, portal):
        a, q = portal["clients"]["alice"], portal["qivis"]
        await login(a, "alice")
        rid = (await q.post("/api/rhizomes", json={"title": "Ian's research"})).json()["rhizome_id"]
        assert (await a.get("/api/conversations")).json() == []
        assert (await a.get(f"/api/conversations/{rid}")).status_code == 404

    async def test_must_reply_to_an_assistant_turn(self, portal):
        a = portal["clients"]["alice"]
        await login(a, "alice")
        rid = await start(a)
        user = (await say(a, rid, "hi", None))[0][1]
        r = await a.post(
            f"/api/conversations/{rid}/messages", json={"content": "x", "parent_id": user["id"]}
        )
        assert r.status_code == 400
        r = await a.post(
            f"/api/conversations/{rid}/messages", json={"content": "x", "parent_id": None}
        )
        assert r.status_code == 400


class TestLimits:
    async def test_message_length(self, portal):
        a = portal["clients"]["alice"]
        await login(a, "alice")
        rid = await start(a)
        r = await a.post(
            f"/api/conversations/{rid}/messages", json={"content": "x" * 201, "parent_id": None}
        )
        assert r.status_code == 413

    async def test_rate_limit(self, portal):
        a = portal["clients"]["alice"]
        await login(a, "alice")
        rid = await start(a)
        parent = None
        for i in range(5):
            parent = (await say(a, rid, f"m{i}", parent))[-1][1]["id"]
        r = await a.post(
            f"/api/conversations/{rid}/messages", json={"content": "one more", "parent_id": parent}
        )
        assert r.status_code == 429

    async def test_conversation_limit(self, portal):
        a = portal["clients"]["alice"]
        await login(a, "alice")
        for _ in range(3):
            await start(a)
        assert (await a.post("/api/conversations", json={"model_id": "sun"})).status_code == 429


class TestRecovery:
    async def test_unanswered_message_can_get_a_reply(self, portal):
        a, q = portal["clients"]["alice"], portal["qivis"]
        await login(a, "alice")
        rid = await start(a)
        # simulate a failed generation: the guest's message exists with no reply
        user = (
            await q.post(
                f"/api/rhizomes/{rid}/nodes",
                json={"content": "hello?", "participant_name": "Alice"},
            )
        ).json()
        r = await a.post(f"/api/conversations/{rid}/regenerate", json={"node_id": user["node_id"]})
        assert sse(r.text)[-1][0] == "done"
        # but not on a user message that already has a reply
        r = await a.post(f"/api/conversations/{rid}/regenerate", json={"node_id": user["node_id"]})
        assert r.status_code == 400
