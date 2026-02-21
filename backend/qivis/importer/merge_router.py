"""Merge API routes: merge imported conversations into existing trees."""

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile

from qivis.importer.merge import (
    MergePreviewResponse,
    MergeResult,
    MergeService,
    TreeNotFoundError,
)
from qivis.importer.parsers.detection import ImportFormatError

router = APIRouter(prefix="/api/trees/{tree_id}/merge", tags=["merge"])


def get_merge_service() -> MergeService:
    """Dependency placeholder — overridden at startup."""
    raise RuntimeError("MergeService not configured")


@router.post("/preview")
async def preview_merge(
    tree_id: str,
    file: UploadFile,
    service: MergeService = Depends(get_merge_service),
) -> MergePreviewResponse:
    """Parse uploaded file and preview what would be merged into the tree."""
    content = await file.read()
    try:
        return await service.preview_merge(tree_id, content, file.filename or "unknown")
    except TreeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_id}")
    except ImportFormatError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("")
async def execute_merge(
    tree_id: str,
    file: UploadFile,
    conversation_index: int = Query(0),
    service: MergeService = Depends(get_merge_service),
) -> MergeResult:
    """Merge imported conversation into the existing tree."""
    content = await file.read()
    try:
        return await service.execute_merge(
            tree_id,
            content,
            file.filename or "unknown",
            conversation_index=conversation_index,
        )
    except TreeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_id}")
    except ImportFormatError as e:
        raise HTTPException(status_code=422, detail=str(e))
