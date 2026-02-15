"""Context assembly for LLM generation.

ContextBuilder replaces the minimal assemble_messages() from Phase 0.4.
It handles system prompt separation, token counting, boundary-safe truncation,
and ContextUsage/EvictionReport output. Smart eviction (protected ranges,
summarization, digression groups) comes in Phase 3.
"""

from qivis.models import ContextUsage, EvictionReport

# Known model context limits (tokens). Falls back to DEFAULT for unknown models.
MODEL_CONTEXT_LIMITS: dict[str, int] = {
    # Anthropic
    "claude-opus-4-6": 200_000,
    "claude-sonnet-4-5-20250929": 200_000,
    "claude-haiku-4-5-20251001": 200_000,
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-haiku-20240307": 200_000,
    # OpenAI
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
    "o1": 200_000,
    "o3-mini": 200_000,
}
DEFAULT_CONTEXT_LIMIT = 200_000


def get_model_context_limit(model: str) -> int:
    """Look up context limit for a model, falling back to a conservative default."""
    return MODEL_CONTEXT_LIMITS.get(model, DEFAULT_CONTEXT_LIMIT)


class ContextBuilder:
    """Assembles the messages array for LLM generation.

    Handles:
    - Parent-chain walking to build message path
    - System prompt separation (not in messages array)
    - Token counting (character approximation: len // 4)
    - Boundary-safe truncation (whole messages, oldest first)
    - ContextUsage and EvictionReport output

    Phase 0.5 stubs: excluded_ids, digression_groups, bookmarked_ids,
    eviction strategy, participant perspective are accepted but ignored.
    """

    def build(
        self,
        nodes: list[dict],
        target_node_id: str,
        system_prompt: str | None,
        model_context_limit: int,
        *,
        # Phase 3+ parameters — accepted but ignored in 0.5
        excluded_ids: set[str] | None = None,
        digression_groups: dict | None = None,
        excluded_group_ids: set[str] | None = None,
        bookmarked_ids: set[str] | None = None,
        eviction: object | None = None,
        participant: object | None = None,
        mode: str = "chat",
    ) -> tuple[list[dict[str, str]], ContextUsage, EvictionReport]:
        """Build messages array with boundary-safe truncation.

        Returns (messages, context_usage, eviction_report).

        Raises:
            ValueError: If target_node_id is not found or parent chain is broken.
        """
        # 1. Walk the parent chain to get messages in chronological order
        path = self._walk_path(nodes, target_node_id)

        # 2. Filter to API-sendable roles (exclude system, researcher_note)
        messages = [
            {"role": n["role"], "content": n["content"]}
            for n in path
            if n["role"] in ("user", "assistant", "tool")
        ]
        # Keep node_ids aligned with messages for eviction reporting
        message_node_ids = [
            n["node_id"]
            for n in path
            if n["role"] in ("user", "assistant", "tool")
        ]

        # 3. Count tokens
        system_tokens = self._count_tokens(system_prompt) if system_prompt else 0
        message_tokens = [self._count_tokens(m["content"]) for m in messages]
        total = system_tokens + sum(message_tokens)

        # 4. Truncate if over limit
        report = EvictionReport()
        if total > model_context_limit:
            messages, message_node_ids, message_tokens, report = self._truncate_to_fit(
                messages, message_node_ids, message_tokens,
                system_tokens, model_context_limit,
            )
            total = system_tokens + sum(message_tokens)

        # 5. Compute breakdown by role
        breakdown: dict[str, int] = {"system": system_tokens}
        for msg, tok in zip(messages, message_tokens):
            role = msg["role"]
            breakdown[role] = breakdown.get(role, 0) + tok

        report.final_token_count = total

        usage = ContextUsage(
            total_tokens=total,
            max_tokens=model_context_limit,
            breakdown=breakdown,
            excluded_tokens=0,  # Phase 0.5: no exclusions yet
            excluded_count=0,
        )

        return messages, usage, report

    def _walk_path(self, nodes: list[dict], target_node_id: str) -> list[dict]:
        """Walk parent chain from target to root, return in chronological order.

        Raises ValueError if target not found, chain is broken, or cycle detected.
        """
        by_id = {n["node_id"]: n for n in nodes}
        if target_node_id not in by_id:
            raise ValueError(f"Node not found: {target_node_id}")

        chain: list[dict] = []
        current_id: str | None = target_node_id
        visited: set[str] = set()

        while current_id is not None:
            if current_id in visited:
                raise ValueError(f"Cycle detected at node: {current_id}")
            visited.add(current_id)
            node = by_id.get(current_id)
            if node is None:
                raise ValueError(f"Broken chain: node {current_id} not found")
            chain.append(node)
            current_id = node.get("parent_id")

        chain.reverse()
        return chain

    @staticmethod
    def _count_tokens(text: str) -> int:
        """Approximate token count. len(text) // 4 for Phase 0.5.

        Good enough for boundary-safe truncation. Structure allows swapping
        in provider-specific tokenizers later.
        """
        return len(text) // 4

    @staticmethod
    def _truncate_to_fit(
        messages: list[dict[str, str]],
        node_ids: list[str],
        token_counts: list[int],
        system_tokens: int,
        limit: int,
    ) -> tuple[list[dict[str, str]], list[str], list[int], EvictionReport]:
        """Drop whole messages from the beginning until total fits in limit.

        Never drops the last message. System tokens are always preserved.
        """
        total = system_tokens + sum(token_counts)
        evicted_ids: list[str] = []
        tokens_freed = 0

        # Drop from the front (oldest first), but never the last message
        while total > limit and len(messages) > 1:
            evicted_ids.append(node_ids[0])
            freed = token_counts[0]
            tokens_freed += freed
            total -= freed
            messages = messages[1:]
            node_ids = node_ids[1:]
            token_counts = token_counts[1:]

        return messages, node_ids, token_counts, EvictionReport(
            eviction_applied=True,
            evicted_node_ids=evicted_ids,
            tokens_freed=tokens_freed,
            summary_inserted=False,
            final_token_count=total,
        )
