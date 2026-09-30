"""FastAPI routes for rhizome and node CRUD, and generation."""

import json as json_module
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from qivis.errors import InvalidRequestError, NotConfiguredError, QivisError
from qivis.generation.perturbation import PerturbationService
from qivis.generation.replay import ReplayService
from qivis.generation.service import (
    Branch,
    GenerationService,
)
from qivis.providers.base import LLMProvider, StreamChunk
from qivis.providers.registry import ProviderNotFoundError, get_provider
from qivis.rhizomes.schemas import (
    AddAnnotationRequest,
    AnnotationResponse,
    BookmarkResponse,
    BulkAnchorRequest,
    CreateBookmarkRequest,
    CreateDigressionGroupRequest,
    CreateNodeRequest,
    CreateNoteRequest,
    CreateRhizomeRequest,
    CreateSummaryRequest,
    CrossModelGenerateRequest,
    CutNodeRequest,
    DigressionGroupResponse,
    EditHistoryResponse,
    ExcludeNodeRequest,
    GenerateRequest,
    IncludeNodeRequest,
    InterventionTimelineResponse,
    NodeExclusionResponse,
    NodeResponse,
    NoteResponse,
    PatchNodeContentRequest,
    PatchRhizomeRequest,
    PerturbationReportResponse,
    PerturbationRequest,
    ReplayRequest,
    RhizomeDetailResponse,
    RhizomeSummary,
    SummaryResponse,
    TaxonomyResponse,
    ToggleDigressionGroupRequest,
)
from qivis.rhizomes.service import (
    RhizomeService,
)
from qivis.steering.router import get_optional_steering_service
from qivis.steering.service import SteeringService

logger = logging.getLogger(__name__)

# Errors that mean the request was wrong, not that a model failed. The app maps
# them to their status (main.py); streams report them as an error event.
CLIENT_ERRORS: tuple[type[Exception], ...] = (QivisError,)

router = APIRouter(prefix="/api/rhizomes", tags=["rhizomes"])


def get_rhizome_service() -> RhizomeService:
    """Dependency placeholder — replaced at app startup."""
    raise RuntimeError("RhizomeService not initialized")


def get_generation_service() -> GenerationService:
    """Dependency placeholder — replaced at app startup."""
    raise RuntimeError("GenerationService not initialized")


def get_replay_service() -> ReplayService:
    """Dependency placeholder — replaced at app startup."""
    raise RuntimeError("ReplayService not initialized")


