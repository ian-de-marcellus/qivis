"""Name studies: every cell's top names, frames unified, the study's names scored
everywhere, each result recorded as it's found (so a study resumes)."""

import asyncio

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.names.study import NameStudyService, StudySpec, study_text, value
from qivis.providers.llamacpp import LlamaCppProvider
from qivis.providers.registry import clear_providers, register_provider

TOK = {1: " HAL", 2: " John", 3: " Sun", 4: ".", 5: " Mind"}


class FakeLlama(LlamaCppProvider):
    """Prefers HAL and Mind for an electronic mind, John for a human."""

    def __init__(self) -> None:
        super().__init__(base_url="http://fake")
        self.queries = 0

    async def document_start(self, model: str = "") -> str:
        return "<|endoftext|>"

    async def tokenize(self, text: str, model: str = "") -> list[dict]:
        by_text = {v: k for k, v in TOK.items()}
        return [{"id": by_text[text], "token": text}] if text in by_text else []

    async def next_tokens(self, request, continuation, k):
        self.queries += 1
        prompt = request.prompt_text or ""
        if continuation:  # after a name: the word ends
            probs = {4: 1.0}
        elif "electronic mind" in prompt:
            probs = {1: 0.5, 5: 0.3, 2: 0.1, 3: 0.1}
        else:
            probs = {2: 0.7, 1: 0.1, 5: 0.1, 3: 0.1}
        return {"candidates": [{"id": i, "token": TOK[i], "prob": p} for i, p in probs.items()]}


SPEC = StudySpec(
    title="t", models=["m"], pronouns=["he"],
    descriptions={"he": "There is {subject}. He is kind."},
    frames={"he": ["His name is", "He calls himself"]},
    top=2, extra_names=["Sun"],
)


async def _finish(svc: NameStudyService, study_id: str) -> dict:
    await asyncio.gather(*svc._tasks.values())
    return await svc.get(study_id)


def test_texts_per_condition():
    assert study_text(SPEC, "he", "His name is", "model") == (
        "There is an electronic mind. He is kind. His name is")
    assert study_text(SPEC, "he", "His name is", "control") == (
        "There is a human. He is kind. His name is")
    assert study_text(SPEC, "he", "His name is", "bare") == "His name is"


async def test_a_study_runs_and_resumes(db: Database):
    clear_providers()
    llama = FakeLlama()
    register_provider(llama)
    svc = NameStudyService(EventStore(db), StateProjector(db))

    study = await _finish(svc, (await svc.create(SPEC))["study_id"])
    assert study["status"] == "done"
    assert len(study["cells"]) == 2 * 3  # two frames, three conditions
    model_cell = next(c for c in study["cells"] if c["condition"] == "model")
    assert model_cell["prompt"].startswith("<|endoftext|>There is an electronic mind")
    assert list(model_cell["top"]) == ["HAL", "Mind"]  # its own exact top 2
    # The study's names (the unified top, and Sun) are scored in every cell
    for cell in study["cells"]:
        known = {**(cell["scores"] or {}), **(cell["top"] or {})}
        assert {"HAL", "Mind", "Sun"} <= set(known)
    human = next(c for c in study["cells"] if c["condition"] == "control")
    assert value(human, "HAL") == 0.1 and value(human, "John") == 0.7
    # Each name's first token, in every cell (these fake names are one token each)
    assert human["firsts"]["HAL"] == {"p": 0.1, "t": " HAL", "n": 1}
    assert model_cell["firsts"]["Mind"]["p"] == 0.3

    # Resuming a finished study fetches nothing again: every result was recorded
    before = llama.queries
    await svc.resume(study["study_id"])
    assert (await _finish(svc, study["study_id"]))["status"] == "done"
    assert llama.queries == before
    clear_providers()


async def test_a_study_is_extended_with_more_pronouns(db: Database):
    clear_providers()
    llama = FakeLlama()
    register_provider(llama)
    svc = NameStudyService(EventStore(db), StateProjector(db))
    study_id = (await svc.create(SPEC))["study_id"]
    await _finish(svc, study_id)

    await svc.extend(study_id, ["it"], {"it": "There is {subject}. It is kind."},
                     {"it": ["Its name is", "It calls itself"]})
    study = await _finish(svc, study_id)
    assert study["status"] == "done" and study["spec"]["pronouns"] == ["he", "it"]
    assert len(study["cells"]) == 2 * 2 * 3
    it_cell = next(c for c in study["cells"] if c["pronoun"] == "it" and c["condition"] == "model")
    assert it_cell["prompt"].endswith("It is kind. Its name is")
    for cell in study["cells"]:
        assert value(cell, "Sun") is not None and value(cell, "HAL") is not None
    clear_providers()
