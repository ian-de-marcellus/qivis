"""Exact name distributions: how likely a model is to give each name after a text.

A name is a capitalized word (" Aiden", " A" + "iden"), maybe with a title
before it ("Dr. Anderson"), ended by any token that doesn't continue the
word. Its probability is the product of its tokens' probabilities and the
probability that the word ends there, summed over the ways of spelling it
in tokens. The engine enumerates names best-first: a partial name's
probability bounds every name it could become, so once no partial beats
the top-th finished name, the top names are exact. No sampling. Exact up to
the server's arithmetic: llama.cpp's probabilities shift in about the third
significant figure with what else it's computing (a prompt read fresh or from
its cache, other requests batched alongside), so names within ~0.3% of each
other can trade places between runs. A lookup, once cached, is reused as is.

Rules for what counts (a name study records them with its results):
- Function words (articles, pronouns, conjunctions...) are not names.
- A single capital letter counts only before punctuation ("A.", "R,"): an
  initial or a one-letter name, not an article or pronoun ("A computer",
  "I am").
- A title ("Dr", "Mr", "Captain"...) is followed through to the name after it.
"""

import asyncio
import heapq
import json
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cached_property

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


@dataclass(eq=False)
class Summary:
    """What a name search needs from one distribution: every token above FLOOR,
    likeliest first, and how much probability ends a word (all of it, and
    punctuation's). Arrays, not a dict: a distribution keeps tens of thousands
    of tokens, and most searches read only the top of it."""

    ids: Sequence[int]
    ps: Sequence[float]
    vocab: Mapping[int, str] | Sequence[str]  # token text by id
    ends: float
    ends_with_punctuation: float

    @classmethod
    def of(cls, probs: Mapping[int, tuple[str, float]], ends: float, punct: float) -> Summary:
        """From {id: (token, probability)}."""
        order = sorted(probs, key=lambda i: (-probs[i][1], i))
        vocab = {i: probs[i][0] for i in order}
        return cls(order, [probs[i][1] for i in order], vocab, ends, punct)

    @cached_property
    def _index(self) -> dict[int, float]:
        return dict(zip(self.ids, self.ps, strict=True))

    def prob(self, tid: int) -> float:
        return self._index.get(tid, 0.0)

    def token(self, tid: int) -> str:
        return self.vocab[tid]

    def items(self) -> Iterator[tuple[int, str, float]]:
        """(id, token, probability), likeliest first."""
        vocab = self.vocab
        for tid, p in zip(self.ids, self.ps, strict=True):
            yield tid, vocab[tid], p


def keeps(token: str) -> bool:
    """A token a name can start or go on with (or the "." after a title)."""
    return _starts_name(token) or _continues(token) or token == "."


def keeps_any(token: str) -> bool:
    """Every token: what an answer search (qivis.probes.exact) keeps."""
    return True


def summarize(dist: list[Candidate], floor: float = FLOOR,
              keep: Callable[[str], bool] = keeps) -> Summary:
    """One distribution, reduced to what a name search needs (or, with
    keep=keeps_any, every token above the floor)."""
    return Summary.of(
        {c["id"]: (c["token"], c["prob"]) for c in dist
         if c["prob"] > floor and keep(c["token"])},
        sum(c["prob"] for c in dist if not _continues(c["token"])),
        sum(c["prob"] for c in dist if c["token"].startswith(PUNCTUATION)),
    )


def summarize_response(raw: bytes, floor: float = FLOOR) -> Summary:
    """A llama.cpp /completion response (n_probs, one token), summarized. Pure,
    so it can run in a worker process: the response is megabytes of JSON, the
    Summary a few kilobytes."""
    probs = (json.loads(raw).get("completion_probabilities") or [{}])[0]
    return summarize(probs.get("top_probs", []), floor)


def summarize_response_all(raw: bytes, floor: float = FLOOR) -> Summary:
    """summarize_response keeping every token (for answer searches); pure, for a worker."""
    probs = (json.loads(raw).get("completion_probabilities") or [{}])[0]
    return summarize(probs.get("top_probs", []), floor, keeps_any)


@dataclass
class Lookups:
    """Distributions fetched for one text, kept so a study's scoring reuses them.
    `fetch` returns a distribution, or its Summary (e.g. from a persistent cache).
    A lookup asked for twice while in flight is fetched once."""

    fetch: Callable[[list[int]], Awaitable[list[Candidate] | Summary]]
    cache: dict[tuple[int, ...], asyncio.Task[Summary]] = field(default_factory=dict)
    queries: int = 0

    async def _fetch(self, ids: list[int]) -> Summary:
        result = await self.fetch(ids)
        return result if isinstance(result, Summary) else summarize(result)

    def start(self, ids: list[int]) -> asyncio.Task[Summary]:
        key = tuple(ids)
        if key not in self.cache:
            self.queries += 1
            self.cache[key] = asyncio.create_task(self._fetch(ids))
        return self.cache[key]

    async def get(self, ids: list[int]) -> Summary:
        return await self.start(ids)

    async def settle(self) -> None:
        """Let lookups started ahead finish (the model's already at work on them,
        and a persistent cache keeps them for next time)."""
        await asyncio.gather(*self.cache.values(), return_exceptions=True)


def _word_end(name: str, s: Summary) -> float:
    """The probability that the name ends here, as a name (0 for function words)."""
    word = name.split()[-1].rstrip(".")
    if word in FUNCTION_WORDS or word in TITLES:
        return 0.0
    if len(word) == 1:
        return s.ends_with_punctuation  # an initial, not an article or pronoun
    return s.ends


async def enumerate_names(
    lookups: Lookups, top: int = 40, ahead: int = 4,
) -> tuple[dict[str, float], float]:
    """The exact top names and their probabilities; also the probability that the
    next token starts a capitalized word at all.

    Partial names are expanded one at a time, best first, but the lookups for the
    next `ahead` are started early, so several are in flight at once. Which are
    expanded, and in what order, is the same as without: the answer is too."""
    first = await lookups.get([])
    capital = {tid: (tok, p) for tid, tok, p in first.items() if _starts_name(tok)}
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

    try:
        while heap:
            # Start the next few best early (they're among a binary heap's
            # first 2^ahead - 1 entries), if they can still make the top
            for neg, _, later, _ in heapq.nsmallest(ahead, heap[: 2 ** ahead - 1]):
                if -neg >= bound():
                    lookups.start(later)
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
            for tid, tok, q in s.items():
                nxt = p * q
                if nxt <= bound() or nxt < FLOOR:
                    break  # likeliest first: the rest are smaller still
                if _continues(tok):
                    heapq.heappush(heap, (-nxt, text + tok, ids + [tid], titled))
                elif titled and name in TITLES and tok == ".":
                    heapq.heappush(heap, (-nxt, text + tok, ids + [tid], True))
                elif titled and name.rstrip(".") in TITLES and _starts_name(tok):
                    heapq.heappush(heap, (-nxt, text + tok, ids + [tid], False))
    finally:
        await lookups.settle()
    ranked = dict(sorted(names.items(), key=lambda kv: -kv[1])[:top])
    return ranked, capital_mass


async def score_name(lookups: Lookups, ids: list[int], name: str) -> float:
    """P(name, as a whole word) along one spelling in tokens (ids)."""
    p = 1.0
    for i, tid in enumerate(ids):
        s = await lookups.get(ids[:i])
        p *= s.prob(tid)
        if p == 0.0:
            return 0.0
    return p * _word_end(name, await lookups.get(ids))
