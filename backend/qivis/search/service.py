"""Full-text search service using SQLite FTS5."""

import logging

from qivis.db.connection import Database
from qivis.search.schemas import SearchResponse, SearchResultItem

logger = logging.getLogger(__name__)


class SearchService:
    """Cross-tree full-text search over conversation nodes."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def search(
        self,
        query: str,
        *,
        tree_ids: list[str] | None = None,
        models: list[str] | None = None,
        providers: list[str] | None = None,
        roles: list[str] | None = None,
        tags: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 50,
    ) -> SearchResponse:
        """Search nodes by content and system_prompt with optional filters."""
        fts_query = self._sanitize_query(query)
        if not fts_query:
            return SearchResponse(query=query, results=[], total=0)

        # Build dynamic WHERE clauses and params
        clauses: list[str] = []
        params: list[str | int] = [fts_query]

        if tree_ids:
            placeholders = ", ".join("?" for _ in tree_ids)
            clauses.append(f"AND n.tree_id IN ({placeholders})")
            params.extend(tree_ids)

        if models:
            placeholders = ", ".join("?" for _ in models)
            clauses.append(f"AND n.model IN ({placeholders})")
            params.extend(models)

        if providers:
            placeholders = ", ".join("?" for _ in providers)
            clauses.append(f"AND n.provider IN ({placeholders})")
            params.extend(providers)

        if roles:
            placeholders = ", ".join("?" for _ in roles)
            clauses.append(f"AND n.role IN ({placeholders})")
            params.extend(roles)

        if tags:
            placeholders = ", ".join("?" for _ in tags)
            clauses.append(
                f"AND n.node_id IN ("
                f"SELECT DISTINCT node_id FROM annotations WHERE tag IN ({placeholders})"
                f")"
            )
            params.extend(tags)

        if date_from:
            clauses.append("AND n.created_at >= ?")
            params.append(date_from)

        if date_to:
            clauses.append("AND n.created_at <= ?")
            params.append(date_to)

        params.append(limit)
        filter_sql = "\n  ".join(clauses)

        sql = f"""
            SELECT
                n.node_id,
                n.tree_id,
                n.role,
                n.content,
                n.model,
                n.provider,
                n.created_at,
                t.title AS tree_title,
                snippet(nodes_fts, 0, '[[mark]]', '[[/mark]]', '...', 40) AS snippet
            FROM nodes_fts
            JOIN nodes n ON n.rowid = nodes_fts.rowid
            JOIN trees t ON t.tree_id = n.tree_id
            WHERE nodes_fts MATCH ?
              AND n.archived = 0
              AND t.archived = 0
              {filter_sql}
            ORDER BY rank
            LIMIT ?
        """

        rows = await self._db.fetchall(sql, tuple(params))

        results = [
            SearchResultItem(
                node_id=row["node_id"],
                tree_id=row["tree_id"],
                tree_title=row["tree_title"],
                role=row["role"],
                content=row["content"],
                snippet=row["snippet"],
                model=row["model"],
                provider=row["provider"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

        return SearchResponse(
            query=query,
            results=results,
            total=len(results),
        )

    @staticmethod
    def _sanitize_query(raw: str) -> str:
        """Escape user input for safe FTS5 querying.

        Splits into words, double-quotes each (prevents FTS5 operator injection).
        Result is implicit AND: all terms must be present.
        """
        words = raw.strip().split()
        if not words:
            return ""
        return " ".join(f'"{w}"' for w in words)
