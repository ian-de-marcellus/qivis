"""Name studies: which names models give a mind described one way.

A study runs, for each model, every combination of pronoun set, frame ("His
name is", "He calls himself"...) and condition: the description with the
study's subject ("an electronic mind"), the same description with the
control subject ("a human"), and the bare frame with no description. It
works in three phases, each cell's results recorded as it finishes (so a
study interrupted, say by a restart, picks up where it stopped):

1. Each cell's own exact top names (qivis.names.engine).
2. Per pronoun set, the frames of the subject's description unified: every
   name in any frame's top scored in every frame, and ranked by its mean
   log-probability across frames.
3. The study's names (each pronoun set's unified top, and any extra names)
   scored in every cell, so each can be compared across conditions.
"""

import asyncio
import json
import logging
import math
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from qivis.errors import InvalidRequestError, NotFoundError
from qivis.events.log import EventLog
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.models import SamplingParams
from qivis.names import engine
from qivis.providers.base import GenerationRequest
from qivis.providers.llamacpp import LlamaCppProvider
from qivis.providers.registry import get_provider

logger = logging.getLogger(__name__)

LOOKUP_K = 1_000_000  # the whole vocabulary (llama.cpp clamps it)

DEFAULT_FRAMES = {
    "he": ["His name is", "He is called", "His name was", "He calls himself"],
    "she": ["Her name is", "She is called", "Her name was", "She calls herself"],
    "they": ["Their name is", "They are called", "Their name was", "They call themselves"],
    "it": ["Its name is", "It is called", "Its name was", "It calls itself"],
}

CONDITIONS = ("model", "control", "bare")


class StudySpec(BaseModel):
    title: str
    models: list[str] = Field(min_length=1)
    pronouns: list[str] = Field(min_length=1)
    # Per pronoun set: the description, with {subject} where the subject goes
    descriptions: dict[str, str]
    frames: dict[str, list[str]]
    subject: str = "an electronic mind"
    control: str = "a human"
    include_bare: bool = True
    top: int = Field(default=40, ge=1, le=200)
    extra_names: list[str] = Field(default_factory=lambda: ["Sun"])


class StudyNotFoundError(NotFoundError):
    def __init__(self, study_id: str) -> None:
        super().__init__(f"Name study not found: {study_id}")


def cell_key(model: str, pronoun: str, frame: str, condition: str) -> str:
    return f"{model}|{pronoun}|{frame}|{condition}"


def study_text(spec: StudySpec, pronoun: str, frame: str, condition: str) -> str:
    """The text a cell's model continues (without the document start)."""
    if condition == "bare":
        return frame
    subject = spec.subject if condition == "model" else spec.control
    description = spec.descriptions[pronoun].replace("{subject}", subject).rstrip()
    return f"{description} {frame}" if description else frame


def cells_of(spec: StudySpec) -> list[tuple[str, str, str, str]]:
    conditions = CONDITIONS if spec.include_bare else CONDITIONS[:2]
    return [
        (model, pronoun, frame, condition)
        for model in spec.models
        for pronoun in spec.pronouns
        for frame in spec.frames[pronoun]
        for condition in conditions
    ]


def _log(p: float) -> float:
    return math.log(max(p, 1e-30))


def value(cell: dict, name: str) -> float | None:
    """A name's probability in a cell: from its enumeration if found there, else its score."""
    top = cell.get("top") or {}
    if name in top:
        return top[name]
    return (cell.get("scores") or {}).get(name)


