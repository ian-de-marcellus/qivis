"""Search API request/response schemas."""

from pydantic import BaseModel


class SearchResultItem(BaseModel):
    node_id: str
    tree_id: str
    tree_title: str | None = None
    role: str
    content: str
    snippet: str
    model: str | None = None
    provider: str | None = None
    created_at: str


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultItem]
    total: int
