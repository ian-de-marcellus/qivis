"""Direct lookups: name searches' next-token distributions from llama.cpp
itself, not through llama-server.

A full distribution through llama-server is ~9 MB of JSON, written and then
parsed; the model's own work is a small part of a lookup. Here a small C
library (direct_lookups.c) runs batches of lookups through the model and
returns each already summarized, as arrays. It's built on first use against
llama-server's own libllama (the same llama.cpp, so the same arithmetic) and
runs in a process of its own (direct_worker.py): llama.cpp failing can't take
the backend with it. The model file is memory-mapped, so its weights are
shared with llama-server's copy; what's extra is the worker's attention cache.

Opt in with QIVIS_DIRECT_LOOKUPS=1. It needs llama-server's library and
header where its install put them (Homebrew's llama.cpp does), a C compiler,
and a GPU llama.cpp supports (it's been run on Apple silicon, with Metal).
"""

import asyncio
import hashlib
import logging
import os
import pickle
import platform
import shutil
import struct
import subprocess
import sys
from array import array
from pathlib import Path
from typing import Any

from qivis.names import engine

logger = logging.getLogger(__name__)

SOURCE = Path(__file__).with_name("direct_lookups.c")
CACHE_DIR = Path(os.environ.get("QIVIS_CACHE_DIR", Path.home() / "Library" / "Caches" / "qivis"))
N_CTX = int(os.environ.get("QIVIS_DIRECT_N_CTX", "4096"))
MAX_BATCH = 256  # lookups per request to the worker
# The worker lets its model go after this long without lookups
IDLE_SECONDS = 120
# The GPU memory it holds is leased from llama-server's supervisor, so the two
# don't both fill it: the model file plus its attention cache and buffers
LEASE = "qivis-direct-lookups"
LEASE_EXTRA = 1024**3
LEASE_TTL = 180.0


def enabled() -> bool:
    return os.environ.get("QIVIS_DIRECT_LOOKUPS", "").lower() in ("1", "true", "yes")


def _server() -> Path:
    server = shutil.which("llama-server")
    if not server:
        raise RuntimeError("Direct lookups need llama-server's llama.cpp: it isn't on PATH")
    return Path(server)


def llama_prefix() -> Path:
    """Where llama-server's llama.cpp is installed (its bin/'s parent)."""
    return _server().resolve().parent.parent


def library() -> Path:
    """The compiled library, built if this source or llama.cpp changed."""
    prefix = llama_prefix()
    lib = next((prefix / "lib" / n for n in ("libllama.dylib", "libllama.so")
                if (prefix / "lib" / n).exists()), None)
    header = prefix / "include" / "llama.h"
    if lib is None or not header.exists():
        raise RuntimeError(f"Direct lookups need libllama and llama.h under {prefix}")
    stamp = hashlib.sha256(
        SOURCE.read_bytes() + str(lib.resolve()).encode() + str(lib.stat().st_mtime).encode(),
    ).hexdigest()[:16]
    out = CACHE_DIR / f"direct-lookups-{stamp}{lib.suffix}"
    if not out.exists():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cc = os.environ.get("CC", "cc")
        # Its own headers, and ggml's (Homebrew keeps those in its shared prefix)
        includes = dict.fromkeys([prefix / "include", _server().parent.parent / "include"])
        cmd = [cc, "-O2", "-shared", "-fPIC", str(SOURCE), *[f"-I{i}" for i in includes],
               f"-L{lib.parent}", "-lllama", f"-Wl,-rpath,{lib.parent}", "-o", str(out)]
        done = subprocess.run(cmd, capture_output=True, text=True)
        if done.returncode != 0:
            raise RuntimeError(f"Couldn't build the direct lookup library:\n{done.stderr}")
    return out


def engine_name() -> str:
    """What computes lookups now, as a record names it."""
    return "direct" if enabled() else "llama-server"


def identity() -> dict[str, Any]:
    """What distinguishes this engine's numbers from llama-server's."""
    return {"engine": "direct", "llama": str(llama_prefix())}


