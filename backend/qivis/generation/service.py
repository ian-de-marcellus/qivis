"""Generation service: orchestrates LLM calls and event emission."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.context import ContextBuilder, get_model_context_limit
from qivis.models import (
    ContextUsage,
    EventEnvelope,
    GenerationStartedPayload,
    NodeCreatedPayload,
    SamplingParams,
)
from qivis.providers.base import GenerationRequest, GenerationResult, LLMProvider, StreamChunk
from qivis.trees.schemas import NodeResponse
from qivis.trees.service import TreeService


class GenerationService:
    """Orchestrates LLM generation: context assembly, API call, event emission."""

    def __init__(
        self,
        tree_service: TreeService,
        store: EventStore,
        projector: StateProjector,
    ) -> None:
        self._tree_service = tree_service
        self._store = store
        self._projector = projector
        self._context_builder = ContextBuilder()

    async def generate(
        self,
        tree_id: str,
        node_id: str,
        provider: LLMProvider,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        sampling_params: SamplingParams | None = None,
    ) -> NodeResponse:
        """Generate a non-streaming response and store as a new node."""
        tree, nodes, resolved_model, resolved_prompt, resolved_params = (
            await self._resolve_context(tree_id, node_id, model, system_prompt, sampling_params)
        )
        context_limit = get_model_context_limit(resolved_model)
        messages, context_usage, _eviction_report = self._context_builder.build(
            nodes=nodes,
            target_node_id=node_id,
            system_prompt=resolved_prompt,
            model_context_limit=context_limit,
        )
        generation_id = str(uuid4())

        await self._emit_generation_started(
            tree_id, generation_id, node_id,
            resolved_model, provider.name, resolved_prompt, resolved_params,
        )

        request = GenerationRequest(
            model=resolved_model,
            messages=messages,
            system_prompt=resolved_prompt,
            sampling_params=resolved_params,
        )
        result = await provider.generate(request)

        return await self._emit_node_created(
            tree_id, generation_id, node_id, result,
            provider.name, resolved_prompt, resolved_params,
            context_usage=context_usage,
        )

    async def generate_n(
        self,
        tree_id: str,
        node_id: str,
        provider: LLMProvider,
        *,
        n: int,
        model: str | None = None,
        system_prompt: str | None = None,
        sampling_params: SamplingParams | None = None,
    ) -> list[NodeResponse]:
        """Generate N responses in parallel and store as sibling nodes."""
        tree, nodes, resolved_model, resolved_prompt, resolved_params = (
            await self._resolve_context(tree_id, node_id, model, system_prompt, sampling_params)
        )
        context_limit = get_model_context_limit(resolved_model)
        messages, context_usage, _eviction_report = self._context_builder.build(
            nodes=nodes,
            target_node_id=node_id,
            system_prompt=resolved_prompt,
            model_context_limit=context_limit,
        )
        generation_id = str(uuid4())

        await self._emit_generation_started(
            tree_id, generation_id, node_id,
            resolved_model, provider.name, resolved_prompt, resolved_params,
            n=n,
        )

        request = GenerationRequest(
            model=resolved_model,
            messages=messages,
            system_prompt=resolved_prompt,
            sampling_params=resolved_params,
        )
        results = await asyncio.gather(*[provider.generate(request) for _ in range(n)])

        created: list[NodeResponse] = []
        for result in results:
            node = await self._emit_node_created(
                tree_id, generation_id, node_id, result,
                provider.name, resolved_prompt, resolved_params,
                context_usage=context_usage,
            )
            created.append(node)
        return created

    async def generate_stream(
        self,
        tree_id: str,
        node_id: str,
        provider: LLMProvider,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        sampling_params: SamplingParams | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Generate a streaming response, yielding chunks."""
        tree, nodes, resolved_model, resolved_prompt, resolved_params = (
            await self._resolve_context(tree_id, node_id, model, system_prompt, sampling_params)
        )
        context_limit = get_model_context_limit(resolved_model)
        messages, context_usage, _eviction_report = self._context_builder.build(
            nodes=nodes,
            target_node_id=node_id,
            system_prompt=resolved_prompt,
            model_context_limit=context_limit,
        )
        generation_id = str(uuid4())

        await self._emit_generation_started(
            tree_id, generation_id, node_id,
            resolved_model, provider.name, resolved_prompt, resolved_params,
        )

        request = GenerationRequest(
            model=resolved_model,
            messages=messages,
            system_prompt=resolved_prompt,
            sampling_params=resolved_params,
        )

        async for chunk in provider.generate_stream(request):
            if chunk.is_final and chunk.result is not None:
                node = await self._emit_node_created(
                    tree_id, generation_id, node_id, chunk.result,
                    provider.name, resolved_prompt, resolved_params,
                    context_usage=context_usage,
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

    async def _resolve_context(
        self,
        tree_id: str,
        node_id: str,
        model: str | None,
        system_prompt: str | None,
        sampling_params: SamplingParams | None,
    ) -> tuple[dict, list[dict], str, str | None, SamplingParams]:
        """Validate tree/node and resolve parameters from request or tree defaults."""
        tree = await self._projector.get_tree(tree_id)
        if tree is None:
            raise TreeNotFoundForGenerationError(tree_id)

        nodes = await self._projector.get_nodes(tree_id)
        node_ids = {n["node_id"] for n in nodes}
        if node_id not in node_ids:
            raise NodeNotFoundForGenerationError(node_id)

        resolved_model = model or tree.get("default_model") or "claude-sonnet-4-5-20250929"
        resolved_prompt = system_prompt if system_prompt is not None else tree.get(
            "default_system_prompt"
        )
        resolved_params = sampling_params or SamplingParams()

        return tree, nodes, resolved_model, resolved_prompt, resolved_params

    async def _emit_generation_started(
        self,
        tree_id: str,
        generation_id: str,
        parent_node_id: str,
        model: str,
        provider_name: str,
        system_prompt: str | None,
        sampling_params: SamplingParams,
        *,
        n: int = 1,
    ) -> None:
        payload = GenerationStartedPayload(
            generation_id=generation_id,
            parent_node_id=parent_node_id,
            model=model,
            provider=provider_name,
            system_prompt=system_prompt,
            sampling_params=sampling_params,
            n=n,
        )
        event = EventEnvelope(
            event_id=str(uuid4()),
            tree_id=tree_id,
            timestamp=datetime.now(UTC),
            device_id="local",
            event_type="GenerationStarted",
            payload=payload.model_dump(),
        )
        await self._store.append(event)
        await self._projector.project([event])

    async def _emit_node_created(
        self,
        tree_id: str,
        generation_id: str,
        parent_id: str,
        result: GenerationResult,
        provider_name: str,
        system_prompt: str | None,
        sampling_params: SamplingParams,
        *,
        context_usage: ContextUsage | None = None,
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
            mode="chat",
            usage=result.usage,
            latency_ms=result.latency_ms,
            finish_reason=result.finish_reason,
            logprobs=result.logprobs,
            context_usage=context_usage,
            raw_response=result.raw_response,
        )
        event = EventEnvelope(
            event_id=str(uuid4()),
            tree_id=tree_id,
            timestamp=datetime.now(UTC),
            device_id="local",
            event_type="NodeCreated",
            payload=payload.model_dump(),
        )
        await self._store.append(event)
        await self._projector.project([event])

        # Read back the projected node with sibling info
        nodes = await self._projector.get_nodes(tree_id)
        sibling_info = TreeService._compute_sibling_info(nodes)
        node_row = next(n for n in nodes if n["node_id"] == node_id)
        return TreeService._node_from_row(node_row, sibling_info=sibling_info)


class TreeNotFoundForGenerationError(Exception):
    def __init__(self, tree_id: str) -> None:
        self.tree_id = tree_id
        super().__init__(f"Tree not found: {tree_id}")


class NodeNotFoundForGenerationError(Exception):
    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        super().__init__(f"Node not found: {node_id}")
