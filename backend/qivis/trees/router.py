"""FastAPI routes for tree and node CRUD, and generation."""

import json as json_module
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from qivis.generation.service import (
    GenerationService,
    NodeNotFoundForGenerationError,
    TreeNotFoundForGenerationError,
)
from qivis.providers.base import LLMProvider
from qivis.providers.registry import ProviderNotFoundError, get_provider
from qivis.trees.schemas import (
    AddAnnotationRequest,
    AnnotationResponse,
    BookmarkResponse,
    BulkAnchorRequest,
    CreateBookmarkRequest,
    CreateDigressionGroupRequest,
    CreateNodeRequest,
    CreateNoteRequest,
    CreateTreeRequest,
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
    PatchTreeRequest,
    TaxonomyResponse,
    ToggleDigressionGroupRequest,
    TreeDetailResponse,
    TreeSummary,
)
from qivis.trees.service import (
    AnnotationNotFoundError,
    BookmarkNotFoundError,
    DigressionGroupNotFoundError,
    InvalidParentError,
    NodeNotFoundError,
    NonContiguousGroupError,
    NoteNotFoundError,
    SummaryClientNotConfiguredError,
    TreeNotFoundError,
    TreeService,
)

router = APIRouter(prefix="/api/trees", tags=["trees"])


def get_tree_service() -> TreeService:
    """Dependency placeholder — replaced at app startup."""
    raise RuntimeError("TreeService not initialized")


def get_generation_service() -> GenerationService:
    """Dependency placeholder — replaced at app startup."""
    raise RuntimeError("GenerationService not initialized")


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_tree(
    request: CreateTreeRequest,
    service: TreeService = Depends(get_tree_service),
) -> TreeDetailResponse:
    return await service.create_tree(request)


@router.get("")
async def list_trees(
    service: TreeService = Depends(get_tree_service),
) -> list[TreeSummary]:
    return await service.list_trees()


@router.get("/{tree_id}")
async def get_tree(
    tree_id: str,
    service: TreeService = Depends(get_tree_service),
) -> TreeDetailResponse:
    tree = await service.get_tree(tree_id)
    if tree is None:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_id}")
    return tree


@router.patch("/{tree_id}")
async def update_tree(
    tree_id: str,
    request: PatchTreeRequest,
    service: TreeService = Depends(get_tree_service),
) -> TreeDetailResponse:
    try:
        return await service.update_tree(tree_id, request)
    except TreeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_id}")


@router.post("/{tree_id}/nodes", status_code=status.HTTP_201_CREATED)
async def create_node(
    tree_id: str,
    request: CreateNodeRequest,
    service: TreeService = Depends(get_tree_service),
) -> NodeResponse:
    try:
        return await service.create_node(tree_id, request)
    except TreeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_id}")
    except InvalidParentError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{tree_id}/nodes/{node_id}/content")
async def edit_node_content(
    tree_id: str,
    node_id: str,
    request: PatchNodeContentRequest,
    service: TreeService = Depends(get_tree_service),
) -> NodeResponse:
    try:
        return await service.edit_node_content(tree_id, node_id, request.edited_content)
    except TreeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_id}")
    except NodeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")


@router.get("/{tree_id}/nodes/{node_id}/edit-history")
async def get_edit_history(
    tree_id: str,
    node_id: str,
    service: TreeService = Depends(get_tree_service),
) -> EditHistoryResponse:
    try:
        return await service.get_edit_history(tree_id, node_id)
    except TreeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_id}")
    except NodeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")


@router.get("/{tree_id}/interventions")
async def get_interventions(
    tree_id: str,
    service: TreeService = Depends(get_tree_service),
) -> InterventionTimelineResponse:
    try:
        return await service.get_intervention_timeline(tree_id)
    except TreeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_id}")


@router.post(
    "/{tree_id}/nodes/{node_id}/annotations",
    status_code=status.HTTP_201_CREATED,
)
async def add_annotation(
    tree_id: str,
    node_id: str,
    request: AddAnnotationRequest,
    service: TreeService = Depends(get_tree_service),
) -> AnnotationResponse:
    try:
        return await service.add_annotation(tree_id, node_id, request)
    except TreeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_id}")
    except NodeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")


@router.get("/{tree_id}/nodes/{node_id}/annotations")
async def get_node_annotations(
    tree_id: str,
    node_id: str,
    service: TreeService = Depends(get_tree_service),
) -> list[AnnotationResponse]:
    return await service.get_node_annotations(tree_id, node_id)


@router.delete(
    "/{tree_id}/annotations/{annotation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_annotation(
    tree_id: str,
    annotation_id: str,
    service: TreeService = Depends(get_tree_service),
) -> None:
    try:
        await service.remove_annotation(tree_id, annotation_id)
    except AnnotationNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Annotation not found: {annotation_id}"
        )


