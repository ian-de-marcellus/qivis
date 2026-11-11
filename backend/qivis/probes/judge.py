"""Naming the answer each sample gives, with a small local instruct model
(or, for exact probes, any model a provider serves, e.g. a frontier model).

The grouping is an interpretation, not the model's record: a judge's
labels are stored with the judge that made them and exactly what it was
asked, so a probe can be judged again (by another judge) and compared.

Exact probes (qivis.probes.exact) judge many more texts, so in batches, and
add a second step: one call over all the distinct labels, grouping those
that give the same answer ("large" and "big"), since labelling each batch
alone can't keep spellings consistent. With a menu of answers, the judge
picks from it instead, and no grouping is needed.
"""

import json
import re
from typing import Any

from qivis.models import SamplingParams
from qivis.providers.base import GenerationRequest
from qivis.providers.llamacpp import LlamaCppProvider
from qivis.providers.registry import get_provider

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


def numbered(context: str, texts: list[str]) -> str:
    """The continuations, numbered, each joined to the text's last few words, so
    one that finishes a word ("A" + "iden") reads whole ("...his name is Aiden")."""
    end = context[-40:]
    if len(context) > 40 and " " in end:
        end = end[end.index(" ") + 1:]  # start at a word
    lead = "..." + end if context.strip() else ""
    return "\n".join(f"{i + 1}. {(lead + t).strip()}" for i, t in enumerate(texts))


def judge_request(context: str, texts: list[str]) -> str:
    tail = context[-TAIL_CHARS:]
    listed = numbered(context, texts)
    return (
        "The text so far ends like this:\n<<<\n" + tail + "\n>>>\n\n"
        f"Below are {len(texts)} possible continuations, numbered. For each, name the "
        "specific answer it gives to what the text leads up to (the name, the thing, the "
        "choice itself, not its category), in one to four lowercase words, in its plainest "
        "form, without hedges or intensity: \"probably X\", \"X, i think\", \"definitely "
        "X!\" and \"my X\" are all \"x\". Each continuation is shown after the text's "
        "last few words. Give continuations that give the same answer exactly "
        "the same label. If a continuation gives no answer, label it \"no answer\".\n\n"
        + listed
    )


def normalize(label: str) -> str:
    """One spelling per answer: lowercase, no surrounding punctuation or extra spaces."""
    # A small judge sometimes echoes the item number ("3: aiden")
    label = re.sub(r"^\s*\d+\s*[:.)]\s+", "", label)
    label = label.replace("_", " ")  # a judge sometimes names a group like a variable
    return re.sub(r"\s+", " ", label.strip().strip(".,!?;:\"'").lower()) or "no answer"


def merge_forms(labels: list[str]) -> list[str]:
    """Normalized labels, with plural and singular of the same answer made one
    ("dogs" and "dog"): the label used more often wins, the shorter on a tie."""
    normal = [normalize(label) for label in labels]
    counts: dict[str, int] = {}
    for label in normal:
        counts[label] = counts.get(label, 0) + 1

    def twin(label: str) -> str | None:
        for other in (label[:-1], label[:-2], label + "s", label + "es"):
            if other != label and other in counts:
                return other
        return None

    merged = {}
    for label in counts:
        other = twin(label) if label.endswith("s") else None
        if other is None and not label.endswith("s"):
            other = twin(label)
        if other is None:
            continue
        keep = max((label, other), key=lambda x: (counts[x], -len(x)))
        merged[label if keep == other else other] = keep
    return [merged.get(label, label) for label in normal]


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
    raw = [str(a) for a in reply["answers"]][: len(texts)]
    return {"model": judge, "messages": messages, "raw": raw, "answers": merge_forms(raw)}


# -- Exact probes: batched labels, a menu, grouping, any judge --

BATCH = 30  # texts per labelling call

MENU_INSTRUCTIONS = (
    "You read possible continuations of a text and say which of the given answers each "
    "one gives. Reply in JSON."
)

BUCKET_INSTRUCTIONS = (
    "You group answer labels that give the same answer. Reply in JSON."
)


def menu_request(context: str, texts: list[str], menu: list[str]) -> str:
    """As judge_request, but each continuation is matched to one of the menu's answers."""
    options = "\n".join(f"- {m}" for m in menu)
    return (
        "The text so far ends like this:\n<<<\n" + context[-TAIL_CHARS:] + "\n>>>\n\n"
        f"Below are {len(texts)} possible continuations, numbered. For each, say which of "
        "these answers it gives, copying the answer exactly:\n" + options + "\n\n"
        "If it gives an answer that isn't listed, write \"other: \" and the answer in one "
        "to four lowercase words. If it gives no answer, write \"no answer\". Each "
        "continuation is shown after the text's last few words.\n\n" + numbered(context, texts)
    )


def menu_label(raw: str, menu: list[str]) -> str:
    """A judge's pick, as one of the menu's answers, "other: ..." or "no answer"."""
    label = normalize(raw)
    for m in menu:
        if label == normalize(m):
            return normalize(m)
    if label.startswith("other"):
        rest = label[5:].lstrip(" :-")
        return f"other: {rest}" if rest else "other"
    return label if label == "no answer" else f"other: {label}"


