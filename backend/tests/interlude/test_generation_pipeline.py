"""One generation pipeline: every kind of generation records what its model saw.

Before Sep 2026 each kind of generation (single, n>1, cross-model, replay,
perturbation) assembled its own request and its own node, and they drifted:
perturbation answered the turn it was regenerating and recorded "chat" for
completion models; n>1 threw away every reply if one failed; cross-model
dropped thinking from its stream; a provider stream that ended without a
result was silently lost. These tests hold the shared pipeline to what the
record promises.
"""

import json
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.perturbation import PerturbationService
from qivis.generation.replay import ReplayService
from qivis.generation.service import GenerationService
from qivis.main import app
from qivis.providers.base import GenerationRequest, GenerationResult, LLMProvider, StreamChunk
from qivis.providers.registry import clear_providers, register_provider
from qivis.rhizomes.router import (
    get_generation_service,
    get_perturbation_service,
    get_replay_service,
    get_rhizome_service,
)
from qivis.rhizomes.service import RhizomeService
from tests.fixtures import create_rhizome_with_messages


class Recorder(LLMProvider):
    """Records requests; optional failures and a truncated stream on demand."""

    def __init__(self, name: str, modes: list[str], *, thinking: str | None = None):
        self._name = name
        self.supported_modes = modes
        self.requests: list[GenerationRequest] = []
        self.fail_every: int | None = None
        self.no_final = False
        self.thinking = thinking

    @property
    def name(self) -> str:
        return self._name

    def _result(self, request: GenerationRequest) -> GenerationResult:
        self.requests.append(request)
        if self.fail_every and len(self.requests) % self.fail_every == 0:
            raise RuntimeError("provider hiccup")
        return GenerationResult(
            content=f"{self._name} reply", model=request.model, finish_reason="stop",
            thinking_content=self.thinking,
        )

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        return self._result(request)

    async def generate_stream(self, request) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(type="text_delta", text="partial")
        if self.no_final:
            return
        yield StreamChunk(type="message_stop", is_final=True, result=self._result(request))


@pytest.fixture
async def env(db: Database):
    store, projector, service = EventStore(db), StateProjector(db), RhizomeService(db)
    gen = GenerationService(service, store, projector)
    providers = {
        "chatty": Recorder("chatty", ["chat"], thinking="hmm"),
        "local": Recorder("local", ["completion"]),
    }
    clear_providers()
    for p in providers.values():
        register_provider(p)
    app.dependency_overrides[get_rhizome_service] = lambda: service
    app.dependency_overrides[get_generation_service] = lambda: gen
    app.dependency_overrides[get_perturbation_service] = lambda: PerturbationService(
        gen, store, projector)
    app.dependency_overrides[get_replay_service] = lambda: ReplayService(
        service, gen, store, projector)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c, providers
    app.dependency_overrides.clear()
    clear_providers()


def _events(body: str) -> list[tuple[str, dict]]:
    out = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


async def _nodes(c: AsyncClient, rid: str) -> dict[str, dict]:
    return {n["node_id"]: n for n in (await c.get(f"/api/rhizomes/{rid}")).json()["nodes"]}


async def test_perturbation_regenerates_an_assistant_turn_as_its_sibling(env):
    c, providers = env
    conv = await create_rhizome_with_messages(c, n_messages=4)
    anchor = conv["node_ids"][-1]  # assistant "Message 4"
    r = await c.post(f"/api/rhizomes/{conv['rhizome_id']}/nodes/{anchor}/perturb", json={
        "provider": "chatty", "model": "m", "stream": False,
        "perturbations": [{"type": "system_prompt", "system_prompt": "Be a pirate."}],
    })
    assert r.status_code == 200, r.text
    nodes = await _nodes(c, conv["rhizome_id"])
    for step in r.json()["steps"]:
        assert nodes[step["node_id"]]["parent_id"] == conv["node_ids"][-2]
    # The model answered "Message 3"; it never saw the turn it was regenerating
    for req in providers["chatty"].requests:
        assert req.messages[-1]["content"] == "Message 3"
        assert all(m["content"] != "Message 4" for m in req.messages)
    assert providers["chatty"].requests[1].system_prompt == "Be a pirate."
    pirate = nodes[r.json()["steps"][1]["node_id"]]
    assert pirate["system_prompt"] == "Be a pirate."


