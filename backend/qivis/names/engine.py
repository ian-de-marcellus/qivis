"""Exact name distributions: how likely a model is to give each name after a text.

A name is a capitalized word (" Aiden", " A" + "iden"), maybe with a title
before it ("Dr. Anderson"), ended by any token that doesn't continue the
word. Its probability is the product of its tokens' probabilities and the
probability that the word ends there, summed over the ways of spelling it
in tokens. The engine enumerates names best-first: a partial name's
probability bounds every name it could become, so once no partial beats
the top-th finished name, the top names are exact. No sampling: the same
model and text always give the same answer.

Rules for what counts (a name study records them with its results):
- Function words (articles, pronouns, conjunctions...) are not names.
- A single capital letter counts only before punctuation ("A.", "R,"): an
  initial or a one-letter name, not an article or pronoun ("A computer",
  "I am").
- A title ("Dr", "Mr", "Captain"...) is followed through to the name after it.
"""

import heapq
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

# Probability below which a token is not worth keeping from a distribution
FLOOR = 1e-10

FUNCTION_WORDS = frozenset("""
The An This That These Those It Its He She They We You His Her Hers Their Theirs Our Ours
Your Yours My Mine Me Him Them Us Who Whom Whose What Which When Where Why How Not No Yes
And But Or Nor So Yet For If Then Than Because Although Though While As Of In On At By To
From With Without Into Onto Upon About Over Under After Before Also Just Only Still Even
Now Here There Is Was Are Were Be Been Being Has Have Had Do Does Did Will Would Can Could
Shall Should May Might Must Very Too Some Any All Each Every Both Either Neither One
""".split())

TITLES = frozenset("""
Mr Mrs Ms Mx Dr Prof Professor Doctor Sir Dame Lord Lady Saint St Captain Capt Father
Sister Brother Master Miss Uncle Aunt Madam Madame Mister Rev Reverend
""".split())

PUNCTUATION = tuple(".,;:!?)\"'\n")

Candidate = dict  # {"id": int, "token": str, "prob": float}
Distribution = Callable[[list[int]], Awaitable[list[Candidate]]]


def _starts_name(token: str) -> bool:
    return len(token) > 1 and token[0] == " " and token[1].isupper()


def _continues(token: str) -> bool:
    """The token goes on with the same word: letters, or ' or - then letters ("'Brien")."""
    if not token or token.startswith("'s"):
        return False
    if token[0].isalpha():
        return True
    return token[0] in "'-" and len(token) > 1 and token[1].isalpha()


@dataclass
class Summary:
    """What a name search needs from one distribution: every token above FLOOR,
    and how much probability ends a word (all of it, and punctuation's)."""

    probs: dict[int, tuple[str, float]]
    ends: float
    ends_with_punctuation: float


def keeps(token: str) -> bool:
    """A token a name can start or go on with (or the "." after a title)."""
    return _starts_name(token) or _continues(token) or token == "."


def summarize(dist: list[Candidate], floor: float = FLOOR) -> Summary:
    """One distribution, reduced to what a name search needs."""
    return Summary(
        probs={c["id"]: (c["token"], c["prob"]) for c in dist
               if c["prob"] > floor and keeps(c["token"])},
        ends=sum(c["prob"] for c in dist if not _continues(c["token"])),
        ends_with_punctuation=sum(c["prob"] for c in dist if c["token"].startswith(PUNCTUATION)),
    )


def summarize_response(raw: bytes, floor: float = FLOOR) -> Summary:
    """A llama.cpp /completion response (n_probs, one token), summarized. Pure,
    so it can run in a worker process: the response is megabytes of JSON, the
    Summary a few kilobytes."""
    probs = (json.loads(raw).get("completion_probabilities") or [{}])[0]
    return summarize(probs.get("top_probs", []), floor)


@dataclass
class Lookups:
    """Distributions fetched for one text, kept so a study's scoring reuses them.
    `fetch` returns a distribution, or its Summary (e.g. from a persistent cache)."""

    fetch: Callable[[list[int]], Awaitable[list[Candidate] | Summary]]
    cache: dict[tuple[int, ...], Summary] = field(default_factory=dict)
    queries: int = 0

    async def get(self, ids: list[int]) -> Summary:
        key = tuple(ids)
        if key not in self.cache:
            self.queries += 1
            result = await self.fetch(ids)
            self.cache[key] = result if isinstance(result, Summary) else summarize(result)
        return self.cache[key]


def _word_end(name: str, s: Summary) -> float:
    """The probability that the name ends here, as a name (0 for function words)."""
    word = name.split()[-1].rstrip(".")
    if word in FUNCTION_WORDS or word in TITLES:
        return 0.0
    if len(word) == 1:
        return s.ends_with_punctuation  # an initial, not an article or pronoun
    return s.ends


async def enumerate_names(lookups: Lookups, top: int = 40) -> tuple[dict[str, float], float]:
    """The exact top names and their probabilities; also the probability that the
    next token starts a capitalized word at all."""
    first = await lookups.get([])
    capital = {tid: (tok, p) for tid, (tok, p) in first.probs.items() if _starts_name(tok)}
    capital_mass = sum(p for _, p in capital.values())
    # (negative probability, text so far, token ids, in a title)
    heap: list[tuple[float, str, list[int], bool]] = [
        (-p, tok, [tid], tok.strip() in TITLES) for tid, (tok, p) in capital.items()
    ]
    heapq.heapify(heap)
    names: dict[str, float] = {}
    best: list[float] = []  # a min-heap of the top finished names' probabilities

    def bound() -> float:
        return best[0] if len(best) >= top else 0.0

    while heap:
        neg, text, ids, titled = heapq.heappop(heap)
        p = -neg
        if p < bound():
            break
        s = await lookups.get(ids)
        name = text.strip()
        end = _word_end(name, s)
        if end > 0 and not (titled and name in TITLES):
            total = names.get(name, 0.0) + p * end
            names[name] = total
            heapq.heappush(best, total)
            if len(best) > top:
                heapq.heappop(best)
        for tid, (tok, q) in s.probs.items():
            nxt = p * q
            if nxt <= bound() or nxt < FLOOR:
                continue
            if _continues(tok):
                heapq.heappush(heap, (-nxt, text + tok, ids + [tid], titled))
            elif titled and name in TITLES and tok == ".":
                heapq.heappush(heap, (-nxt, text + tok, ids + [tid], True))
            elif titled and name.rstrip(".") in TITLES and _starts_name(tok):
                heapq.heappush(heap, (-nxt, text + tok, ids + [tid], False))
    ranked = dict(sorted(names.items(), key=lambda kv: -kv[1])[:top])
    return ranked, capital_mass


async def score_name(lookups: Lookups, ids: list[int], name: str) -> float:
    """P(name, as a whole word) along one spelling in tokens (ids)."""
    p = 1.0
    for i, tid in enumerate(ids):
        s = await lookups.get(ids[:i])
        p *= s.probs.get(tid, ("", 0.0))[1]
        if p == 0.0:
            return 0.0
    return p * _word_end(name, await lookups.get(ids))
