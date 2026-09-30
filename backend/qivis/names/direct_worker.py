"""The direct lookup engine's process (see qivis.names.direct).

Run as `python -m qivis.names.direct_worker <library>`. Requests and replies
are pickled, each after its length (4 bytes), on stdin and stdout; llama.cpp's
own output goes to stderr. It holds one model at a time.

A prompt's tokens but the last are kept in a sequence of their own, so each
lookup (the last prompt token, then its token path) copies that sequence
and computes only its own few tokens; a batch's lookups go through the model
together.
"""

import ctypes as ct
import os
import pickle
import struct
import sys
from collections import OrderedDict
from typing import Any

from qivis.names import engine

PROMPT_SEQS = 32  # prompts kept, most recently used
SCRATCH_SEQS = 32  # lookups per pass through the model
N_BATCH = 2048


def _bind(path: str) -> ct.CDLL:
    lib = ct.CDLL(path)
    lib.eng_load.restype = ct.c_void_p
    lib.eng_load.argtypes = [ct.c_char_p, ct.c_int, ct.c_int, ct.c_int]
    lib.eng_free.argtypes = [ct.c_void_p]
    lib.eng_n_vocab.argtypes = [ct.c_void_p]
    ids = ct.POINTER(ct.c_int32)
    lib.eng_tokenize.argtypes = [ct.c_void_p, ct.c_char_p, ct.c_int, ids, ct.c_int]
    lib.eng_piece.argtypes = [ct.c_void_p, ct.c_int32, ct.c_char_p, ct.c_int]
    lib.eng_decode.argtypes = [ct.c_void_p, ct.c_int, ids, ids, ids, ct.POINTER(ct.c_int8)]
    lib.eng_seq_cp.argtypes = [ct.c_void_p, ct.c_int, ct.c_int, ct.c_int, ct.c_int]
    lib.eng_seq_rm.argtypes = [ct.c_void_p, ct.c_int, ct.c_int, ct.c_int]
    lib.eng_summarize.argtypes = [
        ct.c_void_p, ct.c_int, ct.c_void_p, ct.c_char_p, ct.c_char_p, ct.c_char_p, ct.c_float,
        ids, ct.POINTER(ct.c_float), ct.POINTER(ct.c_double), ct.POINTER(ct.c_double),
    ]
    return lib