def bucket_request(context: str, labels: list[str], masses: dict[str, float],
                   grain: str | None) -> str:
    listed = "\n".join(f"- {label} ({masses[label]:.1%})" for label in labels)
    return (
        "A model was asked to continue this text:\n<<<\n" + context[-TAIL_CHARS:] + "\n>>>\n\n"
        "These are the answers its continuations give, as short labels (with how much of "
        "its probability each carries):\n" + listed + "\n\n"
        "Group the labels that give the same answer. "
        + (f"How fine to make the groups: {grain}. " if grain else
           "Different wordings, synonyms and intensities of the same answer (\"big\", "
           "\"large\", \"huge\") are one group; answers that differ in substance stay apart, "
           "and so does a negation (\"anything but x\" is not \"x\"). ")
        + "Never group labels just because they are all wrong, unusual or not answers: two "
        "different wrong answers are two groups, and a question back (\"why do you ask?\") "
        "is not the same as \"i don't know\". A label that matches nothing else is a group of "
        "its own. Name each group with its plainest label, in plain lowercase words. Every "
        "label goes in exactly one group, copied exactly."
    )


async def resolve_judge(llama: LlamaCppProvider | None, spec: dict | None) -> dict | None:
    """The judge to use: the one asked for ({"provider", "model"}), else the best local one."""
    if spec and spec.get("provider") and spec.get("model"):
        return {"provider": spec["provider"], "model": spec["model"]}
    name = await pick_judge(llama) if llama is not None else None
    return {"provider": "llamacpp", "model": name} if name else None


def _json_object(text: str) -> Any:
    """The JSON object in a reply (a frontier model may wrap it in a code fence)."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"No JSON object in the judge's reply: {text[:200]!r}")
    return json.loads(text[start:end + 1])


async def ask_json(llama: LlamaCppProvider | None, judge: dict, messages: list[dict],
                   schema: dict, max_tokens: int) -> Any:
    """A JSON reply from the judge: a local one constrained to the schema, or any
    provider's model asked for the schema in words."""
    if judge["provider"] == "llamacpp":
        assert llama is not None
        return await llama.chat_json(judge["model"], messages, schema, max_tokens=max_tokens)
    provider = get_provider(judge["provider"])
    system = next((m["content"] for m in messages if m["role"] == "system"), None)
    turns = [dict(m) for m in messages if m["role"] != "system"]
    turns[-1]["content"] += (
        "\n\nReply with only a JSON object matching this JSON schema, nothing else:\n"
        + json.dumps(schema)
    )
    result = await provider.generate(GenerationRequest(
        model=judge["model"], messages=turns, system_prompt=system,
        sampling_params=SamplingParams(max_tokens=max_tokens, logprobs=False, top_logprobs=None),
    ))
    return _json_object(result.content)


async def judge_answers(
    llama: LlamaCppProvider | None, judge: dict, context: str, texts: list[str],
    menu: list[str] | None = None,
) -> dict[str, Any]:
    """Each text's answer, labelled in batches (from the menu, if there is one)."""
    local = judge["provider"] == "llamacpp"
    raw: list[str] = []
    first: list[dict] | None = None
    for i in range(0, len(texts), BATCH):
        part = texts[i:i + BATCH]
        ask = menu_request(context, part, menu) if menu else judge_request(context, part)
        messages = [
            {"role": "system", "content": MENU_INSTRUCTIONS if menu else INSTRUCTIONS},
            {"role": "user", "content": ask + ("\n\n/no_think" if local else "")},
        ]
        schema = {
            "type": "object",
            "properties": {"answers": {
                "type": "array", "items": {"type": "string"},
                "minItems": len(part), "maxItems": len(part),
            }},
            "required": ["answers"],
        }
        reply = await ask_json(llama, judge, messages, schema,
                               max_tokens=(24 if local else 48) * len(part) + 256)
        got = [str(a) for a in reply["answers"]][: len(part)]
        raw += got + ["no answer"] * (len(part) - len(got))
        first = first or messages
    answers = [menu_label(r, menu) for r in raw] if menu else merge_forms(raw)
    return {**judge, "messages": first, "batches": -(-len(texts) // BATCH), "raw": raw,
            "answers": answers, "menu": menu}


async def bucket_answers(
    llama: LlamaCppProvider | None, judge: dict, context: str, masses: dict[str, float],
    grain: str | None = None,
) -> dict[str, Any]:
    """One call over the distinct labels: which give the same answer. Returns
    {"buckets": {label: group}}, "no answer" always its own group."""
    labels = sorted((label for label in masses if label != "no answer"), key=lambda x: -masses[x])
    buckets = {label: label for label in masses}
    if len(labels) <= 1:
        return {"provider": None, "model": None, "messages": None, "raw": None,
                "buckets": buckets, "grain": grain}
    messages = [
        {"role": "system", "content": BUCKET_INSTRUCTIONS},
        {"role": "user", "content": bucket_request(context, labels, masses, grain)
         + ("\n\n/no_think" if judge["provider"] == "llamacpp" else "")},
    ]
    schema = {
        "type": "object",
        "properties": {"groups": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"},
                           "labels": {"type": "array", "items": {"type": "string"}}},
            "required": ["name", "labels"],
        }}},
        "required": ["groups"],
    }
    local = judge["provider"] == "llamacpp"
    reply = await ask_json(llama, judge, messages, schema,
                           max_tokens=(16 if local else 48) * len(labels) + 1024)
    placed: set[str] = set()
    for group in reply.get("groups", []):
        name = normalize(str(group.get("name", ""))) or "no answer"
        for label in group.get("labels", []):
            label = normalize(str(label))
            if label in buckets and label not in placed and label != "no answer":
                buckets[label] = name
                placed.add(label)
    return {**judge, "messages": messages, "raw": reply, "buckets": buckets, "grain": grain}
