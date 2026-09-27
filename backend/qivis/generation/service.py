"""Generation service: orchestrates LLM calls and event emission.

Every generation -- single, n>1, cross-model, replay, perturbation -- goes
through the same three steps:

  load     the rhizome state a generation depends on (path, exclusions,
           settings), as a LoadedContext that callers may adjust
  prepare  one Prepared request per target: its mode, context, rendered
           prompt, and everything the node will record
  run      complete() or stream() a Prepared, which persists the node

so what each node records is exactly what its model was sent.
"""

import asyncio
import dataclasses
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

from qivis.events.log import EventLog
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.context import ContextBuilder, resolve_context_limit
from qivis.generation.interventions import (
    InterventionConfig,
    InterventionContext,
    InterventionPipeline,
    default_registry,
)
from qivis.generation.templates import render_prompt
from qivis.generation.tokens import ApproximateTokenCounter
from qivis.model_catalog import get_catalog
from qivis.models import (
    ContextUsage,
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

logger = logging.getLogger(__name__)

FALLBACK_MODEL = "claude-sonnet-4-5-20250929"


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


@dataclass
class Target:
    """Who generates: a provider, a model (None: the rhizome's default), and
    an explicit mode (None: the model's own, else the rhizome's)."""

    provider: LLMProvider
    model: str | None = None
    mode: str | None = None


@dataclass
class LoadedContext:
    """The rhizome state a generation depends on, before any messages are built.

    Callers may adjust a copy (dataclasses.replace) before preparing, as
    perturbation experiments do.
    """

    rhizome_id: str
    rhizome: dict
    nodes: list[dict]
    metadata: dict
    parent_id: str | None  # the node being answered; None: the model speaks first
    system_prompt: str | None
    params: SamplingParams
    include_timestamps: bool  # the rhizome's setting; only chat-mode generations use it
    include_thinking: bool
    excluded_ids: set[str]
    digression_groups: dict
    excluded_group_ids: set[str]
    anchored_ids: set[str]
    eviction: EvictionStrategy | None


@dataclass
class Prepared:
    """One generation, ready to send; everything its node will record."""

    rhizome_id: str
    parent_id: str | None
    generation_id: str
    provider: LLMProvider
    model: str
    mode: str  # "chat" | "completion"
    request: GenerationRequest
    context_usage: ContextUsage
    active_interventions: list[dict] | None
    include_timestamps: bool
    include_thinking: bool
    prefill: str | None = None
    device_id: str = "local"
    completion_index: int | None = None

    @property
    def recorded_mode(self) -> str:
        return "prefill" if self.prefill else self.mode


@dataclass
class _Built:
    messages: list[dict[str, str]]
    usage: ContextUsage
    system_prompt: str | None
    active_interventions: list[dict] | None


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
        self._events = EventLog(store, projector)
        self._context_builder = ContextBuilder()

    # -- Entry points --

    async def generate(
        self,
        rhizome_id: str,
        node_id: str | None,
        provider: LLMProvider,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        sampling_params: SamplingParams | None = None,
        prefill_content: str | None = None,
        mode_override: str | None = None,
    ) -> NodeResponse:
        """Generate a non-streaming response and store as a new node."""
        p = await self._prepare_one(
            rhizome_id, node_id, provider, model, system_prompt, sampling_params,
            prefill_content, mode_override,
        )
        await self._started(p)
        return await self.complete(p)

    async def generate_stream(
        self,
        rhizome_id: str,
        node_id: str | None,
        provider: LLMProvider,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        sampling_params: SamplingParams | None = None,
        prefill_content: str | None = None,
        mode_override: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Generate a streaming response, yielding chunks."""
        p = await self._prepare_one(
            rhizome_id, node_id, provider, model, system_prompt, sampling_params,
            prefill_content, mode_override,
        )
        await self._started(p)
        async for chunk in self.stream(p):
            yield chunk

    async def generate_n(
        self,
        rhizome_id: str,
        node_id: str | None,
        provider: LLMProvider,
        *,
        n: int,
        model: str | None = None,
        system_prompt: str | None = None,
        sampling_params: SamplingParams | None = None,
        prefill_content: str | None = None,
        mode_override: str | None = None,
    ) -> list[NodeResponse]:
        """Generate N responses in parallel and store as sibling nodes."""
        p = await self._prepare_one(
            rhizome_id, node_id, provider, model, system_prompt, sampling_params,
            prefill_content, mode_override,
        )
        await self._started(p, n=n)
        return await self._complete_all([p] * n)

    async def generate_n_stream(
        self,
        rhizome_id: str,
        node_id: str | None,
        provider: LLMProvider,
        *,
        n: int,
        model: str | None = None,
        system_prompt: str | None = None,
        sampling_params: SamplingParams | None = None,
        prefill_content: str | None = None,
        mode_override: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream N responses simultaneously, yielding chunks tagged by completion_index."""
        p = await self._prepare_one(
            rhizome_id, node_id, provider, model, system_prompt, sampling_params,
            prefill_content, mode_override,
        )
        await self._started(p, n=n)
        runs = [dataclasses.replace(p, completion_index=i) for i in range(n)]
        async for chunk in self.fan_out(runs):
            yield chunk

    async def generate_cross(
        self,
        rhizome_id: str,
        node_id: str,
        targets: list[dict],
        *,
        system_prompt: str | None = None,
        sampling_params: SamplingParams | None = None,
    ) -> list[NodeResponse]:
        """Generate from several models and store as sibling nodes.

        Each target is a dict with 'provider', 'model' and optional 'mode' keys.
        """
        prepared = await self._prepare_cross(
            rhizome_id, node_id, targets, system_prompt, sampling_params,
        )
        return await self._complete_all(prepared)

    async def generate_cross_stream(
        self,
        rhizome_id: str,
        node_id: str,
        targets: list[dict],
        *,
        system_prompt: str | None = None,
        sampling_params: SamplingParams | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream from several models simultaneously."""
        prepared = await self._prepare_cross(
            rhizome_id, node_id, targets, system_prompt, sampling_params,
        )
        async for chunk in self.fan_out(prepared):
            yield chunk

    # -- Load --

    async def load(
        self,
        rhizome_id: str,
        parent_id: str | None,
        *,
        system_prompt: str | None = None,
        sampling_params: SamplingParams | None = None,
    ) -> LoadedContext:
        """Read what a generation answering parent_id depends on."""
        rhizome = await self._projector.get_rhizome(rhizome_id)
        if rhizome is None:
            raise RhizomeNotFoundForGenerationError(rhizome_id)

        nodes = await self._projector.get_nodes(rhizome_id)
        if parent_id is not None and not any(n["node_id"] == parent_id for n in nodes):
            raise NodeNotFoundForGenerationError(parent_id)

        metadata = parse_json_field(rhizome.get("metadata")) or {}

        # Exclusions apply when scoped to a node on this path
        exclusion_rows = await self._projector.get_node_exclusions(rhizome_id)
        path_ids = self._get_path_node_ids(nodes, parent_id)
        groups = await self._projector.get_digression_groups(rhizome_id)

        eviction_raw = metadata.get("eviction_strategy")
        eviction = (
            EvictionStrategy.model_validate(eviction_raw)
            if eviction_raw and isinstance(eviction_raw, dict) else None
        )

        return LoadedContext(
            rhizome_id=rhizome_id,
            rhizome=rhizome,
            nodes=nodes,
            metadata=metadata,
            parent_id=parent_id,
            system_prompt=(
                system_prompt if system_prompt is not None
                else rhizome.get("default_system_prompt")
            ),
            params=merge_sampling_params(
                sampling_params, rhizome.get("default_sampling_params"), metadata=metadata,
            ),
            include_timestamps=bool(metadata.get("include_timestamps", False)),
            include_thinking=bool(metadata.get("include_thinking_in_context", False)),
            excluded_ids={
                r["node_id"] for r in exclusion_rows if r["scope_node_id"] in path_ids
            },
            digression_groups={g["group_id"]: g["node_ids"] for g in groups},
            excluded_group_ids={g["group_id"] for g in groups if not g["included"]},
            anchored_ids=await self._projector.get_anchored_ids(rhizome_id),
            eviction=eviction,
        )

    # -- Prepare --

    async def prepare(
        self,
        ctx: LoadedContext,
        targets: list[Target],
        *,
        prefill: str | None = None,
        generation_id: str | None = None,
        device_id: str = "local",
    ) -> list[Prepared]:
        """One Prepared per target.

        Each target runs in its own mode. Targets share context building where
        they can: one build per mode (timestamps are chat-only), sized to the
        tightest window among them so every target sees the same turns.
        """
        generation_id = generation_id or str(uuid4())
        default_model = ctx.rhizome.get("default_model") or FALLBACK_MODEL
        models = [t.model or default_model for t in targets]
        modes = [
            self._mode_for(t.provider, m, ctx.rhizome, ctx.metadata, t.mode)
            for t, m in zip(targets, models, strict=True)
        ]
        limits = [
            await resolve_context_limit(t.provider, m, ctx.params.max_tokens)
            for t, m in zip(targets, models, strict=True)
        ]
        context_limit = self._debug_context_limit(ctx.metadata) or min(limits)

        builds: dict[str, _Built] = {}
        prepared: list[Prepared] = []
        for index, (target, model, mode) in enumerate(zip(targets, models, modes, strict=True)):
            if mode not in builds:
                builds[mode] = await self._build(ctx, context_limit, mode, model)
            built = builds[mode]

            messages = [m.copy() for m in built.messages]
            params = ctx.params
            prompt_text = None
            if mode == "completion":
                prompt_text, params = self._render_completion(
                    model, messages, built.system_prompt, params, ctx.metadata,
                )
            if prefill:
                if prompt_text is not None:
                    prompt_text += prefill
                else:
                    messages.append({"role": "assistant", "content": prefill})

            prepared.append(Prepared(
                rhizome_id=ctx.rhizome_id,
                parent_id=ctx.parent_id,
                generation_id=generation_id,
                provider=target.provider,
                model=model,
                mode=mode,
                request=GenerationRequest(
                    model=model,
                    messages=messages,
                    system_prompt=built.system_prompt,
                    sampling_params=params,
                    prompt_text=prompt_text,
                ),
                context_usage=built.usage,
                active_interventions=built.active_interventions,
                include_timestamps=ctx.include_timestamps and mode == "chat",
                include_thinking=ctx.include_thinking,
                prefill=prefill,
                device_id=device_id,
                completion_index=index if len(targets) > 1 else None,
            ))
        return prepared

    async def _prepare_one(
        self,
        rhizome_id: str,
        node_id: str | None,
        provider: LLMProvider,
        model: str | None,
        system_prompt: str | None,
        sampling_params: SamplingParams | None,
        prefill: str | None,
        mode_override: str | None,
    ) -> Prepared:
        ctx = await self.load(
            rhizome_id, node_id, system_prompt=system_prompt, sampling_params=sampling_params,
        )
        [p] = await self.prepare(ctx, [Target(provider, model, mode_override)], prefill=prefill)
        return p

    async def _prepare_cross(
        self,
        rhizome_id: str,
        node_id: str,
        targets: list[dict],
        system_prompt: str | None,
        sampling_params: SamplingParams | None,
    ) -> list[Prepared]:
        ctx = await self.load(
            rhizome_id, node_id, system_prompt=system_prompt, sampling_params=sampling_params,
        )
        return await self.prepare(ctx, [
            Target(get_provider(t["provider"]), t["model"], t.get("mode")) for t in targets
        ])

    @staticmethod
    def _mode_for(
        provider: LLMProvider, model: str, rhizome: dict, metadata: dict, override: str | None,
    ) -> str:
        """The mode a generation runs in: a model's format comes from the model.

        Single-mode providers decide for themselves. For dual-mode providers:
        an explicit override, else the model's own profile, else -- for the
        rhizome's own default model only -- the rhizome's generation_mode, else
        chat. (Another model visiting a completion rhizome, say GPT on a Sun
        branch, is a chat model unless told otherwise.)
        """
        if "completion" not in provider.supported_modes:
            return "chat"
        if "chat" not in provider.supported_modes:
            return "completion"
        if override in ("chat", "completion"):
            return override
        profile_mode = (get_catalog().profile(model) or {}).get("generation_mode")
        if profile_mode in ("chat", "completion"):
            return profile_mode
        is_rhizome_model = model == (rhizome.get("default_model") or FALLBACK_MODEL)
        if is_rhizome_model and metadata.get("generation_mode") == "completion":
            return "completion"
        return "chat"

    @staticmethod
    def _render_completion(
        model: str,
        messages: list[dict[str, str]],
        system_prompt: str | None,
        params: SamplingParams,
        metadata: dict,
    ) -> tuple[str, SamplingParams]:
        """Render the prompt text; the template's stop tokens join the sampling params.

        The template is the rhizome's, unless unset or "auto": then the model's
        own (its profile), else raw.
        """
        template_name = metadata.get("prompt_template")
        if not template_name or template_name == "auto":
            template_name = (get_catalog().profile(model) or {}).get("prompt_template") or "raw"
        prompt_text, stop_tokens = render_prompt(template_name, messages, system_prompt)
        stops = list(params.stop_sequences or [])
        stops += [t for t in stop_tokens if t not in stops]
        return prompt_text, params.model_copy(update={"stop_sequences": stops})

    @staticmethod
    def _debug_context_limit(metadata: dict) -> int | None:
        limit = metadata.get("debug_context_limit")
        return limit if isinstance(limit, int) and limit > 0 else None

    async def _build(
        self, ctx: LoadedContext, context_limit: int, mode: str, model: str,
    ) -> _Built:
        """Messages for the path to ctx.parent_id: exclusions, interventions,
        eviction, and an eviction summary if the strategy asks for one."""
        pipeline = self._resolve_interventions(ctx.metadata)
        include_timestamps = ctx.include_timestamps and mode == "chat"

        if pipeline.is_empty:
            messages, usage, report = self._context_builder.build(
                nodes=ctx.nodes,
                target_node_id=ctx.parent_id,
                system_prompt=ctx.system_prompt,
                model_context_limit=context_limit,
                include_timestamps=include_timestamps,
                include_thinking=ctx.include_thinking,
                excluded_ids=ctx.excluded_ids,
                digression_groups=ctx.digression_groups,
                excluded_group_ids=ctx.excluded_group_ids,
                anchored_ids=ctx.anchored_ids,
                eviction=ctx.eviction,
            )
            system_prompt, active = ctx.system_prompt, None
        else:
            # build_messages -> pre_eviction -> count_and_evict -> post_eviction
            messages, node_ids, created_ats, excluded = self._context_builder.build_messages(
                nodes=ctx.nodes,
                target_node_id=ctx.parent_id,
                include_timestamps=include_timestamps,
                include_thinking=ctx.include_thinking,
                excluded_ids=ctx.excluded_ids,
                digression_groups=ctx.digression_groups,
                excluded_group_ids=ctx.excluded_group_ids,
            )
            ictx = pipeline.run_pre_eviction(InterventionContext(
                messages=messages,
                system_prompt=ctx.system_prompt,
                node_ids=node_ids,
                model=model,
                metadata=ctx.metadata,
                mode=mode,
                created_ats=created_ats,
            ))
            ictx.messages, usage, report = self._context_builder.count_and_evict(
                messages=ictx.messages,
                node_ids=ictx.node_ids,
                system_prompt=ictx.system_prompt,
                model_context_limit=context_limit,
                excluded_token_total=excluded["excluded_tokens"],
                excluded_node_count=excluded["excluded_count"],
                excluded_node_ids=excluded["excluded_node_ids"],
                anchored_ids=ctx.anchored_ids,
                eviction=ctx.eviction,
            )
            ictx = pipeline.run_post_eviction(ictx)
            messages, system_prompt = ictx.messages, ictx.system_prompt
            active = pipeline.get_active_configs()

        messages, usage = await self._maybe_inject_summary(messages, usage, report)
        return _Built(messages, usage, system_prompt, active)

    @staticmethod
    def _resolve_interventions(metadata: dict) -> InterventionPipeline:
        """Build an intervention pipeline from rhizome metadata."""
        raw_configs = metadata.get("context_interventions")
        if not raw_configs or not isinstance(raw_configs, list):
            return InterventionPipeline([])
        configs = [InterventionConfig.model_validate(c) for c in raw_configs]
        return default_registry.create_pipeline(configs)

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
        insert_pos = min(report.keep_first_turns, len(messages))
        messages = messages[:insert_pos] + [summary_msg] + messages[insert_pos:]
        report.summary_inserted = True

        summary_tokens = ApproximateTokenCounter().count(summary_msg["content"])
        updated_usage = context_usage.model_copy(update={
            "total_tokens": context_usage.total_tokens + summary_tokens,
            "breakdown": {
                **context_usage.breakdown,
                "user": context_usage.breakdown.get("user", 0) + summary_tokens,
            },
        })
        return messages, updated_usage

    @staticmethod
    def _get_path_node_ids(nodes: list[dict], target_node_id: str | None) -> set[str]:
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

    # -- Run --

    async def complete(self, p: Prepared) -> NodeResponse:
        """Send a prepared request and store the reply."""
        return await self.persist(p, self._with_prefill(p, await p.provider.generate(p.request)))

    async def stream(self, p: Prepared) -> AsyncIterator[StreamChunk]:
        """Stream a prepared request; the final chunk carries the stored node's id."""
        async for chunk in p.provider.generate_stream(p.request):
            if chunk.is_final and chunk.result is not None:
                result = self._with_prefill(p, chunk.result)
                node = await self.persist(p, result)
                yield StreamChunk(
                    type="message_stop", is_final=True, result=result,
                    completion_index=p.completion_index, node_id=node.node_id,
                )
                return
            yield chunk.model_copy(update={"completion_index": p.completion_index})
        raise RuntimeError(f"{p.provider.name} stream ended without a result")

    async def fan_out(self, prepared: list[Prepared]) -> AsyncIterator[StreamChunk]:
        """Stream several prepared requests at once, interleaved as chunks arrive.

        A failure is an error chunk for that completion; the others go on.
        Ends with generation_complete.
        """
        queue: asyncio.Queue[StreamChunk | None] = asyncio.Queue()

        async def pump(p: Prepared) -> None:
            try:
                async for chunk in self.stream(p):
                    await queue.put(chunk)
            except Exception as e:
                logger.exception("Generation %s failed", p.completion_index)
                await queue.put(StreamChunk(
                    type="error", text=str(e) or type(e).__name__,
                    completion_index=p.completion_index,
                ))
            finally:
                await queue.put(None)

        tasks = [asyncio.create_task(pump(p)) for p in prepared]
        try:
            remaining = len(tasks)
            while remaining:
                chunk = await queue.get()
                if chunk is None:
                    remaining -= 1
                else:
                    yield chunk
            yield StreamChunk(type="generation_complete")
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _complete_all(self, prepared: list[Prepared]) -> list[NodeResponse]:
        """Run several at once; keep every reply that succeeds.

        Raises only if all of them fail (the others are logged).
        """
        results = await asyncio.gather(
            *[self.complete(p) for p in prepared], return_exceptions=True,
        )
        nodes = [r for r in results if isinstance(r, NodeResponse)]
        errors = [r for r in results if isinstance(r, BaseException)]
        for e in errors:
            logger.error("Generation failed: %s", e, exc_info=e)
        if not nodes and errors:
            raise errors[0]
        return nodes

    # -- Record --

    async def _started(self, p: Prepared, *, n: int = 1) -> None:
        await self._events.emit(p.rhizome_id, "GenerationStarted", GenerationStartedPayload(
            generation_id=p.generation_id,
            parent_node_id=p.parent_id,
            model=p.model,
            provider=p.provider.name,
            system_prompt=p.request.system_prompt,
            sampling_params=p.request.sampling_params,
            n=n,
            mode=p.recorded_mode,
            prefill_content=p.prefill,
        ), device_id=p.device_id)

    @staticmethod
    def _with_prefill(p: Prepared, result: GenerationResult) -> GenerationResult:
        """The whole reply: a prefilled start is part of what the model said."""
        if not p.prefill:
            return result
        return result.model_copy(update={"content": p.prefill + result.content})

    async def persist(self, p: Prepared, result: GenerationResult) -> NodeResponse:
        """Store a reply as a node, recording exactly what produced it."""
        sampling_params = p.request.sampling_params
        if result.applied_sampling_params:
            # What the provider applied beyond the request (e.g. a model's logit bias)
            sampling_params = sampling_params.model_copy(update=SamplingParams.model_validate(
                {**sampling_params.model_dump(), **result.applied_sampling_params}
            ).model_dump(include=set(result.applied_sampling_params)))
        node_id = str(uuid4())
        await self._events.emit(p.rhizome_id, "NodeCreated", NodeCreatedPayload(
            node_id=node_id,
            generation_id=p.generation_id,
            parent_id=p.parent_id,
            role="assistant",
            content=result.content,
            model=result.model or p.model,
            provider=p.provider.name,
            system_prompt=p.request.system_prompt,
            sampling_params=sampling_params,
            mode=p.recorded_mode,
            prefill_content=p.prefill,
            prompt_text=result.effective_prompt_text or p.request.prompt_text,
            usage=result.usage,
            latency_ms=result.latency_ms,
            finish_reason=result.finish_reason,
            logprobs=result.logprobs,
            thinking_content=result.thinking_content,
            include_thinking_in_context=p.include_thinking,
            include_timestamps=p.include_timestamps,
            active_interventions=p.active_interventions,
            context_usage=p.context_usage,
            raw_response=result.raw_response,
        ), device_id=p.device_id)
        return await self._rhizome_service.node_response(p.rhizome_id, node_id)


class RhizomeNotFoundForGenerationError(Exception):
    def __init__(self, rhizome_id: str) -> None:
        self.rhizome_id = rhizome_id
        super().__init__(f"Rhizome not found: {rhizome_id}")


class NodeNotFoundForGenerationError(Exception):
    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        super().__init__(f"Node not found: {node_id}")
