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
from qivis.names import discover as discovery
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


class DiscoverySpec(BaseModel):
    title: str
    model: str
    pronoun: str
    # The description (and its control, and its "it" version) come from this study;
    # the failure modes from these (their descriptions for the same pronoun)
    study_id: str
    failure_study_ids: list[str] = Field(default_factory=list)
    weights: dict[str, float] = Field(
        default_factory=lambda: {"ai": 1.0, "gender": 1.0, "character": 1.0},
    )
    beam: int = Field(default=40, ge=1, le=400)
    depth: int = Field(default=4, ge=1, le=8)
    alpha: float = Field(default=0.01, gt=0, le=1)
    top: int = Field(default=60, ge=1, le=500)


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

    async def create(self, spec: StudySpec, start: bool = True) -> dict[str, Any]:
        """A new study; it runs now, or waits ("queued") until resumed."""
        for pronoun in spec.pronouns:
            if pronoun not in spec.descriptions or not spec.frames.get(pronoun):
                raise InvalidRequestError(f"Pronoun set '{pronoun}' needs a description and frames")
        study_id = f"study-{uuid4()}"
        await self._events.emit(study_id, "NameStudyCreated", {
            "study_id": study_id, "title": spec.title, "spec": spec.model_dump(),
            "rules": engine.__doc__ or "",
        })
        if start:
            self.start(study_id)
        else:
            await self._status(study_id, "queued")
        return await self.get(study_id)

    def start(self, study_id: str) -> None:
        if study_id in self._tasks and not self._tasks[study_id].done():
            return
        self._tasks[study_id] = asyncio.create_task(self._run(study_id))

    async def extend(
        self,
        study_id: str,
        pronouns: list[str],
        descriptions: dict[str, str],
        frames: dict[str, list[str]],
        names: list[str] | None = None,
    ) -> dict[str, Any]:
        """Add pronoun sets and names to score; the study goes on to fill in the
        cells they add, and to score every new name in every cell."""
        spec = StudySpec.model_validate(json.loads((await self._row(study_id))["spec"]))
        new = [p for p in pronouns if p not in spec.pronouns]
        cleaned = [n.strip() for n in names or [] if n.strip()]
        new_names = [n for n in dict.fromkeys(cleaned) if n not in spec.extra_names]
        if not new and not new_names:
            raise InvalidRequestError("Nothing new to add to the study")
        for pronoun in new:
            if pronoun not in descriptions or not frames.get(pronoun):
                raise InvalidRequestError(f"Pronoun set '{pronoun}' needs a description and frames")
        task = self._tasks.get(study_id)
        if task and not task.done():
            raise InvalidRequestError("Stop the study (or let it finish) before extending it")
        await self._events.emit(study_id, "NameStudyExtended", {
            "study_id": study_id, "pronouns": new,
            "descriptions": {p: descriptions[p] for p in new},
            "frames": {p: frames[p] for p in new},
            "extra_names": new_names,
        })
        status = (await self._row(study_id))["status"]
        if status == "queued":
            return await self.get(study_id)  # it'll score them when it runs
        return await self.resume(study_id)

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

        # 4. Each name's first token in every cell, to split its lean from its
        # first token's (" Mind" + "y": Mindy's lean may be all Mind's)
        spellings: dict[str, list[dict]] = {}
        for name in sorted(names):
            spellings[name] = await llama.tokenize(" " + name, model)
        for i, c in enumerate(mine):
            self._progress[study_id] = {
                "model": model, "phase": "first tokens", "done": i, "of": len(mine),
            }
            cell = await self._cell(study_id, c)
            if set(names) <= set(cell.get("firsts") or {}):
                continue
            dist = await self._fetcher(llama, model, prompt_of(c))([])
            probs = {d["id"]: d["prob"] for d in dist}
            firsts = dict(cell.get("firsts") or {})
            for name, tokens in spellings.items():
                if tokens:
                    firsts[name] = {
                        "p": probs.get(tokens[0]["id"], 0.0),
                        "t": tokens[0]["token"], "n": len(tokens),
                    }
            await self._record(study_id, "NameStudyCellFirsts", c, prompt_of(c), {
                "firsts": firsts, "queries": 1,
            })

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

    # -- Excluded names --

    async def excluded_names(self) -> list[str]:
        row = await self._db.fetchone("SELECT value FROM app_settings WHERE key = 'excluded_names'")
        return json.loads(row["value"]) if row else []

    async def set_excluded_names(self, names: list[str]) -> list[str]:
        clean = list(dict.fromkeys(n.strip() for n in names if n.strip()))
        await self._events.emit("settings", "ExcludedNamesSet", {"names": clean})
        return clean

    # -- Discovery --

    async def create_discovery(self, spec: DiscoverySpec) -> dict[str, Any]:
        llama = get_provider("llamacpp")
        if not isinstance(llama, LlamaCppProvider):
            raise InvalidRequestError("Discovery needs a llama.cpp model")
        study = StudySpec.model_validate(json.loads((await self._row(spec.study_id))["spec"]))
        failures = [
            StudySpec.model_validate(json.loads((await self._row(f))["spec"]))
            for f in spec.failure_study_ids
        ]
        p = spec.pronoun
        if p not in study.pronouns:
            raise InvalidRequestError(f"The study has no '{p}' pronoun set")
        frames = study.frames[p]
        start = await llama.document_start(spec.model)

        def texts(s: StudySpec, pronoun: str, condition: str) -> list[str]:
            fs = s.frames[pronoun][: len(frames)]
            if len(fs) < len(frames):
                raise InvalidRequestError(f"'{s.title}' has too few '{pronoun}' frames")
            return [start + study_text(s, pronoun, f, condition) for f in fs]

        use_it = p != "it" and "it" in study.pronouns and spec.weights.get("gender", 0) != 0
        for f in failures:
            if p not in f.pronouns:
                raise InvalidRequestError(f"'{f.title}' has no '{p}' pronoun set")
        prompts = {
            "description": texts(study, p, "model"),
            "control": texts(study, p, "control"),
            "it": texts(study, "it", "model") if use_it else None,
            "failures": [texts(f, p, "model") for f in failures],
            "failure_titles": [f.title for f in failures],
        }
        discovery_id = f"discovery-{uuid4()}"
        await self._events.emit(discovery_id, "NameDiscoveryCreated", {
            "discovery_id": discovery_id, "title": spec.title,
            "spec": spec.model_dump(), "prompts": prompts,
        })
        self._tasks[discovery_id] = asyncio.create_task(self._run_discovery(discovery_id))
        return await self.get_discovery(discovery_id)

    async def _run_discovery(self, discovery_id: str) -> None:
        row = await self._discovery_row(discovery_id)
        spec = DiscoverySpec.model_validate(json.loads(row["spec"]))
        prompts = json.loads(row["prompts"])
        roles = discovery.Roles(
            description=prompts["description"], control=prompts["control"],
            it=prompts["it"], failures=prompts["failures"],
        )
        weights = discovery.Weights(**spec.weights)
        llama = get_provider("llamacpp")
        assert isinstance(llama, LlamaCppProvider)
        queries = 0

        async def fetch(prompt: str, ids: list[int]) -> list[dict]:
            nonlocal queries
            queries += 1
            request = GenerationRequest(
                model=spec.model, messages=[], prompt_text=prompt,
                sampling_params=SamplingParams(),
            )
            return (await llama.next_tokens(request, ids, LOOKUP_K))["candidates"]

        def progress(done: int, of: int) -> None:
            self._progress[discovery_id] = {
                "model": spec.model, "phase": "searching", "done": done, "of": of,
            }

        try:
            found = await discovery.discover(
                fetch, roles, weights, beam=spec.beam, depth=spec.depth,
                alpha=spec.alpha, top=spec.top, progress=progress,
                excluded=set(await self.excluded_names()),
            )
            results = [
                {"name": f.name, "score": f.score, **discovery.terms(roles, f.logs)}
                for f in found
            ]
            await self._events.emit(discovery_id, "NameDiscoveryFinished", {
                "discovery_id": discovery_id, "status": "done", "results": results,
                "queries": queries,
            })
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Name discovery %s failed", discovery_id)
            await self._events.emit(discovery_id, "NameDiscoveryFinished", {
                "discovery_id": discovery_id, "status": "failed",
                "error": str(e) or type(e).__name__, "queries": queries,
            })
        finally:
            self._progress.pop(discovery_id, None)

    async def _discovery_row(self, discovery_id: str) -> dict:
        row = await self._db.fetchone(
            "SELECT * FROM name_discoveries WHERE discovery_id = ?", (discovery_id,),
        )
        if row is None:
            raise NotFoundError(f"Name discovery not found: {discovery_id}")
        return dict(row)

    async def list_discoveries(self) -> list[dict[str, Any]]:
        rows = await self._db.fetchall(
            "SELECT discovery_id FROM name_discoveries ORDER BY created_at DESC",
        )
        return [await self.get_discovery(r["discovery_id"]) for r in rows]

    async def get_discovery(self, discovery_id: str) -> dict[str, Any]:
        row = await self._discovery_row(discovery_id)
        return {
            "discovery_id": discovery_id, "title": row["title"], "status": row["status"],
            "spec": json.loads(row["spec"]), "prompts": json.loads(row["prompts"]),
            "results": json.loads(row["results"]) if row["results"] else None,
            "error": row["error"], "queries": row["queries"],
            "created_at": row["created_at"], "progress": self._progress.get(discovery_id),
        }

    async def resume_unfinished_discoveries(self) -> None:
        """Discoveries cut off by a restart start over (they keep no partial state)."""
        rows = await self._db.fetchall(
            "SELECT discovery_id FROM name_discoveries WHERE status = 'running'",
        )
        for row in rows:
            did = row["discovery_id"]
            self._tasks[did] = asyncio.create_task(self._run_discovery(did))

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
        cell["firsts"] = json.loads(cell["firsts"]) if cell.get("firsts") else None
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
                "firsts": cell.get("firsts"), "queries": cell.get("queries", 0),
            })
        return {
            "study_id": study_id, "title": row["title"], "status": row["status"],
            "error": row["error"], "spec": spec.model_dump(), "rules": row["rules"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "progress": self._progress.get(study_id),
            "cells": cells,
        }
