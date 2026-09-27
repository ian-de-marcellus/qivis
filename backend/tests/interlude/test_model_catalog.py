"""Model catalog: models carry their own defaults (label, mode, template).

A rhizome's prompt template defaults to "auto", meaning the generating
model's profile decides; a profile's mode beats the rhizome's (an explicit
per-request mode override still wins). /api/models feeds the model picker.
"""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.service import GenerationService
from qivis.main import app
from qivis.model_catalog import ModelCatalog, get_catalog, set_catalog
from qivis.providers.base import GenerationRequest, GenerationResult, LLMProvider, StreamChunk
from qivis.providers.registry import clear_providers, register_provider
from qivis.rhizomes.router import get_generation_service, get_rhizome_service
from qivis.rhizomes.service import RhizomeService

PROFILES = {
    "_comment": "notes are ignored",
    "sun.gguf": {"label": "Sun 1.0.1", "provider": "local", "generation_mode": "completion",
                 "prompt_template": "llama3", "bos_tokens": 2},
    "gpt-x": {"label": "GPT X", "provider": "dual", "generation_mode": "chat"},
    "base-y": {"label": "Base Y", "provider": "dual", "generation_mode": "completion",
               "prompt_template": "chatml"},
    "elsewhere": {"label": "Not here", "provider": "unconfigured"},
}


class Recording(LLMProvider):
    def __init__(self, name, modes, suggested):
        self._name, self.supported_modes, self.suggested_models = name, modes, suggested
        self.calls: list[GenerationRequest] = []

    @property
    def name(self) -> str:
        return self._name

    async def generate(self, request):
        self.calls.append(request)
        return GenerationResult(content="ok", model=request.model, finish_reason="stop")

    async def generate_stream(self, request) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(type="message_stop", is_final=True, result=await self.generate(request))


@pytest.fixture
async def setup(db: Database):
    store, projector, service = EventStore(db), StateProjector(db), RhizomeService(db)
    gen = GenerationService(service, store, projector)
    providers = {
        "local": Recording("local", ["completion"], ["sun.gguf"]),
        "dual": Recording("dual", ["chat", "completion"], ["gpt-x", "gpt-plain"]),
    }
    clear_providers()
    for p in providers.values():
        register_provider(p)
    previous = get_catalog()
    set_catalog(ModelCatalog(PROFILES))
    app.dependency_overrides[get_rhizome_service] = lambda: service
    app.dependency_overrides[get_generation_service] = lambda: gen
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, providers
    app.dependency_overrides.clear()
    clear_providers()
    set_catalog(previous)


async def _rhizome(c, metadata: dict, default_model: str | None = None) -> tuple[str, str]:
    body = {"title": "t", **({"default_model": default_model} if default_model else {})}
    rid = (await c.post("/api/rhizomes", json=body)).json()["rhizome_id"]
    await c.patch(f"/api/rhizomes/{rid}", json={"metadata": metadata})
    nid = (await c.post(f"/api/rhizomes/{rid}/nodes", json={"content": "hi"})).json()["node_id"]
    return rid, nid


async def _gen(c, rid, nid, provider, model):
    r = await c.post(f"/api/rhizomes/{rid}/nodes/{nid}/generate", json={"provider": provider, "model": model})
    assert r.status_code == 201, r.text
    return r.json()


class TestModelsEndpoint:
    async def test_profiles_first_then_discovered_without_duplicates(self, setup):
        c, _ = setup
        entries = (await c.get("/api/models")).json()
        ids = [e["id"] for e in entries]
        assert ids[:3] == ["local:sun.gguf", "dual:gpt-x", "dual:base-y"]
        assert ids.count("dual:gpt-x") == 1 and "dual:gpt-plain" in ids
        assert "unconfigured:elsewhere" not in ids
        sun = entries[0]
        assert sun["label"] == "Sun 1.0.1" and sun["mode"] == "completion"
        assert sun["prompt_template"] == "llama3" and sun["source"] == "profile"
        plain = next(e for e in entries if e["model"] == "gpt-plain")
        assert plain == {"id": "dual:gpt-plain", "label": "gpt-plain", "provider": "dual",
                         "model": "gpt-plain", "mode": "chat", "prompt_template": None,
                         "source": "discovered"}


