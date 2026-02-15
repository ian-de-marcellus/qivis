"""Qivis FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.service import GenerationService
from qivis.providers.anthropic import AnthropicProvider
from qivis.providers.registry import clear_providers, register_provider
from qivis.trees.router import get_generation_service, get_tree_service
from qivis.trees.router import router as trees_router
from qivis.trees.service import TreeService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage database lifecycle and service wiring."""
    # Load .env from backend/ directory (secrets stay out of shell profile)
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    db = await Database.connect("qivis.db")

    # Tree service
    service = TreeService(db)
    app.dependency_overrides[get_tree_service] = lambda: service

    # Provider setup
    anthropic_client = AsyncAnthropic()
    anthropic_provider = AnthropicProvider(anthropic_client)
    register_provider(anthropic_provider)

    # Generation service
    store = EventStore(db)
    projector = StateProjector(db)
    gen_service = GenerationService(service, store, projector)
    app.dependency_overrides[get_generation_service] = lambda: gen_service

    app.state.db = db
    yield

    clear_providers()
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(trees_router)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "version": "0.1.0"}
