"""Export API routes."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse

from qivis.export.service import ExportService

router = APIRouter(prefix="/api/trees", tags=["export"])


def get_export_service() -> ExportService:
    """Dependency placeholder — overridden at startup."""
    raise RuntimeError("ExportService not configured")


@router.get("/{tree_id}/export")
async def export_tree(
    tree_id: str,
    format: Literal["json", "csv"] = Query("json"),
    include_events: bool = Query(False),
    service: ExportService = Depends(get_export_service),
) -> Response:
    """Export a tree in JSON or CSV format."""
    if format == "json":
        result = await service.export_json(tree_id, include_events=include_events)
        if result is None:
            raise HTTPException(status_code=404, detail="Tree not found")
        return JSONResponse(content=result)

    elif format == "csv":
        result = await service.export_csv(tree_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Tree not found")
        return Response(
            content=result,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{tree_id}.csv"',
            },
        )

    raise HTTPException(status_code=422, detail=f"Unsupported format: {format}")


@router.get("/{tree_id}/paths")
async def get_tree_paths(
    tree_id: str,
    service: ExportService = Depends(get_export_service),
) -> dict:
    """Get all root-to-leaf paths in the tree."""
    paths = await service.get_paths(tree_id)
    if paths is None:
        raise HTTPException(status_code=404, detail="Tree not found")
    return {"paths": paths}
