"""The name engine: exact name probabilities, by its rules for what a name is."""

import pytest

from qivis.names.engine import Lookups, enumerate_names, score_name

TOK = {
    1: " Ai", 2: "den", 3: ".", 4: " A", 5: " computer", 6: " The", 7: " Dr",
    8: " Anderson", 9: " Sun", 10: ",", 11: " HAL", 12: "'s", 13: " I", 14: " am",
}

# Next-token probabilities after each prefix (token ids); unlisted mass ends words
TREE: dict[tuple[int, ...], dict[int, float]] = {
    (): {1: 0.20, 4: 0.20, 6: 0.15, 7: 0.10, 9: 0.05, 11: 0.10, 13: 0.10, 5: 0.10},
    (1,): {2: 0.5, 3: 0.5},            # " Ai" -> "Aiden" half the time, "Ai." half
    (1, 2): {3: 0.8, 12: 0.2},         # "Aiden." or "Aiden's"
    (4,): {5: 0.75, 3: 0.25},          # " A computer" (article) or " A." (initial)
    (6,): {5: 1.0},
    (7,): {3: 1.0},                    # " Dr" "."
    (7, 3): {8: 1.0},                  # " Dr." " Anderson"
    (7, 3, 8): {3: 1.0},
    (9,): {10: 1.0},                   # " Sun,"
    (11,): {3: 1.0},
    (13,): {14: 1.0},                  # " I am": a pronoun, not a name
}


async def fetch(ids: list[int]) -> list[dict]:
    probs = TREE.get(tuple(ids), {3: 1.0})
    return [{"id": i, "token": TOK[i], "prob": p} for i, p in probs.items()]


async def test_names_and_their_exact_probabilities():
    names, capital = await enumerate_names(Lookups(fetch), top=10)
    assert capital == pytest.approx(0.90)  # every token here but " computer"
    assert names == pytest.approx({
        "Ai": 0.20 * 0.5,             # " Ai" "." : a whole word
        "Aiden": 0.20 * 0.5 * 1.0,    # both "Aiden." and "Aiden's" end the word
        "HAL": 0.10,
        "Dr. Anderson": 0.10,         # a title, followed to the name
        "A": 0.20 * 0.25,             # only before punctuation: an initial
        "Sun": 0.05,
    })
    assert "The" not in names and "I" not in names  # function words, a pronoun


async def test_only_the_top_are_kept_in_order():
    names, _ = await enumerate_names(Lookups(fetch), top=2)
    # Four names tie at 0.10, above "A" (0.05) and "Sun" (0.05): two of them come back
    assert len(names) == 2 and list(names.values()) == pytest.approx([0.10, 0.10])


async def test_scoring_a_name_along_its_tokens_matches():
    lookups = Lookups(fetch)
    assert await score_name(lookups, [1, 2], "Aiden") == pytest.approx(0.10)
    assert await score_name(lookups, [7, 3, 8], "Dr. Anderson") == pytest.approx(0.10)
    assert await score_name(lookups, [4], "A") == pytest.approx(0.05)
    assert await score_name(lookups, [6], "The") == 0.0


async def test_lookups_are_fetched_once():
    lookups = Lookups(fetch)
    await enumerate_names(lookups, top=10)
    before = lookups.queries
    await score_name(lookups, [1, 2], "Aiden")
    assert lookups.queries == before  # already known from the enumeration
