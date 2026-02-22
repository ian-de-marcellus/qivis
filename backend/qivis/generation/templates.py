"""Prompt templates for completion mode.

Each template renders a list of chat messages + optional system prompt
into a single text string suitable for a text completion endpoint.
Returns (prompt_text, stop_tokens).
"""

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


TEMPLATES: dict[str, Callable[..., tuple[str, list[str]]]] = {
    "raw": render_raw,
    "chatml": render_chatml,
    "alpaca": render_alpaca,
    "llama3": render_llama3,
}


def render_prompt(
    template_name: str,
    messages: list[dict[str, str]],
    system_prompt: str | None,
) -> tuple[str, list[str]]:
    """Render messages using the named template. Falls back to raw if unknown."""
    template_fn = TEMPLATES.get(template_name, render_raw)
    return template_fn(messages, system_prompt)
