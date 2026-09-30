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
"""

import hashlib
import json
import zlib
from array import array
from typing import Any

from qivis.db.connection import Database
from qivis.models import SamplingParams
from qivis.names import engine
from qivis.providers.base import GenerationRequest
from qivis.providers.llamacpp import LlamaCppProvider

LOOKUP_K = 1_000_000  # the whole vocabulary (llama.cpp clamps it)


class DistributionCache:
    def __init__(self, db: Database, llama: LlamaCppProvider) -> None:
        self._db = db
        self._llama = llama
        self._identities: dict[str, str] = {}
        self._vocab: dict[str, dict[int, str]] = {}
        self.hits = 0
        self.misses = 0

    async def identity(self, model: str) -> str:
        if model not in self._identities:
            ident = await self._llama.model_identity(model)
            self._identities[model] = hashlib.sha256(
                json.dumps(ident, sort_keys=True).encode(),
            ).hexdigest()[:32]
        return self._identities[model]

    async def summary(self, model: str, prompt: str, ids: list[int]) -> engine.Summary:
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
        dist = (await self._llama.next_tokens(request, ids, LOOKUP_K))["candidates"]
        summary = engine.summarize(dist)
        await self._store(ident, key, summary)
        return summary

    async def _store(self, ident: str, key: str, s: engine.Summary) -> None:
        ids = sorted(s.probs)
        data = zlib.compress(
            len(ids).to_bytes(4, "little")
            + array("i", ids).tobytes()
            + array("d", [s.probs[i][1] for i in ids]).tobytes(),
        )
        vocab = self._vocab.setdefault(ident, {})
        new = [(ident, i, s.probs[i][0]) for i in ids if i not in vocab]
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
        raw = zlib.decompress(row["data"])
        n = int.from_bytes(raw[:4], "little")
        ids = array("i")
        ids.frombytes(raw[4:4 + 4 * n])
        probs = array("d")
        probs.frombytes(raw[4 + 4 * n:])
        vocab = await self._vocabulary(ident)
        if any(i not in vocab for i in ids):  # stored by an earlier run: read them in
            self._vocab.pop(ident, None)
            vocab = await self._vocabulary(ident)
        return engine.Summary(
            probs={i: (vocab[i], p) for i, p in zip(ids, probs, strict=True)},
            ends=row["ends"], ends_with_punctuation=row["punct"],
        )

    async def _vocabulary(self, ident: str) -> dict[int, str]:
        if ident not in self._vocab or not self._vocab[ident]:
            rows = await self._db.fetchall(
                "SELECT id, token FROM name_vocab WHERE identity = ?", (ident,),
            )
            self._vocab[ident] = {r["id"]: r["token"] for r in rows}
        return self._vocab[ident]
