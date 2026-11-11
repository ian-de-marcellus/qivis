"""Exact answer probes: the answer distribution at a point, enumerated.

Every one-line answer down to epsilon gets its exact probability; what's
pruned is known exactly and sampled (tail rollouts), each rollout carrying
an equal share of it. Labels and groups are the judge's reading, kept with
the judge. Continuing from an enumerated answer records that it wasn't
sampled, and its probability.
"""

import random

import pytest

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.service import GenerationService
from qivis.names.engine import Lookups, Summary
from qivis.probes import exact
from qivis.probes import judge as judging
from qivis.probes.service import ProbeService
from qivis.providers.llamacpp import LlamaCppProvider
from qivis.rhizomes.schemas import CreateNodeRequest, CreateRhizomeRequest
from qivis.rhizomes.service import RhizomeService

# A toy model: token ids -> text, and the next-token distribution after each path
VOCAB = {0: " Can", 1: "berra", 2: "\n", 3: " Syd", 4: "ney", 5: " The", 6: " capital", 7: " is", 8: "?"}


# The next token depends only on the last: Canberra, Sydney, a wordier route to either
NEXT = {
    None: {0: 0.6, 3: 0.25, 5: 0.1, 8: 0.05},
    0: {1: 0.95, 2: 0.05},  # " Can" -> "berra" or the line ends
    1: {2: 0.9, 8: 0.1},
    3: {4: 1.0},
    4: {2: 0.8, 8: 0.2},
    5: {6: 1.0},  # " The capital is" ...
    6: {7: 1.0},
    7: {0: 0.7, 3: 0.3},
    8: {2: 1.0},  # "?" then the line ends
}


def toy(path: tuple[int, ...]) -> dict[int, float]:
    return NEXT[path[-1] if path else None]


def summary(path: tuple[int, ...]) -> Summary:
    return Summary.of({t: (VOCAB[t], p) for t, p in toy(path).items()}, 0.0, 0.0)


def lookups() -> Lookups:
    async def fetch(ids: list[int]) -> Summary:
        return summary(tuple(ids))
    return Lookups(fetch)


def brute_force(max_tokens: int) -> dict[str, float]:
    """Every path to max_tokens, the slow way."""
    out: dict[str, float] = {}

    def walk(path: tuple[int, ...], text: str, p: float) -> None:
        for t, q in toy(path).items():
            tok = VOCAB[t]
            if "\n" in tok:
                out[text] = out.get(text, 0.0) + p * q
            elif len(path) + 1 >= max_tokens:
                out[text + tok + " (cut off)"] = out.get(text + tok + " (cut off)", 0.0) + p * q
            else:
                walk(path + (t,), text + tok, p * q)
    walk((), "", 1.0)
    return out


async def test_with_a_tiny_epsilon_it_matches_brute_force():
    found = await exact.enumerate_answers(lookups(), epsilon=1e-12, max_tokens=8)
    got: dict[str, float] = {}
    for leaf in found.leaves:
        key = leaf.text + (" (cut off)" if leaf.finish == "length" else "")
        got[key] = got.get(key, 0.0) + leaf.p
    want = brute_force(8)
    assert got.keys() == want.keys()
    for k in want:
        assert got[k] == pytest.approx(want[k])
    assert found.pruned == pytest.approx(0.0, abs=1e-12)


async def test_explored_and_pruned_mass_add_to_one_and_leaves_are_exact():
    found = await exact.enumerate_answers(lookups(), epsilon=0.05, max_tokens=8)
    assert found.explored + found.pruned == pytest.approx(1.0)
    canberra = sum(x.p for x in found.leaves if x.text == " Canberra")
    assert canberra == pytest.approx(0.6 * 0.95 * 0.9)
    # Everything enumerated is at least epsilon; nothing at least epsilon was pruned unexpanded
    assert all(x.p >= 0.05 for x in found.leaves)
    assert all(s.pruned < 0.05 or s.kept for s in found.stubs)


async def test_the_token_cap_counts_a_whole_subtree_as_cut_off():
    found = await exact.enumerate_answers(lookups(), epsilon=1e-9, max_tokens=2)
    assert found.cut_off == pytest.approx(sum(p for k, p in brute_force(2).items() if "(cut off)" in k))
    assert found.explored + found.pruned == pytest.approx(1.0)


class ToySampler:
    """sample_after on the toy model: forbidden tokens are never drawn."""

    def __init__(self, seed: int = 0) -> None:
        self.rng = random.Random(seed)

    async def sample_after(self, request, continuation, max_tokens, forbid=None, stop=None):
        path, ids, text = tuple(continuation), [], ""
        for _ in range(max_tokens):
            dist = {t: p for t, p in toy(path).items() if t not in set(forbid or [])}
            forbid = None  # only the first token is restricted (as the service asks)
            t = self.rng.choices(list(dist), weights=list(dist.values()))[0]
            tok = VOCAB[t]
            ids.append(t)
            if stop and "\n" in tok:
                return {"ids": ids, "text": text + tok.split("\n")[0], "stop_type": "word"}
            text += tok
            path += (t,)
        return {"ids": ids, "text": text, "stop_type": "limit"}


async def test_tail_rollouts_estimate_the_pruned_mass_without_bias():
    found = await exact.enumerate_answers(lookups(), epsilon=0.2, max_tokens=8)
    tails = await exact.rollouts(ToySampler(), None, found.stubs, n=4000, max_tokens=8, seed=1)
    assert sum(r.weight for r in tails) == pytest.approx(found.pruned)
    # Exact part plus tail estimate recovers the true distribution
    est: dict[str, float] = {}
    for leaf in found.leaves:
        est[leaf.text] = est.get(leaf.text, 0.0) + leaf.p
    for r in tails:
        est[r.text] = est.get(r.text, 0.0) + r.weight
    truth = brute_force(8)
    for answer in (" Canberra", " Sydney"):
        assert est[answer] == pytest.approx(truth[answer], abs=0.02)


