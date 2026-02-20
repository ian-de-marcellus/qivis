"""Search API routes."""

from fastapi import APIRouter, Depends, Query

from qivis.search.schemas import SearchResponse
from qivis.search.service import SearchService

router = APIRouter(prefix="/api", tags=["search"])


def get_search_service() -> SearchService:
    """Dependency placeholder — overridden at startup."""
    raise RuntimeError("SearchService not configured")


def _split_csv(value: str | None) -> list[str] | None:
    """Split a comma-separated query param into a list, or None."""
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


@router.get("/search")
async def search(
    q: str = Query(..., min_length=1),
    tree_ids: str | None = Query(None),
    models: str | None = Query(None),
    providers: str | None = Query(None),
    roles: str | None = Query(None),
    tags: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    service: SearchService = Depends(get_search_service),
) -> SearchResponse:
    """Full-text search across all conversation nodes."""
    return await service.search(
        q,
        tree_ids=_split_csv(tree_ids),
        models=_split_csv(models),
        providers=_split_csv(providers),
        roles=_split_csv(roles),
        tags=_split_csv(tags),
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
