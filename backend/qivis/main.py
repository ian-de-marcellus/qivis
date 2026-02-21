"""Qivis FastAPI application entry point."""

import os
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
from qivis.providers.openai import OpenAIProvider
from qivis.providers.openrouter import OpenRouterProvider
from qivis.providers.registry import clear_providers, get_all_providers, register_provider
from qivis.export.router import get_export_service
from qivis.export.router import router as export_router
from qivis.export.service import ExportService
from qivis.importer.merge import MergeService
from qivis.importer.merge_router import get_merge_service
from qivis.importer.merge_router import router as merge_router
from qivis.importer.router import get_import_service
from qivis.importer.router import router as import_router
from qivis.importer.service import ImportService
from qivis.search.router import get_search_service
from qivis.search.router import router as search_router
from qivis.search.service import SearchService
from qivis.trees.router import get_generation_service, get_tree_service
from qivis.trees.router import router as trees_router
from qivis.trees.service import TreeService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage database lifecycle and service wiring."""
    # Load .env from backend/ directory (secrets stay out of shell profile)
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    db = await Database.connect("qivis.db")

    # Summary client (dedicated API key for cost tracking — no fallback)
    summary_api_key = os.environ.get("SUMMARY_API_KEY")
    summary_client = AsyncAnthropic(api_key=summary_api_key) if summary_api_key else None

    # Tree service
    service = TreeService(db, summary_client=summary_client)
    app.dependency_overrides[get_tree_service] = lambda: service

    # Provider setup — auto-discover from env vars
    if os.environ.get("ANTHROPIC_API_KEY"):
        register_provider(AnthropicProvider(AsyncAnthropic()))

    if os.environ.get("OPENAI_API_KEY"):
        register_provider(OpenAIProvider(api_key=os.environ["OPENAI_API_KEY"]))

    if os.environ.get("OPENROUTER_API_KEY"):
        register_provider(OpenRouterProvider(api_key=os.environ["OPENROUTER_API_KEY"]))

    # Generation service
    store = EventStore(db)
    projector = StateProjector(db)
    gen_service = GenerationService(service, store, projector)
    app.dependency_overrides[get_generation_service] = lambda: gen_service

    # Export service
    export_service = ExportService(db, store, projector)
    app.dependency_overrides[get_export_service] = lambda: export_service

    # Search service
    search_svc = SearchService(db)
    app.dependency_overrides[get_search_service] = lambda: search_svc

    # Import service
    import_svc = ImportService(db, store, projector)
    app.dependency_overrides[get_import_service] = lambda: import_svc

    # Merge service
    merge_svc = MergeService(db, store, projector)
    app.dependency_overrides[get_merge_service] = lambda: merge_svc

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
app.include_router(export_router)
app.include_router(search_router)
app.include_router(import_router)
app.include_router(merge_router)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/providers")
async def providers() -> list[dict]:
    return [
        {"name": p.name, "available": True, "models": p.suggested_models, "supported_params": p.supported_params}
        for p in get_all_providers()
    ]
