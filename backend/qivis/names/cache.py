"""A persistent memo of next-token distributions, for name studies and discovery.

The same lookup (same model, same prompt, same token path) always gives the
same distribution, so it's kept: re-running a cell, sharing a bare frame
across studies, scoring discovery's names in a study, all become reads.

The key is everything that shapes the numbers: the model's identity (its
file and size, the llama.cpp build, its profile's logit bias and BOS count),
the exact prompt, and the token path. What's kept is what a name search
reads (qivis.names.engine.summarize): every token a name can start or go on
with, above the engine's floor, and the probability of ending a word.

It's derived data, like a projection, not a record: clearing it loses
nothing but time.

With direct lookups on (qivis.names.direct), lookups go to llama.cpp itself
and skip this table: computing one takes less time than reading it back.

A lookup's response is the whole vocabulary as JSON (about 9 MB for OLMo);
parsing it takes longer than the model takes to read the prompt. So it's
parsed in worker processes, several at once, and only the small Summary
comes back to the event loop.
"""

import asyncio
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Any

from qivis.db.connection import Database
from qivis.models import SamplingParams
from qivis.names import direct, engine, packing
from qivis.providers.base import GenerationRequest
from qivis.providers.llamacpp import _LLAMA3_BOS, LlamaCppProvider

LOOKUP_K = 1_000_000  # the whole vocabulary (llama.cpp clamps it)

# Worker processes parsing responses (one per llama.cpp slot)
PARSERS = 4

_pool: ProcessPoolExecutor | None = None


def _parsers() -> ProcessPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor(max_workers=PARSERS)
    return _pool


def shutdown_parsers() -> None:
    """Stop the workers (at app shutdown; left running, they outlive a reload)."""
    global _pool
    if _pool is not None:
        _pool.shutdown(cancel_futures=True)
        _pool = None


async def parse_and_pack(raw: bytes) -> tuple[engine.Summary, bytes]:
    """packing.parse_and_pack, in a worker process."""
    global _pool
    try:
        return await asyncio.get_running_loop().run_in_executor(
            _parsers(), packing.parse_and_pack, raw,
        )
    except BrokenProcessPool:  # a worker died: start fresh ones next time, parse this here
        _pool = None
        return packing.parse_and_pack(raw)


class DistributionCache:
    def __init__(self, db: Database, llama: LlamaCppProvider) -> None:
        self._db = db
        self._llama = llama
        self._identities: dict[str, str] = {}
        self._vocab: dict[str, dict[int, str]] = {}
        self._spellings: dict[tuple[str, str], list[dict]] = {}
        self._paths: dict[str, str] = {}
        self._inputs: dict[tuple[str, str], tuple[str, dict[int, float] | None]] = {}
        self.hits = 0
        self.misses = 0
        # Lookups worth having in flight at once: llama-server has 4 slots; the
        # direct engine batches whatever's waiting
        self.direct = direct.enabled()
        self.parallel = 32 if self.direct else 4

    async def identity(self, model: str) -> str:
        if model not in self._identities:
            # Direct lookups don't need llama-server's copy: don't wake it
            ident = await (self._llama.model_identity(model, wake=False) if self.direct
                           else self._llama.model_identity(model))
            self._paths[model] = ident.get("path") or ""
            if self.direct:
                ident = {**ident, **direct.identity()}
            self._identities[model] = hashlib.sha256(
                json.dumps(ident, sort_keys=True).encode(),
            ).hexdigest()[:32]
        return self._identities[model]

    async def spelling(self, model: str, name: str) -> list[dict]:
        """A name's tokens (" " + name), asked of the model once."""
        key = (await self.identity(model), name)
        if key not in self._spellings:
            if self.direct:
                self._spellings[key] = await self._engine().tokenize(self._paths[model], " " + name)
            else:
                self._spellings[key] = await self._llama.tokenize(" " + name, model)
        return self._spellings[key]

    async def document_start(self, model: str) -> str:
        """What the model has seen right before a document begins (as
        LlamaCppProvider.document_start: its BOS if its prompts get one, else
        its end-of-text token), from whichever copy of it lookups use."""
        if not self.direct:
            return await self._llama.document_start(model)
        await self.identity(model)
        info = await self._engine().info(self._paths[model])
        return _LLAMA3_BOS if info["adds_bos"] else (info["eos"] or "")

    def _engine(self) -> direct.DirectEngine:
        return direct.get_engine(self._llama)

    async def summary(self, model: str, prompt: str, ids: list[int]) -> engine.Summary:
        if self.direct:
            return await self._direct(model, prompt, ids)
        ident = await self.identity(model)
        key = hashlib.sha256(json.dumps([ident, prompt, ids]).encode()).hexdigest()
        row = await self._db.fetchone(
            "SELECT data, ends, punct FROM name_lookup_cache WHERE key = ?", (key,),
        )
        if row is not None:
            self.hits += 1
            return await self._decode(ident, row)
        self.misses += 1
        request = GenerationRequest(
            model=model, messages=[], prompt_text=prompt, sampling_params=SamplingParams(),
        )
        raw, _, _ = await self._llama.next_tokens_raw(request, ids, LOOKUP_K)
        summary, data = await parse_and_pack(raw)
        await self._store(ident, key, summary, data)
        return summary

    async def _direct(self, model: str, prompt: str, ids: list[int]) -> engine.Summary:
        await self.identity(model)
        path = self._paths[model]
        if not path:
            raise RuntimeError(f"llama-server doesn't say where {model}'s file is")
        if (model, prompt) not in self._inputs:  # asking llama-server once per prompt
            request = GenerationRequest(
                model=model, messages=[], prompt_text=prompt, sampling_params=SamplingParams(),
            )
            text, bias, _ = await self._llama.lookup_inputs(request)
            self._inputs[model, prompt] = (text, bias)
        text, bias = self._inputs[model, prompt]
        self.misses += 1
        return await self._engine().summary(path, text, ids, bias)

    async def _store(self, ident: str, key: str, s: engine.Summary, data: bytes) -> None:
        vocab = self._vocab.setdefault(ident, {})
        new = [(ident, i, s.token(i)) for i in s.ids if i not in vocab]
        if new:
            await self._db.executemany(
                "INSERT OR IGNORE INTO name_vocab (identity, id, token) VALUES (?, ?, ?)", new,
            )
            vocab.update({i: t for _, i, t in new})
        await self._db.execute(
            "INSERT OR REPLACE INTO name_lookup_cache (key, identity, data, ends, punct) "
            "VALUES (?, ?, ?, ?, ?)",
            (key, ident, data, s.ends, s.ends_with_punctuation),
        )

    async def _decode(self, ident: str, row: Any) -> engine.Summary:
        ids, probs = packing.unpack(row["data"])
        vocab = await self._vocabulary(ident)
        if any(i not in vocab for i in ids):  # stored by an earlier run: read them in
            self._vocab.pop(ident, None)
            vocab = await self._vocabulary(ident)
        order = sorted(zip(probs, ids), key=lambda x: (-x[0], x[1]))
        return engine.Summary(
            ids=[i for _, i in order], ps=[p for p, _ in order], vocab=vocab,
            ends=row["ends"], ends_with_punctuation=row["punct"],
        )

    async def _vocabulary(self, ident: str) -> dict[int, str]:
        if ident not in self._vocab or not self._vocab[ident]:
            rows = await self._db.fetchall(
                "SELECT id, token FROM name_vocab WHERE identity = ?", (ident,),
            )
            self._vocab[ident] = {r["id"]: r["token"] for r in rows}
        return self._vocab[ident]
