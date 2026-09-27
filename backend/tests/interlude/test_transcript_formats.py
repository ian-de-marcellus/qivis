"""Base-model formats: a named transcript, and a plain continuous document."""

from qivis.generation.templates import render_prompt

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
