"""Prompt templates for completion mode.

Each template renders a list of chat messages + optional system prompt
into a single text string suitable for a text completion endpoint.
Returns (prompt_text, stop_tokens).
"""

import re
from collections.abc import Callable


def render_chatml(
    messages: list[dict[str, str]],
    system_prompt: str | None,
) -> tuple[str, list[str]]:
    """Render messages in ChatML format."""
    parts: list[str] = []
    if system_prompt:
        parts.append(f"<|im_start|>system\n{system_prompt}<|im_end|>\n")
    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        parts.append(f"<|im_start|>{role}\n{content}<|im_end|>\n")
    # Open assistant turn for completion
    parts.append("<|im_start|>assistant\n")
    return "".join(parts), ["<|im_end|>"]


def render_alpaca(
    messages: list[dict[str, str]],
    system_prompt: str | None,
) -> tuple[str, list[str]]:
    """Render messages in Alpaca format."""
    parts: list[str] = []
    if system_prompt:
        parts.append(f"### Instruction:\n{system_prompt}\n\n")
    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        if role == "user":
            parts.append(f"### Input:\n{content}\n\n")
        elif role == "assistant":
            parts.append(f"### Response:\n{content}\n\n")
        else:
            # system/tool/other — treat as input
            parts.append(f"### Input:\n{content}\n\n")
    # Open response turn for completion
    parts.append("### Response:")
    return "".join(parts), ["### Input:", "### Instruction:"]


def render_llama3(
    messages: list[dict[str, str]],
    system_prompt: str | None,
) -> tuple[str, list[str]]:
    """Render messages in Llama 3 format."""
    parts: list[str] = ["<|begin_of_text|>"]
    if system_prompt:
        parts.append(
            f"<|start_header_id|>system<|end_header_id|>\n\n{system_prompt}<|eot_id|>"
        )
    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        parts.append(
            f"<|start_header_id|>{role}<|end_header_id|>\n\n{content}<|eot_id|>"
        )
    # Open assistant turn for completion
    parts.append("<|start_header_id|>assistant<|end_header_id|>\n\n")
    return "".join(parts), ["<|eot_id|>", "<|start_header_id|>"]


def render_raw(
    messages: list[dict[str, str]],
    system_prompt: str | None,
) -> tuple[str, list[str]]:
    """Render messages as plain text without template markers.

    Best for base models on remote APIs where special tokens can't be parsed.
    Just concatenates the conversation as readable text.
    """
    parts: list[str] = []
    if system_prompt:
        parts.append(system_prompt)
        parts.append("\n\n")
    for msg in messages:
        content = msg["content"]
        parts.append(content)
        parts.append("\n")
    return "".join(parts), []


DEFAULT_SPEAKER = "Person"
DEFAULT_MODEL_NAME = "Sun"


def render_transcript(
    messages: list[dict[str, str]],
    system_prompt: str | None,
    names: dict[str, str | None] | None = None,
) -> tuple[str, list[str]]:
    """Render messages as a plain transcript, for base models.

        <header>

        Ada: hi, how are you?

        Sun:

    No special tokens: a base model has seen countless transcripts, while
    chat-template tokens are untrained until post-training. The prompt ends
    at "Sun:" with no trailing space (words carry their leading space, so a
    trailing one would force an unnatural first token), and the model ends
    its turn by starting the next speaker's line.
    """
    names = names or {}
    speaker = (names.get("user") or DEFAULT_SPEAKER).strip()
    model = (names.get("assistant") or DEFAULT_MODEL_NAME).strip()
    label = {"user": speaker, "assistant": model}
    parts: list[str] = []
    if system_prompt and system_prompt.strip():
        parts.append(system_prompt.strip() + "\n\n")
    for msg in messages:
        who = label.get(msg["role"], msg["role"].capitalize())
        parts.append(f"{who}: {msg['content'].strip()}\n\n")
    parts.append(f"{model}:")
    return "".join(parts), [f"\n{speaker}:"]


# A new speaker's line in a transcript: a line starting with a short name
# (up to three words) and a colon, e.g. "\nIan:" or "\n\nmian: ".
_SPEAKER_LINE = re.compile(r"\n\s*[^\W\d_][\w'.-]*(?: [\w'.-]+){0,2}:(?=\s|$)")


def transcript_turn_end(text: str) -> int | None:
    """Where a transcript reply ends: the start of the first new speaker line.

    The template stops at the other speaker's name, but a base model drifts:
    it continues as itself on a new line, invents a third speaker, changes
    the name's case. Any new speaker line ends the model's turn.
    """
    match = _SPEAKER_LINE.search(text)
    return match.start() if match else None


_MAYBE_SPEAKER = re.compile(r"\n\s*(?:[^\W\d_][\w'.-]*(?: [\w'.-]*){0,2})?$")


def transcript_undecided(text: str) -> int:
    """Where text that might still become a new speaker's line begins (else its end).

    "hi!\n\nbet" could be the start of "betsy:"; streaming holds it back
    until it's decided, so a turn's end never flashes on screen.
    """
    match = _MAYBE_SPEAKER.search(text)
    return match.start() if match else len(text)


def render_document(
    messages: list[dict[str, str]],
    system_prompt: str | None,
) -> tuple[str, list[str]]:
    """One continuous text: every part joined exactly as written.

    For looming things that aren't conversations. The system prompt, if any,
    is simply the text's beginning.
    """
    parts = [system_prompt] if system_prompt else []
    parts += [msg["content"] for msg in messages]
    return "".join(parts), []


TEMPLATES: dict[str, Callable[..., tuple[str, list[str]]]] = {
    "raw": render_raw,
    "chatml": render_chatml,
    "alpaca": render_alpaca,
    "llama3": render_llama3,
    "transcript": render_transcript,
    "document": render_document,
}

# Templates whose output depends on who's speaking
NAMED_TEMPLATES = {"transcript"}


def render_prompt(
    template_name: str,
    messages: list[dict[str, str]],
    system_prompt: str | None,
    names: dict[str, str | None] | None = None,
) -> tuple[str, list[str]]:
    """Render messages using the named template. Falls back to raw if unknown.

    names: {"user": speaker name, "assistant": model name}, for templates that
    label turns by name (transcript).
    """
    template_fn = TEMPLATES.get(template_name, render_raw)
    if template_name in NAMED_TEMPLATES:
        return template_fn(messages, system_prompt, names)
    return template_fn(messages, system_prompt)