def test_menu_picks_are_kept_to_the_menu():
    menu = ["an AI or model", "a person", "something else"]
    assert judging.menu_label("A person", menu) == "a person"
    assert judging.menu_label("other: a ghost", menu) == "other: a ghost"
    assert judging.menu_label("a ghost", menu) == "other: a ghost"
    assert judging.menu_label("No answer.", menu) == "no answer"


def test_the_menu_request_keeps_the_context_whole():
    ctx = "Other: hi\n\nMind: hello\n\nOther: what are you?\n\nMind:"
    req = judging.menu_request(ctx, [" A mind", " A person"], ["a person"])
    assert "- a person" in req and req.endswith("2. ...hello\n\nOther: what are you?\n\nMind: A person")


async def test_grouping_puts_every_label_somewhere_and_never_merges_no_answer(monkeypatch):
    async def fake_ask(llama, judge, messages, schema, max_tokens):
        return {"groups": [{"name": "large", "labels": ["big", "large", "no answer", "huge"]},
                           {"name": "small", "labels": ["small"]}]}
    monkeypatch.setattr(judging, "ask_json", fake_ask)
    masses = {"big": 0.3, "large": 0.4, "small": 0.2, "no answer": 0.05, "tiny": 0.05}
    out = await judging.bucket_answers(None, {"provider": "x", "model": "y"}, "ctx", masses)
    assert out["buckets"] == {"big": "large", "large": "large", "small": "small",
                              "no answer": "no answer", "tiny": "tiny"}


# -- Through the service --

class FakeLlama(LlamaCppProvider):
    """A llama.cpp provider whose lookups and samples are the toy model's."""
    supported_modes = ["completion"]

    def __init__(self) -> None:
        super().__init__(base_url="http://nowhere")
        self.sampler = ToySampler()
        self.leases: list[tuple[str, str]] = []

    async def sample_after(self, *a, **k):
        return await self.sampler.sample_after(*a, **k)

    async def lease_gpu(self, name, size, ttl=180):
        self.leases.append(("lease", name))

    async def release_gpu(self, name):
        self.leases.append(("release", name))


@pytest.fixture
async def setup(db: Database, monkeypatch):
    rhizomes = RhizomeService(db)
    store, projector = EventStore(db), StateProjector(db)
    gen = GenerationService(rhizomes, store, projector)
    probes = ProbeService(rhizomes, gen, store, projector)
    probes.store = store  # for reading back what was recorded
    rid = (await rhizomes.create_rhizome(CreateRhizomeRequest(
        title="t", default_provider="llamacpp", default_model="m",
        metadata={"generation_mode": "completion", "prompt_template": "transcript",
                  "speaker_name": "Other", "model_name": "Mind"},
    ))).rhizome_id
    uid = (await rhizomes.create_node(rid, CreateNodeRequest(
        content="What is the capital of Australia?"))).node_id

    async def toy_lookups(llama, request):
        return lookups()
    monkeypatch.setattr(exact, "answer_lookups", toy_lookups)

    async def fake_judge(self, record, spec):
        return None
    monkeypatch.setattr(ProbeService, "_judge_exact", fake_judge)
    return rhizomes, probes, rid, uid


async def test_an_exact_probe_records_exact_masses_and_its_settings(setup):
    rhizomes, probes, rid, uid = setup
    llama = FakeLlama()
    probe = await probes.run_exact(rid, uid, llama, "m", epsilon=0.05, max_tokens=8, tail=50)
    ex = probe["exact"]
    assert probe["mode"] == "exact" and probe["samples"] == []
    assert ex["settings"]["epsilon"] == 0.05 and ex["settings"]["tail"] == 50
    assert ex["explored"] + ex["pruned"] == pytest.approx(1.0)
    leaves = [i for i in ex["items"] if i["kind"] == "leaf"]
    tails = [i for i in ex["items"] if i["kind"] == "tail"]
    assert sum(i["mass"] for i in tails) == pytest.approx(ex["pruned"])
    # A transcript turn is stored as the turn's text
    assert any(i["text"] == "Canberra" for i in leaves)
    assert probe["prompt_text"].endswith("Mind:")


async def test_continuing_from_an_enumerated_answer_says_it_was_enumerated(setup):
    rhizomes, probes, rid, uid = setup
    probe = await probes.run_exact(rid, uid, FakeLlama(), "m", epsilon=0.05, max_tokens=8, tail=10)
    i = next(k for k, it in enumerate(probe["exact"]["items"]) if it["text"] == "Canberra")
    node = await probes.continue_from(rid, probe["probe_id"], i)
    assert node.content == "Canberra"
    created = [e for e in await probes.store.get_events(rid) if e.event_type == "NodeCreated"][-1]
    assert created.payload["from_probe"] == probe["probe_id"]
    raw = created.payload["raw_response"]
    assert raw["enumerated"] is True and raw["probability"] == pytest.approx(probe["exact"]["items"][i]["mass"])
    assert created.payload["logprobs"] is None  # not sampled: no sampling record to show


async def test_exact_probes_need_llama_cpp(setup):
    from qivis.errors import InvalidRequestError
    from tests.interlude.test_probes import Sampler
    rhizomes, probes, rid, uid = setup
    with pytest.raises(InvalidRequestError):
        await probes.run_exact(rid, uid, Sampler(), "m")

