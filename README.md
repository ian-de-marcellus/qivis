# Qivis

A research instrument for studying AI conversational behavior. Qivis treats conversations as branching trees rather than linear threads, giving researchers tools to fork, compare, intervene, and measure at every point in a conversation's history.

The goal is to see the shape of the model itself. A generated response always reads as certain — every sentence, once written, looks like it was inevitable. But underneath the text is a probability landscape: places where the model was confident, places where it hesitated, places where a different word would have sent the conversation down an entirely different path. Qivis makes that landscape visible. The logprob heatmap is a shadow of the model's uncertainty projected onto the surface of its output; the branching tree maps everywhere the researcher went and everywhere they didn't; the comparison view reveals what's missing from one response by holding it next to another. The interesting moments aren't the confident assertions — they're the hesitations, the near-misses, the places where the model's inner landscape was uncertain and the text doesn't show it.

Developed as a collaboration between Ian de Marcellus and Claude Opus 4.6.

## What it does

**Branching conversation trees.** Every message is a node in a tree. Fork at any point to try a different prompt, model, or set of parameters. Navigate between branches freely. The tree is the fundamental data structure, not an afterthought bolted onto linear chat.

**Provider-agnostic generation.** Anthropic, OpenAI, OpenRouter, Ollama, any OpenAI-compatible server, and llama.cpp's native completion API. Switch providers mid-conversation. Compare how different models handle the same context.

**Token-level uncertainty visualization.** When a model generates a response, Qivis captures the probability distribution over tokens — how confident the model was at each word, and what it almost said instead. With local models via llama.cpp, this extends to full-vocabulary distributions: not just the top 5 alternatives, but the model's confidence across every token in its vocabulary. The logprob overlay renders this as a heatmap directly on the text.

**Context transparency.** See exactly what the model saw when it generated each response — the full prompt as assembled, with edits, evictions, and augmentations visible. A split view shows the researcher's truth on one side and the model's received context on the other. Diff badges on each response summarize what changed.

**Research interventions.** Edit any message after the fact and regenerate downstream. Exclude messages or groups of messages from context and observe the effect. Supply the first words of a response (prefill) and let the model continue. Run the same conversation through multiple models. The 2D canvas view shows the full intervention history as a grid of eras.

**Annotation and analysis.** Tag nodes with a configurable taxonomy (coherence scales, behavioral markers, basin types). Add free-form research notes. Bookmark significant moments with auto-generated summaries. Search across the entire corpus with full-text search.

**Conversation import and organization.** Import from ChatGPT (with full branch structure preserved), ShareGPT, or generic formats. Merge new messages into existing trees. Organize trees into hierarchical folders and tags. Full-screen library view with drag-and-drop.

**Completion mode.** For base models and local inference, Qivis renders conversations as text prompts using configurable templates (ChatML, Alpaca, Llama 3) and sends them to completion endpoints. The exact prompt string is stored alongside each response for debugging and reproducibility.

## Architecture

Event-sourced with CQRS. Every mutation — creating a node, editing content, adding an annotation, toggling an exclusion — is an immutable event in an append-only log. The current state is a projection derived from replaying those events. This means the full history of every research intervention is preserved and auditable.

- **Backend**: Python 3.14, FastAPI, SQLite (WAL mode + FTS5 for search)
- **Frontend**: React 19, TypeScript, Vite, Zustand
- **Communication**: REST + Server-Sent Events for streaming

## Status

Active development, thoroughly tested. Phases 0 through 8 complete (foundation, branching, provider selection, uncertainty visualization, thinking tokens, sampling controls, graph view, side-by-side comparison, message editing, context transparency, annotations, bookmarks, notes, context exclusion, smart eviction, export, full-text search, conversation import, tree merge, summarization, tree organization, prefill mode, local providers, completion mode, full-vocab logprobs).

## Setup

### Backend

```bash
cd backend
uv sync
uv run uvicorn qivis.main:app --reload
```

Configure providers in `backend/.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
OPENROUTER_API_KEY=sk-or-...
OLLAMA_BASE_URL=http://localhost:11434
LLAMACPP_BASE_URL=http://localhost:8080
GENERIC_OPENAI_BASE_URL=http://localhost:5000
GENERIC_OPENAI_API_KEY=...
GENERIC_OPENAI_NAME=my-server
```

Only configure the providers you have. The app registers whatever is present.

### Frontend

```bash
cd frontend
pnpm install
pnpm dev
```

### Tests

```bash
cd backend
uv run pytest tests/ -v
```

## License

MIT
