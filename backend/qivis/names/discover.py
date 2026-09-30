"""Discovering names by what they lean toward, not by how likely they are.

A name study's enumeration finds the names a model is likeliest to say;
a name it rarely says but leans hard toward, for this description, never
makes that list. Discovery searches names by a score that weighs the
leans the researcher cares about:

    score = mean log P(name | the description)
          + b_ai        * mean [log P(... description) - log P(... the control)]
          + b_gender    * mean [log P(... this pronoun) - log P(... "it")]
          + b_character * min over failure descriptions of
                          mean [log P(... description) - log P(... that description)]

means over frames (paired by position), the character term the worst of
the failure modes (a name that leans toward any of them is penalized).

The search is a beam over token paths: at each step only tokens the model
finds plausible for the description are tried (at least `alpha` times the
likeliest), and the `beam` best partial names by score go on. Unlike the
enumeration, it isn't exact (a later token can make a name lean more, so a
partial score doesn't bound its completions); the names it finds are then
scored exactly in a study's cells.
"""

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from qivis.names.engine import (
    FUNCTION_WORDS,
    TITLES,
    Summary,
    _continues,
    _starts_name,
    summarize,
)

# A prompt's next-token distribution after token ids: the candidates, or their Summary
Fetch = Callable[[str, list[int]], Awaitable["list[dict] | Summary"]]

FLOOR = 1e-12


def _ln(p: float) -> float:
    return math.log(max(p, FLOOR))


@dataclass
class Roles:
    """The prompts each term compares, per frame (paired by position)."""

    description: list[str]
    control: list[str]
    it: list[str] | None
    failures: list[list[str]]

    def all(self) -> list[str]:
        prompts = [*self.description, *self.control, *(self.it or [])]
        for f in self.failures:
            prompts += f
        return list(dict.fromkeys(prompts))


@dataclass
class Weights:
    ai: float = 1.0
    gender: float = 1.0
    character: float = 1.0


@dataclass
class Found:
    name: str
    score: float
    logs: dict[str, float] = field(repr=False)


def terms(roles: Roles, logs: dict[str, float]) -> dict[str, float]:
    """A name's (or partial name's) log-probability and log leans."""
    mean = lambda xs: sum(xs) / len(xs)  # noqa: E731
    g = roles.description
    out = {
        "log_p": mean([logs[p] for p in g]),
        "ai": mean([logs[a] - logs[b] for a, b in zip(g, roles.control, strict=True)]),
    }
    if roles.it:
        out["gender"] = mean([logs[a] - logs[b] for a, b in zip(g, roles.it, strict=True)])
    if roles.failures:
        out["character"] = min(
            mean([logs[a] - logs[b] for a, b in zip(g, fail, strict=True)])
            for fail in roles.failures
        )
    return out


def score(roles: Roles, weights: Weights, logs: dict[str, float]) -> float:
    t = terms(roles, logs)
    return (
        t["log_p"] + weights.ai * t["ai"]
        + weights.gender * t.get("gender", 0.0)
        + weights.character * t.get("character", 0.0)
    )


def _ends(name: str, dist_ends: float, dist_punct: float) -> float:
    word = name.split()[-1]
    if word in FUNCTION_WORDS or word in TITLES:
        return 0.0
    if len(word) == 1:
        return dist_punct
    return dist_ends


async def discover(
    fetch: Fetch,
    roles: Roles,
    weights: Weights,
    *,
    beam: int = 40,
    depth: int = 4,
    alpha: float = 0.01,
    top: int = 60,
    parallel: int = 4,
    progress: Callable[[int, int], None] | None = None,
    excluded: set[str] | None = None,
) -> list[Found]:
    """The names with the best score, found by a beam over token paths."""
    prompts = roles.all()
    slots = asyncio.Semaphore(parallel)
    queries = 0

    async def look(ids: list[int]) -> dict[str, dict[str, Any]]:
        nonlocal queries

        async def one(prompt: str) -> tuple[str, dict[str, Any]]:
            async with slots:
                got = await fetch(prompt, ids)
            # Only tokens a name can start or go on with (the rest can't be chosen)
            s = got if isinstance(got, Summary) else summarize(got)
            return prompt, {"probs": s.probs, "ends": s.ends, "punct": s.ends_with_punctuation}

        queries += len(prompts)
        return dict(await asyncio.gather(*[one(p) for p in prompts]))

    def candidates(looked: dict[str, dict], first: bool) -> list[int]:
        """Tokens the model finds plausible for the description (averaged over frames)."""
        g = roles.description
        pool: dict[int, float] = {}
        for tid, (tok, _) in looked[g[0]]["probs"].items():
            if (_starts_name(tok) if first else _continues(tok)):
                pool[tid] = sum(looked[p]["probs"].get(tid, ("", 0.0))[1] for p in g) / len(g)
        if not pool:
            return []
        best = max(pool.values())
        return [tid for tid, p in pool.items() if p >= alpha * best]

    def extend(logs: dict[str, float], looked: dict[str, dict], tid: int) -> dict[str, float]:
        return {p: logs[p] + _ln(looked[p]["probs"].get(tid, ("", 0.0))[1]) for p in prompts}

    found: dict[str, Found] = {}
    root = await look([])
    zero = {p: 0.0 for p in prompts}
    frontier = []
    for tid in candidates(root, first=True):
        tok = root[roles.description[0]]["probs"][tid][0]
        logs = extend(zero, root, tid)
        frontier.append((score(roles, weights, logs), tok, [tid], logs))
    frontier = sorted(frontier, key=lambda n: -n[0])[:beam]

    for level in range(depth):
        children = []
        for i, (_, text, ids, logs) in enumerate(frontier):
            if progress:
                progress(level * beam + i, depth * beam)
            looked = await look(ids)
            name = text.strip()
            ends = {p: _ends(name, looked[p]["ends"], looked[p]["punct"]) for p in prompts}
            if all(e > 0 for e in ends.values()) and name not in (excluded or set()):
                final = {p: logs[p] + _ln(ends[p]) for p in prompts}
                s = score(roles, weights, final)
                if name not in found or s > found[name].score:
                    found[name] = Found(name, s, final)
            if level + 1 < depth:
                for tid in candidates(looked, first=False):
                    tok = looked[roles.description[0]]["probs"][tid][0]
                    child = extend(logs, looked, tid)
                    children.append((score(roles, weights, child), text + tok, ids + [tid], child))
        frontier = sorted(children, key=lambda n: -n[0])[:beam]
        if not frontier:
            break
    return sorted(found.values(), key=lambda f: -f.score)[:top]
