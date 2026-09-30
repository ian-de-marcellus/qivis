"""The lookup cache's storage: what's read back is exactly what was stored."""

from qivis.names import packing
from qivis.names.engine import Summary


def _roundtrip(probs: dict[int, float]) -> list[tuple[int, float]]:
    s = Summary(probs={i: (f"t{i}", p) for i, p in probs.items()}, ends=0.5, ends_with_punctuation=0.1)
    ids, back = packing.unpack(packing.pack(s))
    return list(zip(ids, back, strict=True))


def test_float32_probabilities_are_stored_compactly_and_exactly():
    probs = {5: 0.5, 70000: 0.25, 12: 2.0 ** -30, 99999: 0.125}  # float32 holds these exactly
    assert _roundtrip(probs) == sorted(probs.items())
    wide = Summary(probs={i: ("", 0.1) for i in range(1000)}, ends=0, ends_with_punctuation=0)
    narrow = Summary(probs={i: ("", 0.125) for i in range(1000)}, ends=0, ends_with_punctuation=0)
    assert len(packing.pack(narrow)) < len(packing.pack(wide))


def test_anything_float32_cant_hold_is_stored_in_full():
    probs = {3: 0.1, 8: 1e-11 / 3}
    assert _roundtrip(probs) == sorted(probs.items())


def test_the_first_layout_still_reads():
    import zlib
    from array import array

    old = zlib.compress((2).to_bytes(4, "little") + array("i", [4, 9]).tobytes() + array("d", [0.1, 0.2]).tobytes())
    assert packing.unpack(old) == ([4, 9], [0.1, 0.2])
