"""HTTP for answer probes (qivis.probes.service)."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from qivis.probes.service import ProbeService
from qivis.providers.registry import get_provider
from qivis.rhizomes.schemas import NodeResponse

router = APIRouter(prefix="/api/rhizomes", tags=["probes"])


def get_probe_service() -> ProbeService:
    """Dependency placeholder -- replaced at app startup."""
    raise RuntimeError("ProbeService not initialized")


class JudgeChoice(BaseModel):
    """A judge for exact probes: any provider's model (e.g. a frontier model);
    unset, the best local one."""
    provider: str
    model: str


class RunProbe(BaseModel):
    node_id: str | None = None  # the point to probe (None: the beginning)
    provider: str
    model: str | None = None
    # "sample": n samples, grouped; "exact": the answer distribution, enumerated
    # (qivis.probes.exact)
    mode: Literal["sample", "exact"] = "sample"
    n: int = Field(default=20, ge=1, le=64)
    max_tokens: int = Field(default=24, ge=1, le=256)
    # Exact probes only
    epsilon: float = Field(default=1e-3, gt=0, le=0.5)
    tail: int = Field(default=100, ge=0, le=1000)
    menu: list[str] | None = None  # answers for the judge to choose from
    judge: JudgeChoice | None = None
    grain: str | None = None  # how fine to group answers, in words


@router.post("/{rhizome_id}/probes", status_code=status.HTTP_201_CREATED)
async def run_probe(
    rhizome_id: str, body: RunProbe, svc: ProbeService = Depends(get_probe_service),
) -> dict[str, Any]:
    if body.mode == "exact":
        menu = [m.strip() for m in body.menu or [] if m.strip()] or None
        return await svc.run_exact(
            rhizome_id, body.node_id, get_provider(body.provider), body.model,
            epsilon=body.epsilon, max_tokens=body.max_tokens, tail=body.tail, menu=menu,
            judge=body.judge.model_dump() if body.judge else None, grain=body.grain,
        )
    return await svc.run(
        rhizome_id, body.node_id, get_provider(body.provider), body.model,
        n=body.n, max_tokens=body.max_tokens,
    )


@router.get("/{rhizome_id}/probes")
async def list_probes(
    rhizome_id: str, svc: ProbeService = Depends(get_probe_service),
) -> list[dict[str, Any]]:
    return await svc.list(rhizome_id)


@router.post("/{rhizome_id}/probes/{probe_id}/judge")
async def judge_again(
    rhizome_id: str, probe_id: str, judge: JudgeChoice | None = None,
    svc: ProbeService = Depends(get_probe_service),
) -> dict[str, Any]:
    return await svc.judge_again(rhizome_id, probe_id, judge.model_dump() if judge else None)


@router.post(
    "/{rhizome_id}/probes/{probe_id}/samples/{index}/continue",
    status_code=status.HTTP_201_CREATED,
)
async def continue_from(
    rhizome_id: str, probe_id: str, index: int, svc: ProbeService = Depends(get_probe_service),
) -> NodeResponse:
    return await svc.continue_from(rhizome_id, probe_id, index)
