"""Qivis FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from qivis.db.connection import Database
from qivis.trees.router import get_tree_service
from qivis.trees.router import router as trees_router
from qivis.trees.service import TreeService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage database lifecycle: connect on startup, close on shutdown."""
    db = await Database.connect("qivis.db")
    service = TreeService(db)
    app.dependency_overrides[get_tree_service] = lambda: service
    app.state.db = db
    yield
    await db.close()


app = FastAPI(
    title="Qivis",
    description=(
        "Research instrument for exploring AI personality, emotion, and behavior"
        " through branching conversation trees"
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(trees_router)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "version": "0.1.0"}