@router.get("/{tree_id}/taxonomy")
async def get_tree_taxonomy(
    tree_id: str,
    service: TreeService = Depends(get_tree_service),
) -> TaxonomyResponse:
    try:
        return await service.get_tree_taxonomy(tree_id)
    except TreeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_id}")


@router.post(
    "/{tree_id}/nodes/{node_id}/notes",
    status_code=status.HTTP_201_CREATED,
)
async def add_note(
    tree_id: str,
    node_id: str,
    request: CreateNoteRequest,
    service: TreeService = Depends(get_tree_service),
) -> NoteResponse:
    try:
        return await service.add_note(tree_id, node_id, request)
    except TreeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_id}")
    except NodeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")


@router.get("/{tree_id}/nodes/{node_id}/notes")
async def get_node_notes(
    tree_id: str,
    node_id: str,
    service: TreeService = Depends(get_tree_service),
) -> list[NoteResponse]:
    return await service.get_node_notes(tree_id, node_id)


@router.get("/{tree_id}/notes")
async def get_tree_notes(
    tree_id: str,
    q: str | None = None,
    service: TreeService = Depends(get_tree_service),
) -> list[NoteResponse]:
    return await service.get_tree_notes(tree_id, query=q)


@router.delete(
    "/{tree_id}/notes/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_note(
    tree_id: str,
    note_id: str,
    service: TreeService = Depends(get_tree_service),
) -> None:
    try:
        await service.remove_note(tree_id, note_id)
    except NoteNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Note not found: {note_id}"
        )


@router.get("/{tree_id}/annotations")
async def get_tree_annotations(
    tree_id: str,
    service: TreeService = Depends(get_tree_service),
) -> list[AnnotationResponse]:
    return await service.get_tree_annotations(tree_id)


@router.post(
    "/{tree_id}/nodes/{node_id}/bookmarks",
    status_code=status.HTTP_201_CREATED,
)
async def add_bookmark(
    tree_id: str,
    node_id: str,
    request: CreateBookmarkRequest,
    service: TreeService = Depends(get_tree_service),
) -> BookmarkResponse:
    try:
        return await service.add_bookmark(tree_id, node_id, request)
    except TreeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_id}")
    except NodeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")


@router.get("/{tree_id}/bookmarks")
async def get_tree_bookmarks(
    tree_id: str,
    q: str | None = None,
    service: TreeService = Depends(get_tree_service),
) -> list[BookmarkResponse]:
    return await service.get_tree_bookmarks(tree_id, query=q)


@router.delete(
    "/{tree_id}/bookmarks/{bookmark_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_bookmark(
    tree_id: str,
    bookmark_id: str,
    service: TreeService = Depends(get_tree_service),
) -> None:
    try:
        await service.remove_bookmark(tree_id, bookmark_id)
    except BookmarkNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Bookmark not found: {bookmark_id}"
        )


@router.post("/{tree_id}/bookmarks/{bookmark_id}/summarize")
async def summarize_bookmark(
    tree_id: str,
    bookmark_id: str,
    service: TreeService = Depends(get_tree_service),
) -> BookmarkResponse:
    try:
        return await service.generate_bookmark_summary(tree_id, bookmark_id)
    except TreeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_id}")
    except BookmarkNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Bookmark not found: {bookmark_id}"
        )
    except SummaryClientNotConfiguredError:
        raise HTTPException(
            status_code=503, detail="Summary API key not configured"
        )


@router.post("/{tree_id}/nodes/{node_id}/exclude")
async def exclude_node(
    tree_id: str,
    node_id: str,
    request: ExcludeNodeRequest,
    service: TreeService = Depends(get_tree_service),
) -> NodeExclusionResponse:
    try:
        return await service.exclude_node(tree_id, node_id, request)
    except TreeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_id}")
    except NodeNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/{tree_id}/nodes/{node_id}/include",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def include_node(
    tree_id: str,
    node_id: str,
    request: IncludeNodeRequest,
    service: TreeService = Depends(get_tree_service),
) -> None:
    await service.include_node(tree_id, node_id, request.scope_node_id)


@router.get("/{tree_id}/exclusions")
async def get_tree_exclusions(
    tree_id: str,
    service: TreeService = Depends(get_tree_service),
) -> list[NodeExclusionResponse]:
    return await service.get_tree_exclusions(tree_id)


@router.post(
    "/{tree_id}/digression-groups",
    status_code=status.HTTP_201_CREATED,
)
async def create_digression_group(
    tree_id: str,
    request: CreateDigressionGroupRequest,
    service: TreeService = Depends(get_tree_service),
) -> DigressionGroupResponse:
    try:
        return await service.create_digression_group(tree_id, request)
    except TreeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_id}")
    except NodeNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except NonContiguousGroupError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{tree_id}/digression-groups")
