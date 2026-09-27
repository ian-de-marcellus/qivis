"""Per-model begin-of-text count for llama.cpp, and recording what the model saw.

Qivis's llama3 template writes <|begin_of_text|>, and llama-server prepends its
own BOS to string prompts (when the vocab says to), so a model would see two.
Standard Llama 3 models expect one. Sun 1.0 was trained with two (her SFT text
began with <|begin_of_text|> and TRL 0.8.6 added another): on her own training
replies she scores -0.115 nats/token with two vs -0.174 with one. So the count
is a per-model setting (`bos_tokens`, default 1), and when the effective prompt
differs from the rendered template the node records the effective one.
"""

import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.service import GenerationService
from qivis.main import app
from qivis.models import SamplingParams
from qivis.providers.base import GenerationRequest, GenerationResult, LLMProvider, StreamChunk
from qivis.providers.llamacpp import LlamaCppProvider
from qivis.providers.registry import clear_providers, register_provider
from qivis.rhizomes.router import get_generation_service, get_rhizome_service
from qivis.rhizomes.service import RhizomeService

BOS = "<|begin_of_text|>"
LLAMA3 = BOS + "<|start_header_id|>assistant<|end_header_id|>\n\n"


class MockStream:
    def __init__(self, lines):
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    def raise_for_status(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _client(served: str, server_adds_bos: bool) -> AsyncMock:
    lines = [
        "data: " + json.dumps({"content": "Hi.", "stop": False}),
        "data: " + json.dumps({"content": "", "stop": True, "stop_type": "eos"}),
    ]
    client = AsyncMock()
    client.stream = MagicMock(side_effect=lambda *a, **kw: MockStream(lines))

    props = MagicMock()
    props.json.return_value = {"model_alias": served}
    props.raise_for_status = MagicMock()
    client.get = AsyncMock(return_value=props)

    tokenized = MagicMock()
    tokenized.json.return_value = {"tokens": [128000, 87] if server_adds_bos else [87]}
    tokenized.raise_for_status = MagicMock()
    client.post = AsyncMock(return_value=tokenized)
    return client


def _request(prompt: str = LLAMA3) -> GenerationRequest:
    return GenerationRequest(
        model="m", messages=[], prompt_text=prompt,
        sampling_params=SamplingParams(max_tokens=20),
    )


def _sent_prompt(client: AsyncMock) -> str:
    return client.stream.call_args.kwargs["json"]["prompt"]


SUN = {"sun.gguf": {"bos_tokens": 2}}


class TestBosCount:
    async def test_default_one_bos_strips_template_copy(self):
        client = _client("base.gguf", server_adds_bos=True)
        provider = LlamaCppProvider(http_client=client, model_defaults=SUN)
        result = await provider.generate(_request())
        assert _sent_prompt(client) == LLAMA3[len(BOS):]  # server supplies the one BOS
        assert result.effective_prompt_text is None       # model saw the template as rendered

    async def test_sun_keeps_two(self):
        client = _client("sun.gguf", server_adds_bos=True)
        provider = LlamaCppProvider(http_client=client, model_defaults=SUN)
        result = await provider.generate(_request())
        assert _sent_prompt(client) == LLAMA3
        assert result.effective_prompt_text == BOS + LLAMA3

    async def test_server_without_bos_default_one(self):
        client = _client("base.gguf", server_adds_bos=False)
        provider = LlamaCppProvider(http_client=client, model_defaults=SUN)
        result = await provider.generate(_request())
        assert _sent_prompt(client) == LLAMA3
        assert result.effective_prompt_text is None

    async def test_server_without_bos_two_requested(self):
        client = _client("sun.gguf", server_adds_bos=False)
        provider = LlamaCppProvider(http_client=client, model_defaults=SUN)
        result = await provider.generate(_request())
        assert _sent_prompt(client) == BOS + LLAMA3
        assert result.effective_prompt_text == BOS + LLAMA3

    async def test_non_llama3_prompt_untouched(self):
        client = _client("base.gguf", server_adds_bos=True)
        provider = LlamaCppProvider(http_client=client, model_defaults=SUN)
        chatml = "<|im_start|>user\nhi<|im_end|>\n<|im_start|>assistant\n"
        result = await provider.generate(_request(chatml))
        assert _sent_prompt(client) == chatml
        assert result.effective_prompt_text is None


# -- Recording --


class ReportsEffectivePrompt(LLMProvider):
    supported_modes = ["completion"]

    @property
    def name(self) -> str:
        return "effective"

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(
            content="hi", model="m", finish_reason="stop",
            effective_prompt_text=BOS + (request.prompt_text or ""),
        )

    async def generate_stream(self, request: GenerationRequest) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(type="message_stop", is_final=True, result=await self.generate(request))


@pytest.fixture
async def client(db: Database):
    store, projector, service = EventStore(db), StateProjector(db), RhizomeService(db)
    gen = GenerationService(service, store, projector)
    clear_providers()
    register_provider(ReportsEffectivePrompt())
    app.dependency_overrides[get_rhizome_service] = lambda: service
    app.dependency_overrides[get_generation_service] = lambda: gen
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    clear_providers()


async def _llama3_rhizome(client) -> str:
    rid = (await client.post("/api/rhizomes", json={"title": "t"})).json()["rhizome_id"]
    await client.patch(f"/api/rhizomes/{rid}", json={"metadata": {
        "generation_mode": "completion", "prompt_template": "llama3"}})
    return rid


class TestRecordingEffectivePrompt:
    @pytest.mark.parametrize("stream", [False, True])
    async def test_node_records_what_the_model_saw(self, client, stream):
        rid = await _llama3_rhizome(client)
        await client.post(f"/api/rhizomes/{rid}/generate", json={"provider": "effective", "stream": stream})
        node = (await client.get(f"/api/rhizomes/{rid}")).json()["nodes"][0]
        assert node["prompt_text"] == BOS + LLAMA3

    async def test_cross_model_nodes_record_prompt_text(self, client):
        rid = await _llama3_rhizome(client)
        nid = (await client.post(f"/api/rhizomes/{rid}/nodes", json={"content": "hi"})).json()["node_id"]
        resp = await client.post(f"/api/rhizomes/{rid}/nodes/{nid}/generate-cross", json={
            "targets": [{"provider": "effective", "model": "m"}]})
        assert resp.status_code == 200
        assert resp.json()[0]["prompt_text"].startswith(BOS + BOS)
