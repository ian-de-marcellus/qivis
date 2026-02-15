# Qivis

## Project Overview
Qivis is an open-source research instrument for exploring AI personality, emotion, and behavior through branching conversation trees. Event-sourced architecture with CQRS pattern.

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
- Test-first: contract tests → integration tests → implement → cleanup → full regression
- Tests encode promises from the architecture doc (.Claude/qivis-architecture.md)
- Never modify tests to make them pass without flagging and confirming
- One subphase at a time from the build plan (.Claude/qivis-build-plan.md)

## Project Structure
- `.Claude/` — architecture docs, build plan, dev workflow, scratchpad/notes
- `backend/` — Python/FastAPI backend (package: `qivis`)
- `frontend/` — React/TypeScript frontend
- `tests/` — organized by phase (phase0/, phase1/, etc.)

## Conventions
- All references to "loom" in architecture docs should be read as "qivis"
- User preferences: no emojis in code, modern tooling (uv, pnpm), latest Python
