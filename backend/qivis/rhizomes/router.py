"""FastAPI routes for rhizome and node CRUD, and generation."""

import json as json_module
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from qivis.generation.perturbation import PerturbationService
from qivis.generation.replay import InvalidReplayPathError, ReplayService
from qivis.generation.service import (
    GenerationService,
    NodeNotFoundForGenerationError,
    RhizomeNotFoundForGenerationError,
)
from qivis.providers.base import LLMProvider
from qivis.providers.registry import ProviderNotFoundError, get_provider
from qivis.rhizomes.schemas import (
    AddAnnotationRequest,
    AnnotationResponse,
    BookmarkResponse,
    BulkAnchorRequest,
    CreateBookmarkRequest,
    CreateDigressionGroupRequest,
    CreateNodeRequest,
    CreateNoteRequest,
    CreateSummaryRequest,
    CreateRhizomeRequest,
    CrossModelGenerateRequest,
    DivergenceMetrics,
    DigressionGroupResponse,
    EditHistoryResponse,
    ExcludeNodeRequest,
    GenerateRequest,
    IncludeNodeRequest,
    InterventionTimelineResponse,
    NodeExclusionResponse,
    NodeResponse,
    NoteResponse,
    PatchNodeContentRequest,
    PatchRhizomeRequest,
    PerturbationConfig,
    PerturbationReportResponse,
    PerturbationRequest,
    PerturbationStepResponse,
    ReplayRequest,
    SummaryResponse,
    TaxonomyResponse,
    ToggleDigressionGroupRequest,
    RhizomeDetailResponse,
    RhizomeSummary,
)
from qivis.rhizomes.service import (
    AnnotationNotFoundError,
    BookmarkNotFoundError,
    DigressionGroupNotFoundError,
    InvalidParentError,
    NodeNotFoundError,
    NonContiguousGroupError,
    NoteNotFoundError,
    SummaryClientNotConfiguredError,
    SummaryNotFoundError,
    RhizomeNotFoundError,
    RhizomeService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rhizomes", tags=["rhizomes"])


def get_rhizome_service() -> RhizomeService:
    """Dependency placeholder — replaced at app startup."""
    raise RuntimeError("RhizomeService not initialized")


def get_generation_service() -> GenerationService:
    """Dependency placeholder — replaced at app startup."""
    raise RuntimeError("GenerationService not initialized")


def get_replay_service() -> ReplayService:
    """Dependency placeholder — replaced at app startup."""
    raise RuntimeError("ReplayService not initialized")


def get_perturbation_service() -> PerturbationService:
    """Dependency placeholder — replaced at app startup."""
    raise RuntimeError("PerturbationService not initialized")


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_rhizome(
    request: CreateRhizomeRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> RhizomeDetailResponse:
    return await service.create_rhizome(request)


@router.get("")
async def list_rhizomes(
    include_archived: bool = False,
    service: RhizomeService = Depends(get_rhizome_service),
) -> list[RhizomeSummary]:
    return await service.list_rhizomes(include_archived=include_archived)


@router.get("/{rhizome_id}")
async def get_rhizome(
    rhizome_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> RhizomeDetailResponse:
    rhizome = await service.get_rhizome(rhizome_id)
    if rhizome is None:
        raise HTTPException(status_code=404, detail=f"Rhizome not found: {rhizome_id}")
    return rhizome


@router.patch("/{rhizome_id}")
async def update_rhizome(
    rhizome_id: str,
    request: PatchRhizomeRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> RhizomeDetailResponse:
    try:
        return await service.update_rhizome(rhizome_id, request)
    except RhizomeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Rhizome not found: {rhizome_id}")


@router.post("/{rhizome_id}/archive")
async def archive_rhizome(
    rhizome_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> RhizomeDetailResponse:
    try:
        return await service.archive_rhizome(rhizome_id)
    except RhizomeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Rhizome not found: {rhizome_id}")


@router.post("/{rhizome_id}/unarchive")
async def unarchive_rhizome(
    rhizome_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> RhizomeDetailResponse:
    try:
        return await service.unarchive_rhizome(rhizome_id)
    except RhizomeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Rhizome not found: {rhizome_id}")


@router.post("/{rhizome_id}/nodes", status_code=status.HTTP_201_CREATED)
async def create_node(
    rhizome_id: str,
    request: CreateNodeRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> NodeResponse:
    try:
        return await service.create_node(rhizome_id, request)
    except RhizomeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Rhizome not found: {rhizome_id}")
    except InvalidParentError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{rhizome_id}/nodes/{node_id}/content")
async def edit_node_content(
    rhizome_id: str,
    node_id: str,
    request: PatchNodeContentRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> NodeResponse:
    try:
        return await service.edit_node_content(rhizome_id, node_id, request.edited_content)
    except RhizomeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Rhizome not found: {rhizome_id}")
    except NodeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")


@router.get("/{rhizome_id}/nodes/{node_id}/edit-history")
async def get_edit_history(
    rhizome_id: str,
    node_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> EditHistoryResponse:
    try:
        return await service.get_edit_history(rhizome_id, node_id)
    except RhizomeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Rhizome not found: {rhizome_id}")
    except NodeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")


@router.get("/{rhizome_id}/interventions")
async def get_interventions(
    rhizome_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> InterventionTimelineResponse:
    try:
        return await service.get_intervention_timeline(rhizome_id)
    except RhizomeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Rhizome not found: {rhizome_id}")


@router.post(
    "/{rhizome_id}/nodes/{node_id}/annotations",
    status_code=status.HTTP_201_CREATED,
)
async def add_annotation(
    rhizome_id: str,
    node_id: str,
    request: AddAnnotationRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> AnnotationResponse:
    try:
        return await service.add_annotation(rhizome_id, node_id, request)
    except RhizomeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Rhizome not found: {rhizome_id}")
    except NodeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")


@router.get("/{rhizome_id}/nodes/{node_id}/annotations")
async def get_node_annotations(
    rhizome_id: str,
    node_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> list[AnnotationResponse]:
    return await service.get_node_annotations(rhizome_id, node_id)


@router.delete(
    "/{rhizome_id}/annotations/{annotation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_annotation(
    rhizome_id: str,
    annotation_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> None:
    try:
        await service.remove_annotation(rhizome_id, annotation_id)
    except AnnotationNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Annotation not found: {annotation_id}"
        )


@router.get("/{rhizome_id}/taxonomy")
async def get_rhizome_taxonomy(
    rhizome_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> TaxonomyResponse:
    try:
        return await service.get_rhizome_taxonomy(rhizome_id)
    except RhizomeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Rhizome not found: {rhizome_id}")


@router.post(
    "/{rhizome_id}/nodes/{node_id}/notes",
    status_code=status.HTTP_201_CREATED,
)
async def add_note(
    rhizome_id: str,
    node_id: str,
    request: CreateNoteRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> NoteResponse:
    try:
        return await service.add_note(rhizome_id, node_id, request)
    except RhizomeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Rhizome not found: {rhizome_id}")
    except NodeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")


@router.get("/{rhizome_id}/nodes/{node_id}/notes")
async def get_node_notes(
    rhizome_id: str,
    node_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> list[NoteResponse]:
    return await service.get_node_notes(rhizome_id, node_id)


@router.get("/{rhizome_id}/notes")
async def get_rhizome_notes(
    rhizome_id: str,
    q: str | None = None,
    service: RhizomeService = Depends(get_rhizome_service),
) -> list[NoteResponse]:
    return await service.get_rhizome_notes(rhizome_id, query=q)


@router.delete(
    "/{rhizome_id}/notes/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_note(
    rhizome_id: str,
    note_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> None:
    try:
        await service.remove_note(rhizome_id, note_id)
    except NoteNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Note not found: {note_id}"
        )


@router.get("/{rhizome_id}/annotations")
async def get_rhizome_annotations(
    rhizome_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> list[AnnotationResponse]:
    return await service.get_rhizome_annotations(rhizome_id)


@router.post(
    "/{rhizome_id}/nodes/{node_id}/bookmarks",
    status_code=status.HTTP_201_CREATED,
)
async def add_bookmark(
    rhizome_id: str,
    node_id: str,
    request: CreateBookmarkRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> BookmarkResponse:
    try:
        return await service.add_bookmark(rhizome_id, node_id, request)
    except RhizomeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Rhizome not found: {rhizome_id}")
    except NodeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")


@router.get("/{rhizome_id}/bookmarks")
async def get_rhizome_bookmarks(
    rhizome_id: str,
    q: str | None = None,
    service: RhizomeService = Depends(get_rhizome_service),
) -> list[BookmarkResponse]:
    return await service.get_rhizome_bookmarks(rhizome_id, query=q)


@router.delete(
    "/{rhizome_id}/bookmarks/{bookmark_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_bookmark(
    rhizome_id: str,
    bookmark_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> None:
    try:
        await service.remove_bookmark(rhizome_id, bookmark_id)
    except BookmarkNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Bookmark not found: {bookmark_id}"
        )


@router.post("/{rhizome_id}/bookmarks/{bookmark_id}/summarize")
async def summarize_bookmark(
    rhizome_id: str,
    bookmark_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> BookmarkResponse:
    try:
        return await service.generate_bookmark_summary(rhizome_id, bookmark_id)
    except RhizomeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Rhizome not found: {rhizome_id}")
    except BookmarkNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Bookmark not found: {bookmark_id}"
        )
    except SummaryClientNotConfiguredError:
        raise HTTPException(
            status_code=503, detail="Summary API key not configured"
        )


# -- Manual summarization --


@router.post("/{rhizome_id}/nodes/{node_id}/summarize")
async def generate_summary(
    rhizome_id: str,
    node_id: str,
    request: CreateSummaryRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> SummaryResponse:
    try:
        return await service.generate_summary(rhizome_id, node_id, request)
    except RhizomeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Rhizome not found: {rhizome_id}")
    except NodeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")
    except SummaryClientNotConfiguredError:
        raise HTTPException(
            status_code=503, detail="Summary API key not configured"
        )


@router.get("/{rhizome_id}/summaries")
async def list_summaries(
    rhizome_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> list[SummaryResponse]:
    return await service.list_summaries(rhizome_id)


@router.delete(
    "/{rhizome_id}/summaries/{summary_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_summary(
    rhizome_id: str,
    summary_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> None:
    try:
        await service.remove_summary(rhizome_id, summary_id)
    except SummaryNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Summary not found: {summary_id}"
        )


@router.post("/{rhizome_id}/nodes/{node_id}/exclude")
async def exclude_node(
    rhizome_id: str,
    node_id: str,
    request: ExcludeNodeRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> NodeExclusionResponse:
    try:
        return await service.exclude_node(rhizome_id, node_id, request)
    except RhizomeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Rhizome not found: {rhizome_id}")
    except NodeNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/{rhizome_id}/nodes/{node_id}/include",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def include_node(
    rhizome_id: str,
    node_id: str,
    request: IncludeNodeRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> None:
    await service.include_node(rhizome_id, node_id, request.scope_node_id)


@router.get("/{rhizome_id}/exclusions")
async def get_rhizome_exclusions(
    rhizome_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> list[NodeExclusionResponse]:
    return await service.get_rhizome_exclusions(rhizome_id)


@router.post(
    "/{rhizome_id}/digression-groups",
    status_code=status.HTTP_201_CREATED,
)
async def create_digression_group(
    rhizome_id: str,
    request: CreateDigressionGroupRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> DigressionGroupResponse:
    try:
        return await service.create_digression_group(rhizome_id, request)
    except RhizomeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Rhizome not found: {rhizome_id}")
    except NodeNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except NonContiguousGroupError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{rhizome_id}/digression-groups")
async def get_digression_groups(
    rhizome_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> list[DigressionGroupResponse]:
    return await service.get_digression_groups(rhizome_id)


@router.post("/{rhizome_id}/digression-groups/{group_id}/toggle")
async def toggle_digression_group(
    rhizome_id: str,
    group_id: str,
    request: ToggleDigressionGroupRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> DigressionGroupResponse:
    try:
        return await service.toggle_digression_group(rhizome_id, group_id, request.included)
    except DigressionGroupNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Digression group not found: {group_id}"
        )


@router.delete(
    "/{rhizome_id}/digression-groups/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_digression_group(
    rhizome_id: str,
    group_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> None:
    try:
        await service.delete_digression_group(rhizome_id, group_id)
    except DigressionGroupNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Digression group not found: {group_id}"
        )


@router.post("/{rhizome_id}/bulk-anchor")
async def bulk_anchor(
    rhizome_id: str,
    request: BulkAnchorRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> dict:
    try:
        changed = await service.bulk_anchor(rhizome_id, request.node_ids, request.anchor)
        return {"changed": changed, "anchor": request.anchor}
    except RhizomeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Rhizome not found: {rhizome_id}")


@router.post("/{rhizome_id}/nodes/{node_id}/anchor")
async def toggle_anchor(
    rhizome_id: str,
    node_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> dict:
    try:
        is_anchored = await service.anchor_node(rhizome_id, node_id)
        return {"is_anchored": is_anchored}
    except RhizomeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Rhizome not found: {rhizome_id}")
    except NodeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")


@router.post(
    "/{rhizome_id}/nodes/{node_id}/generate",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
)
async def generate(
    rhizome_id: str,
    node_id: str,
    request: GenerateRequest,
    gen_service: GenerationService = Depends(get_generation_service),
) -> NodeResponse | StreamingResponse:
    try:
        provider = get_provider(request.provider)
    except ProviderNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if request.prefill_content and request.n > 1:
        raise HTTPException(
            status_code=400,
            detail="prefill_content cannot be combined with n > 1",
        )

    if request.stream and request.n > 1:
        return StreamingResponse(
            _stream_n_sse(gen_service, rhizome_id, node_id, provider, request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    if request.stream:
        return StreamingResponse(
            _stream_sse(gen_service, rhizome_id, node_id, provider, request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        if request.n > 1:
            nodes = await gen_service.generate_n(
                rhizome_id,
                node_id,
                provider,
                n=request.n,
                model=request.model,
                system_prompt=request.system_prompt,
                sampling_params=request.sampling_params,
                prefill_content=request.prefill_content,
            )
            return nodes[0]

        return await gen_service.generate(
            rhizome_id,
            node_id,
            provider,
            model=request.model,
            system_prompt=request.system_prompt,
            sampling_params=request.sampling_params,
            prefill_content=request.prefill_content,
        )
    except RhizomeNotFoundForGenerationError:
        raise HTTPException(status_code=404, detail=f"Rhizome not found: {rhizome_id}")
    except NodeNotFoundForGenerationError:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")
    except (RuntimeError, Exception) as e:
        raise HTTPException(status_code=502, detail=str(e))


async def _stream_sse(
    gen_service: GenerationService,
    rhizome_id: str,
    node_id: str,
    provider: LLMProvider,
    request: GenerateRequest,
) -> AsyncIterator[str]:
    """Async generator that yields SSE-formatted lines."""
    try:
        async for chunk in gen_service.generate_stream(
            rhizome_id,
            node_id,
            provider,
            model=request.model,
            system_prompt=request.system_prompt,
            sampling_params=request.sampling_params,
            prefill_content=request.prefill_content,
        ):
            if chunk.is_final and chunk.result:
                data = {
                    "type": "message_stop",
                    "content": chunk.result.content,
                    "finish_reason": chunk.result.finish_reason,
                    "usage": chunk.result.usage,
                    "latency_ms": chunk.result.latency_ms,
                    "node_id": (
                        chunk.result.raw_response.get("node_id")
                        if chunk.result.raw_response
                        else None
                    ),
                    "thinking_content": chunk.result.thinking_content,
                }
                yield f"event: message_stop\ndata: {json_module.dumps(data)}\n\n"
            elif chunk.type == "thinking_delta" and chunk.thinking:
                data = {"type": "thinking_delta", "thinking": chunk.thinking}
                yield f"event: thinking_delta\ndata: {json_module.dumps(data)}\n\n"
            elif chunk.text:
                data = {"type": "text_delta", "text": chunk.text}
                yield f"event: text_delta\ndata: {json_module.dumps(data)}\n\n"
    except RhizomeNotFoundForGenerationError:
        error = {"error": f"Rhizome not found: {rhizome_id}"}
        yield f"event: error\ndata: {json_module.dumps(error)}\n\n"
    except NodeNotFoundForGenerationError:
        error = {"error": f"Node not found: {node_id}"}
        yield f"event: error\ndata: {json_module.dumps(error)}\n\n"
    except Exception as e:
        detail = str(e) or f"{type(e).__name__} (no message)"
        logger.exception("Streaming generation error")
        error = {"error": detail}
        yield f"event: error\ndata: {json_module.dumps(error)}\n\n"


async def _stream_n_sse(
    gen_service: GenerationService,
    rhizome_id: str,
    node_id: str,
    provider: LLMProvider,
    request: GenerateRequest,
) -> AsyncIterator[str]:
    """SSE generator for simultaneous n>1 streaming with completion_index."""
    try:
        async for chunk in gen_service.generate_n_stream(
            rhizome_id,
            node_id,
            provider,
            n=request.n,
            model=request.model,
            system_prompt=request.system_prompt,
            sampling_params=request.sampling_params,
            prefill_content=request.prefill_content,
        ):
            if chunk.type == "generation_complete":
                data = {"type": "generation_complete"}
                yield (
                    f"event: generation_complete\n"
                    f"data: {json_module.dumps(data)}\n\n"
                )
            elif chunk.type == "error":
                data = {
                    "error": chunk.text,
                    "completion_index": chunk.completion_index,
                }
                yield (
                    f"event: error\n"
                    f"data: {json_module.dumps(data)}\n\n"
                )
            elif chunk.is_final and chunk.result:
                data = {
                    "type": "message_stop",
                    "completion_index": chunk.completion_index,
                    "content": chunk.result.content,
                    "finish_reason": chunk.result.finish_reason,
                    "usage": chunk.result.usage,
                    "latency_ms": chunk.result.latency_ms,
                    "node_id": (
                        chunk.result.raw_response.get("node_id")
                        if chunk.result.raw_response
                        else None
                    ),
                    "thinking_content": chunk.result.thinking_content,
                }
                yield (
                    f"event: message_stop\n"
                    f"data: {json_module.dumps(data)}\n\n"
                )
            elif chunk.type == "thinking_delta" and chunk.thinking:
                data = {
                    "type": "thinking_delta",
                    "thinking": chunk.thinking,
                    "completion_index": chunk.completion_index,
                }
                yield (
                    f"event: thinking_delta\n"
                    f"data: {json_module.dumps(data)}\n\n"
                )
            elif chunk.text:
                data = {
                    "type": "text_delta",
                    "text": chunk.text,
                    "completion_index": chunk.completion_index,
                }
                yield (
                    f"event: text_delta\n"
                    f"data: {json_module.dumps(data)}\n\n"
                )
    except RhizomeNotFoundForGenerationError:
        error = {"error": f"Rhizome not found: {rhizome_id}"}
        yield f"event: error\ndata: {json_module.dumps(error)}\n\n"
    except NodeNotFoundForGenerationError:
        error = {"error": f"Node not found: {node_id}"}
        yield f"event: error\ndata: {json_module.dumps(error)}\n\n"
    except Exception as e:
        detail = str(e) or f"{type(e).__name__} (no message)"
        logger.exception("Streaming generation error (n>1)")
        error = {"error": detail}
        yield f"event: error\ndata: {json_module.dumps(error)}\n\n"


# -- Replay --


@router.post(
    "/{rhizome_id}/replay",
    response_model=None,
)
async def replay(
    rhizome_id: str,
    request: ReplayRequest,
    replay_service: ReplayService = Depends(get_replay_service),
) -> list[NodeResponse] | StreamingResponse:
    try:
        provider = get_provider(request.provider)
    except ProviderNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if request.stream:
        return StreamingResponse(
            _stream_replay_sse(
                replay_service, rhizome_id, provider, request,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        return await replay_service.replay_path(
            rhizome_id,
            request.path_node_ids,
            provider,
            mode=request.mode,
            model=request.model,
            system_prompt=request.system_prompt,
            sampling_params=request.sampling_params,
        )
    except InvalidReplayPathError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RhizomeNotFoundForGenerationError:
        raise HTTPException(
            status_code=404, detail=f"Rhizome not found: {rhizome_id}",
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


async def _stream_replay_sse(
    replay_service: ReplayService,
    rhizome_id: str,
    provider: LLMProvider,
    request: ReplayRequest,
) -> AsyncIterator[str]:
    """SSE generator for streaming replay."""
    try:
        async for chunk in replay_service.replay_path_stream(
            rhizome_id,
            request.path_node_ids,
            provider,
            mode=request.mode,
            model=request.model,
            system_prompt=request.system_prompt,
            sampling_params=request.sampling_params,
        ):
            if chunk.type == "replay_step":
                yield (
                    f"event: replay_step\n"
                    f"data: {chunk.text}\n\n"
                )
            elif chunk.type == "replay_complete":
                yield (
                    f"event: replay_complete\n"
                    f"data: {chunk.text}\n\n"
                )
            elif chunk.type == "message_stop":
                data = {
                    "type": "message_stop",
                    "completion_index": chunk.completion_index,
                }
                if chunk.result:
                    data.update({
                        "content": chunk.result.content,
                        "finish_reason": chunk.result.finish_reason,
                        "node_id": (
                            chunk.result.raw_response.get("node_id")
                            if chunk.result.raw_response
                            else None
                        ),
                    })
                yield (
                    f"event: message_stop\n"
                    f"data: {json_module.dumps(data)}\n\n"
                )
            elif chunk.text:
                data = {
                    "type": "text_delta",
                    "text": chunk.text,
                    "completion_index": chunk.completion_index,
                }
                yield (
                    f"event: text_delta\n"
                    f"data: {json_module.dumps(data)}\n\n"
                )
    except InvalidReplayPathError as e:
        error = {"error": str(e)}
        yield f"event: error\ndata: {json_module.dumps(error)}\n\n"
    except Exception as e:
        detail = str(e) or f"{type(e).__name__} (no message)"
        logger.exception("Streaming replay error")
        error = {"error": detail}
        yield f"event: error\ndata: {json_module.dumps(error)}\n\n"


# -- Cross-model generation --


@router.post(
    "/{rhizome_id}/nodes/{node_id}/generate-cross",
    response_model=None,
)
async def generate_cross(
    rhizome_id: str,
    node_id: str,
    request: CrossModelGenerateRequest,
    gen_service: GenerationService = Depends(get_generation_service),
) -> list[NodeResponse] | StreamingResponse:
    # Validate all providers exist up front
    for target in request.targets:
        try:
            get_provider(target.provider)
        except ProviderNotFoundError as e:
            raise HTTPException(status_code=400, detail=str(e))

    targets = [{"provider": t.provider, "model": t.model} for t in request.targets]

    if request.stream:
        return StreamingResponse(
            _stream_cross_sse(gen_service, rhizome_id, node_id, targets, request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        return await gen_service.generate_cross(
            rhizome_id,
            node_id,
            targets,
            system_prompt=request.system_prompt,
            sampling_params=request.sampling_params,
        )
    except RhizomeNotFoundForGenerationError:
        raise HTTPException(
            status_code=404, detail=f"Rhizome not found: {rhizome_id}",
        )
    except NodeNotFoundForGenerationError:
        raise HTTPException(
            status_code=404, detail=f"Node not found: {node_id}",
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


async def _stream_cross_sse(
    gen_service: GenerationService,
    rhizome_id: str,
    node_id: str,
    targets: list[dict],
    request: CrossModelGenerateRequest,
) -> AsyncIterator[str]:
    """SSE generator for cross-model streaming (reuses generate_n_stream SSE format)."""
    try:
        async for chunk in gen_service.generate_cross_stream(
            rhizome_id,
            node_id,
            targets,
            system_prompt=request.system_prompt,
            sampling_params=request.sampling_params,
        ):
            if chunk.type == "generation_complete":
                data = {"type": "generation_complete"}
                yield (
                    f"event: generation_complete\n"
                    f"data: {json_module.dumps(data)}\n\n"
                )
            elif chunk.type == "error":
                data = {
                    "error": chunk.text,
                    "completion_index": chunk.completion_index,
                }
                yield (
                    f"event: error\n"
                    f"data: {json_module.dumps(data)}\n\n"
                )
            elif chunk.is_final and chunk.result:
                data = {
                    "type": "message_stop",
                    "completion_index": chunk.completion_index,
                    "content": chunk.result.content,
                    "finish_reason": chunk.result.finish_reason,
                    "usage": chunk.result.usage,
                    "latency_ms": chunk.result.latency_ms,
                    "node_id": (
                        chunk.result.raw_response.get("node_id")
                        if chunk.result.raw_response
                        else None
                    ),
                }
                yield (
                    f"event: message_stop\n"
                    f"data: {json_module.dumps(data)}\n\n"
                )
            elif chunk.text:
                data = {
                    "type": "text_delta",
                    "text": chunk.text,
                    "completion_index": chunk.completion_index,
                }
                yield (
                    f"event: text_delta\n"
                    f"data: {json_module.dumps(data)}\n\n"
                )
    except RhizomeNotFoundForGenerationError:
        error = {"error": f"Rhizome not found: {rhizome_id}"}
        yield f"event: error\ndata: {json_module.dumps(error)}\n\n"
    except NodeNotFoundForGenerationError:
        error = {"error": f"Node not found: {node_id}"}
        yield f"event: error\ndata: {json_module.dumps(error)}\n\n"
    except Exception as e:
        detail = str(e) or f"{type(e).__name__} (no message)"
        logger.exception("Streaming cross-model error")
        error = {"error": detail}
        yield f"event: error\ndata: {json_module.dumps(error)}\n\n"


# -- Perturbation experiments --


@router.post(
    "/{rhizome_id}/nodes/{node_id}/perturb",
    response_model=None,
)
async def perturb(
    rhizome_id: str,
    node_id: str,
    request: PerturbationRequest,
    perturb_service: PerturbationService = Depends(get_perturbation_service),
) -> PerturbationReportResponse | StreamingResponse:
    try:
        provider = get_provider(request.provider)
    except ProviderNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if request.stream:
        return StreamingResponse(
            _stream_perturbation_sse(
                perturb_service, rhizome_id, node_id, provider, request,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        return await perturb_service.run_experiment(
            rhizome_id,
            node_id,
            request.perturbations,
            provider,
            model=request.model,
            sampling_params=request.sampling_params,
            include_control=request.include_control,
        )
    except RhizomeNotFoundForGenerationError:
        raise HTTPException(
            status_code=404, detail=f"Rhizome not found: {rhizome_id}",
        )
    except NodeNotFoundForGenerationError:
        raise HTTPException(
            status_code=404, detail=f"Node not found: {node_id}",
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


async def _stream_perturbation_sse(
    perturb_service: PerturbationService,
    rhizome_id: str,
    node_id: str,
    provider: LLMProvider,
    request: PerturbationRequest,
) -> AsyncIterator[str]:
    """SSE generator for streaming perturbation experiments."""
    try:
        async for chunk in perturb_service.run_experiment_stream(
            rhizome_id,
            node_id,
            request.perturbations,
            provider,
            model=request.model,
            sampling_params=request.sampling_params,
            include_control=request.include_control,
        ):
            if chunk.type == "perturbation_step":
                yield (
                    f"event: perturbation_step\n"
                    f"data: {chunk.text}\n\n"
                )
            elif chunk.type == "perturbation_complete":
                yield (
                    f"event: perturbation_complete\n"
                    f"data: {chunk.text}\n\n"
                )
            elif chunk.type == "message_stop":
                yield (
                    f"event: message_stop\n"
                    f"data: {chunk.text}\n\n"
                )
            elif chunk.type == "text_delta" and chunk.text:
                data = {
                    "type": "text_delta",
                    "text": chunk.text,
                    "step_index": chunk.completion_index,
                }
                yield (
                    f"event: text_delta\n"
                    f"data: {json_module.dumps(data)}\n\n"
                )
    except RhizomeNotFoundForGenerationError:
        error = {"error": f"Rhizome not found: {rhizome_id}"}
        yield f"event: error\ndata: {json_module.dumps(error)}\n\n"
    except NodeNotFoundForGenerationError:
        error = {"error": f"Node not found: {node_id}"}
        yield f"event: error\ndata: {json_module.dumps(error)}\n\n"
    except Exception as e:
        detail = str(e) or f"{type(e).__name__} (no message)"
        logger.exception("Streaming perturbation error")
        error = {"error": detail}
        yield f"event: error\ndata: {json_module.dumps(error)}\n\n"


# -- Perturbation report CRUD --


@router.get("/{rhizome_id}/perturbation-reports")
async def list_perturbation_reports(
    rhizome_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> list[PerturbationReportResponse]:
    return await service.list_perturbation_reports(rhizome_id)


@router.get("/{rhizome_id}/perturbation-reports/{report_id}")
async def get_perturbation_report(
    rhizome_id: str,
    report_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> PerturbationReportResponse:
    report = await service.get_perturbation_report(rhizome_id, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Report not found: {report_id}")
    return report


@router.delete("/{rhizome_id}/perturbation-reports/{report_id}")
async def delete_perturbation_report(
    rhizome_id: str,
    report_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
):
    await service.remove_perturbation_report(rhizome_id, report_id)
    return {"status": "ok"}
