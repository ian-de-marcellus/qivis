"""Discovering names by what they lean toward, not only how likely they are."""

import math

import pytest

from qivis.names.discover import Roles, Weights, discover, terms

TOK = {1: " John", 2: " Wren", 3: " Hal", 4: ".", 5: " Mind", 6: "y"}

# Next-token probabilities per prompt: the description (D), the control (C),
# the "it" version (I), and two failure descriptions (F1 cold, F2 dysregulated)
FIRST = {
    "D": {1: 0.50, 2: 0.02, 3: 0.20, 5: 0.28},
    "C": {1: 0.60, 2: 0.002, 3: 0.02, 5: 0.02},
    "I": {1: 0.50, 2: 0.004, 3: 0.20, 5: 0.28},
    "F1": {1: 0.50, 2: 0.004, 3: 0.40, 5: 0.10},
    "F2": {1: 0.50, 2: 0.004, 3: 0.05, 5: 0.45},
}


async def fetch(prompt: str, ids: list[int]) -> list[dict]:
    probs = FIRST[prompt] if not ids else {4: 1.0}
    return [{"id": i, "token": TOK[i], "prob": p} for i, p in probs.items()]


ROLES = Roles(description=["D"], control=["C"], it=["I"], failures=[["F1"], ["F2"]])


async def test_without_leans_the_likely_names_win():
    found = await discover(fetch, ROLES, Weights(ai=0, gender=0, character=0), alpha=0.01)
    assert [f.name for f in found][:2] == ["John", "Mind"]


async def test_with_leans_a_rare_leaning_name_wins():
    found = await discover(fetch, ROLES, Weights(ai=1, gender=1, character=1), alpha=0.01)
    assert found[0].name == "Wren"  # 10x vs the control, 5x over "it", 5x over both failures


async def test_the_character_term_is_the_worst_failure_mode():
    t = terms(ROLES, {"D": math.log(0.2), "C": math.log(0.02), "I": math.log(0.2),
                      "F1": math.log(0.4), "F2": math.log(0.05)})
    assert t["character"] == pytest.approx(math.log(0.2 / 0.4))  # Hal leans cold: penalized
    assert t["ai"] == pytest.approx(math.log(10))


async def test_implausible_tokens_are_not_tried():
    found = await discover(fetch, ROLES, Weights(), alpha=0.6)  # only tokens >= 0.6x the best (0.30)
    assert {f.name for f in found} == {"John"}


async def test_excluded_names_are_never_found():
    found = await discover(fetch, ROLES, Weights(), alpha=0.01, excluded={"Wren"})
    assert "Wren" not in {f.name for f in found} and found


async def test_names_under_the_floor_with_no_description_are_dropped():
    bare = {"B": {1: 0.5, 2: 1e-9, 3: 0.01, 5: 0.01}}  # Wren: almost never a name
    FIRST.update(bare)
    roles = Roles(description=["D"], control=["C"], it=["I"], failures=[["F1"], ["F2"]], bare=["B"])
    found = await discover(fetch, roles, Weights(), alpha=0.01, name_floor=1e-7)
    assert "Wren" not in {f.name for f in found} and "Hal" in {f.name for f in found}
    del FIRST["B"]


async def test_another_description_is_weighed_on_its_own():
    FIRST["O"] = {1: 0.50, 2: 0.10, 3: 0.20, 5: 0.28}  # Wren leans this way too
    roles = Roles(description=["D"], control=["C"], it=["I"], failures=[["F1"], ["F2"]], other=["O"])
    t = terms(roles, {"D": math.log(0.02), "C": math.log(0.002), "I": math.log(0.004),
                      "F1": math.log(0.004), "F2": math.log(0.004), "O": math.log(0.10)})
    assert t["other"] == pytest.approx(math.log(0.2))
    found = await discover(fetch, roles, Weights(ai=1, gender=1, character=1, other=0), alpha=0.01)
    assert found[0].name == "Wren"
    found = await discover(fetch, roles, Weights(ai=1, gender=1, character=1, other=4), alpha=0.01)
    assert found[0].name != "Wren"  # weighed heavily, leaning toward the other costs it the top
    del FIRST["O"]
