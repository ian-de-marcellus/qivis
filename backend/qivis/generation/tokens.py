"""Token counting abstractions for context building.

Provides a TokenCounter interface and implementations. The approximate counter
(len // 4) is the Phase 0.5 heuristic. Provider-specific counters (tiktoken,
Anthropic API) come in Phase 8.
"""

from abc import ABC, abstractmethod


class TokenCounter(ABC):
    """Interface for counting tokens in text."""

    @abstractmethod
    def count(self, text: str) -> int:
        """Return the estimated token count for the given text."""
        ...


class ApproximateTokenCounter(TokenCounter):
    """len(text) // 4 — the original heuristic.

    Roughly 4 characters per token for English text. Adequate for
    boundary-safe truncation decisions; not precise enough for
    research-grade token attribution.
    """

    def count(self, text: str) -> int:
        return len(text) // 4
