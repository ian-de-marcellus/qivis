"""Base-model formats: a named transcript, and a plain continuous document."""

from qivis.generation.templates import render_prompt, transcript_turn_end, transcript_undecided

MSGS = [
    {"role": "user", "content": "hi, how are you?"},
    {"role": "assistant", "content": "Good! A little sleepy."},
    {"role": "user", "content": "same "},
]


def test_transcript_names_turns_and_ends_on_the_model():
    text, stops = render_prompt(
        "transcript", MSGS, "A conversation between Ada and Sun.", {"user": "Ada", "assistant": "Sun"},
    )
    assert text == (
        "A conversation between Ada and Sun.\n\n"
        "Ada: hi, how are you?\n\n"
        "Sun: Good! A little sleepy.\n\n"
        "Ada: same\n\n"
        "Sun:"  # no trailing space: the model's first word brings its own
    )
    assert stops == ["\nAda:"]


def test_transcript_defaults():
    text, stops = render_prompt("transcript", MSGS[:1], None)
    assert text == "Person: hi, how are you?\n\nSun:" and stops == ["\nPerson:"]


def test_document_joins_exactly():
    parts = [{"role": "user", "content": "Once upon a"}, {"role": "assistant", "content": " time, there"}]
    text, stops = render_prompt("document", parts, "Chapter 1\n\n")
    assert text == "Chapter 1\n\nOnce upon a time, there" and stops == []


def test_turn_ends_at_any_new_speaker_line():
    """A base model drifts: its own name again, a third speaker, another case."""
    assert transcript_turn_end(" hi!\n\nbetsy: fine!") == 4
    assert transcript_turn_end(" hi!\nmian: me too") == 4
    assert transcript_turn_end(" sure\n\nIan Smith: ok") == 5
    assert transcript_turn_end(" and then\nbetsy:") == 9  # the colon may be the last thing so far


def test_turn_goes_on_through_lines_that_are_not_speakers():
    assert transcript_turn_end(" at\n10:30 we left") is None
    assert transcript_turn_end(" see\nhttp://example.com") is None
    assert transcript_turn_end(" a list:\n- one\n- two") is None
    assert transcript_turn_end(" one line, no break") is None


async def test_streamed_reply_stops_at_a_new_speaker_line(db):
    """The model is cut off as soon as it starts another speaker's line."""
    from qivis.events.projector import StateProjector
    from qivis.events.store import EventStore
    from qivis.generation.service import GenerationService, Target
    from qivis.models import LogprobData, TokenLogprob
    from qivis.providers.base import GenerationResult, LLMProvider, StreamChunk
    from qivis.rhizomes.schemas import CreateNodeRequest, CreateRhizomeRequest
    from qivis.rhizomes.service import RhizomeService

    class Drifting(LLMProvider):
        supported_modes = ["completion"]
        closed = False
        said: list[str] = []

        @property
        def name(self):
            return "drifting"

        async def generate(self, request):
            raise AssertionError("streamed only")

        async def generate_stream(self, request):
            try:
                for t in [" hi", "!", "\n\n", "bet", "sy", ":", " fine", "!"]:
                    self.said.append(t)
                    yield StreamChunk(type="text_delta", text=t, logprobs=LogprobData(
                        tokens=[TokenLogprob(token=t, logprob=-0.1, linear_prob=0.9, top_alternatives=[])],
                        provider_format="llamacpp", top_k_available=5,
                    ))
                yield StreamChunk(type="message_stop", is_final=True, result=GenerationResult(
                    content="".join(self.said), model="m", finish_reason="length",
                ))
            finally:
                self.closed = True

    service = RhizomeService(db)
    gen = GenerationService(service, EventStore(db), StateProjector(db))
    rid = (await service.create_rhizome(CreateRhizomeRequest(
        title="t", default_provider="drifting", default_model="m",
        metadata={"generation_mode": "completion", "prompt_template": "transcript",
                  "speaker_name": "ian", "model_name": "betsy"},
    ))).rhizome_id
    uid = (await service.create_node(rid, CreateNodeRequest(content="hi betsy!"))).node_id
    model = Drifting()
    [p] = await gen.prepare(await gen.load(rid, uid), [Target(provider=model, model="m")])
    chunks = [c async for c in gen.stream(p)]

    shown = "".join(c.text for c in chunks if c.type == "text_delta")
    assert "betsy" not in shown and " fine" not in model.said  # stopped before going on
    assert model.closed
    [node] = [n for n in (await service.get_rhizome(rid)).nodes if n.role == "assistant"]
    assert node.content == "hi!" and node.finish_reason == "stop"
    # The record keeps the tokens it said, the start of the new line included
    assert [t["token"] for t in node.logprobs["tokens"]][-1] == ":"


def test_a_line_that_may_become_a_speaker_waits():
    assert transcript_undecided(" hi!\n\nbet") == 4  # could be "betsy:"
    assert transcript_undecided(" hi!\n") == 4
    assert transcript_undecided(" hi there") == 9  # no new line: all of it
    assert transcript_undecided(" hi!\n- a list item") == 18  # can't be a name any more
