"""Exact answer probes: the model's answer distribution at a point, enumerated.

A sampled probe estimates how often each answer comes up. This one computes
it: continuations are expanded best-first by their probability as a whole
(the product of their tokens', at temperature 1 with no truncation, as the
model would sample), each one a node in a tree of next-token lookups.

- A continuation is finished when its next token ends the line (or is an
  end-of-text token): a one-line answer. Its probability is exact.
- One that reaches the token cap without ending is "cut off", its whole
  subtree's probability counted with it.
- A continuation whose probability falls under epsilon isn't expanded. What
  every expanded node leaves unexpanded is its pruned mass, known exactly;
  explored and pruned mass add up to 1 (up to the server's arithmetic).

The pruned mass isn't answer-neutral: long, hedging phrasings fall under
epsilon first, so leaving it out would make the model look more decisive
than it is. So some of it is sampled ("tail rollouts"): a node is picked in
proportion to its pruned mass, its next token drawn from what it left
unexpanded (the expanded tokens forbidden, so the draw is exactly from the
pruned part), and the rest sampled as usual. Each rollout carries an equal
share of the pruned mass: an unbiased estimate of how it splits by answer.
"""

import asyncio
import heapq
import logging
import random
import re
from dataclasses import dataclass, field

import httpx

from qivis.names import cache, direct, engine
from qivis.names.engine import Lookups, Summary
from qivis.providers.base import GenerationRequest
from qivis.providers.llamacpp import LlamaCppProvider

EPSILON = 1e-3
MAX_LOOKUPS = 20_000  # a backstop: past it, what's left unexpanded is pruned
TAIL = 100
AHEAD = 4  # lookups started early, as in the name engine
ROLLOUT_SLOTS = 4
RETRIES = 3  # a rollout's server errors (e.g. a transient out-of-memory) before giving up

logger = logging.getLogger(__name__)

# End-of-text and similar special tokens end an answer as a line end does
_SPECIAL = re.compile(r"^<\|[^|>]+\|>$|^</s>$")


def ends_answer(token: str) -> bool:
    return "\n" in token or bool(_SPECIAL.match(token))


def head(token: str) -> str:
    """What a line-ending token adds before the line ends (special tokens add nothing)."""
    return "" if _SPECIAL.match(token) else token.split("\n", 1)[0]


@dataclass
class Leaf:
    text: str
    ids: list[int]
    p: float
    finish: str  # "stop" (the line ended) or "length" (cut off at the cap)


@dataclass
class Stub:
    """An expanded node and what it left unexpanded."""
    text: str
    ids: list[int]
    kept: list[int]  # the next tokens it expanded (or finished on)
    pruned: float  # its probability times the unexpanded share of its next token


@dataclass
class Enumeration:
    leaves: list[Leaf] = field(default_factory=list)
    stubs: list[Stub] = field(default_factory=list)
    lookups: int = 0
    stopped_early: bool = False  # MAX_LOOKUPS reached

    @property
    def explored(self) -> float:
        return sum(leaf.p for leaf in self.leaves)

    @property
    def cut_off(self) -> float:
        return sum(leaf.p for leaf in self.leaves if leaf.finish == "length")

    @property
    def pruned(self) -> float:
        return sum(s.pruned for s in self.stubs)


async def enumerate_answers(
    lookups: Lookups, epsilon: float = EPSILON, max_tokens: int = 24,
    max_lookups: int = MAX_LOOKUPS,
) -> Enumeration:
    """Every one-line answer with probability at least epsilon, exactly, and the
    pruned mass, node by node."""
    out = Enumeration()
    # (negative probability, tie-break, text so far, token ids)
    heap: list[tuple[float, int, str, list[int]]] = []
    order = 0

    def expand(p: float, text: str, ids: list[int], s: Summary) -> None:
        nonlocal order
        kept, kept_q = [], 0.0
        for tid, tok, q in s.items():
            m = p * q
            if m < epsilon:
                break  # likeliest first: the rest are smaller still
            kept.append(tid)
            kept_q += q
            if ends_answer(tok):
                out.leaves.append(Leaf(text + head(tok), ids + [tid], m, "stop"))
            elif len(ids) + 1 >= max_tokens:
                out.leaves.append(Leaf(text + tok, ids + [tid], m, "length"))
            else:
                order += 1
                heapq.heappush(heap, (-m, order, text + tok, ids + [tid]))
        pruned = p * max(0.0, 1.0 - kept_q)
        if pruned > 0:
            out.stubs.append(Stub(text, ids, kept, pruned))

    try:
        expand(1.0, "", [], await lookups.get([]))
        while heap:
            if lookups.queries >= max_lookups:
                out.stopped_early = True
                for neg, _, text, ids in heap:  # unexpanded: all of it pruned
                    out.stubs.append(Stub(text, ids, [], -neg))
                heap.clear()
                break
            for neg, _, _, later in heapq.nsmallest(AHEAD, heap[: 2 ** AHEAD - 1]):
                lookups.start(later)
            neg, _, text, ids = heapq.heappop(heap)
            expand(-neg, text, ids, await lookups.get(ids))
    finally:
        await lookups.settle()
    out.lookups = lookups.queries
    return out