def get_perturbation_service() -> PerturbationService:
    """Dependency placeholder — replaced at app startup."""
    raise RuntimeError("PerturbationService not initialized")


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_rhizome(
    request: CreateRhizomeRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> RhizomeDetailResponse:
    return await service.create_rhizome(request)


@router.get("")
async def list_rhizomes(
    include_archived: bool = False,
    service: RhizomeService = Depends(get_rhizome_service),
) -> list[RhizomeSummary]:
    return await service.list_rhizomes(include_archived=include_archived)


@router.get("/{rhizome_id}")
async def get_rhizome(
    rhizome_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> RhizomeDetailResponse:
    rhizome = await service.get_rhizome(rhizome_id)
    if rhizome is None:
        raise HTTPException(status_code=404, detail=f"Rhizome not found: {rhizome_id}")
    return rhizome


@router.patch("/{rhizome_id}")
async def update_rhizome(
    rhizome_id: str,
    request: PatchRhizomeRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> RhizomeDetailResponse:
    return await service.update_rhizome(rhizome_id, request)


@router.post("/{rhizome_id}/archive")
async def archive_rhizome(
    rhizome_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> RhizomeDetailResponse:
    return await service.archive_rhizome(rhizome_id)


@router.post("/{rhizome_id}/unarchive")
async def unarchive_rhizome(
    rhizome_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> RhizomeDetailResponse:
    return await service.unarchive_rhizome(rhizome_id)


@router.post("/{rhizome_id}/nodes", status_code=status.HTTP_201_CREATED)
async def create_node(
    rhizome_id: str,
    request: CreateNodeRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> NodeResponse:
    return await service.create_node(rhizome_id, request)


@router.patch("/{rhizome_id}/nodes/{node_id}/content")
async def edit_node_content(
    rhizome_id: str,
    node_id: str,
    request: PatchNodeContentRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> NodeResponse:
    return await service.edit_node_content(rhizome_id, node_id, request.edited_content)


@router.get("/{rhizome_id}/nodes/{node_id}/edit-history")
async def get_edit_history(
    rhizome_id: str,
    node_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> EditHistoryResponse:
    return await service.get_edit_history(rhizome_id, node_id)


@router.get("/{rhizome_id}/interventions")
async def get_interventions(
    rhizome_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> InterventionTimelineResponse:
    return await service.get_intervention_timeline(rhizome_id)


@router.post(
    "/{rhizome_id}/nodes/{node_id}/annotations",
    status_code=status.HTTP_201_CREATED,
)
async def add_annotation(
    rhizome_id: str,
    node_id: str,
    request: AddAnnotationRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> AnnotationResponse:
    return await service.add_annotation(rhizome_id, node_id, request)


@router.get("/{rhizome_id}/nodes/{node_id}/annotations")
async def get_node_annotations(
    rhizome_id: str,
    node_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> list[AnnotationResponse]:
    return await service.get_node_annotations(rhizome_id, node_id)


@router.delete(
    "/{rhizome_id}/annotations/{annotation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_annotation(
    rhizome_id: str,
    annotation_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> None:
    await service.remove_annotation(rhizome_id, annotation_id)


@router.get("/{rhizome_id}/taxonomy")
async def get_rhizome_taxonomy(
    rhizome_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> TaxonomyResponse:
    return await service.get_rhizome_taxonomy(rhizome_id)


@router.post(
    "/{rhizome_id}/nodes/{node_id}/notes",
    status_code=status.HTTP_201_CREATED,
)
async def add_note(
    rhizome_id: str,
    node_id: str,
    request: CreateNoteRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> NoteResponse:
    return await service.add_note(rhizome_id, node_id, request)


@router.get("/{rhizome_id}/nodes/{node_id}/notes")
async def get_node_notes(
    rhizome_id: str,
    node_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> list[NoteResponse]:
    return await service.get_node_notes(rhizome_id, node_id)


@router.get("/{rhizome_id}/notes")
async def get_rhizome_notes(
    rhizome_id: str,
    q: str | None = None,
    service: RhizomeService = Depends(get_rhizome_service),
) -> list[NoteResponse]:
    return await service.get_rhizome_notes(rhizome_id, query=q)


@router.delete(
    "/{rhizome_id}/notes/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_note(
    rhizome_id: str,
    note_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> None:
    await service.remove_note(rhizome_id, note_id)


@router.get("/{rhizome_id}/annotations")
async def get_rhizome_annotations(
    rhizome_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> list[AnnotationResponse]:
    return await service.get_rhizome_annotations(rhizome_id)


@router.post(
    "/{rhizome_id}/nodes/{node_id}/bookmarks",
    status_code=status.HTTP_201_CREATED,
)
async def add_bookmark(
    rhizome_id: str,
    node_id: str,
    request: CreateBookmarkRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> BookmarkResponse:
    return await service.add_bookmark(rhizome_id, node_id, request)


@router.get("/{rhizome_id}/bookmarks")
async def get_rhizome_bookmarks(
    rhizome_id: str,
    q: str | None = None,
    service: RhizomeService = Depends(get_rhizome_service),
) -> list[BookmarkResponse]:
    return await service.get_rhizome_bookmarks(rhizome_id, query=q)


@router.delete(
    "/{rhizome_id}/bookmarks/{bookmark_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_bookmark(
    rhizome_id: str,
    bookmark_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> None:
    await service.remove_bookmark(rhizome_id, bookmark_id)


@router.post("/{rhizome_id}/bookmarks/{bookmark_id}/summarize")
async def summarize_bookmark(
    rhizome_id: str,
    bookmark_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> BookmarkResponse:
    return await service.generate_bookmark_summary(rhizome_id, bookmark_id)


# -- Manual summarization --


@router.post("/{rhizome_id}/nodes/{node_id}/summarize")
async def generate_summary(
    rhizome_id: str,
    node_id: str,
    request: CreateSummaryRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> SummaryResponse:
    return await service.generate_summary(rhizome_id, node_id, request)


@router.get("/{rhizome_id}/summaries")
async def list_summaries(
    rhizome_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> list[SummaryResponse]:
    return await service.list_summaries(rhizome_id)


@router.delete(
    "/{rhizome_id}/summaries/{summary_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_summary(
    rhizome_id: str,
    summary_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> None:
    await service.remove_summary(rhizome_id, summary_id)


@router.post("/{rhizome_id}/nodes/{node_id}/exclude")
async def exclude_node(
    rhizome_id: str,
    node_id: str,
    request: ExcludeNodeRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> NodeExclusionResponse:
    return await service.exclude_node(rhizome_id, node_id, request)


@router.post(
    "/{rhizome_id}/nodes/{node_id}/include",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def include_node(
    rhizome_id: str,
    node_id: str,
    request: IncludeNodeRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> None:
    await service.include_node(rhizome_id, node_id, request.scope_node_id)


@router.get("/{rhizome_id}/exclusions")
async def get_rhizome_exclusions(
    rhizome_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> list[NodeExclusionResponse]:
    return await service.get_rhizome_exclusions(rhizome_id)


@router.post(
    "/{rhizome_id}/digression-groups",
    status_code=status.HTTP_201_CREATED,
)
async def create_digression_group(
    rhizome_id: str,
    request: CreateDigressionGroupRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> DigressionGroupResponse:
    return await service.create_digression_group(rhizome_id, request)


@router.get("/{rhizome_id}/digression-groups")
async def get_digression_groups(
    rhizome_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> list[DigressionGroupResponse]:
    return await service.get_digression_groups(rhizome_id)


@router.post("/{rhizome_id}/digression-groups/{group_id}/toggle")
async def toggle_digression_group(
    rhizome_id: str,
    group_id: str,
    request: ToggleDigressionGroupRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> DigressionGroupResponse:
    return await service.toggle_digression_group(rhizome_id, group_id, request.included)


@router.delete(
    "/{rhizome_id}/digression-groups/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_digression_group(
    rhizome_id: str,
    group_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> None:
    await service.delete_digression_group(rhizome_id, group_id)


@router.post("/{rhizome_id}/bulk-anchor")
async def bulk_anchor(
    rhizome_id: str,
    request: BulkAnchorRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> dict:
    changed = await service.bulk_anchor(rhizome_id, request.node_ids, request.anchor)
    return {"changed": changed, "anchor": request.anchor}


@router.post("/{rhizome_id}/nodes/{node_id}/cut", status_code=status.HTTP_201_CREATED)
async def cut_node(
    rhizome_id: str,
    node_id: str,
    request: CutNodeRequest,
    service: RhizomeService = Depends(get_rhizome_service),
) -> NodeResponse:
    return await service.cut_node(rhizome_id, node_id, request.keep)


@router.post("/{rhizome_id}/nodes/{node_id}/anchor")
async def toggle_anchor(
    rhizome_id: str,
    node_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> dict:
    is_anchored = await service.anchor_node(rhizome_id, node_id)
    return {"is_anchored": is_anchored}


@router.post(
    "/{rhizome_id}/nodes/{node_id}/generate",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
)
async def generate(
    rhizome_id: str,
    node_id: str,
    request: GenerateRequest,
    gen_service: GenerationService = Depends(get_generation_service),
    service: RhizomeService = Depends(get_rhizome_service),
    steering: SteeringService | None = Depends(get_optional_steering_service),
) -> NodeResponse | StreamingResponse:
    branch = None
    if request.branch is not None:
        if steering is None:
            raise NotConfiguredError("Branching at a token needs the steering service")
        branch = await _branch_start(rhizome_id, node_id, request, service, steering)
    return await _dispatch_generate(rhizome_id, node_id, request, gen_service, branch)


async def _branch_start(
    rhizome_id: str,
    node_id: str,
    request: GenerateRequest,
    service: RhizomeService,
    steering: SteeringService,
) -> tuple[str, Branch]:
    """The prefill and records for a reply branched at a token (the reply must
    answer node_id: the new version is its sibling)."""
    spec = request.branch
    assert spec is not None
    original = await service.node_response(rhizome_id, spec.node_id)
    if original.parent_id != node_id:
        raise InvalidRequestError("A branched reply is generated under the original's parent")
    if request.n > 1:
        raise InvalidRequestError("A branch can't be combined with n > 1")
    text, tokens = await steering.branch_start(
        rhizome_id, original, spec.keep, spec.token_ids, _provider(request.provider),
    )
    return text, Branch(tokens=tokens, origin={"node_id": spec.node_id, "keep": spec.keep})


@router.post(
    "/{rhizome_id}/generate",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
)
async def generate_root(
    rhizome_id: str,
    request: GenerateRequest,
    gen_service: GenerationService = Depends(get_generation_service),
) -> NodeResponse | StreamingResponse:
    """Generate a new root assistant node: the model speaks first, with no prior turns."""
    return await _dispatch_generate(rhizome_id, None, request, gen_service)


async def _dispatch_generate(
    rhizome_id: str,
    node_id: str | None,
    request: GenerateRequest,
    gen_service: GenerationService,
    branch: tuple[str, Branch] | None = None,
) -> NodeResponse | StreamingResponse:
    provider = _provider(request.provider, request.mode)
    if branch is not None:
        # The branch's start is the prefill (and its records head the reply's)
        request = request.model_copy(update={"prefill_content": branch[0]})
    if request.prefill_content and request.n > 1:
        raise HTTPException(
            status_code=400,
            detail="prefill_content cannot be combined with n > 1",
        )
    kwargs: dict[str, Any] = dict(
        model=request.model,
        system_prompt=request.system_prompt,
        sampling_params=request.sampling_params,
        prefill_content=request.prefill_content,
        mode_override=request.mode,
    )
    if branch is not None:
        kwargs["branch"] = branch[1]

    if request.stream:
        chunks = (
            gen_service.generate_n_stream(rhizome_id, node_id, provider, n=request.n, **kwargs)
            if request.n > 1
            else gen_service.generate_stream(rhizome_id, node_id, provider, **kwargs)
        )
        return _sse_response(chunks, "generation")

    with _upstream_errors("Generation"):
        if request.n > 1:
            # All n are stored as siblings; the response is the first (clients refresh)
            nodes = await gen_service.generate_n(
                rhizome_id, node_id, provider, n=request.n, **kwargs,
            )
            return nodes[0]
        return await gen_service.generate(rhizome_id, node_id, provider, **kwargs)


def _provider(name: str, mode: str | None = None) -> LLMProvider:
    """The named provider, checked to support the requested mode (400 otherwise)."""
    try:
        provider = get_provider(name)
    except ProviderNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if mode is not None and mode not in provider.supported_modes:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{name}' does not support {mode} mode",
        )
    return provider


@contextmanager
def _upstream_errors(what: str) -> Iterator[None]:
    """Anything but a known client error is the model's side failing: 502, logged."""
    try:
        yield
    except (HTTPException, *CLIENT_ERRORS):
        raise
    except Exception as e:
        logger.exception("%s error", what)
        raise HTTPException(status_code=502, detail=str(e) or type(e).__name__)


# -- Server-sent events --

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json_module.dumps(data)}\n\n"


def _chunk_event(chunk: StreamChunk) -> str | None:
    """One chunk from a generation service as an SSE event (None: nothing to send)."""
    index = {} if chunk.completion_index is None else {"completion_index": chunk.completion_index}
    if chunk.data is not None:  # a service event: replay_step, perturbation_complete, ...
        return sse(chunk.type, chunk.data)
    if chunk.type == "message_stop" and chunk.result is not None:
        result = chunk.result
        return sse("message_stop", {
            "type": "message_stop",
            **index,
            "node_id": chunk.node_id,
            "content": result.content,
            "finish_reason": result.finish_reason,
            "usage": result.usage,
            "latency_ms": result.latency_ms,
            "thinking_content": result.thinking_content,
        })
    if chunk.type == "error":
        return sse("error", {"error": chunk.text, **index})
    if chunk.type == "generation_complete":
        return sse("generation_complete", {"type": "generation_complete"})
    if chunk.type == "thinking_delta" and chunk.thinking:
        return sse(
            "thinking_delta", {"type": "thinking_delta", "thinking": chunk.thinking, **index},
        )
    if chunk.text:
        return sse("text_delta", {"type": "text_delta", "text": chunk.text, **index})
    return None


def _sse_response(chunks: AsyncIterator[StreamChunk], what: str) -> StreamingResponse:
    """Stream a generation service's chunks; failures become a final error event."""

    async def body() -> AsyncIterator[str]:
        try:
            async for chunk in chunks:
                event = _chunk_event(chunk)
                if event is not None:
                    yield event
        except CLIENT_ERRORS as e:
            yield sse("error", {"error": str(e)})
        except Exception as e:
            logger.exception("Streaming %s error", what)
            yield sse("error", {"error": str(e) or f"{type(e).__name__} (no message)"})

    return StreamingResponse(body(), media_type="text/event-stream", headers=SSE_HEADERS)


# -- Replay --


@router.post(
    "/{rhizome_id}/replay",
    response_model=None,
)
async def replay(
    rhizome_id: str,
    request: ReplayRequest,
    replay_service: ReplayService = Depends(get_replay_service),
) -> list[NodeResponse] | StreamingResponse:
    provider = _provider(request.provider, request.generation_mode)
    kwargs: dict[str, Any] = dict(
        generation_mode=request.generation_mode,
        model=request.model,
        system_prompt=request.system_prompt,
        sampling_params=request.sampling_params,
    )
    if request.stream:
        return _sse_response(
            replay_service.replay_path_stream(
                rhizome_id, request.path_node_ids, provider, **kwargs,
            ),
            "replay",
        )
    with _upstream_errors("Replay"):
        return await replay_service.replay_path(
            rhizome_id, request.path_node_ids, provider, **kwargs,
        )


# -- Cross-model generation --


@router.post(
    "/{rhizome_id}/nodes/{node_id}/generate-cross",
    response_model=None,
)
async def generate_cross(
    rhizome_id: str,
    node_id: str,
    request: CrossModelGenerateRequest,
    gen_service: GenerationService = Depends(get_generation_service),
) -> list[NodeResponse] | StreamingResponse:
    # Validate all providers (and any requested modes) up front
    for target in request.targets:
        _provider(target.provider, target.mode)
    targets = [
        {"provider": t.provider, "model": t.model, "mode": t.mode}
        for t in request.targets
    ]
    kwargs: dict[str, Any] = dict(
        system_prompt=request.system_prompt, sampling_params=request.sampling_params,
    )

    if request.stream:
        return _sse_response(
            gen_service.generate_cross_stream(rhizome_id, node_id, targets, **kwargs),
            "cross-model",
        )
    with _upstream_errors("Cross-model"):
        return await gen_service.generate_cross(rhizome_id, node_id, targets, **kwargs)


# -- Perturbation experiments --


@router.post(
    "/{rhizome_id}/nodes/{node_id}/perturb",
    response_model=None,
)
async def perturb(
    rhizome_id: str,
    node_id: str,
    request: PerturbationRequest,
    perturb_service: PerturbationService = Depends(get_perturbation_service),
) -> PerturbationReportResponse | StreamingResponse:
    provider = _provider(request.provider)
    kwargs: dict[str, Any] = dict(
        model=request.model,
        sampling_params=request.sampling_params,
        include_control=request.include_control,
    )
    if request.stream:
        return _sse_response(
            perturb_service.run_experiment_stream(
                rhizome_id, node_id, request.perturbations, provider, **kwargs,
            ),
            "perturbation",
        )
    with _upstream_errors("Perturbation"):
        return await perturb_service.run_experiment(
            rhizome_id, node_id, request.perturbations, provider, **kwargs,
        )


# -- Perturbation report CRUD --


@router.get("/{rhizome_id}/perturbation-reports")
async def list_perturbation_reports(
    rhizome_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> list[PerturbationReportResponse]:
    return await service.list_perturbation_reports(rhizome_id)


@router.get("/{rhizome_id}/perturbation-reports/{report_id}")
async def get_perturbation_report(
    rhizome_id: str,
    report_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
) -> PerturbationReportResponse:
    report = await service.get_perturbation_report(rhizome_id, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Report not found: {report_id}")
    return report


@router.delete("/{rhizome_id}/perturbation-reports/{report_id}")
async def delete_perturbation_report(
    rhizome_id: str,
    report_id: str,
    service: RhizomeService = Depends(get_rhizome_service),
):
    await service.remove_perturbation_report(rhizome_id, report_id)
    return {"status": "ok"}
