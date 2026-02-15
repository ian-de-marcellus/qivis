# Qivis

Open-source research instrument for exploring AI personality, emotion, and behavior through branching conversation trees.

## Status

Early development — Phase 0 (Foundation).

## Setup

### Backend

```bash
cd backend
uv sync
uv run uvicorn qivis.main:app --reload
```

### Frontend

```bash
cd frontend
pnpm install
pnpm dev
```

## License

MIT
