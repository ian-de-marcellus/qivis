"""Qivis FastAPI application entry point."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from qivis.db.connection import Database
from qivis.errors import QivisError
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.export.router import get_export_service
from qivis.export.router import router as export_router
from qivis.export.service import ExportService
from qivis.generation.perturbation import PerturbationService
from qivis.generation.replay import ReplayService
from qivis.generation.service import GenerationService
from qivis.importer.merge import MergeService
from qivis.importer.merge_router import get_merge_service
from qivis.importer.merge_router import router as merge_router
from qivis.importer.router import get_import_service
from qivis.importer.router import router as import_router
from qivis.importer.service import ImportService
from qivis.model_catalog import ModelCatalog, get_catalog, set_catalog
from qivis.probes.router import get_probe_service
from qivis.probes.router import router as probes_router
from qivis.probes.service import ProbeService
from qivis.providers.anthropic import AnthropicProvider
from qivis.providers.openai import OpenAIProvider
from qivis.providers.openrouter import OpenRouterProvider
from qivis.providers.registry import clear_providers, get_all_providers, register_provider
from qivis.rhizomes.router import (
    get_generation_service,
    get_perturbation_service,
    get_replay_service,
    get_rhizome_service,
)
from qivis.rhizomes.router import router as rhizomes_router
from qivis.rhizomes.service import RhizomeService
from qivis.search.router import get_search_service
from qivis.search.router import router as search_router
from qivis.search.service import SearchService
from qivis.steering.router import get_optional_steering_service, get_steering_service
from qivis.steering.router import router as steering_router
from qivis.steering.service import SteeringService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage database lifecycle and service wiring."""
    # Load .env from backend/ directory (secrets stay out of shell profile)
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    db = await Database.connect("qivis.db")
    # Model profiles (backend/model_defaults.json): labels, formats, per-model settings
    set_catalog(ModelCatalog.load())

    # Summary client (dedicated API key for cost tracking — no fallback)
    summary_api_key = os.environ.get("SUMMARY_API_KEY")
    summary_client = AsyncAnthropic(api_key=summary_api_key) if summary_api_key else None

    # Rhizome service
    service = RhizomeService(db, summary_client=summary_client)
    app.dependency_overrides[get_rhizome_service] = lambda: service

    # Provider setup — auto-discover from env vars
    if os.environ.get("ANTHROPIC_API_KEY"):
        register_provider(AnthropicProvider(AsyncAnthropic()))

    if os.environ.get("OPENAI_API_KEY"):
        register_provider(OpenAIProvider(api_key=os.environ["OPENAI_API_KEY"]))

    if os.environ.get("OPENROUTER_API_KEY"):
        register_provider(OpenRouterProvider(api_key=os.environ["OPENROUTER_API_KEY"]))

    if os.environ.get("OLLAMA_BASE_URL"):
        from qivis.providers.ollama import OllamaProvider

        ollama = OllamaProvider(base_url=os.environ["OLLAMA_BASE_URL"])
        discovered = await ollama.discover_models()
        if discovered:
            ollama.suggested_models = discovered
        register_provider(ollama)

    if os.environ.get("GENERIC_OPENAI_BASE_URL"):
        from qivis.providers.generic_openai import GenericOpenAIProvider

        generic = GenericOpenAIProvider(
            base_url=os.environ["GENERIC_OPENAI_BASE_URL"],
            api_key=os.environ.get("GENERIC_OPENAI_API_KEY", ""),
            provider_name=os.environ.get("GENERIC_OPENAI_NAME", "local"),
        )
        discovered = await generic.discover_models()
        if discovered:
            generic.suggested_models = discovered
        register_provider(generic)

    if os.environ.get("LLAMACPP_BASE_URL"):
        from qivis.providers.llamacpp import LlamaCppProvider

        llamacpp = LlamaCppProvider(
            base_url=os.environ["LLAMACPP_BASE_URL"], model_defaults=get_catalog().profiles,
        )
        discovered = await llamacpp.discover_models()
        if discovered:
            llamacpp.suggested_models = discovered
        register_provider(llamacpp)

    # Generation service
    store = EventStore(db)
    projector = StateProjector(db)
    gen_service = GenerationService(service, store, projector)
    app.dependency_overrides[get_generation_service] = lambda: gen_service

    # Steering (token-by-token) sessions
    steering_service = SteeringService(gen_service)
    app.dependency_overrides[get_steering_service] = lambda: steering_service
    app.dependency_overrides[get_optional_steering_service] = lambda: steering_service

    # Answer probes
    probe_service = ProbeService(service, gen_service, store, projector)
    app.dependency_overrides[get_probe_service] = lambda: probe_service

    # Replay service
    replay_service = ReplayService(service, gen_service, store, projector)
    app.dependency_overrides[get_replay_service] = lambda: replay_service

    # Perturbation service
    perturbation_service = PerturbationService(gen_service, store, projector)
    app.dependency_overrides[get_perturbation_service] = lambda: perturbation_service

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
        " through branching conversation rhizomes"
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



@app.exception_handler(QivisError)
async def qivis_error(request: Request, exc: QivisError) -> JSONResponse:
    """Not found / invalid request / not configured, raised by any service."""
    return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)


app.include_router(rhizomes_router)
app.include_router(export_router)
app.include_router(search_router)
app.include_router(import_router)
app.include_router(merge_router)
app.include_router(steering_router)
app.include_router(probes_router)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/providers")
async def providers() -> list[dict]:
    return [
        {
            "name": p.name,
            "available": True,
            "models": p.suggested_models,
            "supported_params": p.supported_params,
            "supported_modes": p.supported_modes,
        }
        for p in get_all_providers()
    ]


@app.get("/api/models")
async def models() -> list[dict]:
    """Named models for the picker: profiled models first, then discovered ones."""
    return get_catalog().entries(get_all_providers())


@app.get("/api/intervention-types")
async def intervention_types() -> list[dict]:
    from qivis.generation.interventions import default_registry
    return default_registry.available_types()
