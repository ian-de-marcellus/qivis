"""Import API routes."""

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile

from qivis.importer.parsers.detection import ImportFormatError
from qivis.importer.schemas import ImportPreviewResponse, ImportResponse
from qivis.importer.service import ImportService

router = APIRouter(prefix="/api/import", tags=["import"])


def get_import_service() -> ImportService:
    """Dependency placeholder — overridden at startup."""
    raise RuntimeError("ImportService not configured")


@router.post("/preview")
async def preview_import(
    file: UploadFile,
    service: ImportService = Depends(get_import_service),
) -> ImportPreviewResponse:
    """Parse uploaded file and return preview without creating anything."""
    content = await file.read()
    try:
        return await service.preview(content, file.filename or "unknown")
    except ImportFormatError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.post("")
async def import_conversations(
    file: UploadFile,
    format: str | None = Query(None),
    selected: str | None = Query(None),
    service: ImportService = Depends(get_import_service),
) -> ImportResponse:
    """Import conversations from uploaded file."""
    content = await file.read()
    selected_indices = (
        [int(x.strip()) for x in selected.split(",") if x.strip()]
        if selected
        else None
    )
    try:
        results = await service.import_trees(
            content,
            file.filename or "unknown",
            format_hint=format,
            selected_indices=selected_indices,
        )
    except ImportFormatError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    return ImportResponse(results=results)
