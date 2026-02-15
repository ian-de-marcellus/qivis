"""FastAPI routes for tree and node CRUD."""

from fastapi import APIRouter, Depends, HTTPException, status

from qivis.trees.schemas import (
    CreateNodeRequest,
    CreateTreeRequest,
    NodeResponse,
    TreeDetailResponse,
    TreeSummary,
)
from qivis.trees.service import InvalidParentError, TreeNotFoundError, TreeService

router = APIRouter(prefix="/api/trees", tags=["trees"])


def get_tree_service() -> TreeService:
    """Dependency placeholder — replaced at app startup."""
    raise RuntimeError("TreeService not initialized")


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
