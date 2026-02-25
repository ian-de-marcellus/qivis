"""SystemPromptReposition: move system prompt into a message.

Moves system prompt content out of the `system_prompt` parameter and into
a user message at a configurable position. Some models respond differently
to the same instructions in different positions.
"""

from qivis.generation.interventions import ContextIntervention, InterventionContext


class SystemPromptReposition(ContextIntervention):
    """Move system prompt into a user message at a configurable position."""

    type_name = "system_prompt_reposition"
    phase = "pre_eviction"

    def __init__(
        self,
        placement: str = "first_user_message",
        wrapper_template: str = "[System Instructions]\n{content}\n[/System Instructions]",
    ) -> None:
        self._placement = placement
        self._wrapper_template = wrapper_template

    def apply(self, ctx: InterventionContext) -> InterventionContext:
        if not ctx.system_prompt or not ctx.messages:
            return ctx

        wrapped = self._wrapper_template.format(content=ctx.system_prompt)

        if self._placement == "first_user_message":
            ctx.messages[0]["content"] = f"{wrapped}\n\n{ctx.messages[0]['content']}"
            ctx.system_prompt = None

        elif self._placement == "standalone_preamble":
            preamble = {"role": "user", "content": wrapped}
            ctx.messages.insert(0, preamble)
            ctx.node_ids.insert(0, "__intervention_system_prompt__")
            ctx.system_prompt = None

        elif self._placement == "last_before_final":
            insert_pos = max(0, len(ctx.messages) - 1)
            preamble = {"role": "user", "content": wrapped}
            ctx.messages.insert(insert_pos, preamble)
            ctx.node_ids.insert(insert_pos, "__intervention_system_prompt__")
            ctx.system_prompt = None

        return ctx

    @classmethod
    def config_schema(cls) -> type | None:
        return None
