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
    CreateNodeRequest,
    CreateTreeRequest,
    GenerateRequest,
    NodeResponse,
    PatchTreeRequest,
    TreeDetailResponse,
    TreeSummary,
)
from qivis.trees.service import InvalidParentError, TreeNotFoundError, TreeService

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

    if request.stream:
        return StreamingResponse(
            _stream_sse(gen_service, tree_id, node_id, provider, request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
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
                }
                yield f"event: message_stop\ndata: {json_module.dumps(data)}\n\n"
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
