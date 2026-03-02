"""Perturbation experiment service: systematic context manipulation with divergence measurement."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.context import get_model_context_limit
from qivis.generation.divergence import (
    certainty_delta,
    length_ratio,
    normalized_edit_distance,
    word_diff_ratio,
)
from qivis.generation.service import GenerationService
from qivis.models import (
    EventEnvelope,
    NodeCreatedPayload,
    PerturbationReportGeneratedPayload,
    SamplingParams,
)
from qivis.providers.base import GenerationRequest, GenerationResult, LLMProvider, StreamChunk
from qivis.rhizomes.schemas import (
    DivergenceMetrics,
    PerturbationConfig,
    PerturbationReportResponse,
    PerturbationStepResponse,
)
from qivis.rhizomes.service import RhizomeService


class PerturbationService:
    """Orchestrates perturbation experiments.

    Resolves context once, then generates N+1 responses (control + perturbations),
    computing divergence metrics between control and each perturbation.
    """

    def __init__(
        self,
        gen_service: GenerationService,
        store: EventStore,
        projector: StateProjector,
    ) -> None:
        self._gen_svc = gen_service
        self._store = store
        self._projector = projector

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
        """Run a perturbation experiment (non-streaming).

        Returns a complete report with divergence metrics.
        """
        resolved = await self._gen_svc._resolve_context(
            rhizome_id, node_id, model, None, sampling_params,
        )
        (rhizome, nodes, resolved_model, resolved_prompt, resolved_params,
         include_ts, include_think, excluded_ids, dg_map, excluded_gids,
         anchored_ids, eviction, metadata) = resolved

        experiment_id = str(uuid4())
        steps: list[PerturbationStepResponse] = []
        control_result: _StepResult | None = None

        # Parent of the anchor node — perturbation results are siblings of anchor
        anchor_parent_id = None
        for n in nodes:
            if n["node_id"] == node_id:
                anchor_parent_id = n.get("parent_id")
                break

        # Control step
        if include_control:
            result = await self._run_step(
                rhizome_id=rhizome_id,
                experiment_id=experiment_id,
                parent_id=anchor_parent_id,
                provider=provider,
                nodes=nodes,
                node_id=node_id,
                system_prompt=resolved_prompt,
                model=resolved_model,
                params=resolved_params,
                metadata=metadata,
                include_ts=include_ts,
                include_think=include_think,
                excluded_ids=excluded_ids,
                dg_map=dg_map,
                excluded_gids=excluded_gids,
                anchored_ids=anchored_ids,
                eviction=eviction,
            )
            control_result = result
            steps.append(PerturbationStepResponse(
                label="Control (unmodified)",
                type="control",
                config=None,
                content=result.content,
                node_id=result.node_id,
                latency_ms=result.latency_ms,
                usage=result.usage,
            ))

        # Perturbation steps
        for config in perturbations:
            label = config.label or self._auto_label(config)
            patched = self._apply_perturbation(
                system_prompt=resolved_prompt,
                excluded_ids=excluded_ids,
                excluded_gids=excluded_gids,
                metadata=metadata,
                config=config,
            )

            result = await self._run_step(
                rhizome_id=rhizome_id,
                experiment_id=experiment_id,
                parent_id=anchor_parent_id,
                provider=provider,
                nodes=nodes,
                node_id=node_id,
                system_prompt=patched["system_prompt"],
                model=resolved_model,
                params=resolved_params,
                metadata=patched["metadata"],
                include_ts=include_ts,
                include_think=include_think,
                excluded_ids=patched["excluded_ids"],
                dg_map=dg_map,
                excluded_gids=patched["excluded_gids"],
                anchored_ids=anchored_ids,
                eviction=eviction,
            )
            steps.append(PerturbationStepResponse(
                label=label,
                type=config.type,
                config=config.model_dump(exclude_none=True),
                content=result.content,
                node_id=result.node_id,
                latency_ms=result.latency_ms,
                usage=result.usage,
            ))

        # Compute divergence
        divergence = self._compute_divergence(control_result, steps)

        # Emit report
        report_id = str(uuid4())
        report = PerturbationReportResponse(
            report_id=report_id,
            rhizome_id=rhizome_id,
            experiment_id=experiment_id,
            node_id=node_id,
            provider=provider.name,
            model=resolved_model,
            include_control=include_control,
            steps=steps,
            divergence=divergence,
            created_at=datetime.now(UTC).isoformat(),
        )
        await self._emit_report(rhizome_id, report)
        return report

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
        """Run a perturbation experiment with SSE streaming.

        Yields perturbation_step, text_delta, message_stop, perturbation_complete events.
        """
        resolved = await self._gen_svc._resolve_context(
            rhizome_id, node_id, model, None, sampling_params,
        )
        (rhizome, nodes, resolved_model, resolved_prompt, resolved_params,
         include_ts, include_think, excluded_ids, dg_map, excluded_gids,
         anchored_ids, eviction, metadata) = resolved

        experiment_id = str(uuid4())
        steps: list[PerturbationStepResponse] = []
        control_result: _StepResult | None = None
        total = len(perturbations) + (1 if include_control else 0)
        step_num = 0

        anchor_parent_id = None
        for n in nodes:
            if n["node_id"] == node_id:
                anchor_parent_id = n.get("parent_id")
                break

        # Control step
        if include_control:
            step_num += 1
            yield StreamChunk(
                type="perturbation_step",
                text=json.dumps({
                    "step": step_num, "total": total,
                    "type": "control", "label": "Control (unmodified)",
                }),
            )

            result_gen = self._run_step_stream(
                rhizome_id=rhizome_id,
                experiment_id=experiment_id,
                parent_id=anchor_parent_id,
                provider=provider,
                nodes=nodes,
                node_id=node_id,
                system_prompt=resolved_prompt,
                model=resolved_model,
                params=resolved_params,
                metadata=metadata,
                include_ts=include_ts,
                include_think=include_think,
                excluded_ids=excluded_ids,
                dg_map=dg_map,
                excluded_gids=excluded_gids,
                anchored_ids=anchored_ids,
                eviction=eviction,
                step_index=step_num - 1,
                yield_chunks=True,
            )
            # Consume generator, yielding text_delta chunks
            gen_result = None
            async for chunk in result_gen:
                if chunk.type == "step_result":
                    gen_result = chunk.result
                else:
                    yield chunk

            if gen_result:
                control_result = _StepResult(
                    content=gen_result.content,
                    node_id="",  # filled below
                    latency_ms=gen_result.latency_ms,
                    usage=gen_result.usage,
                    logprobs_tokens=_extract_logprob_tokens(gen_result),
                )
                # Emit the node
                node_resp = await self._emit_step_node(
                    rhizome_id, experiment_id, anchor_parent_id,
                    gen_result, provider.name, resolved_prompt,
                    resolved_params, resolved_model,
                )
                control_result.node_id = node_resp.node_id

                steps.append(PerturbationStepResponse(
                    label="Control (unmodified)",
                    type="control",
                    config=None,
                    content=gen_result.content,
                    node_id=node_resp.node_id,
                    latency_ms=gen_result.latency_ms,
                    usage=gen_result.usage,
                ))

                yield StreamChunk(
                    type="message_stop",
                    text=json.dumps({
                        "node_id": node_resp.node_id,
                        "content": gen_result.content,
                        "finish_reason": gen_result.finish_reason,
                        "step_index": step_num - 1,
                    }),
                    is_final=False,
                    result=gen_result,
                    completion_index=step_num - 1,
                )

        # Perturbation steps
        for config in perturbations:
            step_num += 1
            label = config.label or self._auto_label(config)

            yield StreamChunk(
                type="perturbation_step",
                text=json.dumps({
                    "step": step_num, "total": total,
                    "type": config.type, "label": label,
                }),
            )

            patched = self._apply_perturbation(
                system_prompt=resolved_prompt,
                excluded_ids=excluded_ids,
                excluded_gids=excluded_gids,
                metadata=metadata,
                config=config,
            )

            result_gen = self._run_step_stream(
                rhizome_id=rhizome_id,
                experiment_id=experiment_id,
                parent_id=anchor_parent_id,
                provider=provider,
                nodes=nodes,
                node_id=node_id,
                system_prompt=patched["system_prompt"],
                model=resolved_model,
                params=resolved_params,
                metadata=patched["metadata"],
                include_ts=include_ts,
                include_think=include_think,
                excluded_ids=patched["excluded_ids"],
                dg_map=dg_map,
                excluded_gids=patched["excluded_gids"],
                anchored_ids=anchored_ids,
                eviction=eviction,
                step_index=step_num - 1,
                yield_chunks=True,
            )
            gen_result = None
            async for chunk in result_gen:
                if chunk.type == "step_result":
                    gen_result = chunk.result
                else:
                    yield chunk

            if gen_result:
                node_resp = await self._emit_step_node(
                    rhizome_id, experiment_id, anchor_parent_id,
                    gen_result, provider.name, patched["system_prompt"],
                    resolved_params, resolved_model,
                )

                steps.append(PerturbationStepResponse(
                    label=label,
                    type=config.type,
                    config=config.model_dump(exclude_none=True),
                    content=gen_result.content,
                    node_id=node_resp.node_id,
                    latency_ms=gen_result.latency_ms,
                    usage=gen_result.usage,
                ))

                yield StreamChunk(
                    type="message_stop",
                    text=json.dumps({
                        "node_id": node_resp.node_id,
                        "content": gen_result.content,
                        "finish_reason": gen_result.finish_reason,
                        "step_index": step_num - 1,
                    }),
                    is_final=False,
                    result=gen_result,
                    completion_index=step_num - 1,
                )

        # Compute divergence and emit report
        divergence = self._compute_divergence(control_result, steps)

        report_id = str(uuid4())
        report = PerturbationReportResponse(
            report_id=report_id,
            rhizome_id=rhizome_id,
            experiment_id=experiment_id,
            node_id=node_id,
            provider=provider.name,
            model=resolved_model,
            include_control=include_control,
            steps=steps,
            divergence=divergence,
            created_at=datetime.now(UTC).isoformat(),
        )
        await self._emit_report(rhizome_id, report)

        yield StreamChunk(
            type="perturbation_complete",
            text=json.dumps(report.model_dump()),
        )

    # -- Context perturbation --

    @staticmethod
    def _apply_perturbation(
        *,
        system_prompt: str | None,
        excluded_ids: set[str],
        excluded_gids: set[str],
        metadata: dict,
        config: PerturbationConfig,
    ) -> dict:
        """Apply a single perturbation to context kwargs. Returns patched copies."""
        patched_prompt = system_prompt
        patched_excl_ids = set(excluded_ids)
        patched_excl_gids = set(excluded_gids)
        patched_meta = dict(metadata)

        if config.type == "digression_toggle":
            if config.include is False:
                patched_excl_gids.add(config.group_id)
            elif config.include is True:
                patched_excl_gids.discard(config.group_id)

        elif config.type == "node_exclusion":
            if config.exclude is True:
                patched_excl_ids.add(config.node_id)
            elif config.exclude is False:
                patched_excl_ids.discard(config.node_id)

        elif config.type == "system_prompt":
            patched_prompt = config.system_prompt

        elif config.type == "intervention_toggle":
            raw_configs = list(patched_meta.get("context_interventions", []))
            idx = config.intervention_index
            if idx is not None and 0 <= idx < len(raw_configs):
                raw_configs[idx] = {
                    **raw_configs[idx],
                    "enabled": config.enabled if config.enabled is not None else True,
                }
                patched_meta["context_interventions"] = raw_configs

        return {
            "system_prompt": patched_prompt,
            "excluded_ids": patched_excl_ids,
            "excluded_gids": patched_excl_gids,
            "metadata": patched_meta,
        }

    # -- Step execution --

    async def _run_step(
        self,
        *,
        rhizome_id: str,
        experiment_id: str,
        parent_id: str | None,
        provider: LLMProvider,
        nodes: list[dict],
        node_id: str,
        system_prompt: str | None,
        model: str,
        params: SamplingParams,
        metadata: dict,
        include_ts: bool,
        include_think: bool,
        excluded_ids: set[str],
        dg_map: dict,
        excluded_gids: set[str],
        anchored_ids: set[str],
        eviction,
    ) -> _StepResult:
        """Run a single generation step with the given context kwargs."""
        context_limit = get_model_context_limit(model)
        pipeline = GenerationService._resolve_interventions(metadata)

        messages, ctx_usage, eviction_report, final_prompt, active_intv = (
            self._gen_svc._build_context_with_interventions(
                nodes=nodes,
                node_id=node_id,
                system_prompt=system_prompt,
                context_limit=context_limit,
                include_timestamps=include_ts,
                include_thinking=include_think,
                excluded_ids=excluded_ids,
                digression_groups=dg_map,
                excluded_group_ids=excluded_gids,
                anchored_ids=anchored_ids,
                eviction=eviction,
                pipeline=pipeline,
                model=model,
                metadata=metadata,
            )
        )

        # Handle completion mode
        prompt_text, resolved_params, mode_hint = GenerationService._prepare_completion_mode(
            provider, messages, final_prompt, params, metadata,
        )

        request = GenerationRequest(
            model=model,
            messages=messages,
            system_prompt=final_prompt,
            sampling_params=resolved_params,
            prompt_text=prompt_text,
        )
        gen_result = await provider.generate(request)

        # Emit the node
        node_resp = await self._emit_step_node(
            rhizome_id, experiment_id, parent_id,
            gen_result, provider.name, system_prompt,
            params, model,
        )

        return _StepResult(
            content=gen_result.content,
            node_id=node_resp.node_id,
            latency_ms=gen_result.latency_ms,
            usage=gen_result.usage,
            logprobs_tokens=_extract_logprob_tokens(gen_result),
        )

    async def _run_step_stream(
        self,
        *,
        rhizome_id: str,
        experiment_id: str,
        parent_id: str | None,
        provider: LLMProvider,
        nodes: list[dict],
        node_id: str,
        system_prompt: str | None,
        model: str,
        params: SamplingParams,
        metadata: dict,
        include_ts: bool,
        include_think: bool,
        excluded_ids: set[str],
        dg_map: dict,
        excluded_gids: set[str],
        anchored_ids: set[str],
        eviction,
        step_index: int,
        yield_chunks: bool = True,
    ) -> AsyncIterator[StreamChunk]:
        """Run a single streaming generation step, yielding text_delta chunks."""
        context_limit = get_model_context_limit(model)
        pipeline = GenerationService._resolve_interventions(metadata)

        messages, ctx_usage, eviction_report, final_prompt, active_intv = (
            self._gen_svc._build_context_with_interventions(
                nodes=nodes,
                node_id=node_id,
                system_prompt=system_prompt,
                context_limit=context_limit,
                include_timestamps=include_ts,
                include_thinking=include_think,
                excluded_ids=excluded_ids,
                digression_groups=dg_map,
                excluded_group_ids=excluded_gids,
                anchored_ids=anchored_ids,
                eviction=eviction,
                pipeline=pipeline,
                model=model,
                metadata=metadata,
            )
        )

        prompt_text, resolved_params, mode_hint = GenerationService._prepare_completion_mode(
            provider, messages, final_prompt, params, metadata,
        )

        request = GenerationRequest(
            model=model,
            messages=messages,
            system_prompt=final_prompt,
            sampling_params=resolved_params,
            prompt_text=prompt_text,
        )

        accumulated = ""
        final_result = None
        async for chunk in provider.generate_stream(request):
            if chunk.is_final and chunk.result:
                final_result = chunk.result
                accumulated = chunk.result.content
            elif chunk.text:
                accumulated += chunk.text
                if yield_chunks:
                    yield StreamChunk(
                        type="text_delta",
                        text=chunk.text,
                        completion_index=step_index,
                    )

        if final_result is None:
            final_result = GenerationResult(
                content=accumulated,
                model=model,
                finish_reason="stop",
            )

        # Yield the final result as a special chunk type for the caller to consume
        yield StreamChunk(
            type="step_result",
            text="",
            is_final=True,
            result=final_result,
        )

    # -- Node emission --

    async def _emit_step_node(
        self,
        rhizome_id: str,
        experiment_id: str,
        parent_id: str | None,
        result: GenerationResult,
        provider_name: str,
        system_prompt: str | None,
        sampling_params: SamplingParams,
        model: str,
    ):
        """Emit a NodeCreated event for a perturbation step."""
        node_id = str(uuid4())
        payload = NodeCreatedPayload(
            node_id=node_id,
            generation_id=experiment_id,
            parent_id=parent_id,
            role="assistant",
            content=result.content,
            model=result.model or model,
            provider=provider_name,
            system_prompt=system_prompt,
            sampling_params=sampling_params,
            mode="chat",
            usage=result.usage,
            latency_ms=result.latency_ms,
            finish_reason=result.finish_reason,
            logprobs=result.logprobs,
            thinking_content=result.thinking_content,
        )
        event = EventEnvelope(
            event_id=str(uuid4()),
            rhizome_id=rhizome_id,
            timestamp=datetime.now(UTC),
            device_id="perturbation",
            event_type="NodeCreated",
            payload=payload.model_dump(),
        )
        await self._store.append(event)
        await self._projector.project([event])

        nodes = await self._projector.get_nodes(rhizome_id)
        sibling_info = RhizomeService._compute_sibling_info(nodes)
        node_row = next(n for n in nodes if n["node_id"] == node_id)
        return RhizomeService._node_from_row(node_row, sibling_info=sibling_info)

    # -- Divergence computation --

    @staticmethod
    def _compute_divergence(
        control_result: _StepResult | None,
        steps: list[PerturbationStepResponse],
    ) -> list[DivergenceMetrics]:
        """Compute divergence metrics for each perturbation vs control."""
        if control_result is None:
            return []

        metrics = []
        for i, step in enumerate(steps):
            if step.type == "control":
                continue
            metrics.append(DivergenceMetrics(
                step_index=i,
                label=step.label,
                word_diff_ratio=word_diff_ratio(control_result.content, step.content),
                edit_distance=normalized_edit_distance(control_result.content, step.content),
                certainty_delta=certainty_delta(
                    control_result.logprobs_tokens,
                    None,  # We don't store logprobs_tokens on PerturbationStepResponse
                ),
                length_ratio=length_ratio(control_result.content, step.content),
            ))
        return metrics

    # -- Report emission --

    async def _emit_report(
        self,
        rhizome_id: str,
        report: PerturbationReportResponse,
    ) -> None:
        """Emit a PerturbationReportGenerated event."""
        payload = PerturbationReportGeneratedPayload(
            report_id=report.report_id,
            experiment_id=report.experiment_id,
            node_id=report.node_id,
            provider=report.provider,
            model=report.model,
            include_control=report.include_control,
            steps=[s.model_dump() for s in report.steps],
            divergence=[d.model_dump() for d in report.divergence],
        )
        event = EventEnvelope(
            event_id=str(uuid4()),
            rhizome_id=rhizome_id,
            timestamp=datetime.now(UTC),
            device_id="perturbation",
            event_type="PerturbationReportGenerated",
            payload=payload.model_dump(),
        )
        await self._store.append(event)
        await self._projector.project([event])

    # -- Label generation --

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


class _StepResult:
    """Internal container for step generation results."""

    __slots__ = ("content", "node_id", "latency_ms", "usage", "logprobs_tokens")

    def __init__(
        self,
        content: str,
        node_id: str,
        latency_ms: int | None,
        usage: dict | None,
        logprobs_tokens: list[dict] | None,
    ):
        self.content = content
        self.node_id = node_id
        self.latency_ms = latency_ms
        self.usage = usage
        self.logprobs_tokens = logprobs_tokens


def _extract_logprob_tokens(result: GenerationResult) -> list[dict] | None:
    """Extract logprob token dicts from a GenerationResult."""
    if result.logprobs and result.logprobs.tokens:
        return [t.model_dump() for t in result.logprobs.tokens]
    return None
