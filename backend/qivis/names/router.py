"""HTTP for name studies (qivis.names.study)."""

from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from qivis.names.study import DEFAULT_FRAMES, DiscoverySpec, NameStudyService, StudySpec

router = APIRouter(prefix="/api/name-studies", tags=["name-studies"])


def get_name_study_service() -> NameStudyService:
    """Dependency placeholder -- replaced at app startup."""
    raise RuntimeError("NameStudyService not initialized")


@router.post("/discoveries", status_code=status.HTTP_201_CREATED)
async def create_discovery(
    spec: DiscoverySpec, svc: NameStudyService = Depends(get_name_study_service),
) -> dict[str, Any]:
    return await svc.create_discovery(spec)


@router.get("/discoveries")
async def list_discoveries(svc: NameStudyService = Depends(get_name_study_service)) -> list[dict]:
    return await svc.list_discoveries()


@router.get("/discoveries/{discovery_id}")
async def get_discovery(
    discovery_id: str, svc: NameStudyService = Depends(get_name_study_service),
) -> dict[str, Any]:
    return await svc.get_discovery(discovery_id)


@router.get("/defaults")
async def defaults() -> dict[str, Any]:
    return {"frames": DEFAULT_FRAMES}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(
    spec: StudySpec, start: bool = True, svc: NameStudyService = Depends(get_name_study_service),
) -> dict[str, Any]:
    return await svc.create(spec, start)


@router.get("")
async def list_studies(svc: NameStudyService = Depends(get_name_study_service)) -> list[dict]:
    return await svc.list()


@router.get("/{study_id}")
async def get_study(
    study_id: str, svc: NameStudyService = Depends(get_name_study_service),
) -> dict[str, Any]:
    return await svc.get(study_id)


class Extension(BaseModel):
    pronouns: list[str] = []
    descriptions: dict[str, str] = {}
    frames: dict[str, list[str]] = {}
    names: list[str] = []


@router.post("/{study_id}/extend")
async def extend(
    study_id: str, body: Extension, svc: NameStudyService = Depends(get_name_study_service),
) -> dict:
    return await svc.extend(study_id, body.pronouns, body.descriptions, body.frames, body.names)


@router.post("/{study_id}/stop")
async def stop(study_id: str, svc: NameStudyService = Depends(get_name_study_service)) -> dict:
    return await svc.stop(study_id)


@router.post("/{study_id}/resume")
async def resume(study_id: str, svc: NameStudyService = Depends(get_name_study_service)) -> dict:
    return await svc.resume(study_id)
