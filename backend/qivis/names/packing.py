"""How a lookup's Summary is stored in the cache: its token ids and probabilities
as arrays, compressed. Token text is kept once per model (name_vocab).

Two layouts, told apart by length (n tokens after a 4-byte count):
- 12n bytes: int32 ids, then float64 probabilities (the first layout).
- 8n bytes: uint32 gaps between sorted ids, then float32 probabilities.
llama.cpp computes probabilities in float32, so its lookups take the second;
anything float32 can't hold exactly takes the first. Either way a lookup read
back is the lookup stored.
"""

import zlib
from array import array

from qivis.names import engine


def pack(s: engine.Summary) -> bytes:
    pairs = sorted(zip(s.ids, s.ps, strict=True))
    ids = [i for i, _ in pairs]
    probs = [p for _, p in pairs]
    narrow = array("f", probs)
    if narrow.tolist() != probs:
        body = array("i", ids).tobytes() + array("d", probs).tobytes()
    else:
        gaps = array("I", [b - a for a, b in zip([0, *ids], ids, strict=False)])
        body = gaps.tobytes() + narrow.tobytes()
    return zlib.compress(len(ids).to_bytes(4, "little") + body)


def unpack(data: bytes) -> tuple[list[int], list[float]]:
    """Token ids and their probabilities, in either layout."""
    raw = zlib.decompress(data)
    n = int.from_bytes(raw[:4], "little")
    body = raw[4:]
    if len(body) == 12 * n:
        ids = array("i")
        ids.frombytes(body[:4 * n])
        probs = array("d")
        probs.frombytes(body[4 * n:])
        return list(ids), list(probs)
    gaps = array("I")
    gaps.frombytes(body[:4 * n])
    probs = array("f")
    probs.frombytes(body[4 * n:])
    ids, total = [], 0
    for g in gaps:
        total += g
        ids.append(total)
    return ids, list(probs)


def parse_and_pack(raw: bytes) -> tuple[engine.Summary, bytes]:
    """A llama.cpp response, summarized and packed (in a worker process)."""
    s = engine.summarize_response(raw)
    return s, pack(s)
