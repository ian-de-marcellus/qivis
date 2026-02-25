"""Export API routes."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse

from qivis.export.service import ExportService

router = APIRouter(prefix="/api/rhizomes", tags=["export"])


def get_export_service() -> ExportService:
    """Dependency placeholder — overridden at startup."""
    raise RuntimeError("ExportService not configured")


@router.get("/{rhizome_id}/export")
async def export_rhizome(
    rhizome_id: str,
    format: Literal["json", "csv"] = Query("json"),
    include_events: bool = Query(False),
    service: ExportService = Depends(get_export_service),
) -> Response:
    """Export a rhizome in JSON or CSV format."""
    if format == "json":
        result = await service.export_json(rhizome_id, include_events=include_events)
        if result is None:
            raise HTTPException(status_code=404, detail="Rhizome not found")
        return JSONResponse(content=result)

    elif format == "csv":
        result = await service.export_csv(rhizome_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Rhizome not found")
        return Response(
            content=result,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{rhizome_id}.csv"',
            },
        )

    raise HTTPException(status_code=422, detail=f"Unsupported format: {format}")


@router.get("/{rhizome_id}/paths")
async def get_rhizome_paths(
    rhizome_id: str,
    service: ExportService = Depends(get_export_service),
) -> dict:
    """Get all root-to-leaf paths in the rhizome."""
    paths = await service.get_paths(rhizome_id)
    if paths is None:
        raise HTTPException(status_code=404, detail="Rhizome not found")
    return {"paths": paths}
