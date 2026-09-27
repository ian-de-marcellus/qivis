# Qivis

## Project Overview
Qivis is an open-source research instrument for exploring AI personality, emotion, and behavior through branching conversation rhizomes. Event-sourced architecture with CQRS pattern.

## Tech Stack
- **Backend**: Python 3.14 + FastAPI + SQLite (WAL + FTS5)
- **Frontend**: React + TypeScript + Vite
- **Python tooling**: uv (package manager, venv, lockfile)
- **Frontend tooling**: pnpm
- **Communication**: REST + SSE

## Key Architecture Decisions
- Package name is `qivis` (not "loom" — that was a working name)
- Event sourcing: all mutations are immutable events; materialized tables are read projections
- Provider-agnostic: each LLM provider normalizes to canonical data structures (LogprobData, etc.)
- Tree-native: conversation tree is the fundamental unit, not linear chat

## Development Workflow
- Verify against the real system (live models, real data, the UI in a browser), then write tests; tests are a safety net, not a ritual
- Tests encode promises from the architecture doc (.Claude/qivis-architecture.md)
- Never modify tests to make them pass without flagging it
- The record doesn't lie: Qivis must never misrepresent what a model saw or said (context, provenance, what's the model's vs the researcher's)
- Build plan (.Claude/qivis-build-plan.md) is a map, not a mandate; build features around questions Ian actually has
- Test changes without touching Ian's data: run a scratch backend from another directory (the DB path is relative), e.g. on port 8001, and a scratch frontend with `QIVIS_API=http://localhost:8001 pnpm exec vite --port 5174`
- Early-2026 workflow docs and notes are in .Claude/archive/

## Project Structure
- `.Claude/` — architecture docs, build plan, archive/
- `backend/` — Python/FastAPI backend (package: `qivis`)
- `frontend/` — React/TypeScript frontend
- `backend/tests/` — organized by phase (phase0/, phase1/, etc.) plus interlude/, guest/, tools/; frontend tests sit beside their modules (`*.test.ts`)

## Conventions
- All references to "loom" in architecture docs should be read as "qivis"
- Domain concept is "rhizome" (not "tree"); "tree" refers only to the data structure
- User preferences: no emojis in code, modern tooling (uv, pnpm), latest Python