class DirectEngine:
    """Lookups gathered into batches for the worker: while it's busy with one
    batch, the next accumulates.

    `gpu` (the llama.cpp provider) leases the memory the worker's model needs
    from llama-server's supervisor before loading it, renews the lease while
    working, and releases it when the worker stops."""

    def __init__(self, gpu: Any = None) -> None:
        self.gpu = gpu
        self._leased: tuple[str, float] | None = None  # (model path, when renewed)
        self._proc: asyncio.subprocess.Process | None = None
        self._pending: list[tuple[tuple, str, list[int], asyncio.Future]] = []
        self._runner: asyncio.Task | None = None
        self._idle: asyncio.TimerHandle | None = None
        self._vocab: dict[str, list[str]] = {}
        self._talk = asyncio.Lock()
        self.batches = 0
        self.lookups = 0

    async def _start(self) -> asyncio.subprocess.Process:
        if self._proc is None or self._proc.returncode is not None:
            lib = await asyncio.to_thread(library)
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            log = open(CACHE_DIR / "direct-lookups.log", "ab")  # noqa: SIM115 - the child's
            self._proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "qivis.names.direct_worker", str(lib),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=log,
            )
            log.close()
        return self._proc

    async def _lease(self, path: str) -> None:
        """Hold GPU memory for `path` (renewed when a third of its time is gone)."""
        if self.gpu is None:
            return
        now = asyncio.get_running_loop().time()
        if self._leased and self._leased[0] == path and now - self._leased[1] < LEASE_TTL / 3:
            return
        if self._leased and self._leased[0] != path and self._proc is not None:
            await self._stop()  # one model at a time: let the other go first
        size = os.path.getsize(path) + LEASE_EXTRA
        await self.gpu.lease_gpu(LEASE, size, LEASE_TTL)
        self._leased = (path, now)

    async def _ask(self, request: dict) -> Any:
        async with self._talk:
            await self._lease(request["path"])
            proc = await self._start()
            assert proc.stdin is not None and proc.stdout is not None
            data = pickle.dumps(request, protocol=pickle.HIGHEST_PROTOCOL)
            try:
                proc.stdin.write(struct.pack("<I", len(data)) + data)
                await proc.stdin.drain()
                (n,) = struct.unpack("<I", await proc.stdout.readexactly(4))
                reply = pickle.loads(await proc.stdout.readexactly(n))
            except (asyncio.IncompleteReadError, ConnectionError, BrokenPipeError) as e:
                raise RuntimeError(
                    f"The direct lookup process stopped (see {CACHE_DIR / 'direct-lookups.log'})",
                ) from e
        if "error" in reply:
            raise RuntimeError(f"Direct lookup failed: {reply['error']}")
        return reply["ok"]

    async def tokenize(self, path: str, text: str) -> list[dict]:
        """Text as the model's tokens, as llama-server's /tokenize gives them: [{id, token}]."""
        got = await self._ask({"op": "tokenize", "path": path, "n_ctx": N_CTX, "text": text})
        return [{"id": i, "token": t} for i, t in got]

    async def info(self, path: str) -> dict:
        """Whether the model's string prompts get its BOS; its end-of-text token."""
        return await self._ask({"op": "info", "path": path, "n_ctx": N_CTX})

    async def vocab(self, path: str) -> list[str]:
        if path not in self._vocab:
            self._vocab[path] = await self._ask({"op": "vocab", "path": path, "n_ctx": N_CTX})
        return self._vocab[path]

    async def summary(self, path: str, prompt: str, ids: list[int],
                      bias: dict[int, float] | None = None) -> engine.Summary:
        """One lookup: the distribution after the prompt and token ids, summarized."""
        key = (path, tuple(sorted((bias or {}).items())))
        future = asyncio.get_running_loop().create_future()
        self._pending.append((key, prompt, list(ids), future))
        if self._idle is not None:
            self._idle.cancel()
            self._idle = None
        if self._runner is None or self._runner.done():
            self._runner = asyncio.create_task(self._run())
        return await future

    async def _run(self) -> None:
        while self._pending:
            key = self._pending[0][0]
            batch = [x for x in self._pending if x[0] == key][:MAX_BATCH]
            taken = {id(x) for x in batch}
            self._pending = [x for x in self._pending if id(x) not in taken]
            path, bias = key[0], dict(key[1]) or None
            try:
                vocab = await self.vocab(path)
                results = await self._ask({
                    "op": "lookups", "path": path, "n_ctx": N_CTX, "bias": bias,
                    "floor": engine.FLOOR, "items": [(p, ids) for _, p, ids, _ in batch],
                })
            except Exception as e:
                for *_, f in batch:
                    if not f.done():
                        f.set_exception(e)
                continue
            self.batches += 1
            self.lookups += len(batch)
            for (*_, f), (ids_raw, probs_raw, ends, punct) in zip(batch, results, strict=True):
                ids, probs = array("i"), array("f")
                ids.frombytes(ids_raw)
                probs.frombytes(probs_raw)
                if not f.done():
                    f.set_result(engine.Summary(ids, probs, vocab, ends, punct))
        loop = asyncio.get_running_loop()
        self._idle = loop.call_later(IDLE_SECONDS, lambda: loop.create_task(self._rest()))

    async def _rest(self) -> None:
        """Stop the worker (and free its model) if nothing's come in since."""
        self._idle = None
        if not self._pending and (self._runner is None or self._runner.done()):
            async with self._talk:
                await self._stop()

    async def close(self) -> None:
        if self._idle is not None:
            self._idle.cancel()
        if self._runner is not None:
            self._runner.cancel()
        await self._stop()

    async def _stop(self) -> None:
        if self._leased is not None and self.gpu is not None:
            await self.gpu.release_gpu(LEASE)
        self._leased = None
        if self._proc is not None and self._proc.returncode is None:
            assert self._proc.stdin is not None
            self._proc.stdin.close()  # the worker exits at the end of its input
            try:
                await asyncio.wait_for(self._proc.wait(), 5)
            except TimeoutError:
                self._proc.kill()
        self._proc = None


_engine: DirectEngine | None = None


def get_engine(gpu: Any = None) -> DirectEngine:
    global _engine
    if _engine is not None and gpu is not None:
        _engine.gpu = gpu
    if _engine is None:
        if (sys.platform, platform.machine()) != ("darwin", "arm64"):
            logger.warning(
                "Direct lookups have only been tested on Apple silicon; if they fail, "
                "unset QIVIS_DIRECT_LOOKUPS to go through llama-server",
            )
        _engine = DirectEngine(gpu)
    return _engine


async def shutdown() -> None:
    global _engine
    if _engine is not None:
        await _engine.close()
        _engine = None
