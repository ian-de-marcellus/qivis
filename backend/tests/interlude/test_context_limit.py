"""Local models evict to fit their own window.

A local model's window (its profile's context_limit, else what the provider
reports, e.g. llama-server's n_ctx) holds the prompt and the reply together,
so the prompt budget is the window minus max_tokens. Without this, unknown
models fell back to 200k and a long conversation overflowed the server.
"""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.context import DEFAULT_REPLY_RESERVE, resolve_context_limit
from qivis.generation.service import GenerationService
from qivis.main import app
from qivis.model_catalog import ModelCatalog, get_catalog, set_catalog
from qivis.providers.base import GenerationRequest, GenerationResult, LLMProvider, StreamChunk
from qivis.providers.llamacpp import LlamaCppProvider
from qivis.providers.registry import clear_providers, register_provider
from qivis.rhizomes.router import get_generation_service, get_rhizome_service
from qivis.rhizomes.service import RhizomeService
from qivis.tools.llama_supervisor import Supervisor


class WindowedProvider(LLMProvider):
    def __init__(self, window: int | None):
        self.window = window
        self.requests: list[GenerationRequest] = []

    @property
    def name(self) -> str:
        return "windowed"

    async def context_window(self, model: str) -> int | None:
        return self.window

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.requests.append(request)
        return GenerationResult(content="ok", model=request.model, finish_reason="stop")

    async def generate_stream(self, request) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(type="message_stop", is_final=True, result=await self.generate(request))


@pytest.fixture
def catalog():
    previous = get_catalog()
    yield lambda profiles: set_catalog(ModelCatalog(profiles))
    set_catalog(previous)


async def test_profile_window_wins_and_reply_is_set_aside(catalog):
    catalog({"local.gguf": {"context_limit": 4096}})
    assert await resolve_context_limit(WindowedProvider(8192), "local.gguf", 512) == 3584


async def test_provider_window_when_no_profile_limit(catalog):
    catalog({})
    provider = WindowedProvider(8192)
    assert await resolve_context_limit(provider, "local.gguf", None) == 8192 - DEFAULT_REPLY_RESERVE


async def test_known_model_table_when_nobody_knows_the_window(catalog):
    catalog({})
    assert await resolve_context_limit(WindowedProvider(None), "gpt-4", 512) == 8_192


async def test_huge_max_tokens_leaves_some_prompt(catalog):
    catalog({})
    assert await resolve_context_limit(WindowedProvider(2048), "m", 4096) == 512


async def test_llamacpp_reads_n_ctx_from_props():
    client = AsyncMock()
    props = MagicMock()
    props.json.return_value = {"default_generation_settings": {"n_ctx": 8192}}
    client.get = AsyncMock(return_value=props)
    provider = LlamaCppProvider(http_client=client)
    assert await provider.context_window("anything") == 8192

    client.get = AsyncMock(side_effect=ConnectionError("down"))
    assert await provider.context_window("anything") is None


def test_sleeping_supervisor_reports_its_ctx_size(tmp_path: Path):
    sup = Supervisor(model=tmp_path / "sun.gguf", backend_port=1, idle_seconds=60,
                     llama_cmd=["llama-server"], extra_args=["-ngl", "99", "-c", "8192"])
    assert sup.placeholder_props()["default_generation_settings"] == {"n_ctx": 8192}


async def test_long_conversation_evicts_to_fit_the_window(db: Database, catalog):
    catalog({})
    store, projector, service = EventStore(db), StateProjector(db), RhizomeService(db)
    gen = GenerationService(service, store, projector)
    provider = WindowedProvider(400)
    clear_providers()
    register_provider(provider)
    app.dependency_overrides[get_rhizome_service] = lambda: service
    app.dependency_overrides[get_generation_service] = lambda: gen
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            rid = (await c.post("/api/rhizomes", json={
                "title": "long", "default_provider": "windowed", "default_model": "local.gguf",
            })).json()["rhizome_id"]
            parent = None
            for i in range(6):  # ~100 tokens each by the len/4 estimate
                role = "user" if i % 2 == 0 else "assistant"
                parent = (await c.post(f"/api/rhizomes/{rid}/nodes", json={
                    "content": f"{i} " + "word " * 80, "role": role, "parent_id": parent,
                })).json()["node_id"]
            r = await c.post(f"/api/rhizomes/{rid}/nodes/{parent}/generate", json={
                "provider": "windowed", "model": "local.gguf",
                "sampling_params": {"max_tokens": 100},
            })
            assert r.status_code == 201, r.text
            usage = r.json()["context_usage"]
            assert usage["max_tokens"] == 300
            assert usage["total_tokens"] <= 300
            sent = provider.requests[-1].messages
            assert [m["content"][:2] for m in sent] == ["3 ", "4 ", "5 "]
    finally:
        app.dependency_overrides.clear()
        clear_providers()


def test_json_example_documents_context_limit():
    example = Path(__file__).parents[2] / "model_defaults.example.json"
    assert "context_limit" in json.loads(example.read_text())["_comment"]
