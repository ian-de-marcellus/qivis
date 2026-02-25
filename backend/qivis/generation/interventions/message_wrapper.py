"""MessageWrapper: wrap messages in configurable templates.

Wraps each message in a configurable template with access to role, index,
content, and timestamp. Research tool for XML-tagged context, structured
separators, and role annotation experiments.
"""

from datetime import datetime

from qivis.generation.interventions import ContextIntervention, InterventionContext


class MessageWrapper(ContextIntervention):
    """Wrap each message in a configurable template."""

    type_name = "message_wrapper"
    phase = "pre_eviction"

    def __init__(
        self,
        template: str = "{content}",
        apply_to_roles: list[str] | None = None,
        separator: str | None = None,
    ) -> None:
        self._template = template
        self._apply_to_roles = set(apply_to_roles) if apply_to_roles else None
        self._separator = separator

    @staticmethod
    def _format_timestamp(created_at: str | None) -> str:
        if not created_at:
            return ""
        try:
            dt = datetime.fromisoformat(created_at)
            return dt.strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            return ""

    def apply(self, ctx: InterventionContext) -> InterventionContext:
        for i, msg in enumerate(ctx.messages):
            should_wrap = (
                self._apply_to_roles is None
                or msg["role"] in self._apply_to_roles
            )

            content = msg["content"]

            if should_wrap:
                timestamp = ""
                if ctx.created_ats and i < len(ctx.created_ats):
                    timestamp = self._format_timestamp(ctx.created_ats[i])
                content = self._template.format(
                    content=content,
                    role=msg["role"],
                    index=i,
                    timestamp=timestamp,
                )

            if self._separator and i > 0:
                content = f"{self._separator}\n{content}"

            msg["content"] = content

        return ctx

    @classmethod
    def config_schema(cls) -> type | None:
        return None