async def get_digression_groups(
    tree_id: str,
    service: TreeService = Depends(get_tree_service),
) -> list[DigressionGroupResponse]:
    return await service.get_digression_groups(tree_id)


@router.post("/{tree_id}/digression-groups/{group_id}/toggle")
async def toggle_digression_group(
    tree_id: str,
    group_id: str,
    request: ToggleDigressionGroupRequest,
    service: TreeService = Depends(get_tree_service),
) -> DigressionGroupResponse:
    try:
        return await service.toggle_digression_group(tree_id, group_id, request.included)
    except DigressionGroupNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Digression group not found: {group_id}"
        )


@router.delete(
    "/{tree_id}/digression-groups/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_digression_group(
    tree_id: str,
    group_id: str,
    service: TreeService = Depends(get_tree_service),
) -> None:
    try:
        await service.delete_digression_group(tree_id, group_id)
    except DigressionGroupNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Digression group not found: {group_id}"
        )


@router.post("/{tree_id}/bulk-anchor")
async def bulk_anchor(
    tree_id: str,
    request: BulkAnchorRequest,
    service: TreeService = Depends(get_tree_service),
) -> dict:
    try:
        changed = await service.bulk_anchor(tree_id, request.node_ids, request.anchor)
        return {"changed": changed, "anchor": request.anchor}
    except TreeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_id}")


@router.post("/{tree_id}/nodes/{node_id}/anchor")
async def toggle_anchor(
    tree_id: str,
    node_id: str,
    service: TreeService = Depends(get_tree_service),
) -> dict:
    try:
        is_anchored = await service.anchor_node(tree_id, node_id)
        return {"is_anchored": is_anchored}
    except TreeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_id}")
    except NodeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")


@router.post(
    "/{tree_id}/nodes/{node_id}/generate",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
)
async def generate(
    tree_id: str,
    node_id: str,
    request: GenerateRequest,
    gen_service: GenerationService = Depends(get_generation_service),
) -> NodeResponse | StreamingResponse:
    try:
        provider = get_provider(request.provider)
    except ProviderNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if request.stream and request.n > 1:
        return StreamingResponse(
            _stream_n_sse(gen_service, tree_id, node_id, provider, request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    if request.stream:
        return StreamingResponse(
            _stream_sse(gen_service, tree_id, node_id, provider, request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        if request.n > 1:
            nodes = await gen_service.generate_n(
                tree_id,
                node_id,
                provider,
                n=request.n,
                model=request.model,
                system_prompt=request.system_prompt,
                sampling_params=request.sampling_params,
            )
            return nodes[0]

        return await gen_service.generate(
            tree_id,
            node_id,
            provider,
            model=request.model,
            system_prompt=request.system_prompt,
            sampling_params=request.sampling_params,
        )
    except TreeNotFoundForGenerationError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_id}")
    except NodeNotFoundForGenerationError:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")


async def _stream_sse(
    gen_service: GenerationService,
    tree_id: str,
    node_id: str,
    provider: LLMProvider,
    request: GenerateRequest,
) -> AsyncIterator[str]:
    """Async generator that yields SSE-formatted lines."""
    try:
        async for chunk in gen_service.generate_stream(
            tree_id,
            node_id,
            provider,
            model=request.model,
            system_prompt=request.system_prompt,
            sampling_params=request.sampling_params,
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
    except TreeNotFoundForGenerationError:
        error = {"error": f"Tree not found: {tree_id}"}
        yield f"event: error\ndata: {json_module.dumps(error)}\n\n"
    except NodeNotFoundForGenerationError:
        error = {"error": f"Node not found: {node_id}"}
        yield f"event: error\ndata: {json_module.dumps(error)}\n\n"
    except Exception as e:
        error = {"error": str(e)}
        yield f"event: error\ndata: {json_module.dumps(error)}\n\n"


async def _stream_n_sse(
    gen_service: GenerationService,
    tree_id: str,
    node_id: str,
    provider: LLMProvider,
    request: GenerateRequest,
) -> AsyncIterator[str]:
    """SSE generator for simultaneous n>1 streaming with completion_index."""
    try:
        async for chunk in gen_service.generate_n_stream(
            tree_id,
            node_id,
            provider,
            n=request.n,
            model=request.model,
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
    except TreeNotFoundForGenerationError:
        error = {"error": f"Tree not found: {tree_id}"}
        yield f"event: error\ndata: {json_module.dumps(error)}\n\n"
    except NodeNotFoundForGenerationError:
        error = {"error": f"Node not found: {node_id}"}
        yield f"event: error\ndata: {json_module.dumps(error)}\n\n"
    except Exception as e:
        error = {"error": str(e)}
        yield f"event: error\ndata: {json_module.dumps(error)}\n\n"