async def test_perturbation_records_completion_mode_and_prompt(env):
    c, providers = env
    conv = await create_rhizome_with_messages(c, n_messages=2)
    await c.patch(f"/api/rhizomes/{conv['rhizome_id']}", json={
        "metadata": {"prompt_template": "llama3"}})
    r = await c.post(
        f"/api/rhizomes/{conv['rhizome_id']}/nodes/{conv['node_ids'][-1]}/perturb",
        json={"provider": "local", "model": "sun.gguf", "stream": False,
              "perturbations": [{"type": "system_prompt", "system_prompt": "Hi."}]},
    )
    assert r.status_code == 200, r.text
    node = (await _nodes(c, conv["rhizome_id"]))[r.json()["steps"][0]["node_id"]]
    assert node["mode"] == "completion"
    assert node["prompt_text"] == providers["local"].requests[0].prompt_text
    assert "<|eot_id|>" in node["sampling_params"]["stop_sequences"]


async def test_cross_model_each_target_in_its_own_mode(env):
    c, providers = env
    conv = await create_rhizome_with_messages(c, n_messages=1)
    await c.patch(f"/api/rhizomes/{conv['rhizome_id']}", json={
        "metadata": {"include_timestamps": True, "prompt_template": "llama3"}})
    r = await c.post(
        f"/api/rhizomes/{conv['rhizome_id']}/nodes/{conv['node_ids'][0]}/generate-cross",
        json={"targets": [{"provider": "chatty", "model": "gpt"},
                          {"provider": "local", "model": "sun.gguf"}]},
    )
    assert r.status_code == 200, r.text
    chat_req, = providers["chatty"].requests
    local_req, = providers["local"].requests
    assert chat_req.prompt_text is None and "[" in chat_req.messages[0]["content"]  # timestamped
    assert local_req.prompt_text is not None and "Message 1" in local_req.prompt_text
    assert "[20" not in local_req.prompt_text  # timestamps are chat context only
    by_provider = {n["provider"]: n for n in r.json()}
    assert by_provider["chatty"]["mode"] == "chat" and by_provider["chatty"]["include_timestamps"]
    assert by_provider["local"]["mode"] == "completion"
    assert not by_provider["local"]["include_timestamps"]


async def test_cross_model_stream_carries_thinking(env):
    c, _ = env
    conv = await create_rhizome_with_messages(c, n_messages=1)
    r = await c.post(
        f"/api/rhizomes/{conv['rhizome_id']}/nodes/{conv['node_ids'][0]}/generate-cross",
        json={"targets": [{"provider": "chatty", "model": "a"},
                          {"provider": "chatty", "model": "b"}], "stream": True},
    )
    stops = [d for e, d in _events(r.text) if e == "message_stop"]
    assert len(stops) == 2 and all(s["thinking_content"] == "hmm" for s in stops)
    assert sorted(s["completion_index"] for s in stops) == [0, 1]


async def test_n_keeps_the_replies_that_succeeded(env):
    c, providers = env
    providers["chatty"].fail_every = 2  # the 2nd of 3 fails
    conv = await create_rhizome_with_messages(c, n_messages=1)
    r = await c.post(
        f"/api/rhizomes/{conv['rhizome_id']}/nodes/{conv['node_ids'][0]}/generate",
        json={"provider": "chatty", "model": "m", "n": 3},
    )
    assert r.status_code == 201
    replies = [n for n in (await _nodes(c, conv["rhizome_id"])).values()
               if n["role"] == "assistant"]
    assert len(replies) == 2


async def test_stream_without_a_result_is_an_error_not_silence(env):
    c, providers = env
    providers["chatty"].no_final = True
    conv = await create_rhizome_with_messages(c, n_messages=1)
    r = await c.post(
        f"/api/rhizomes/{conv['rhizome_id']}/nodes/{conv['node_ids'][0]}/generate",
        json={"provider": "chatty", "model": "m", "stream": True},
    )
    events = _events(r.text)
    assert events[-1][0] == "error" and "ended without a result" in events[-1][1]["error"]


async def test_trajectory_replay_is_gone(env):
    c, _ = env
    conv = await create_rhizome_with_messages(c, n_messages=2)
    r = await c.post(f"/api/rhizomes/{conv['rhizome_id']}/replay", json={
        "path_node_ids": conv["node_ids"], "provider": "chatty", "mode": "trajectory"})
    assert r.status_code == 422
