"""Generation service: orchestrates LLM calls and event emission."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.context import ContextBuilder, get_model_context_limit
from qivis.generation.interventions import (
    InterventionConfig,
    InterventionContext,
    InterventionPipeline,
    default_registry,
)
from qivis.generation.templates import render_prompt
from qivis.generation.tokens import ApproximateTokenCounter
from qivis.models import (
    ContextUsage,
    EventEnvelope,
    EvictionReport,
    EvictionStrategy,
    GenerationStartedPayload,
    NodeCreatedPayload,
    SamplingParams,
)
from qivis.providers.base import GenerationRequest, GenerationResult, LLMProvider, StreamChunk
from qivis.providers.registry import get_provider
from qivis.rhizomes.schemas import NodeResponse
from qivis.rhizomes.service import RhizomeService
from qivis.utils.json import parse_json_field


def merge_sampling_params(
    request_params: SamplingParams | None,
    rhizome_defaults_raw: str | dict | None,
    *,
    metadata: dict | None = None,
) -> SamplingParams:
    """Merge sampling params: request overrides > rhizome defaults > SamplingParams() base.

    Uses Pydantic's model_fields_set on request_params to only apply fields
    that were explicitly provided, preserving rhizome defaults for the rest.
    """
    base = SamplingParams()

    rhizome_dict = parse_json_field(rhizome_defaults_raw)

    # Backward compat: if no default_sampling_params but metadata has extended_thinking
    if not rhizome_dict and metadata:
        if metadata.get("extended_thinking"):
            rhizome_dict = {
                "extended_thinking": True,
                "thinking_budget": metadata.get("thinking_budget", 10000),
            }

    # Layer 1: apply rhizome defaults over base
    if rhizome_dict:
        rhizome_sp = SamplingParams.model_validate(rhizome_dict)
        for field_name in rhizome_dict:
            if field_name in SamplingParams.model_fields:
                setattr(base, field_name, getattr(rhizome_sp, field_name))

    # Layer 2: apply request overrides (only explicitly set fields)
    if request_params is not None:
        for field_name in request_params.model_fields_set:
            setattr(base, field_name, getattr(request_params, field_name))

    return base


def _apply_debug_context_limit(rhizome: dict, context_limit: int) -> int:
    """Override context limit with debug value from rhizome metadata, if set."""
    metadata = parse_json_field(rhizome.get("metadata")) or {}
    debug_limit = metadata.get("debug_context_limit")
    if isinstance(debug_limit, int) and debug_limit > 0:
        return debug_limit
    return context_limit


class GenerationService:
    """Orchestrates LLM generation: context assembly, API call, event emission."""

    def __init__(
        self,
        rhizome_service: RhizomeService,
        store: EventStore,
        projector: StateProjector,
    ) -> None:
        self._rhizome_service = rhizome_service
        self._store = store
        self._projector = projector
        self._context_builder = ContextBuilder()

    async def generate(
        self,
        rhizome_id: str,
        node_id: str,
        provider: LLMProvider,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        sampling_params: SamplingParams | None = None,
        prefill_content: str | None = None,
    ) -> NodeResponse:
        """Generate a non-streaming response and store as a new node."""
        (rhizome, nodes, resolved_model, resolved_prompt, resolved_params,
         include_ts, include_think, excl_ids, dg_map, excl_gids,
         anchored_ids, eviction_strategy, metadata) = (
            await self._resolve_context(rhizome_id, node_id, model, system_prompt, sampling_params)
        )
        context_limit = _apply_debug_context_limit(rhizome, get_model_context_limit(resolved_model))
        pipeline = self._resolve_interventions(metadata)
        messages, context_usage, eviction_report, resolved_prompt, active_interventions = (
            self._build_context_with_interventions(
                nodes=nodes, node_id=node_id,
                system_prompt=resolved_prompt, context_limit=context_limit,
                include_timestamps=include_ts, include_thinking=include_think,
                excluded_ids=excl_ids, digression_groups=dg_map,
                excluded_group_ids=excl_gids, anchored_ids=anchored_ids,
                eviction=eviction_strategy, pipeline=pipeline,
                model=resolved_model, metadata=metadata,
            )
        )
        messages, context_usage = await self._maybe_inject_summary(
            messages, context_usage, eviction_report,
        )

        # Completion mode: render prompt text from messages
        prompt_text, resolved_params, mode_hint = self._prepare_completion_mode(
            provider, messages, resolved_prompt, resolved_params, metadata,
        )

        if prefill_content:
            if prompt_text is not None:
                # Completion + prefill: append prefill to prompt text
                prompt_text += prefill_content
            else:
                messages.append({"role": "assistant", "content": prefill_content})

        generation_id = str(uuid4())
        mode = "prefill" if prefill_content else mode_hint

        await self._emit_generation_started(
            rhizome_id, generation_id, node_id,
            resolved_model, provider.name, resolved_prompt, resolved_params,
            mode=mode, prefill_content=prefill_content,
        )

        request = GenerationRequest(
            model=resolved_model,
            messages=messages,
            system_prompt=resolved_prompt,
            sampling_params=resolved_params,
            prompt_text=prompt_text,
        )
        result = await provider.generate(request)

        if prefill_content:
            result.content = prefill_content + result.content

        return await self._emit_node_created(
            rhizome_id, generation_id, node_id, result,
            provider.name, resolved_prompt, resolved_params,
            context_usage=context_usage,
            include_thinking_in_context=include_think,
            include_timestamps=include_ts,
            active_interventions=active_interventions,
            mode=mode, prefill_content=prefill_content,
            prompt_text=prompt_text,
        )

    async def generate_n(
        self,
        rhizome_id: str,
        node_id: str,
        provider: LLMProvider,
        *,
        n: int,
        model: str | None = None,
        system_prompt: str | None = None,
        sampling_params: SamplingParams | None = None,
        prefill_content: str | None = None,
    ) -> list[NodeResponse]:
        """Generate N responses in parallel and store as sibling nodes."""
        (rhizome, nodes, resolved_model, resolved_prompt, resolved_params,
         include_ts, include_think, excl_ids, dg_map, excl_gids,
         anchored_ids, eviction_strategy, metadata) = (
            await self._resolve_context(rhizome_id, node_id, model, system_prompt, sampling_params)
        )
        context_limit = _apply_debug_context_limit(rhizome, get_model_context_limit(resolved_model))
        pipeline = self._resolve_interventions(metadata)
        messages, context_usage, eviction_report, resolved_prompt, active_interventions = (
            self._build_context_with_interventions(
                nodes=nodes, node_id=node_id,
                system_prompt=resolved_prompt, context_limit=context_limit,
                include_timestamps=include_ts, include_thinking=include_think,
                excluded_ids=excl_ids, digression_groups=dg_map,
                excluded_group_ids=excl_gids, anchored_ids=anchored_ids,
                eviction=eviction_strategy, pipeline=pipeline,
                model=resolved_model, metadata=metadata,
            )
        )
        messages, context_usage = await self._maybe_inject_summary(
            messages, context_usage, eviction_report,
        )

        prompt_text, resolved_params, mode_hint = self._prepare_completion_mode(
            provider, messages, resolved_prompt, resolved_params, metadata,
        )

        if prefill_content:
            if prompt_text is not None:
                prompt_text += prefill_content
            else:
                messages.append({"role": "assistant", "content": prefill_content})

        generation_id = str(uuid4())
        mode = "prefill" if prefill_content else mode_hint

        await self._emit_generation_started(
            rhizome_id, generation_id, node_id,
            resolved_model, provider.name, resolved_prompt, resolved_params,
            n=n, mode=mode, prefill_content=prefill_content,
        )

        request = GenerationRequest(
            model=resolved_model,
            messages=messages,
            system_prompt=resolved_prompt,
            sampling_params=resolved_params,
            prompt_text=prompt_text,
        )
        results = await asyncio.gather(*[provider.generate(request) for _ in range(n)])

        created: list[NodeResponse] = []
        for result in results:
            if prefill_content:
                result.content = prefill_content + result.content
            node = await self._emit_node_created(
                rhizome_id, generation_id, node_id, result,
                provider.name, resolved_prompt, resolved_params,
                context_usage=context_usage,
                include_thinking_in_context=include_think,
                include_timestamps=include_ts,
                active_interventions=active_interventions,
                mode=mode, prefill_content=prefill_content,
                prompt_text=prompt_text,
            )
            created.append(node)
        return created

    async def generate_n_stream(
        self,
        rhizome_id: str,
        node_id: str,
        provider: LLMProvider,
        *,
        n: int,
        model: str | None = None,
        system_prompt: str | None = None,
        sampling_params: SamplingParams | None = None,
        prefill_content: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream N responses simultaneously, yielding tagged chunks."""
        (rhizome, nodes, resolved_model, resolved_prompt, resolved_params,
         include_ts, include_think, excl_ids, dg_map, excl_gids,
         anchored_ids, eviction_strategy, metadata) = (
            await self._resolve_context(
                rhizome_id, node_id, model, system_prompt, sampling_params
            )
        )
        context_limit = _apply_debug_context_limit(rhizome, get_model_context_limit(resolved_model))
        pipeline = self._resolve_interventions(metadata)
        messages, context_usage, eviction_report, resolved_prompt, active_interventions = (
            self._build_context_with_interventions(
                nodes=nodes, node_id=node_id,
                system_prompt=resolved_prompt, context_limit=context_limit,
                include_timestamps=include_ts, include_thinking=include_think,
                excluded_ids=excl_ids, digression_groups=dg_map,
                excluded_group_ids=excl_gids, anchored_ids=anchored_ids,
                eviction=eviction_strategy, pipeline=pipeline,
                model=resolved_model, metadata=metadata,
            )
        )
        messages, context_usage = await self._maybe_inject_summary(
            messages, context_usage, eviction_report,
        )

        prompt_text, resolved_params, mode_hint = self._prepare_completion_mode(
            provider, messages, resolved_prompt, resolved_params, metadata,
        )

        if prefill_content:
            if prompt_text is not None:
                prompt_text += prefill_content
            else:
                messages.append({"role": "assistant", "content": prefill_content})

        generation_id = str(uuid4())
        mode = "prefill" if prefill_content else mode_hint

        await self._emit_generation_started(
            rhizome_id, generation_id, node_id,
            resolved_model, provider.name,
            resolved_prompt, resolved_params,
            n=n, mode=mode, prefill_content=prefill_content,
        )

        request = GenerationRequest(
            model=resolved_model,
            messages=messages,
            system_prompt=resolved_prompt,
            sampling_params=resolved_params,
            prompt_text=prompt_text,
        )

        queue: asyncio.Queue[tuple[int, StreamChunk] | None] = (
            asyncio.Queue()
        )
        remaining = n

        async def _run_stream(index: int) -> None:
            nonlocal remaining
            try:
                async for chunk in provider.generate_stream(request):
                    if chunk.is_final and chunk.result is not None:
                        if prefill_content:
                            chunk.result.content = prefill_content + chunk.result.content
                        node = await self._emit_node_created(
                            rhizome_id, generation_id, node_id,
                            chunk.result, provider.name,
                            resolved_prompt, resolved_params,
                            context_usage=context_usage,
                            include_thinking_in_context=include_think,
                            include_timestamps=include_ts,
                            active_interventions=active_interventions,
                            mode=mode, prefill_content=prefill_content,
                            prompt_text=prompt_text,
                        )
                        tagged = StreamChunk(
                            type=chunk.type,
                            text=chunk.text,
                            is_final=True,
                            completion_index=index,
                            result=GenerationResult(
                                content=chunk.result.content,
                                model=chunk.result.model,
                                finish_reason=chunk.result.finish_reason,
                                usage=chunk.result.usage,
                                latency_ms=chunk.result.latency_ms,
                                logprobs=chunk.result.logprobs,
                                raw_response={
                                    "node_id": node.node_id,
                                },
                            ),
                        )
                        await queue.put((index, tagged))
                    else:
                        tagged = StreamChunk(
                            type=chunk.type,
                            text=chunk.text,
                            completion_index=index,
                        )
                        await queue.put((index, tagged))
            except Exception as e:
                error_chunk = StreamChunk(
                    type="error",
                    text=str(e),
                    completion_index=index,
                )
                await queue.put((index, error_chunk))
            finally:
                remaining -= 1
                if remaining == 0:
                    await queue.put(None)

        tasks = [
            asyncio.create_task(_run_stream(i)) for i in range(n)
        ]

        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                _index, chunk = item
                yield chunk

            yield StreamChunk(type="generation_complete")
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def generate_cross(
        self,
        rhizome_id: str,
        node_id: str,
        targets: list[dict],
        *,
        system_prompt: str | None = None,
        sampling_params: SamplingParams | None = None,
    ) -> list[NodeResponse]:
        """Generate responses from multiple providers and store as sibling nodes.

        Each target is a dict with 'provider' and 'model' keys.
        Context is resolved once and shared across all targets.
        """
        (rhizome, nodes, _, resolved_prompt, resolved_params,
         include_ts, include_think, excl_ids, dg_map, excl_gids,
         anchored_ids, eviction_strategy, metadata) = (
            await self._resolve_context(
                rhizome_id, node_id, None, system_prompt, sampling_params,
            )
        )
        # Use first target's model for context limit
        first_model = targets[0]["model"]
        context_limit = _apply_debug_context_limit(
            rhizome, get_model_context_limit(first_model),
        )
        pipeline = self._resolve_interventions(metadata)
        messages, context_usage, eviction_report, resolved_prompt, active_interventions = (
            self._build_context_with_interventions(
                nodes=nodes, node_id=node_id,
                system_prompt=resolved_prompt, context_limit=context_limit,
                include_timestamps=include_ts, include_thinking=include_think,
                excluded_ids=excl_ids, digression_groups=dg_map,
                excluded_group_ids=excl_gids, anchored_ids=anchored_ids,
                eviction=eviction_strategy, pipeline=pipeline,
                model=first_model, metadata=metadata,
            )
        )
        messages, context_usage = await self._maybe_inject_summary(
            messages, context_usage, eviction_report,
        )

        generation_id = str(uuid4())

        async def _generate_one(target: dict) -> NodeResponse:
            provider = get_provider(target["provider"])
            target_model = target["model"]

            msgs_copy = [m.copy() for m in messages]
            prompt_text, params, mode_hint = self._prepare_completion_mode(
                provider, msgs_copy, resolved_prompt, resolved_params, metadata,
            )

            request = GenerationRequest(
                model=target_model,
                messages=msgs_copy,
                system_prompt=resolved_prompt,
                sampling_params=params,
                prompt_text=prompt_text,
            )
            result = await provider.generate(request)

            return await self._emit_node_created(
                rhizome_id, generation_id, node_id, result,
                provider.name, resolved_prompt, params,
                context_usage=context_usage,
                include_thinking_in_context=include_think,
                include_timestamps=include_ts,
                active_interventions=active_interventions,
                mode=mode_hint,
            )

        results = await asyncio.gather(*[_generate_one(t) for t in targets])
        return list(results)

    async def generate_cross_stream(
        self,
        rhizome_id: str,
        node_id: str,
        targets: list[dict],
        *,
        system_prompt: str | None = None,
        sampling_params: SamplingParams | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream responses from multiple providers simultaneously."""
        (rhizome, nodes, _, resolved_prompt, resolved_params,
         include_ts, include_think, excl_ids, dg_map, excl_gids,
         anchored_ids, eviction_strategy, metadata) = (
            await self._resolve_context(
                rhizome_id, node_id, None, system_prompt, sampling_params,
            )
        )
        first_model = targets[0]["model"]
        context_limit = _apply_debug_context_limit(
            rhizome, get_model_context_limit(first_model),
        )
        pipeline = self._resolve_interventions(metadata)
        messages, context_usage, eviction_report, resolved_prompt, active_interventions = (
            self._build_context_with_interventions(
                nodes=nodes, node_id=node_id,
                system_prompt=resolved_prompt, context_limit=context_limit,
                include_timestamps=include_ts, include_thinking=include_think,
                excluded_ids=excl_ids, digression_groups=dg_map,
                excluded_group_ids=excl_gids, anchored_ids=anchored_ids,
                eviction=eviction_strategy, pipeline=pipeline,
                model=first_model, metadata=metadata,
            )
        )
        messages, context_usage = await self._maybe_inject_summary(
            messages, context_usage, eviction_report,
        )

        generation_id = str(uuid4())
        n = len(targets)

        queue: asyncio.Queue[tuple[int, StreamChunk] | None] = asyncio.Queue()
        remaining = n

        async def _run_stream(index: int) -> None:
            nonlocal remaining
            try:
                target = targets[index]
                provider = get_provider(target["provider"])
                target_model = target["model"]

                msgs_copy = [m.copy() for m in messages]
                prompt_text, params, mode_hint = self._prepare_completion_mode(
                    provider, msgs_copy, resolved_prompt, resolved_params, metadata,
                )

                request = GenerationRequest(
                    model=target_model,
                    messages=msgs_copy,
                    system_prompt=resolved_prompt,
                    sampling_params=params,
                    prompt_text=prompt_text,
                )

                async for chunk in provider.generate_stream(request):
                    if chunk.is_final and chunk.result is not None:
                        node = await self._emit_node_created(
                            rhizome_id, generation_id, node_id,
                            chunk.result, provider.name,
                            resolved_prompt, params,
                            context_usage=context_usage,
                            include_thinking_in_context=include_think,
                            include_timestamps=include_ts,
                            active_interventions=active_interventions,
                            mode=mode_hint,
                        )
                        tagged = StreamChunk(
                            type=chunk.type,
                            text=chunk.text,
                            is_final=True,
                            completion_index=index,
                            result=GenerationResult(
                                content=chunk.result.content,
                                model=chunk.result.model,
                                finish_reason=chunk.result.finish_reason,
                                usage=chunk.result.usage,
                                latency_ms=chunk.result.latency_ms,
                                logprobs=chunk.result.logprobs,
                                raw_response={"node_id": node.node_id},
                            ),
                        )
                        await queue.put((index, tagged))
                    else:
                        tagged = StreamChunk(
                            type=chunk.type,
                            text=chunk.text,
                            completion_index=index,
                        )
                        await queue.put((index, tagged))
            except Exception as e:
                error_chunk = StreamChunk(
                    type="error",
                    text=str(e),
                    completion_index=index,
                )
                await queue.put((index, error_chunk))
            finally:
                remaining -= 1
                if remaining == 0:
                    await queue.put(None)

        tasks = [asyncio.create_task(_run_stream(i)) for i in range(n)]

        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                _index, chunk = item
                yield chunk

            yield StreamChunk(type="generation_complete")
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def generate_stream(
        self,
        rhizome_id: str,
        node_id: str,
        provider: LLMProvider,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        sampling_params: SamplingParams | None = None,
        prefill_content: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Generate a streaming response, yielding chunks."""
        (rhizome, nodes, resolved_model, resolved_prompt, resolved_params,
         include_ts, include_think, excl_ids, dg_map, excl_gids,
         anchored_ids, eviction_strategy, metadata) = (
            await self._resolve_context(rhizome_id, node_id, model, system_prompt, sampling_params)
        )
        context_limit = _apply_debug_context_limit(rhizome, get_model_context_limit(resolved_model))
        pipeline = self._resolve_interventions(metadata)
        messages, context_usage, eviction_report, resolved_prompt, active_interventions = (
            self._build_context_with_interventions(
                nodes=nodes, node_id=node_id,
                system_prompt=resolved_prompt, context_limit=context_limit,
                include_timestamps=include_ts, include_thinking=include_think,
                excluded_ids=excl_ids, digression_groups=dg_map,
                excluded_group_ids=excl_gids, anchored_ids=anchored_ids,
                eviction=eviction_strategy, pipeline=pipeline,
                model=resolved_model, metadata=metadata,
            )
        )
        messages, context_usage = await self._maybe_inject_summary(
            messages, context_usage, eviction_report,
        )

        prompt_text, resolved_params, mode_hint = self._prepare_completion_mode(
            provider, messages, resolved_prompt, resolved_params, metadata,
        )

        if prefill_content:
            if prompt_text is not None:
                prompt_text += prefill_content
            else:
                messages.append({"role": "assistant", "content": prefill_content})

        generation_id = str(uuid4())
        mode = "prefill" if prefill_content else mode_hint

        await self._emit_generation_started(
            rhizome_id, generation_id, node_id,
            resolved_model, provider.name, resolved_prompt, resolved_params,
            mode=mode, prefill_content=prefill_content,
        )

        request = GenerationRequest(
            model=resolved_model,
            messages=messages,
            system_prompt=resolved_prompt,
            sampling_params=resolved_params,
            prompt_text=prompt_text,
        )

        async for chunk in provider.generate_stream(request):
            if chunk.is_final and chunk.result is not None:
                if prefill_content:
                    chunk.result.content = prefill_content + chunk.result.content
                node = await self._emit_node_created(
                    rhizome_id, generation_id, node_id, chunk.result,
                    provider.name, resolved_prompt, resolved_params,
                    context_usage=context_usage,
                    include_thinking_in_context=include_think,
                    include_timestamps=include_ts,
                    active_interventions=active_interventions,
                    mode=mode, prefill_content=prefill_content,
                    prompt_text=prompt_text,
                )
                # Attach node_id to the final chunk for the SSE handler
                chunk = StreamChunk(
                    type=chunk.type,
                    text=chunk.text,
                    is_final=True,
                    result=GenerationResult(
                        content=chunk.result.content,
                        model=chunk.result.model,
                        finish_reason=chunk.result.finish_reason,
                        usage=chunk.result.usage,
                        latency_ms=chunk.result.latency_ms,
                        logprobs=chunk.result.logprobs,
                        raw_response={"node_id": node.node_id},
                    ),
                )
            yield chunk

    async def _maybe_inject_summary(
        self,
        messages: list[dict[str, str]],
        context_usage: ContextUsage,
        report: EvictionReport,
    ) -> tuple[list[dict[str, str]], ContextUsage]:
        """If eviction produced content to summarize, generate and inject a recap.

        Inserts a user message with the summary at the eviction boundary
        (after the first protected messages, before the remaining ones).
        """
        if not report.summary_needed or not report.evicted_content:
            return messages, context_usage

        summary = await self._rhizome_service.generate_eviction_summary(
            report.evicted_content,
            model=report.summary_model,
        )
        if summary is None:
            return messages, context_usage

        summary_msg = {
            "role": "user",
            "content": f"[Context summary of {len(report.evicted_node_ids)} "
                       f"earlier messages: {summary}]",
        }

        # Insert after the first protected block
        insert_pos = min(report.keep_first_turns, len(messages))

        messages = messages[:insert_pos] + [summary_msg] + messages[insert_pos:]

        report.summary_inserted = True

        # Update context_usage with the summary tokens
        summary_tokens = ApproximateTokenCounter().count(summary_msg["content"])
        updated_usage = ContextUsage(
            total_tokens=context_usage.total_tokens + summary_tokens,
            max_tokens=context_usage.max_tokens,
            breakdown={
                **context_usage.breakdown,
                "user": context_usage.breakdown.get("user", 0) + summary_tokens,
            },
            excluded_tokens=context_usage.excluded_tokens,
            excluded_count=context_usage.excluded_count,
            excluded_node_ids=context_usage.excluded_node_ids,
            evicted_node_ids=context_usage.evicted_node_ids,
        )

        return messages, updated_usage

    async def _resolve_context(
        self,
        rhizome_id: str,
        node_id: str,
        model: str | None,
        system_prompt: str | None,
        sampling_params: SamplingParams | None,
    ) -> tuple[
        dict, list[dict], str, str | None, SamplingParams, bool, bool,
        set[str], dict, set[str], set[str], EvictionStrategy | None, dict,
    ]:
        """Validate rhizome/node and resolve parameters from request or rhizome defaults.

        Returns: (rhizome, nodes, resolved_model, resolved_prompt, resolved_params,
                  include_timestamps, include_thinking,
                  excluded_ids, digression_groups_map, excluded_group_ids,
                  anchored_ids, eviction_strategy, metadata)
        """
        rhizome = await self._projector.get_rhizome(rhizome_id)
        if rhizome is None:
            raise RhizomeNotFoundForGenerationError(rhizome_id)

        nodes = await self._projector.get_nodes(rhizome_id)
        node_ids = {n["node_id"] for n in nodes}
        if node_id not in node_ids:
            raise NodeNotFoundForGenerationError(node_id)

        resolved_model = model or rhizome.get("default_model") or "claude-sonnet-4-5-20250929"
        resolved_prompt = system_prompt if system_prompt is not None else rhizome.get(
            "default_system_prompt"
        )

        # Parse metadata
        metadata = parse_json_field(rhizome.get("metadata")) or {}

        # Three-layer merge: request > rhizome defaults > base
        resolved_params = merge_sampling_params(
            sampling_params,
            rhizome.get("default_sampling_params"),
            metadata=metadata,
        )

        # Rhizome-level settings from metadata
        # Completion mode never uses timestamps — they're chat context, not prompt text
        is_completion = metadata.get("generation_mode") == "completion"
        include_timestamps = False if is_completion else bool(metadata.get("include_timestamps", False))
        include_thinking = bool(metadata.get("include_thinking_in_context", False))

        # Context exclusion data
        exclusion_rows = await self._projector.get_node_exclusions(rhizome_id)
        path_ids = self._get_path_node_ids(nodes, node_id)
        excluded_ids = {r["node_id"] for r in exclusion_rows if r["scope_node_id"] in path_ids}

        groups = await self._projector.get_digression_groups(rhizome_id)
        excluded_group_ids = {g["group_id"] for g in groups if not g["included"]}
        digression_groups_map = {g["group_id"]: g["node_ids"] for g in groups}

        # Anchored node IDs
        anchor_rows = await self._projector._db.fetchall(
            "SELECT DISTINCT node_id FROM node_anchors WHERE rhizome_id = ?",
            (rhizome_id,),
        )
        anchored_ids = {r["node_id"] for r in anchor_rows}

        # Eviction strategy from rhizome metadata
        eviction_raw = metadata.get("eviction_strategy")
        eviction: EvictionStrategy | None = None
        if eviction_raw and isinstance(eviction_raw, dict):
            eviction = EvictionStrategy.model_validate(eviction_raw)

        return (rhizome, nodes, resolved_model, resolved_prompt, resolved_params,
                include_timestamps, include_thinking,
                excluded_ids, digression_groups_map, excluded_group_ids,
                anchored_ids, eviction, metadata)

    @staticmethod
    def _resolve_interventions(metadata: dict) -> InterventionPipeline:
        """Build an intervention pipeline from rhizome metadata."""
        raw_configs = metadata.get("context_interventions")
        if not raw_configs or not isinstance(raw_configs, list):
            return InterventionPipeline([])
        configs = [InterventionConfig.model_validate(c) for c in raw_configs]
        return default_registry.create_pipeline(configs)

    def _build_context_with_interventions(
        self,
        nodes: list[dict],
        node_id: str,
        system_prompt: str | None,
        context_limit: int,
        *,
        include_timestamps: bool = False,
        include_thinking: bool = False,
        excluded_ids: set[str] | None = None,
        digression_groups: dict | None = None,
        excluded_group_ids: set[str] | None = None,
        anchored_ids: set[str] | None = None,
        eviction: EvictionStrategy | None = None,
        pipeline: InterventionPipeline,
        model: str,
        metadata: dict,
        mode: str = "chat",
    ) -> tuple[list[dict[str, str]], ContextUsage, EvictionReport, str | None, list[dict] | None]:
        """Build context with intervention pipeline.

        Returns (messages, context_usage, eviction_report, system_prompt, active_interventions).
        When the pipeline is empty, falls back to the monolithic build().
        """
        if pipeline.is_empty:
            messages, usage, report = self._context_builder.build(
                nodes=nodes,
                target_node_id=node_id,
                system_prompt=system_prompt,
                model_context_limit=context_limit,
                include_timestamps=include_timestamps,
                include_thinking=include_thinking,
                excluded_ids=excluded_ids,
                digression_groups=digression_groups,
                excluded_group_ids=excluded_group_ids,
                anchored_ids=anchored_ids,
                eviction=eviction,
            )
            return messages, usage, report, system_prompt, None

        # Split path: build_messages → pre_eviction → count_and_evict → post_eviction
        messages, msg_node_ids, created_ats, excluded_info = self._context_builder.build_messages(
            nodes=nodes,
            target_node_id=node_id,
            include_timestamps=include_timestamps,
            include_thinking=include_thinking,
            excluded_ids=excluded_ids,
            digression_groups=digression_groups,
            excluded_group_ids=excluded_group_ids,
        )

        ctx = InterventionContext(
            messages=messages,
            system_prompt=system_prompt,
            node_ids=msg_node_ids,
            model=model,
            metadata=metadata,
            mode=mode,
            created_ats=created_ats,
        )
        ctx = pipeline.run_pre_eviction(ctx)

        result_msgs, usage, report = self._context_builder.count_and_evict(
            messages=ctx.messages,
            node_ids=ctx.node_ids,
            system_prompt=ctx.system_prompt,
            model_context_limit=context_limit,
            excluded_token_total=excluded_info["excluded_tokens"],
            excluded_node_count=excluded_info["excluded_count"],
            excluded_node_ids=excluded_info["excluded_node_ids"],
            anchored_ids=anchored_ids,
            eviction=eviction,
        )

        ctx.messages = result_msgs
        ctx = pipeline.run_post_eviction(ctx)

        active_configs = pipeline.get_active_configs()
        return ctx.messages, usage, report, ctx.system_prompt, active_configs

    @staticmethod
    def _prepare_completion_mode(
        provider: LLMProvider,
        messages: list[dict[str, str]],
        system_prompt: str | None,
        sampling_params: SamplingParams,
        metadata: dict,
    ) -> tuple[str | None, SamplingParams, str]:
        """Prepare completion mode if the provider supports it.

        Returns (prompt_text, updated_params, mode_hint).
        mode_hint is "completion" if prompt was rendered, "chat" otherwise.

        Completion mode activates when:
        - Provider is completion-only (e.g. LlamaCpp), OR
        - Provider supports both modes AND metadata.generation_mode == "completion"

        Dual-mode providers (OpenRouter, OpenAI, etc.) default to chat mode.
        """
        if "completion" not in provider.supported_modes:
            return None, sampling_params, "chat"

        # Dual-mode providers require explicit opt-in
        is_completion_only = "chat" not in provider.supported_modes
        explicit_completion = metadata.get("generation_mode") == "completion"

        if not is_completion_only and not explicit_completion:
            return None, sampling_params, "chat"

        template_name = metadata.get("prompt_template", "raw")
        prompt_text, stop_tokens = render_prompt(template_name, messages, system_prompt)

        # Merge template stop tokens into sampling params
        existing_stops = list(sampling_params.stop_sequences or [])
        for token in stop_tokens:
            if token not in existing_stops:
                existing_stops.append(token)

        updated = sampling_params.model_copy(update={"stop_sequences": existing_stops})
        return prompt_text, updated, "completion"

    @staticmethod
    def _get_path_node_ids(nodes: list[dict], target_node_id: str) -> set[str]:
        """Walk parent chain from target to root, return set of node IDs on path."""
        by_id = {n["node_id"]: n for n in nodes}
        path_ids: set[str] = set()
        current_id: str | None = target_node_id
        while current_id is not None:
            path_ids.add(current_id)
            node = by_id.get(current_id)
            if node is None:
                break
            current_id = node.get("parent_id")
        return path_ids

    async def _emit_generation_started(
        self,
        rhizome_id: str,
        generation_id: str,
        parent_node_id: str,
        model: str,
        provider_name: str,
        system_prompt: str | None,
        sampling_params: SamplingParams,
        *,
        n: int = 1,
        mode: str = "chat",
        prefill_content: str | None = None,
    ) -> None:
        payload = GenerationStartedPayload(
            generation_id=generation_id,
            parent_node_id=parent_node_id,
            model=model,
            provider=provider_name,
            system_prompt=system_prompt,
            sampling_params=sampling_params,
            n=n,
            mode=mode,
            prefill_content=prefill_content,
        )
        event = EventEnvelope(
            event_id=str(uuid4()),
            rhizome_id=rhizome_id,
            timestamp=datetime.now(UTC),
            device_id="local",
            event_type="GenerationStarted",
            payload=payload.model_dump(),
        )
        await self._store.append(event)
        await self._projector.project([event])

    async def _emit_node_created(
        self,
        rhizome_id: str,
        generation_id: str,
        parent_id: str,
        result: GenerationResult,
        provider_name: str,
        system_prompt: str | None,
        sampling_params: SamplingParams,
        *,
        context_usage: ContextUsage | None = None,
        include_thinking_in_context: bool = False,
        include_timestamps: bool = False,
        active_interventions: list[dict] | None = None,
        mode: str = "chat",
        prefill_content: str | None = None,
        prompt_text: str | None = None,
    ) -> NodeResponse:
        node_id = str(uuid4())
        payload = NodeCreatedPayload(
            node_id=node_id,
            generation_id=generation_id,
            parent_id=parent_id,
            role="assistant",
            content=result.content,
            model=result.model,
            provider=provider_name,
            system_prompt=system_prompt,
            sampling_params=sampling_params,
            mode=mode,
            prefill_content=prefill_content,
            prompt_text=prompt_text,
            usage=result.usage,
            latency_ms=result.latency_ms,
            finish_reason=result.finish_reason,
            logprobs=result.logprobs,
            thinking_content=result.thinking_content,
            include_thinking_in_context=include_thinking_in_context,
            include_timestamps=include_timestamps,
            active_interventions=active_interventions,
            context_usage=context_usage,
            raw_response=result.raw_response,
        )
        event = EventEnvelope(
            event_id=str(uuid4()),
            rhizome_id=rhizome_id,
            timestamp=datetime.now(UTC),
            device_id="local",
            event_type="NodeCreated",
            payload=payload.model_dump(),
        )
        await self._store.append(event)
        await self._projector.project([event])

        # Read back the projected node with sibling info
        nodes = await self._projector.get_nodes(rhizome_id)
        sibling_info = RhizomeService._compute_sibling_info(nodes)
        node_row = next(n for n in nodes if n["node_id"] == node_id)
        return RhizomeService._node_from_row(node_row, sibling_info=sibling_info)


class RhizomeNotFoundForGenerationError(Exception):
    def __init__(self, rhizome_id: str) -> None:
        self.rhizome_id = rhizome_id
        super().__init__(f"Rhizome not found: {rhizome_id}")


class NodeNotFoundForGenerationError(Exception):
    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        super().__init__(f"Node not found: {node_id}")
