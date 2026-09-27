"""Per-model sampling defaults for llama.cpp, applied to the *served* model.

Some local models need a fixed sampling adjustment to behave as themselves.
Sun 1.0.1, for example, needs +ln(386) on <|eot_id|> to restore end-of-turn
mass that her untrained output row used to share with 385 twins. llama.cpp
serves whatever model is loaded regardless of the requested name, so the
provider keys defaults on the model it is actually serving. It reports what
it applied, and the generation service records it in the node's
sampling_params -- so the record shows exactly what shaped the output.
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

LLAMA3 = "<|begin_of_text|><|start_header_id|>assistant<|end_header_id|>\n\n"
SUN_DEFAULTS = {"sun-1.0.1.gguf": {"logit_bias": {"128009": 5.955837}}}


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


def _client(served: str | None) -> AsyncMock:
    lines = [
        "data: " + json.dumps({"content": "Hi.", "stop": False}),
        "data: " + json.dumps({"content": "", "stop": True, "stop_type": "eos"}),
    ]
    client = AsyncMock()
    client.stream = MagicMock(side_effect=lambda *a, **kw: MockStream(lines))
    client.post = AsyncMock(side_effect=ConnectionError("no /tokenize in this mock"))
    if served is None:
        client.get = AsyncMock(side_effect=ConnectionError("no props"))
    else:
        props = MagicMock()
        props.json.return_value = {"model_alias": served}
        props.raise_for_status = MagicMock()
        client.get = AsyncMock(return_value=props)
    return client


def _request(logit_bias: dict[int, float] | None = None) -> GenerationRequest:
    return GenerationRequest(
        model="whatever-the-rhizome-asked-for.gguf",
        messages=[],
        prompt_text=LLAMA3,
        sampling_params=SamplingParams(max_tokens=50, logit_bias=logit_bias),
    )


def _sent_bias(client: AsyncMock) -> dict[int, float]:
    body = client.stream.call_args.kwargs["json"]
    return {int(t): b for t, b in body.get("logit_bias", [])}


class TestProviderModelDefaults:
    async def test_served_model_defaults_are_sent_and_reported(self):
        client = _client("sun-1.0.1.gguf")
        provider = LlamaCppProvider(http_client=client, model_defaults=SUN_DEFAULTS)
        result = await provider.generate(_request())
        sent = _sent_bias(client)
        assert sent[128009] == pytest.approx(5.955837)
        assert sent[128011] == -100.0  # reserved-range suppression still there
        assert result.applied_sampling_params == {"logit_bias": {128009: pytest.approx(5.955837)}}

    async def test_request_bias_overrides_default_per_token(self):
        client = _client("sun-1.0.1.gguf")
        provider = LlamaCppProvider(http_client=client, model_defaults=SUN_DEFAULTS)
        result = await provider.generate(_request({128009: 1.0, 42: -2.0}))
        sent = _sent_bias(client)
        assert sent[128009] == 1.0 and sent[42] == -2.0
        assert result.applied_sampling_params == {"logit_bias": {128009: 1.0, 42: -2.0}}

    async def test_keyed_on_served_model_not_requested_name(self):
        client = _client("some-other-model.gguf")
        provider = LlamaCppProvider(http_client=client, model_defaults=SUN_DEFAULTS)
        result = await provider.generate(_request())
        assert 128009 not in _sent_bias(client)
        assert result.applied_sampling_params is None

    async def test_explicit_bias_without_defaults_is_still_reported(self):
        client = _client("some-other-model.gguf")
        provider = LlamaCppProvider(http_client=client, model_defaults=SUN_DEFAULTS)
        result = await provider.generate(_request({7: 3.0}))
        assert _sent_bias(client)[7] == 3.0
        assert result.applied_sampling_params == {"logit_bias": {7: 3.0}}

    async def test_unreachable_props_means_no_defaults(self):
        client = _client(None)
        provider = LlamaCppProvider(http_client=client, model_defaults=SUN_DEFAULTS)
        result = await provider.generate(_request())
        assert result.content == "Hi."
        assert result.applied_sampling_params is None


# -- Recording --


class AppliesBiasProvider(LLMProvider):
    supported_modes = ["chat", "completion"]

    @property
    def name(self) -> str:
        return "applies-bias"

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(
            content="done.", model="sun-1.0.1.gguf", finish_reason="stop",
            applied_sampling_params={"logit_bias": {128009: 5.955837}},
        )

    async def generate_stream(self, request: GenerationRequest) -> AsyncIterator[StreamChunk]:
        result = await self.generate(request)
        yield StreamChunk(type="message_stop", is_final=True, result=result)


@pytest.fixture
async def client(db: Database):
    store, projector, service = EventStore(db), StateProjector(db), RhizomeService(db)
    gen = GenerationService(service, store, projector)
    clear_providers()
    register_provider(AppliesBiasProvider())
    app.dependency_overrides[get_rhizome_service] = lambda: service
    app.dependency_overrides[get_generation_service] = lambda: gen
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    clear_providers()


class TestRecording:
    @pytest.mark.parametrize("stream", [False, True])
    async def test_applied_params_are_recorded_on_the_node(self, client, stream):
        rid = (await client.post("/api/rhizomes", json={"title": "t", "default_sampling_params": {
            "temperature": 0.7}})).json()["rhizome_id"]
        await client.post(f"/api/rhizomes/{rid}/generate", json={
            "provider": "applies-bias", "model": "m", "stream": stream})
        node = (await client.get(f"/api/rhizomes/{rid}")).json()["nodes"][0]
        assert node["sampling_params"]["logit_bias"] == {"128009": pytest.approx(5.955837)}
        assert node["sampling_params"]["temperature"] == 0.7