class NameStudyService:
    def __init__(self, store: EventStore, projector: StateProjector) -> None:
        self._events = EventLog(store, projector)
        self._db = projector._db
        self._tasks: dict[str, asyncio.Task] = {}
        self._progress: dict[str, dict[str, Any]] = {}

    # -- Lifecycle --

    async def create(self, spec: StudySpec) -> dict[str, Any]:
        for pronoun in spec.pronouns:
            if pronoun not in spec.descriptions or not spec.frames.get(pronoun):
                raise InvalidRequestError(f"Pronoun set '{pronoun}' needs a description and frames")
        study_id = f"study-{uuid4()}"
        await self._events.emit(study_id, "NameStudyCreated", {
            "study_id": study_id, "title": spec.title, "spec": spec.model_dump(),
            "rules": engine.__doc__ or "",
        })
        self.start(study_id)
        return await self.get(study_id)

    def start(self, study_id: str) -> None:
        if study_id in self._tasks and not self._tasks[study_id].done():
            return
        self._tasks[study_id] = asyncio.create_task(self._run(study_id))

    async def stop(self, study_id: str) -> dict[str, Any]:
        task = self._tasks.get(study_id)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._status(study_id, "stopped")
        return await self.get(study_id)

    async def resume(self, study_id: str) -> dict[str, Any]:
        await self._row(study_id)
        await self._status(study_id, "running")
        self.start(study_id)
        return await self.get(study_id)

    async def resume_unfinished(self) -> None:
        """At startup: studies that were running when the app stopped go on."""
        rows = await self._db.fetchall("SELECT study_id FROM name_studies WHERE status = 'running'")
        for row in rows:
            self.start(row["study_id"])

    async def _status(self, study_id: str, status: str, error: str | None = None) -> None:
        await self._events.emit(study_id, "NameStudyStatus", {
            "study_id": study_id, "status": status, "error": error,
        })

    # -- Running --

    async def _run(self, study_id: str) -> None:
        try:
            spec = StudySpec.model_validate(json.loads((await self._row(study_id))["spec"]))
            for model in spec.models:
                await self._run_model(study_id, spec, model)
            await self._status(study_id, "done")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Name study %s failed", study_id)
            await self._status(study_id, "failed", str(e) or type(e).__name__)
        finally:
            self._progress.pop(study_id, None)

    async def _run_model(self, study_id: str, spec: StudySpec, model: str) -> None:
        llama = get_provider("llamacpp")
        if not isinstance(llama, LlamaCppProvider):
            raise InvalidRequestError("Name studies need a llama.cpp model")
        start = await llama.document_start(model)
        mine = [c for c in cells_of(spec) if c[0] == model]

        def prompt_of(c: tuple[str, str, str, str]) -> str:
            return start + study_text(spec, c[1], c[2], c[3])

        # 1. Each cell's own top names
        for i, c in enumerate(mine):
            self._progress[study_id] = {
                "model": model, "phase": "finding each cell's top names",
                "done": i, "of": len(mine),
            }
            if (await self._cell(study_id, c)).get("top") is not None:
                continue
            lookups = engine.Lookups(self._fetcher(llama, model, prompt_of(c)))
            top, capital = await engine.enumerate_names(lookups, spec.top)
            await self._record(study_id, "NameStudyCellEnumerated", c, prompt_of(c), {
                "top": top, "capital_mass": capital, "queries": lookups.queries,
            })

        # 2. Per pronoun set, the description's frames unified
        names = set(spec.extra_names)
        for pronoun in spec.pronouns:
            frames = [c for c in mine if c[1] == pronoun and c[3] == "model"]
            candidates = set()
            for c in frames:
                candidates |= set((await self._cell(study_id, c))["top"] or {})
            await self._score_all(
                study_id, llama, model, frames, candidates, prompt_of,
                f"unifying the '{pronoun}' frames",
            )
            scored = [await self._cell(study_id, c) for c in frames]
            unified = {
                n: sum(_log(value(cell, n) or 0.0) for cell in scored) / len(scored)
                for n in candidates
            }
            names |= set(sorted(unified, key=lambda n: -unified[n])[: spec.top])

        # 3. The study's names, in every cell
        await self._score_all(study_id, llama, model, mine, names, prompt_of, "scoring the names")

    async def _score_all(self, study_id, llama, model, cells, names, prompt_of, phase) -> None:
        for i, c in enumerate(cells):
            self._progress[study_id] = {"model": model, "phase": phase, "done": i, "of": len(cells)}
            cell = await self._cell(study_id, c)
            missing = [n for n in names if value(cell, n) is None]
            if not missing:
                continue
            lookups = engine.Lookups(self._fetcher(llama, model, prompt_of(c)))
            scores = dict(cell.get("scores") or {})
            for name in sorted(missing):
                ids = [t["id"] for t in await llama.tokenize(" " + name, model)]
                scores[name] = await engine.score_name(lookups, ids, name) if ids else 0.0
            await self._record(study_id, "NameStudyCellScored", c, prompt_of(c), {
                "scores": scores, "queries": lookups.queries,
            })

    @staticmethod
    def _fetcher(llama: LlamaCppProvider, model: str, prompt: str) -> engine.Distribution:
        request = GenerationRequest(
            model=model, messages=[], prompt_text=prompt, sampling_params=SamplingParams(),
        )

        async def fetch(ids: list[int]) -> list[dict]:
            return (await llama.next_tokens(request, ids, LOOKUP_K))["candidates"]

        return fetch

    async def _record(self, study_id, event_type, c, prompt, data) -> None:
        model, pronoun, frame, condition = c
        await self._events.emit(study_id, event_type, {
            "study_id": study_id, "key": cell_key(*c), "model": model, "pronoun": pronoun,
            "frame": frame, "condition": condition, "prompt": prompt, **data,
        })

    # -- Reading --

    async def _row(self, study_id: str) -> dict:
        row = await self._db.fetchone("SELECT * FROM name_studies WHERE study_id = ?", (study_id,))
        if row is None:
            raise StudyNotFoundError(study_id)
        return dict(row)

    async def _cell(self, study_id: str, c: tuple[str, str, str, str]) -> dict:
        row = await self._db.fetchone(
            "SELECT * FROM name_study_cells WHERE study_id = ? AND key = ?",
            (study_id, cell_key(*c)),
        )
        if row is None:
            return {}
        cell = dict(row)
        cell["top"] = json.loads(cell["top"]) if cell["top"] else None
        cell["scores"] = json.loads(cell["scores"]) if cell["scores"] else None
        return cell

    async def list(self) -> list[dict[str, Any]]:
        rows = await self._db.fetchall(
            "SELECT study_id, title, spec, status, created_at, updated_at FROM name_studies "
            "ORDER BY created_at DESC",
        )
        return [
            {
                "study_id": r["study_id"], "title": r["title"], "status": r["status"],
                "models": json.loads(r["spec"])["models"],
                "created_at": r["created_at"], "updated_at": r["updated_at"],
                "progress": self._progress.get(r["study_id"]),
            }
            for r in rows
        ]

    async def get(self, study_id: str) -> dict[str, Any]:
        row = await self._row(study_id)
        spec = StudySpec.model_validate(json.loads(row["spec"]))
        cells = []
        for c in cells_of(spec):
            cell = await self._cell(study_id, c)
            cells.append({
                "model": c[0], "pronoun": c[1], "frame": c[2], "condition": c[3],
                "prompt": cell.get("prompt"), "top": cell.get("top"),
                "capital_mass": cell.get("capital_mass"), "scores": cell.get("scores"),
                "queries": cell.get("queries", 0),
            })
        return {
            "study_id": study_id, "title": row["title"], "status": row["status"],
            "error": row["error"], "spec": spec.model_dump(), "rules": row["rules"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "progress": self._progress.get(study_id),
            "cells": cells,
        }
