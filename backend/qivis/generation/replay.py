"""Replay service: answer a conversation's assistant turns with a different model.

Context-faithful: at each assistant turn on the path, the new model answers
the same context the original model saw. Each answer is stored as a sibling
of the original turn (same parent), generated through the normal generation
path -- so the parent chain is exactly what the model saw, and exclusions,
interventions, and eviction apply as usual.

(Trajectory replay, where the model saw its own earlier replies and the user
turns were copied into a new branch, was removed in Sep 2026: it only made
sense for scripted conversations. It's in git history.)
"""

from collections.abc import AsyncIterator

from qivis.errors import InvalidRequestError
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.service import GenerationService, RhizomeNotFoundForGenerationError
from qivis.models import SamplingParams
from qivis.providers.base import LLMProvider, StreamChunk
from qivis.rhizomes.schemas import NodeResponse
from qivis.rhizomes.service import RhizomeService


class InvalidReplayPathError(InvalidRequestError):
    """Raised when the provided path is empty or disconnected."""


class ReplayService:
    """Replays a path's assistant turns through another model (context-faithful)."""

    def __init__(
        self,
        rhizome_service: RhizomeService,
        generation_service: GenerationService,
        store: EventStore,
        projector: StateProjector,
    ) -> None:
        self._gen_svc = generation_service
        self._projector = projector

    async def replay_path(
        self,
        rhizome_id: str,
        path_node_ids: list[str],
        provider: LLMProvider,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        sampling_params: SamplingParams | None = None,
        generation_mode: str | None = None,
    ) -> list[NodeResponse]:
        """Answer each assistant turn on the path; returns the new sibling nodes."""
        created: list[NodeResponse] = []
        for original in await self._assistant_turns(rhizome_id, path_node_ids):
            # parent_id None (a root assistant turn) is a root generation
            created.append(await self._gen_svc.generate(
                rhizome_id, original.get("parent_id"), provider,
                model=model, system_prompt=system_prompt,
                sampling_params=sampling_params, mode_override=generation_mode,
            ))
        return created

    async def replay_path_stream(
        self,
        rhizome_id: str,
        path_node_ids: list[str],
        provider: LLMProvider,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        sampling_params: SamplingParams | None = None,
        generation_mode: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Streaming replay: replay_step, text_delta, message_stop per turn, then
        replay_complete. Deltas and stops carry the step as completion_index."""
        steps = await self._assistant_turns(rhizome_id, path_node_ids)
        created_node_ids: list[str] = []
        for i, original in enumerate(steps):
            parent_id = original.get("parent_id")
            yield StreamChunk(type="replay_step", data={
                "step": i + 1, "total": len(steps), "type": "generating",
                "parent_id": parent_id, "original_node_id": original["node_id"],
            })
            async for chunk in self._gen_svc.generate_stream(
                rhizome_id, parent_id, provider,
                model=model, system_prompt=system_prompt,
                sampling_params=sampling_params, mode_override=generation_mode,
            ):
                if chunk.node_id:
                    created_node_ids.append(chunk.node_id)
                yield chunk.model_copy(update={"completion_index": i})
        yield StreamChunk(type="replay_complete", data={
            "mode": "context_faithful", "created_node_ids": created_node_ids,
        })

    async def _assistant_turns(self, rhizome_id: str, path_node_ids: list[str]) -> list[dict]:
        """Validate the path and return its assistant nodes (the turns to replay)."""
        if not path_node_ids:
            raise InvalidReplayPathError("Replay path is empty")
        if await self._projector.get_rhizome(rhizome_id) is None:
            raise RhizomeNotFoundForGenerationError(rhizome_id)
        node_map = {n["node_id"]: n for n in await self._projector.get_nodes(rhizome_id)}
        for nid in path_node_ids:
            if nid not in node_map:
                raise InvalidReplayPathError(f"Node {nid} not found in rhizome")
        for parent, child in zip(path_node_ids, path_node_ids[1:], strict=False):
            if node_map[child].get("parent_id") != parent:
                raise InvalidReplayPathError(
                    f"Node {child} is not a child of {parent} — path is disconnected"
                )
        return [node_map[nid] for nid in path_node_ids if node_map[nid]["role"] == "assistant"]
