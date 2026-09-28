"""Answer probes: short samples at a point, and what each one answers.

Samples draw from the model's own distribution (temperature 1, nothing
truncated), each is kept as the node it would become, and continuing from
one records it as a reply like any other, noting its probe. The judge's
labels are an interpretation, stored with the judge and what it was asked.
"""

from collections.abc import AsyncIterator
from itertools import cycle

import pytest

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.service import GenerationService
from qivis.models import LogprobData, TokenLogprob
from qivis.probes import judge as judging
from qivis.probes.service import ProbeService
from qivis.providers.base import GenerationRequest, GenerationResult, LLMProvider, StreamChunk
from qivis.rhizomes.schemas import CreateNodeRequest, CreateRhizomeRequest
from qivis.rhizomes.service import RhizomeService

REPLIES = [" I love cats!", " Probably dogs.\n\nIan:", " cats, i think"]


class Sampler(LLMProvider):
    supported_modes = ["completion"]

    def __init__(self) -> None:
        self.requests: list[GenerationRequest] = []
        self._replies = cycle(REPLIES)

    @property
    def name(self) -> str:
        return "sampler"

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.requests.append(request)
        text = next(self._replies)
        return GenerationResult(
            content=text, model="m", finish_reason="stop", usage={"output_tokens": 3},
            logprobs=LogprobData(
                tokens=[TokenLogprob(token=text, logprob=-1.0, linear_prob=0.37, top_alternatives=[])],
                provider_format="llamacpp", top_k_available=5,
            ),
        )

    async def generate_stream(self, request) -> AsyncIterator[StreamChunk]:
        raise AssertionError("probes don't stream")
        yield


@pytest.fixture
async def setup(db: Database):
    rhizomes = RhizomeService(db)
    store, projector = EventStore(db), StateProjector(db)
    gen = GenerationService(rhizomes, store, projector)
    probes = ProbeService(rhizomes, gen, store, projector)
    rid = (await rhizomes.create_rhizome(CreateRhizomeRequest(
        title="t", default_provider="sampler", default_model="m",
        metadata={"generation_mode": "completion", "prompt_template": "transcript",
                  "speaker_name": "Ian", "model_name": "Betsy"},
    ))).rhizome_id
    uid = (await rhizomes.create_node(rid, CreateNodeRequest(
        content="Betsy, what's your favorite animal?"))).node_id
    return rhizomes, probes, rid, uid


async def test_samples_draw_from_the_model_itself(setup):
    rhizomes, probes, rid, uid = setup
    model = Sampler()
    probe = await probes.run(rid, uid, model, n=6, max_tokens=16)

    sp = model.requests[0].sampling_params
    assert (sp.temperature, sp.top_p, sp.top_k, sp.max_tokens) == (1.0, 1.0, 0, 16)
    assert len(probe["samples"]) == 6
    # A transcript turn ends at a new speaker's line, and is stored as the turn's text
    assert [s["content"] for s in probe["samples"][:3]] == ["I love cats!", "Probably dogs.", "cats, i think"]
    assert probe["prompt_text"].endswith("Betsy:")
    # Samples aren't nodes: the rhizome is unchanged
    assert [n.role for n in (await rhizomes.get_rhizome(rid)).nodes] == ["user"]


async def test_continuing_from_a_sample_records_it_as_a_reply(setup):
    rhizomes, probes, rid, uid = setup
    probe = await probes.run(rid, uid, Sampler(), n=3)
    node = await probes.continue_from(rid, probe["probe_id"], 1)
    assert node.parent_id == uid and node.role == "assistant"
    assert node.content == "Probably dogs." and node.provider == "sampler"
    assert node.logprobs["tokens"][0]["linear_prob"] == 0.37
    assert node.sampling_params["temperature"] == 1.0  # what it was sampled with
    assert node.prompt_text == probe["prompt_text"]


async def test_the_judges_labels_are_kept_with_the_judge(setup, monkeypatch):
    _, probes, rid, uid = setup

    async def fake_judge(self, samples):
        return {"model": "judge.gguf", "messages": [{"role": "user", "content": "..."}],
                "answers": ["cats", "dogs", "cats"][: len(samples)]}

    monkeypatch.setattr(ProbeService, "_judge", fake_judge)
    probe = await probes.run(rid, uid, Sampler(), n=3)
    assert probe["judge"]["answers"] == ["cats", "dogs", "cats"]
    assert probe["judge"]["model"] == "judge.gguf"
    assert [p["probe_id"] for p in await probes.list(rid)] == [probe["probe_id"]]


def test_labels_are_normalized():
    assert judging.normalize(" Cats! ") == "cats"
    assert judging.normalize("the  Giraffe.") == "the giraffe"
    assert judging.normalize("") == "no answer"


def test_the_judge_sees_the_end_of_the_text_and_every_sample():
    request = judging.judge_request("x" * 5000 + "Ian: favorite?\n\nBetsy:", ["cats", "dogs"])
    assert "Ian: favorite?\n\nBetsy:" in request and "x" * 900 not in request
    assert "1. cats\n2. dogs" in request


def test_a_gpu_judge_is_skipped_when_it_would_not_fit():
    gb = 1024**3
    status = {"memory_budget": 36 * gb, "models": [
        {"model": "big.gguf", "running": True, "gpu": True, "size": 34 * gb},
        {"model": "judge.gguf", "running": False, "gpu": True, "size": 3 * gb},
    ]}
    assert not judging._fits(status, "judge.gguf")
    status["models"][0]["running"] = False
    assert judging._fits(status, "judge.gguf")


def test_plural_and_singular_are_one_answer():
    merged = judging.merge_forms(["dogs", "dog", "Dogs", "cat", "cats", "fish", "no answer"])
    assert merged == ["dogs", "dogs", "dogs", "cat", "cat", "fish", "no answer"]
    # A tie goes to the shorter form; a lone plural stays as it is
    assert judging.merge_forms(["horses", "horse"]) == ["horse", "horse"]
    assert judging.merge_forms(["glasses", "fish"]) == ["glasses", "fish"]