@dataclass
class Rollout:
    text: str
    from_ids: list[int]  # the pruned node it started from
    ids: list[int]  # its own tokens after that node
    weight: float  # its share of the pruned mass
    finish: str


async def rollouts(
    llama: LlamaCppProvider, request: GenerationRequest, stubs: list[Stub], n: int = TAIL,
    max_tokens: int = 24, seed: int | None = None,
) -> list[Rollout]:
    """n samples of the pruned mass (see the module docstring), each weighted
    pruned / n."""
    total = sum(s.pruned for s in stubs)
    if n <= 0 or total <= 0:
        return []
    rng = random.Random(seed)
    picks = rng.choices(stubs, weights=[s.pruned for s in stubs], k=n)
    slots = asyncio.Semaphore(ROLLOUT_SLOTS)

    async def sample(*a, **k) -> dict:
        for attempt in range(RETRIES):
            try:
                return await llama.sample_after(*a, **k)
            except httpx.HTTPStatusError as e:
                if e.response.status_code < 500 or attempt == RETRIES - 1:
                    raise
                logger.warning("A tail rollout failed (%s); retrying", e)
                await asyncio.sleep(3 * (attempt + 1))
        raise AssertionError("unreachable")

    async def one(stub: Stub) -> Rollout:
        async with slots:
            # The next token, from what this node left unexpanded only
            first = await sample(request, stub.ids, 1, forbid=stub.kept)
            ids, text = first["ids"][:1], first["text"]
            if first["stop_type"] == "eos" or "\n" in text:
                return Rollout(stub.text + text.split("\n", 1)[0], stub.ids, ids, total / n, "stop")
            used = len(stub.ids) + 1
            if used >= max_tokens:
                return Rollout(stub.text + text, stub.ids, ids, total / n, "length")
            rest = await sample(request, stub.ids + ids, max_tokens - used, stop=["\n"])
            finish = "length" if rest["stop_type"] == "limit" else "stop"
            return Rollout(
                stub.text + text + rest["text"], stub.ids, ids + rest["ids"], total / n, finish,
            )

    return list(await asyncio.gather(*[one(s) for s in picks]))


async def answer_lookups(llama: LlamaCppProvider, request: GenerationRequest) -> Lookups:
    """Next-token lookups after the request's prompt, every token kept: through
    the direct engine if it's on (qivis.names.direct), else llama-server."""
    if direct.enabled():
        ident = await llama.model_identity(request.model, wake=False)
        path = ident.get("path") or ""
        if not path:
            raise RuntimeError(f"llama-server doesn't say where {request.model}'s file is")
        text, bias, _ = await llama.lookup_inputs(request)
        eng = direct.get_engine(llama)

        async def fetch(ids: list[int]) -> Summary:
            return await eng.summary(path, text, ids, bias, kind="answers")
    else:
        loop = asyncio.get_running_loop()

        async def fetch(ids: list[int]) -> Summary:
            raw, _, _ = await llama.next_tokens_raw(request, ids, cache.LOOKUP_K)
            return await loop.run_in_executor(cache._parsers(), engine.summarize_response_all, raw)

    return Lookups(fetch)


async def release_lookups(llama: LlamaCppProvider) -> None:
    """After an enumeration: free the direct-lookup worker's memory (if it's idle)
    before rollouts and judging load models into llama-server."""
    if direct.enabled():
        await direct.get_engine(llama).rest_now()
