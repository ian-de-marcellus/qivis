"""Perturbation experiment service: systematic context manipulation with divergence measurement.

An experiment regenerates one turn several times: a control with the context
as it is, then once per perturbation (a digression toggled, a node excluded,
a different system prompt, an intervention switched). Each result is a node
recorded like any other generation -- what it was sent, in what mode -- and
the report compares each perturbation's reply to the control's.

The anchor is the turn being regenerated. For an assistant turn, results are
its siblings (the model answers the same parent it answered); for any other
turn, results answer it.
"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

from qivis.events.log import EventLog
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.divergence import (
    certainty_delta,
    length_ratio,
    normalized_edit_distance,
    word_diff_ratio,
)
from qivis.generation.service import (
    GenerationService,
    LoadedContext,
    NodeNotFoundForGenerationError,
    RhizomeNotFoundForGenerationError,
    Target,
)
from qivis.models import PerturbationReportGeneratedPayload, SamplingParams
from qivis.providers.base import GenerationResult, LLMProvider, StreamChunk
from qivis.rhizomes.schemas import (
    DivergenceMetrics,
    PerturbationConfig,
    PerturbationReportResponse,
    PerturbationStepResponse,
)


class PerturbationService:
    """Orchestrates perturbation experiments: control + N perturbations, then divergence."""

    def __init__(
        self,
        gen_service: GenerationService,
        store: EventStore,
        projector: StateProjector,
    ) -> None:
        self._gen_svc = gen_service
        self._projector = projector
        self._events = EventLog(store, projector)

    async def run_experiment(
        self,
        rhizome_id: str,
        node_id: str,
        perturbations: list[PerturbationConfig],
        provider: LLMProvider,
        *,
        model: str | None = None,
        sampling_params: SamplingParams | None = None,
        include_control: bool = True,
    ) -> PerturbationReportResponse:
        """Run an experiment to completion and return its report."""
        async for chunk in self.run_experiment_stream(
            rhizome_id, node_id, perturbations, provider,
            model=model, sampling_params=sampling_params, include_control=include_control,
        ):
            if chunk.type == "perturbation_complete" and chunk.data is not None:
                return PerturbationReportResponse.model_validate(chunk.data)
        raise RuntimeError("perturbation experiment ended without a report")

    async def run_experiment_stream(
        self,
        rhizome_id: str,
        node_id: str,
        perturbations: list[PerturbationConfig],
        provider: LLMProvider,
        *,
        model: str | None = None,
        sampling_params: SamplingParams | None = None,
        include_control: bool = True,
    ) -> AsyncIterator[StreamChunk]:
        """Yields perturbation_step, text_delta, message_stop per step (completion_index
        is the step), then perturbation_complete with the report."""
        ctx = await self._gen_svc.load(
            rhizome_id,
            await self._answering(rhizome_id, node_id),
            sampling_params=sampling_params,
        )
        experiment_id = str(uuid4())

        plan: list[tuple[str, PerturbationConfig | None]] = []
        if include_control:
            plan.append(("Control (unmodified)", None))
        plan += [(config.label or self._auto_label(config), config) for config in perturbations]

        steps: list[PerturbationStepResponse] = []
        results: list[GenerationResult] = []
        for index, (label, config) in enumerate(plan):
            yield StreamChunk(type="perturbation_step", data={
                "step": index + 1, "total": len(plan),
                "type": config.type if config else "control", "label": label,
            })
            step_ctx = self._apply_perturbation(ctx, config) if config else ctx
            [p] = await self._gen_svc.prepare(
                step_ctx, [Target(provider, model)],
                generation_id=experiment_id, device_id="perturbation",
            )
            p = dataclasses.replace(p, completion_index=index)
            async for chunk in self._gen_svc.stream(p):
                yield chunk
                if chunk.node_id and chunk.result is not None:
                    results.append(chunk.result)
                    steps.append(PerturbationStepResponse(
                        label=label,
                        type=config.type if config else "control",
                        config=config.model_dump(exclude_none=True) if config else None,
                        content=chunk.result.content,
                        node_id=chunk.node_id,
                        latency_ms=chunk.result.latency_ms,
                        usage=chunk.result.usage,
                    ))

        report = PerturbationReportResponse(
            report_id=str(uuid4()),
            rhizome_id=rhizome_id,
            experiment_id=experiment_id,
            node_id=node_id,
            provider=provider.name,
            model=model or ctx.rhizome.get("default_model") or "",
            include_control=include_control,
            steps=steps,
            divergence=self._compute_divergence(steps, results),
            created_at=datetime.now(UTC).isoformat(),
        )
        await self._emit_report(rhizome_id, report)
        yield StreamChunk(type="perturbation_complete", data=report.model_dump())

    async def _answering(self, rhizome_id: str, anchor_id: str) -> str | None:
        """The node the experiment's generations answer (see module docstring)."""
        if await self._projector.get_rhizome(rhizome_id) is None:
            raise RhizomeNotFoundForGenerationError(rhizome_id)
        anchor = await self._projector.get_node(rhizome_id, anchor_id)
        if anchor is None:
            raise NodeNotFoundForGenerationError(anchor_id)
        return anchor["parent_id"] if anchor["role"] == "assistant" else anchor_id

    # -- Context perturbation --

    @staticmethod
    def _apply_perturbation(ctx: LoadedContext, config: PerturbationConfig) -> LoadedContext:
        """A copy of the context with one perturbation applied."""
        if config.type == "digression_toggle" and config.group_id:
            excluded = set(ctx.excluded_group_ids)
            if config.include is False:
                excluded.add(config.group_id)
            elif config.include is True:
                excluded.discard(config.group_id)
            return dataclasses.replace(ctx, excluded_group_ids=excluded)

        if config.type == "node_exclusion" and config.node_id:
            excluded = set(ctx.excluded_ids)
            if config.exclude is True:
                excluded.add(config.node_id)
            elif config.exclude is False:
                excluded.discard(config.node_id)
            return dataclasses.replace(ctx, excluded_ids=excluded)

        if config.type == "system_prompt":
            return dataclasses.replace(ctx, system_prompt=config.system_prompt)

        if config.type == "intervention_toggle":
            raw_configs = list(ctx.metadata.get("context_interventions", []))
            idx = config.intervention_index
            if idx is not None and 0 <= idx < len(raw_configs):
                raw_configs[idx] = {
                    **raw_configs[idx],
                    "enabled": config.enabled if config.enabled is not None else True,
                }
                return dataclasses.replace(
                    ctx, metadata={**ctx.metadata, "context_interventions": raw_configs},
                )
        return ctx

    # -- Divergence --

    @staticmethod
    def _compute_divergence(
        steps: list[PerturbationStepResponse],
        results: list[GenerationResult],
    ) -> list[DivergenceMetrics]:
        """Compare each perturbation's reply to the control's (none without a control)."""
        control = next(
            (i for i, s in enumerate(steps) if s.type == "control"), None,
        )
        if control is None:
            return []
        control_tokens = _logprob_tokens(results[control])
        return [
            DivergenceMetrics(
                step_index=i,
                label=step.label,
                word_diff_ratio=word_diff_ratio(steps[control].content, step.content),
                edit_distance=normalized_edit_distance(steps[control].content, step.content),
                certainty_delta=certainty_delta(control_tokens, _logprob_tokens(results[i])),
                length_ratio=length_ratio(steps[control].content, step.content),
            )
            for i, step in enumerate(steps) if i != control
        ]

    # -- Report --

    async def _emit_report(self, rhizome_id: str, report: PerturbationReportResponse) -> None:
        await self._events.emit(rhizome_id, "PerturbationReportGenerated",
            PerturbationReportGeneratedPayload(
                report_id=report.report_id,
                experiment_id=report.experiment_id,
                node_id=report.node_id,
                provider=report.provider,
                model=report.model,
                include_control=report.include_control,
                steps=[s.model_dump() for s in report.steps],
                divergence=[d.model_dump() for d in report.divergence],
            ),
            device_id="perturbation",
        )

    @staticmethod
    def _auto_label(config: PerturbationConfig) -> str:
        """Generate a human-readable label for a perturbation config."""
        if config.type == "digression_toggle":
            action = "Include" if config.include else "Exclude"
            return f"{action} digression group"
        elif config.type == "node_exclusion":
            action = "Exclude" if config.exclude else "Include"
            return f"{action} node"
        elif config.type == "system_prompt":
            preview = (config.system_prompt or "")[:40]
            return f"System prompt: {preview}"
        elif config.type == "intervention_toggle":
            action = "Enable" if config.enabled else "Disable"
            return f"{action} intervention #{config.intervention_index}"
        return config.type


def _logprob_tokens(result: GenerationResult) -> list[dict] | None:
    if result.logprobs and result.logprobs.tokens:
        return [t.model_dump() for t in result.logprobs.tokens]
    return None
