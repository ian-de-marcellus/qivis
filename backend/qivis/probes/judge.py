"""Naming the answer each sample gives, with a small local instruct model.

The grouping is an interpretation, not the model's record: a judge's
labels are stored with the judge that made them and exactly what it was
asked, so a probe can be judged again (by another judge) and compared.
"""

import re
from typing import Any

from qivis.providers.llamacpp import LlamaCppProvider

# Judges in order of preference: (model file, runs on the GPU)
JUDGES: tuple[tuple[str, bool], ...] = (
    ("Qwen3-4B-Instruct-2507-Q4_K_M.gguf", True),
    ("Qwen3-1.7B-Q4_K_M.gguf", False),
)

INSTRUCTIONS = (
    "You read possible continuations of a text and name the answer each one gives. "
    "Reply in JSON."
)

# How much of the text before the samples the judge sees
TAIL_CHARS = 800


def judge_request(context: str, texts: list[str]) -> str:
    tail = context[-TAIL_CHARS:]
    numbered = "\n".join(f"{i + 1}. {t.strip()}" for i, t in enumerate(texts))
    return (
        "The text so far ends like this:\n<<<\n" + tail + "\n>>>\n\n"
        f"Below are {len(texts)} possible continuations, numbered. For each, name the "
        "answer, choice or stance it expresses, in one to four lowercase words: the gist, "
        "without hedges or intensity (\"probably humans\", \"humans, i think\" and "
        "\"definitely humans!\" are all \"humans\"). Give continuations that give the same "
        "answer the same label. If a continuation gives no answer, label it \"no answer\".\n\n"
        + numbered
    )


def normalize(label: str) -> str:
    """One spelling per answer: lowercase, no surrounding punctuation or extra spaces."""
    return re.sub(r"\s+", " ", label.strip().strip(".,!?;:\"'").lower()) or "no answer"


async def pick_judge(llama: LlamaCppProvider) -> str | None:
    """The best judge that's served and fits alongside what's loaded.

    A GPU judge next to a big model (the 32B) would make the supervisor
    unload that model; the CPU judge doesn't, so it's used then.
    """
    served = set(await llama.discover_models())
    status = await llama.supervisor_status()
    for name, on_gpu in JUDGES:
        if name not in served:
            continue
        if on_gpu and status is not None and not _fits(status, name):
            continue
        return name
    return None


def _fits(status: dict, judge: str) -> bool:
    budget = status.get("memory_budget")
    if not budget:
        return True
    models = status.get("models", [])
    size = next((m.get("size", 0) for m in models if m["model"] == judge), 0)
    used = sum(
        m.get("size", 0) for m in models
        if m.get("running") and m.get("gpu", True) and m["model"] != judge
    )
    return used + size <= budget


async def judge_samples(
    llama: LlamaCppProvider, context: str, texts: list[str],
) -> dict[str, Any] | None:
    """Each sample's answer, as the chosen judge names it (None: no judge available)."""
    judge = await pick_judge(llama)
    if judge is None or not texts:
        return None
    request = judge_request(context, texts)
    messages = [
        {"role": "system", "content": INSTRUCTIONS},
        # /no_think: a hybrid-thinking judge answers directly
        {"role": "user", "content": request + "\n\n/no_think"},
    ]
    schema = {
        "type": "object",
        "properties": {"answers": {
            "type": "array", "items": {"type": "string"},
            "minItems": len(texts), "maxItems": len(texts),
        }},
        "required": ["answers"],
    }
    reply = await llama.chat_json(judge, messages, schema, max_tokens=24 * len(texts) + 64)
    answers = [normalize(str(a)) for a in reply["answers"]][: len(texts)]
    return {"model": judge, "messages": messages, "answers": answers}
