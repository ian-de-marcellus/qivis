"""A text ending in a space: the space is healed, not left as a trap.

Words carry their own leading space as tokens (" John"), so a prompt ending
in a space leaves the model mostly digits and fragments: OLMo 32B after
"His name is " put 38% of its top-25 mass on '3', '1', '4'... With the
space dropped and the next token required to start with one (a grammar,
recorded in the node's sampling params), it says names.
"""

from collections.abc import AsyncIterator

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.service import GenerationService, Target
from qivis.generation.templates import HEALED_SPACE, heal_trailing_space
from qivis.providers.base import GenerationRequest, GenerationResult, LLMProvider, StreamChunk
from qivis.rhizomes.schemas import CreateNodeRequest, CreateRhizomeRequest
from qivis.rhizomes.service import RhizomeService
from qivis.steering.service import starting_a_word


class Base(LLMProvider):
    supported_modes = ["completion"]

    def __init__(self, grammar: bool) -> None:
        self.supports_grammar = grammar

    @property
    def name(self) -> str:
        return "base"

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(content=" Otto.", model="m")

    async def generate_stream(self, request) -> AsyncIterator[StreamChunk]:
        raise AssertionError("not streamed")
        yield


async def _prepared(db: Database, text: str, grammar: bool):
    service = RhizomeService(db)
    gen = GenerationService(service, EventStore(db), StateProjector(db))
    rid = (await service.create_rhizome(CreateRhizomeRequest(
        title="t", default_provider="base", default_model="m",
        metadata={"generation_mode": "completion", "prompt_template": "document"},
    ))).rhizome_id
    uid = (await service.create_node(rid, CreateNodeRequest(content=text))).node_id
    [p] = await gen.prepare(await gen.load(rid, uid), [Target(provider=Base(grammar), model="m")])
    return gen, p


async def test_a_trailing_space_is_healed(db: Database):
    gen, p = await _prepared(db, "His name is ", grammar=True)
    assert p.request.prompt_text == "His name is"
    assert p.request.sampling_params.grammar == HEALED_SPACE
    node = await gen.complete(p)
    assert node.content == " Otto."
    assert node.prompt_text == "His name is"  # what the model actually saw
    assert node.sampling_params["grammar"] == HEALED_SPACE  # and what constrained it


async def test_without_grammar_support_the_prompt_is_left_alone(db: Database):
    _, p = await _prepared(db, "His name is ", grammar=False)
    assert p.request.prompt_text == "His name is " and p.request.sampling_params.grammar is None


async def test_text_without_a_trailing_space_is_unchanged(db: Database):
    _, p = await _prepared(db, "His name is", grammar=True)
    assert p.request.prompt_text == "His name is" and p.request.sampling_params.grammar is None


def test_only_trailing_spaces_are_healed():
    assert heal_trailing_space("name is  ") == "name is"
    assert heal_trailing_space("a list:\n") is None
    assert heal_trailing_space("   ") is None


def test_steering_shows_word_starts_given_a_healed_space():
    shown = starting_a_word([
        {"id": 1, "token": "3", "prob": 0.4},
        {"id": 2, "token": " John", "prob": 0.3},
        {"id": 3, "token": " ", "prob": 0.2},
        {"id": 4, "token": " A", "prob": 0.1},
    ])
    assert [c["token"] for c in shown] == [" John", " A"]
    assert [round(c["prob"], 2) for c in shown] == [0.75, 0.25]  # conditional
    assert [c["raw_prob"] for c in shown] == [0.3, 0.1]  # the model's own
