"""Pure divergence metrics for perturbation experiments.

All functions are stateless, side-effect free, and operate on plain data.
"""

from __future__ import annotations


def word_diff_ratio(a: str, b: str) -> float:
    """Fraction of words changed between two texts via LCS.

    Returns (added + removed) / (len_a + len_b).
    0.0 = identical, 1.0 = completely different.
    """
    words_a = a.split()
    words_b = b.split()

    if not words_a and not words_b:
        return 0.0
    if not words_a or not words_b:
        return 1.0

    lcs_len = _lcs_length(words_a, words_b)
    removed = len(words_a) - lcs_len
    added = len(words_b) - lcs_len
    return (added + removed) / (len(words_a) + len(words_b))


def normalized_edit_distance(a: str, b: str) -> float:
    """Character-level Levenshtein distance normalized to [0, 1].

    Uses Wagner-Fischer DP. Returns 0.0 for identical strings,
    1.0 for maximally different.
    """
    if a == b:
        return 0.0
    if not a or not b:
        return 1.0

    n, m = len(a), len(b)

    # Use two-row optimization for memory efficiency
    prev = list(range(m + 1))
    curr = [0] * (m + 1)

    for i in range(1, n + 1):
        curr[0] = i
        for j in range(1, m + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(
                prev[j] + 1,       # deletion
                curr[j - 1] + 1,   # insertion
                prev[j - 1] + cost,  # substitution
            )
        prev, curr = curr, prev

    return prev[m] / max(n, m)


def certainty_delta(
    logprobs_a: list[dict] | None,
    logprobs_b: list[dict] | None,
) -> float | None:
    """Difference in average token certainty between two responses.

    logprobs_a is the control, logprobs_b is the perturbation.
    Each entry should have a 'linear_prob' field.

    Returns avg(b) - avg(a):
    - Positive = perturbation is MORE confident
    - Negative = perturbation is LESS confident
    - None if either lacks logprobs
    """
    if not logprobs_a or not logprobs_b:
        return None

    avg_a = sum(t["linear_prob"] for t in logprobs_a) / len(logprobs_a)
    avg_b = sum(t["linear_prob"] for t in logprobs_b) / len(logprobs_b)
    return avg_b - avg_a


def length_ratio(a: str, b: str) -> float:
    """Length of b relative to a.

    > 1.0 means perturbation is longer, < 1.0 means shorter.
    Returns 0.0 if a is empty.
    """
    if not a:
        return 0.0
    return len(b) / len(a)


def _lcs_length(a: list[str], b: list[str]) -> int:
    """Length of longest common subsequence (word-level).

    Uses two-row DP for memory efficiency.
    """
    n, m = len(a), len(b)
    prev = [0] * (m + 1)
    curr = [0] * (m + 1)

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(prev[j], curr[j - 1])
        prev, curr = curr, [0] * (m + 1)

    return prev[m] if n > 0 else 0
