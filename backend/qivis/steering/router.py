"""HTTP for steered generation (qivis.steering.service)."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from qivis.models import SamplingParams
from qivis.providers.registry import get_provider
from qivis.rhizomes.schemas import NodeResponse
from qivis.steering.service import DEFAULT_K, SteeringService

router = APIRouter(prefix="/api", tags=["steering"])


def get_steering_service() -> SteeringService:
    """Dependency placeholder -- replaced at app startup."""
    raise RuntimeError("SteeringService not initialized")


def get_optional_steering_service() -> SteeringService | None:
    """For routes that only sometimes need steering (replaced at app startup)."""
    return None


class StartSteering(BaseModel):
    provider: str = "llamacpp"
    model: str | None = None
    system_prompt: str | None = None
    sampling_params: SamplingParams | None = None


class NextTokens(BaseModel):
    continuation: list[int] = Field(default_factory=list)
    k: int = Field(default=DEFAULT_K, ge=1, le=200)


class CommitSteering(BaseModel):
    token_ids: list[int]
    chosen_by: list[Literal["model", "researcher"]]


@router.post("/rhizomes/{rhizome_id}/nodes/{node_id}/steer")
async def start(
    rhizome_id: str, node_id: str, body: StartSteering,
    svc: SteeringService = Depends(get_steering_service),
) -> dict:
    """Start steering a reply to this node."""
    return await _start(svc, rhizome_id, node_id, body)


@router.post("/rhizomes/{rhizome_id}/steer")
async def start_root(
    rhizome_id: str, body: StartSteering,
    svc: SteeringService = Depends(get_steering_service),
) -> dict:
    """Start steering a first turn (the model speaks first)."""
    return await _start(svc, rhizome_id, None, body)


async def _start(svc: SteeringService, rhizome_id: str, node_id: str | None, body: StartSteering):
    return await svc.start(
        rhizome_id, node_id, get_provider(body.provider),
        model=body.model, system_prompt=body.system_prompt, sampling_params=body.sampling_params,
    )


@router.post("/steer/{session_id}/next")
async def next_tokens(
    session_id: str, body: NextTokens, svc: SteeringService = Depends(get_steering_service),
) -> list[dict]:
    return await svc.next(session_id, body.continuation, body.k)


@router.post("/steer/{session_id}/commit", status_code=201)
async def commit(
    session_id: str, body: CommitSteering, svc: SteeringService = Depends(get_steering_service),
) -> NodeResponse:
    return await svc.commit(session_id, body.token_ids, body.chosen_by)


class Tokenize(BaseModel):
    text: str


@router.post("/steer/{session_id}/tokenize")
async def tokenize(
    session_id: str, body: Tokenize, svc: SteeringService = Depends(get_steering_service),
) -> list[dict]:
    return await svc.tokenize(session_id, body.text)


@router.delete("/steer/{session_id}", status_code=204)
async def discard(session_id: str, svc: SteeringService = Depends(get_steering_service)) -> None:
    svc.discard(session_id)
