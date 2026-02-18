"""Context assembly for LLM generation.

ContextBuilder replaces the minimal assemble_messages() from Phase 0.4.
It handles system prompt separation, token counting, boundary-safe truncation,
and ContextUsage/EvictionReport output. Smart eviction (protected ranges,
summarization, digression groups) comes in Phase 3.
"""

from datetime import datetime

from qivis.models import ContextUsage, EvictionReport, EvictionStrategy

# Known model context limits (tokens). Falls back to DEFAULT for unknown models.
MODEL_CONTEXT_LIMITS: dict[str, int] = {
    # Anthropic
    "claude-opus-4-6": 200_000,
    "claude-sonnet-4-5-20250929": 200_000,
    "claude-haiku-4-5-20251001": 200_000,
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-haiku-20240307": 200_000,
    # OpenAI
    "gpt-5.2": 400_000,
    "gpt-5.2-pro": 400_000,
    "gpt-5-mini": 128_000,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
    "o4-mini": 200_000,
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
        include_timestamps: bool = False,
        include_thinking: bool = False,
        excluded_ids: set[str] | None = None,
        digression_groups: dict | None = None,
        excluded_group_ids: set[str] | None = None,
        anchored_ids: set[str] | None = None,
        eviction: EvictionStrategy | None = None,
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
        path_node_ids = {n["node_id"] for n in path}

        # 1b. Build effective excluded set from node-level + group-level exclusions
        effective_excluded = set(excluded_ids) if excluded_ids else set()
        if digression_groups and excluded_group_ids:
            for gid in excluded_group_ids:
                group_nodes = digression_groups.get(gid)
                if group_nodes and all(nid in path_node_ids for nid in group_nodes):
                    effective_excluded.update(group_nodes)

        # 2. Filter to API-sendable roles (exclude system, researcher_note, excluded nodes)
        messages = []
        excluded_token_total = 0
        excluded_node_count = 0
        excluded_node_id_list: list[str] = []
        for n in path:
            if n["role"] not in ("user", "assistant", "tool"):
                continue
            if n["node_id"] in effective_excluded:
                excluded_token_total += self._count_tokens(
                    self._maybe_prepend_timestamp(n, include_timestamps)
                )
                excluded_node_count += 1
                excluded_node_id_list.append(n["node_id"])
                continue
            content = self._maybe_prepend_timestamp(n, include_timestamps)
            if include_thinking and n["role"] == "assistant":
                thinking = n.get("thinking_content")
                if thinking:
                    content = f"[Model thinking: {thinking}]\n\n{content}"
            messages.append({"role": n["role"], "content": content})
        # Keep node_ids aligned with messages for eviction reporting
        message_node_ids = [
            n["node_id"]
            for n in path
            if n["role"] in ("user", "assistant", "tool")
            and n["node_id"] not in effective_excluded
        ]

        # 3. Count tokens
        system_tokens = self._count_tokens(system_prompt) if system_prompt else 0
        message_tokens = [self._count_tokens(m["content"]) for m in messages]
        total = system_tokens + sum(message_tokens)

        # 4. Evict if over limit (mode dispatch)
        report = EvictionReport()
        eviction_mode = eviction.mode if eviction else None

        if eviction_mode == "none":
            # No eviction — send everything even if over limit
            pass
        elif eviction_mode == "smart" and total > model_context_limit:
            messages, message_node_ids, message_tokens, report = self._smart_evict(
                messages, message_node_ids, message_tokens,
                system_tokens, model_context_limit,
                eviction, anchored_ids or set(),
            )
            total = system_tokens + sum(message_tokens)
        elif total > model_context_limit:
            # Default: truncate (eviction is None or mode="truncate")
            messages, message_node_ids, message_tokens, report = self._truncate_to_fit(
                messages, message_node_ids, message_tokens,
                system_tokens, model_context_limit,
            )
            total = system_tokens + sum(message_tokens)

        # 4b. Warning check (below limit but above threshold)
        if eviction and not report.eviction_applied and total <= model_context_limit:
            ratio = total / model_context_limit if model_context_limit > 0 else 0
            if ratio >= eviction.warn_threshold:
                pct = ratio * 100
                report.warning = (
                    f"Context at {pct:.0f}% of limit "
                    f"({total:,} / {model_context_limit:,} tokens)"
                )

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
            excluded_tokens=excluded_token_total,
            excluded_count=excluded_node_count,
            excluded_node_ids=excluded_node_id_list,
            evicted_node_ids=report.evicted_node_ids,
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
    def _maybe_prepend_timestamp(node: dict, include: bool) -> str:
        """Optionally prepend [YYYY-MM-DD HH:MM] to node content.

        Only applies to user and tool messages — assistant messages are left
        untouched to prevent the model from mirroring the timestamp format.
        """
        content = node.get("edited_content") or node["content"]
        if not include:
            return content
        if node["role"] == "assistant":
            return content
        created_at = node.get("created_at")
        if not created_at:
            return content
        try:
            dt = datetime.fromisoformat(created_at)
            return f"[{dt.strftime('%Y-%m-%d %H:%M')}] {content}"
        except (ValueError, TypeError):
            return content

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

    @staticmethod
    def _smart_evict(
        messages: list[dict[str, str]],
        node_ids: list[str],
        token_counts: list[int],
        system_tokens: int,
        limit: int,
        strategy: EvictionStrategy,
        anchored_ids: set[str],
    ) -> tuple[list[dict[str, str]], list[str], list[int], EvictionReport]:
        """Smart eviction: protect first/last turns and anchored nodes.

        Evicts unprotected messages oldest-first from the middle until total fits.
        """
        n = len(messages)
        total = system_tokens + sum(token_counts)

        # Build protected index set
        protected: set[int] = set()
        # First N turns
        for i in range(min(strategy.keep_first_turns, n)):
            protected.add(i)
        # Last N turns
        for i in range(max(0, n - strategy.recent_turns_to_keep), n):
            protected.add(i)
        # Anchored nodes
        if strategy.keep_anchored:
            for i, nid in enumerate(node_ids):
                if nid in anchored_ids:
                    protected.add(i)

        # Find evictable indices (unprotected, oldest first)
        evictable = [i for i in range(n) if i not in protected]

        evicted_ids: list[str] = []
        evicted_content: list[str] = []
        tokens_freed = 0
        evict_set: set[int] = set()

        for i in evictable:
            if total <= limit:
                break
            evict_set.add(i)
            evicted_ids.append(node_ids[i])
            if strategy.summarize_evicted:
                evicted_content.append(
                    f"{messages[i]['role']}: {messages[i]['content']}"
                )
            tokens_freed += token_counts[i]
            total -= token_counts[i]

        if not evict_set:
            # All messages protected — no eviction possible
            return messages, node_ids, token_counts, EvictionReport()

        # Filter out evicted messages
        new_messages = [m for i, m in enumerate(messages) if i not in evict_set]
        new_node_ids = [nid for i, nid in enumerate(node_ids) if i not in evict_set]
        new_token_counts = [t for i, t in enumerate(token_counts) if i not in evict_set]

        return new_messages, new_node_ids, new_token_counts, EvictionReport(
            eviction_applied=True,
            evicted_node_ids=evicted_ids,
            tokens_freed=tokens_freed,
            summary_inserted=False,
            summary_needed=bool(strategy.summarize_evicted and evicted_content),
            evicted_content=evicted_content,
            final_token_count=total,
        )
