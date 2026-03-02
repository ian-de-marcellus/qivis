"""Replay service: orchestrates conversation replay through a different model."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.context import ContextBuilder, get_model_context_limit
from qivis.generation.service import GenerationService, merge_sampling_params
from qivis.generation.interventions import (
    InterventionContext,
    InterventionPipeline,
)
from qivis.generation.tokens import ApproximateTokenCounter
from qivis.models import (
    ContextUsage,
    EventEnvelope,
    EvictionStrategy,
    NodeCreatedPayload,
    SamplingParams,
)
from qivis.providers.base import GenerationRequest, GenerationResult, LLMProvider, StreamChunk
from qivis.rhizomes.schemas import CreateNodeRequest, NodeResponse
from qivis.rhizomes.service import RhizomeService
from qivis.utils.json import parse_json_field


class InvalidReplayPathError(Exception):
    """Raised when the provided path is empty or disconnected."""
    pass


class ReplayService:
    """Orchestrates conversation replay through a different model.

    Supports two modes:
    - context_faithful: model sees original assistant messages at each step
    - trajectory: model sees its own prior responses at each step
    """

    def __init__(
        self,
        rhizome_service: RhizomeService,
        generation_service: GenerationService,
        store: EventStore,
        projector: StateProjector,
    ) -> None:
        self._rhizome_svc = rhizome_service
        self._gen_svc = generation_service
        self._store = store
        self._projector = projector
        self._context_builder = ContextBuilder()

    async def replay_path(
        self,
        rhizome_id: str,
        path_node_ids: list[str],
        provider: LLMProvider,
        *,
        mode: Literal["context_faithful", "trajectory"] = "context_faithful",
        model: str | None = None,
        system_prompt: str | None = None,
        sampling_params: SamplingParams | None = None,
    ) -> list[NodeResponse]:
        """Replay a conversation path through a different model.

        Returns all created nodes (user copies + assistant generations).
        """
        self._validate_path(path_node_ids)

        rhizome = await self._projector.get_rhizome(rhizome_id)
        if rhizome is None:
            raise InvalidReplayPathError(f"Rhizome not found: {rhizome_id}")

        nodes = await self._projector.get_nodes(rhizome_id)
        node_map = {n["node_id"]: n for n in nodes}

        # Validate all path nodes exist and are connected
        self._validate_path_connectivity(path_node_ids, node_map)

        # Separate path into steps
        path_nodes = [node_map[nid] for nid in path_node_ids]
        original_messages = self._extract_messages(path_nodes)

        # Resolve parameters
        metadata = parse_json_field(rhizome.get("metadata")) or {}
        resolved_model = model or rhizome.get("default_model") or "claude-sonnet-4-5-20250929"
        resolved_prompt = system_prompt if system_prompt is not None else rhizome.get("default_system_prompt")
        resolved_params = merge_sampling_params(
            sampling_params, rhizome.get("default_sampling_params"), metadata=metadata,
        )

        replay_id = str(uuid4())
        created_nodes: list[NodeResponse] = []
        prev_replay_node_id: str | None = path_nodes[0].get("parent_id")  # fork point

        for i, path_node in enumerate(path_nodes):
            role = path_node["role"]

            if role in ("user", "system", "tool", "researcher_note"):
                # Copy user message as new node
                content = path_node.get("edited_content") or path_node["content"]
                node = await self._create_replay_node(
                    rhizome_id=rhizome_id,
                    parent_id=prev_replay_node_id,
                    role=role,
                    content=content,
                    replay_id=replay_id,
                )
                created_nodes.append(node)
                prev_replay_node_id = node.node_id

            elif role == "assistant":
                # Generate new assistant response
                if mode == "context_faithful":
                    messages = self._build_context_faithful_messages(
                        original_messages, i,
                    )
                else:
                    # Trajectory: build context from the replay branch
                    messages = self._build_trajectory_messages(created_nodes)

                result = await self._generate_with_context(
                    provider=provider,
                    messages=messages,
                    system_prompt=resolved_prompt,
                    model=resolved_model,
                    params=resolved_params,
                    metadata=metadata,
                )

                node = await self._emit_replay_assistant(
                    rhizome_id=rhizome_id,
                    replay_id=replay_id,
                    parent_id=prev_replay_node_id,
                    result=result,
                    provider_name=provider.name,
                    system_prompt=resolved_prompt,
                    sampling_params=resolved_params,
                    model=resolved_model,
                )
                created_nodes.append(node)
                prev_replay_node_id = node.node_id

        return created_nodes

    async def replay_path_stream(
        self,
        rhizome_id: str,
        path_node_ids: list[str],
        provider: LLMProvider,
        *,
        mode: Literal["context_faithful", "trajectory"] = "context_faithful",
        model: str | None = None,
        system_prompt: str | None = None,
        sampling_params: SamplingParams | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Streaming replay with progress events.

        Yields replay_step, text_delta, message_stop, and replay_complete events.
        """
        self._validate_path(path_node_ids)

        rhizome = await self._projector.get_rhizome(rhizome_id)
        if rhizome is None:
            raise InvalidReplayPathError(f"Rhizome not found: {rhizome_id}")

        nodes = await self._projector.get_nodes(rhizome_id)
        node_map = {n["node_id"]: n for n in nodes}
        self._validate_path_connectivity(path_node_ids, node_map)

        path_nodes = [node_map[nid] for nid in path_node_ids]
        original_messages = self._extract_messages(path_nodes)

        metadata = parse_json_field(rhizome.get("metadata")) or {}
        resolved_model = model or rhizome.get("default_model") or "claude-sonnet-4-5-20250929"
        resolved_prompt = system_prompt if system_prompt is not None else rhizome.get("default_system_prompt")
        resolved_params = merge_sampling_params(
            sampling_params, rhizome.get("default_sampling_params"), metadata=metadata,
        )

        replay_id = str(uuid4())
        created_nodes: list[NodeResponse] = []
        created_node_ids: list[str] = []
        prev_replay_node_id: str | None = path_nodes[0].get("parent_id")
        total = len(path_nodes)

        for i, path_node in enumerate(path_nodes):
            role = path_node["role"]
            step = i + 1

            if role in ("user", "system", "tool", "researcher_note"):
                content = path_node.get("edited_content") or path_node["content"]
                node = await self._create_replay_node(
                    rhizome_id=rhizome_id,
                    parent_id=prev_replay_node_id,
                    role=role,
                    content=content,
                    replay_id=replay_id,
                )
                created_nodes.append(node)
                created_node_ids.append(node.node_id)
                prev_replay_node_id = node.node_id

                yield StreamChunk(
                    type="replay_step",
                    text=f'{{"step": {step}, "total": {total}, "type": "user_copied", "node_id": "{node.node_id}"}}',
                )

            elif role == "assistant":
                yield StreamChunk(
                    type="replay_step",
                    text=f'{{"step": {step}, "total": {total}, "type": "generating"}}',
                )

                if mode == "context_faithful":
                    messages = self._build_context_faithful_messages(original_messages, i)
                else:
                    messages = self._build_trajectory_messages(created_nodes)

                # Stream the generation
                request = GenerationRequest(
                    model=resolved_model,
                    messages=messages,
                    system_prompt=resolved_prompt,
                    sampling_params=resolved_params,
                )

                accumulated = ""
                final_result = None
                async for chunk in provider.generate_stream(request):
                    if chunk.is_final and chunk.result:
                        final_result = chunk.result
                        accumulated = chunk.result.content
                    elif chunk.text:
                        accumulated += chunk.text
                        yield StreamChunk(
                            type="text_delta",
                            text=chunk.text,
                            completion_index=i,
                        )

                if final_result is None:
                    final_result = GenerationResult(
                        content=accumulated,
                        model=resolved_model,
                        finish_reason="stop",
                    )

                node = await self._emit_replay_assistant(
                    rhizome_id=rhizome_id,
                    replay_id=replay_id,
                    parent_id=prev_replay_node_id,
                    result=final_result,
                    provider_name=provider.name,
                    system_prompt=resolved_prompt,
                    sampling_params=resolved_params,
                    model=resolved_model,
                )
                created_nodes.append(node)
                created_node_ids.append(node.node_id)
                prev_replay_node_id = node.node_id

                # Emit message_stop for this step
                stop_data = {
                    "type": "message_stop",
                    "node_id": node.node_id,
                    "content": final_result.content,
                    "finish_reason": final_result.finish_reason,
                    "completion_index": i,
                }
                yield StreamChunk(
                    type="message_stop",
                    text=str(stop_data),
                    is_final=False,
                    result=final_result,
                    completion_index=i,
                )

        # Final replay_complete event
        yield StreamChunk(
            type="replay_complete",
            text=f'{{"replay_id": "{replay_id}", "created_node_ids": {created_node_ids}}}',
        )

    # -- Validation --

    def _validate_path(self, path_node_ids: list[str]) -> None:
        if not path_node_ids:
            raise InvalidReplayPathError("Replay path is empty")

    def _validate_path_connectivity(
        self, path_node_ids: list[str], node_map: dict[str, dict]
    ) -> None:
        """Validate that path_node_ids form a connected parent→child chain."""
        for nid in path_node_ids:
            if nid not in node_map:
                raise InvalidReplayPathError(f"Node {nid} not found in rhizome")

        for i in range(1, len(path_node_ids)):
            child = node_map[path_node_ids[i]]
            expected_parent = path_node_ids[i - 1]
            if child.get("parent_id") != expected_parent:
                raise InvalidReplayPathError(
                    f"Node {path_node_ids[i]} is not a child of {expected_parent} — path is disconnected"
                )

    # -- Message extraction --

    def _extract_messages(self, path_nodes: list[dict]) -> list[dict[str, str]]:
        """Extract messages from path nodes for context building."""
        messages = []
        for node in path_nodes:
            content = node.get("edited_content") or node["content"]
            messages.append({"role": node["role"], "content": content})
        return messages

    def _build_context_faithful_messages(
        self, original_messages: list[dict[str, str]], current_index: int
    ) -> list[dict[str, str]]:
        """Build message list using original conversation up to current position."""
        # Include all messages up to (but not including) the current assistant message
        return [m.copy() for m in original_messages[:current_index]]

    def _build_trajectory_messages(
        self, created_nodes: list[NodeResponse]
    ) -> list[dict[str, str]]:
        """Build message list from the replay branch's own nodes."""
        return [{"role": n.role, "content": n.content} for n in created_nodes]

    # -- Node creation --

    async def _create_replay_node(
        self,
        rhizome_id: str,
        parent_id: str | None,
        role: str,
        content: str,
        replay_id: str,
    ) -> NodeResponse:
        """Create a user message copy in the replay branch."""
        node_id = str(uuid4())
        payload = NodeCreatedPayload(
            node_id=node_id,
            parent_id=parent_id,
            role=role,
            content=content,
            mode="chat",
            generation_id=replay_id,
        )
        event = EventEnvelope(
            event_id=str(uuid4()),
            rhizome_id=rhizome_id,
            timestamp=datetime.now(UTC),
            device_id="replay",
            event_type="NodeCreated",
            payload=payload.model_dump(),
        )
        await self._store.append(event)
        await self._projector.project([event])

        nodes = await self._projector.get_nodes(rhizome_id)
        sibling_info = RhizomeService._compute_sibling_info(nodes)
        node_row = next(n for n in nodes if n["node_id"] == node_id)
        return RhizomeService._node_from_row(node_row, sibling_info=sibling_info)

    async def _emit_replay_assistant(
        self,
        rhizome_id: str,
        replay_id: str,
        parent_id: str | None,
        result: GenerationResult,
        provider_name: str,
        system_prompt: str | None,
        sampling_params: SamplingParams,
        model: str,
    ) -> NodeResponse:
        """Emit a generated assistant node in the replay branch."""
        node_id = str(uuid4())
        payload = NodeCreatedPayload(
            node_id=node_id,
            generation_id=replay_id,
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
            device_id="replay",
            event_type="NodeCreated",
            payload=payload.model_dump(),
        )
        await self._store.append(event)
        await self._projector.project([event])

        nodes = await self._projector.get_nodes(rhizome_id)
        sibling_info = RhizomeService._compute_sibling_info(nodes)
        node_row = next(n for n in nodes if n["node_id"] == node_id)
        return RhizomeService._node_from_row(node_row, sibling_info=sibling_info)

    async def _generate_with_context(
        self,
        provider: LLMProvider,
        messages: list[dict[str, str]],
        system_prompt: str | None,
        model: str,
        params: SamplingParams,
        metadata: dict,
    ) -> GenerationResult:
        """Generate a response with explicit messages (bypassing normal context resolution)."""
        # Handle completion mode per-provider
        prompt_text, resolved_params, mode_hint = GenerationService._prepare_completion_mode(
            provider, messages, system_prompt, params, metadata,
        )

        request = GenerationRequest(
            model=model,
            messages=messages,
            system_prompt=system_prompt,
            sampling_params=resolved_params,
            prompt_text=prompt_text,
        )
        return await provider.generate(request)