class Model:
    def __init__(self, lib: ct.CDLL, path: str, n_ctx: int) -> None:
        self.lib, self.path = lib, path
        self.e = lib.eng_load(path.encode(), n_ctx, PROMPT_SEQS + SCRATCH_SEQS, N_BATCH)
        if not self.e:
            raise RuntimeError(f"llama.cpp couldn't load {path}")
        self.n_vocab = lib.eng_n_vocab(self.e)
        buf = ct.create_string_buffer(512)
        pieces = []
        for i in range(self.n_vocab):
            n = lib.eng_piece(self.e, i, buf, 512)
            pieces.append(buf.raw[:max(n, 0)].decode("utf-8", "replace"))
        self.pieces = pieces
        # Which tokens a name search keeps, which go on a word, which are punctuation
        self.keep = bytes(engine.keeps(p) for p in pieces)
        self.cont = bytes(engine._continues(p) for p in pieces)
        self.punct = bytes(p.startswith(engine.PUNCTUATION) for p in pieces)
        self.prompts: OrderedDict[str, tuple[int, list[int]]] = OrderedDict()
        self.free = list(range(PROMPT_SEQS))
        self.ids = (ct.c_int32 * self.n_vocab)()
        self.probs = (ct.c_float * self.n_vocab)()

    def close(self) -> None:
        self.lib.eng_free(self.e)

    def tokenize(self, text: str) -> list[int]:
        raw = text.encode()
        out = (ct.c_int32 * (len(raw) + 8))()
        n = self.lib.eng_tokenize(self.e, raw, len(raw), out, len(out))
        if n < 0:
            raise RuntimeError("couldn't tokenize the prompt")
        return list(out[:n])

    def decode(self, items: list[tuple[int, int, int, bool]]) -> None:
        """(token, position, sequence, want its distribution), in passes of N_BATCH."""
        for i in range(0, len(items), N_BATCH):
            part = items[i:i + N_BATCH]
            n = len(part)
            status = self.lib.eng_decode(
                self.e, n,
                (ct.c_int32 * n)(*[t for t, _, _, _ in part]),
                (ct.c_int32 * n)(*[p for _, p, _, _ in part]),
                (ct.c_int32 * n)(*[s for _, _, s, _ in part]),
                (ct.c_int8 * n)(*[int(w) for _, _, _, w in part]),
            )
            if status != 0:
                raise RuntimeError(f"llama_decode failed ({status})")

    def resident(self, prompts: list[str]) -> None:
        """Each prompt's tokens but the last, in a sequence of its own."""
        new = [p for p in dict.fromkeys(prompts) if p not in self.prompts]
        for p in prompts:
            if p in self.prompts:
                self.prompts.move_to_end(p)
        items = []
        for p in new:
            if not self.free:
                _, (seq, _) = self.prompts.popitem(last=False)
                self.lib.eng_seq_rm(self.e, seq, -1, -1)
                self.free.append(seq)
            seq = self.free.pop()
            tokens = self.tokenize(p)
            if not tokens:
                raise RuntimeError("the prompt has no tokens")
            self.prompts[p] = (seq, tokens)
            items += [(t, i, seq, False) for i, t in enumerate(tokens[:-1])]
        try:
            self.decode(items)
        except RuntimeError:
            for p in new:  # half-computed: don't keep them
                seq, _ = self.prompts.pop(p)
                self.lib.eng_seq_rm(self.e, seq, -1, -1)
                self.free.append(seq)
            raise

    def lookups(self, bias: dict[int, float] | None, floor: float,
                items: list[tuple[str, list[int]]]) -> list[tuple[bytes, bytes, float, float]]:
        bias_vec = None
        if bias:
            bias_vec = (ct.c_float * self.n_vocab)()
            for tid, b in bias.items():
                if 0 <= int(tid) < self.n_vocab:
                    bias_vec[int(tid)] = float("-inf") if b is False else float(b)
        out: list[tuple[bytes, bytes, float, float]] = []
        ends, punct = ct.c_double(), ct.c_double()
        # Passes of at most SCRATCH_SEQS lookups over at most PROMPT_SEQS prompts
        start = 0
        while start < len(items):
            chunk: list[tuple[str, list[int]]] = []
            seen: set[str] = set()
            while start < len(items) and len(chunk) < SCRATCH_SEQS:
                p = items[start][0]
                if p not in seen and len(seen) == PROMPT_SEQS:
                    break
                seen.add(p)
                chunk.append(items[start])
                start += 1
            self.resident([p for p, _ in chunk])
            batch, last = [], []
            for j, (p, path) in enumerate(chunk):
                seq, tokens = self.prompts[p]
                scratch = PROMPT_SEQS + j
                self.lib.eng_seq_cp(self.e, seq, scratch, -1, -1)
                own = [tokens[-1], *path]
                base = len(tokens) - 1
                batch += [(t, base + k, scratch, k == len(own) - 1) for k, t in enumerate(own)]
                last.append(len(batch) - 1)
            try:
                self.decode(batch)
                for i in last:
                    k = self.lib.eng_summarize(
                        self.e, i, bias_vec, self.keep, self.cont, self.punct, ct.c_float(floor),
                        self.ids, self.probs, ct.byref(ends), ct.byref(punct),
                    )
                    if k < 0:
                        raise RuntimeError("no distribution for a lookup")
                    out.append((
                        ct.string_at(self.ids, 4 * k), ct.string_at(self.probs, 4 * k),
                        ends.value, punct.value,
                    ))
            finally:
                for j in range(len(chunk)):
                    self.lib.eng_seq_rm(self.e, PROMPT_SEQS + j, -1, -1)
        return out


def _read(stream) -> Any:
    head = stream.read(4)
    if len(head) < 4:
        return None
    (n,) = struct.unpack("<I", head)
    return pickle.loads(stream.read(n))


def _write(stream, obj: Any) -> None:
    data = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
    stream.write(struct.pack("<I", len(data)) + data)
    stream.flush()


def main() -> None:
    # Replies on the real stdout; anything else written to fd 1 goes to stderr
    replies = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)
    requests = sys.stdin.buffer
    lib = _bind(sys.argv[1])
    model: Model | None = None
    while (req := _read(requests)) is not None:
        try:
            if model is None or model.path != req["path"]:
                if model is not None:
                    model.close()
                    model = None
                model = Model(lib, req["path"], req["n_ctx"])
            if req["op"] == "vocab":
                reply: Any = model.pieces
            else:
                reply = model.lookups(req["bias"], req["floor"], req["items"])
            _write(replies, {"ok": reply})
        except Exception as e:  # the backend reports it; this process goes on
            if model is not None and "llama_decode" in str(e):
                # After a failed compute (out of GPU memory, say) llama.cpp's
                # backend stays broken until it's made anew
                model.close()
                model = None
            _write(replies, {"error": f"{type(e).__name__}: {e}"})
    # Exit without llama.cpp's teardown (Metal asserts on it at exit)
    os._exit(0)


if __name__ == "__main__":
    main()
