"""ReminderInjection: insert configurable reminders into the context.

Inserts reminder text at specified positions in the final message list.
Research tool for studying the effects of in-context reminders on long
conversations.
"""

from qivis.generation.interventions import ContextIntervention, InterventionContext


class ReminderInjection(ContextIntervention):
    """Insert configurable reminder text at specified positions."""

    type_name = "reminder_injection"
    phase = "post_eviction"

    def __init__(
        self,
        content: str = "",
        position: str = "before_last",
        n: int = 5,
        fraction: float = 0.5,
        role: str = "user",
    ) -> None:
        self._content = content
        self._position = position
        self._n = n
        self._fraction = fraction
        self._role = role

    def apply(self, ctx: InterventionContext) -> InterventionContext:
        if not ctx.messages or not self._content:
            return ctx

        reminder = {"role": self._role, "content": self._content}

        if self._position == "before_last":
            insert_pos = max(0, len(ctx.messages) - 1)
            ctx.messages.insert(insert_pos, reminder)
            ctx.node_ids.insert(insert_pos, "__intervention_reminder__")

        elif self._position == "at_fraction":
            insert_pos = max(1, int(len(ctx.messages) * self._fraction))
            ctx.messages.insert(insert_pos, reminder)
            ctx.node_ids.insert(insert_pos, "__intervention_reminder__")

        elif self._position == "every_n_turns":
            if self._n <= 0:
                return ctx
            # Insert after every N messages, working backwards to preserve indices
            positions = []
            for i in range(self._n, len(ctx.messages), self._n):
                positions.append(i)
            for pos in reversed(positions):
                ctx.messages.insert(pos, dict(reminder))
                ctx.node_ids.insert(pos, "__intervention_reminder__")

        return ctx

    @classmethod
    def config_schema(cls) -> type | None:
        return None