class TestTemplateResolution:
    async def test_auto_template_uses_the_models_profile(self, setup):
        c, p = setup
        rid, nid = await _rhizome(c, {"generation_mode": "completion", "prompt_template": "auto"})
        node = await _gen(c, rid, nid, "local", "sun.gguf")
        assert p["local"].calls[-1].prompt_text.startswith("<|begin_of_text|><|start_header_id|>user")
        assert node["mode"] == "completion"

    async def test_unset_template_uses_the_models_profile(self, setup):
        c, p = setup
        rid, nid = await _rhizome(c, {"generation_mode": "completion"})
        await _gen(c, rid, nid, "local", "sun.gguf")
        assert "<|start_header_id|>" in p["local"].calls[-1].prompt_text

    async def test_explicit_template_wins(self, setup):
        c, p = setup
        rid, nid = await _rhizome(c, {"generation_mode": "completion", "prompt_template": "raw"})
        await _gen(c, rid, nid, "local", "sun.gguf")
        assert "<|start_header_id|>" not in p["local"].calls[-1].prompt_text

    async def test_unprofiled_model_falls_back_to_raw(self, setup):
        c, p = setup
        rid, nid = await _rhizome(c, {"generation_mode": "completion"}, default_model="gpt-plain")
        await _gen(c, rid, nid, "dual", "gpt-plain")
        assert p["dual"].calls[-1].prompt_text == "hi\n"


class TestModeResolution:
    async def test_rhizome_mode_is_for_its_own_model(self, setup):
        """An unprofiled visitor to a completion rhizome is a chat model, not a raw transcript."""
        c, p = setup
        rid, nid = await _rhizome(c, {"generation_mode": "completion"}, default_model="base-z")
        visitor = await _gen(c, rid, nid, "dual", "gpt-plain")
        assert p["dual"].calls[-1].prompt_text is None and visitor["mode"] == "chat"
        own = await _gen(c, rid, nid, "dual", "base-z")
        assert p["dual"].calls[-1].prompt_text is not None and own["mode"] == "completion"

    async def test_chat_profile_beats_completion_rhizome(self, setup):
        """GPT in a Sun (completion) rhizome gets chat, because its profile says so."""
        c, p = setup
        rid, nid = await _rhizome(c, {"generation_mode": "completion", "prompt_template": "auto"})
        node = await _gen(c, rid, nid, "dual", "gpt-x")
        assert p["dual"].calls[-1].prompt_text is None and node["mode"] == "chat"

    async def test_completion_profile_in_chat_rhizome(self, setup):
        c, p = setup
        rid, nid = await _rhizome(c, {"generation_mode": "chat"})
        await _gen(c, rid, nid, "dual", "base-y")
        assert p["dual"].calls[-1].prompt_text.startswith("<|im_start|>")  # its own chatml template

    async def test_explicit_override_beats_profile(self, setup):
        c, p = setup
        rid, nid = await _rhizome(c, {"generation_mode": "chat"})
        r = await c.post(f"/api/rhizomes/{rid}/nodes/{nid}/generate",
                         json={"provider": "dual", "model": "base-y", "mode": "chat"})
        assert r.status_code == 201 and p["dual"].calls[-1].prompt_text is None

    async def test_cross_model_uses_each_targets_profile(self, setup):
        c, p = setup
        rid, nid = await _rhizome(c, {"generation_mode": "completion", "prompt_template": "auto"})
        r = await c.post(f"/api/rhizomes/{rid}/nodes/{nid}/generate-cross", json={"targets": [
            {"provider": "local", "model": "sun.gguf"}, {"provider": "dual", "model": "gpt-x"}]})
        assert r.status_code == 200
        assert p["local"].calls[-1].prompt_text.startswith("<|begin_of_text|>")
        assert p["dual"].calls[-1].prompt_text is None
