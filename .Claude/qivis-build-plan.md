# Qivis: Build Plan

Detailed breakdown of the architecture document's build phases into discrete, implementable subphases. Each subphase has clear inputs, outputs, blockers, and a definition of done.

**Conventions**: 🔒 = blocker (must be done before next step), 🔀 = can be parallelized with adjacent subphases, ✅ = definition of done.

---

## Phase 0: Foundation (Week 1-2)

_Goal: Talk to Claude through your own tool._

### 0.1 — Project Scaffolding 🔒

Set up the monorepo structure, dependency management, and dev tooling.

**Tasks:**
- Initialize git repo with the file structure from the architecture doc
- Backend: `pyproject.toml` with FastAPI, uvicorn, httpx, aiosqlite, pydantic
- Frontend: Vite + React + TypeScript project via `npm create vite@latest`
- Docker Compose for local dev (backend + frontend, SQLite volume mount)
- `.env.example` with `ANTHROPIC_API_KEY` placeholder
- `providers.yml.example`
- Basic CI: linting (ruff), type checking (pyright), formatting (black)

**Blockers:** None — this is the starting point.

✅ `uvicorn loom.main:app` starts, frontend `npm run dev` serves, both reachable.

### 0.2 — Database + Event Store 🔒

The foundation everything else builds on. Get events flowing and projecting.

**Tasks:**
- SQLite connection manager with WAL mode
- `events` table: `event_id`, `tree_id`, `timestamp`, `device_id`, `user_id`, `event_type`, `payload` (JSON), `sequence_num` (autoincrement)
- `trees` materialized view table: `tree_id`, `title`, `metadata`, `default_model`, `default_provider`, `default_system_prompt`, `default_sampling_params`, `conversation_mode`, `created_at`, `updated_at`, `archived`
- `nodes` materialized view table: `node_id`, `tree_id`, `parent_id`, `role`, `content`, `model`, `provider`, `system_prompt`, `sampling_params`, `mode`, `usage`, `latency_ms`, `finish_reason`, `logprobs`, `context_usage`, `participant_id`, `participant_name`, `created_at`, `archived`
- Event store: `append(event)`, `get_events(tree_id)`, `get_events_since(sequence_num)`
- State projector: listens to new events, updates materialized tables incrementally
- Pydantic models for all event types (`TreeCreated`, `NodeCreated`, etc.)
- Pydantic models for canonical data structures (`SamplingParams`, `LogprobData`, `ContextUsage`)

**Blockers:** 0.1 (project structure must exist).

✅ Can append events, read them back, and query projected state. Unit tests pass for event append → projection round-trip.

### 0.3 — Tree + Node CRUD 🔒

Basic API for creating trees and adding messages. No generation yet — just storing user-written content.

**Tasks:**
- FastAPI router: `POST /api/trees`, `GET /api/trees`, `GET /api/trees/{id}`
- FastAPI router: `POST /api/trees/{id}/nodes` (add a user message with parent_id)
- Tree service: create tree (emits `TreeCreated`), get tree with all nodes
- Node service: create node (emits `NodeCreated` with `role: "user"`, null generation fields)
- Response models: tree with nested node list, individual node detail
- Basic error handling: 404 for missing tree/node, 400 for invalid parent_id

**Blockers:** 0.2 (event store + projected tables must work).

✅ Can create a tree via API, add user messages, retrieve the tree with its messages in order. Postman/curl workflow works.

### 0.4 — Anthropic Provider 🔒

First LLM provider. Just make it generate responses.

**Tasks:**
- `LLMProvider` ABC in `providers/base.py`
- `AnthropicProvider` in `providers/anthropic.py`: implements `generate()` and `generate_stream()`
- Provider registry: loads from `providers.yml`, returns configured providers
- `LogprobNormalizer.from_anthropic()` (even if Anthropic beta logprobs aren't available yet, build the plumbing)
- `LogprobNormalizer.empty()` for graceful fallback
- Generation endpoint: `POST /api/trees/{id}/nodes/{nid}/generate`
  - Reads path from root to `{nid}`
  - Assembles messages array (simple: just role + content for now)
  - Calls Anthropic API
  - Emits `GenerationStarted` + `NodeCreated` events
  - Returns the new node
- SSE streaming endpoint variant (or same endpoint with `Accept: text/event-stream`)

**Blockers:** 0.3 (need tree/node CRUD to have something to generate from).

✅ Can create a tree, add a user message, hit generate, get a Claude response stored as a new node. Streaming works.

### 0.5 — Basic Context Builder 🔒

Assemble the messages array properly — the simplest correct version.

**Tasks:**
- `ContextBuilder.build()` — walks root-to-node path, assembles `[{"role": ..., "content": ...}]`
- System prompt handling: tree default, passed as first system message or via API system parameter
- Boundary-aware safety: if total tokens exceed model limit, truncate from the beginning but never mid-message, always preserve system prompt
- `ContextUsage` computation: count tokens per role, compute total vs. model limit
- Store `context_usage` on `NodeCreated` events
- Wire into the generation endpoint (replace the simple assembly from 0.4)

**Blockers:** 0.4 (need generation working to have something to build context for).

✅ Multi-turn conversations work — context is assembled correctly, token counts are tracked, system prompt is always preserved. A 3+ turn conversation with Claude produces coherent responses.

### 0.6 — Minimal Frontend 🔀

Can be started in parallel with 0.4/0.5 using mocked API responses.

**Tasks:**
- API client module: typed fetch wrappers for all Phase 0 endpoints
- Tree list view: show all trees, create new tree button
- Linear chat view: display messages in order for a selected tree
- Message input: text area + send button, calls `POST /api/trees/{id}/nodes` then `POST .../generate`
- Streaming display: SSE connection for token-by-token rendering
- System prompt input: editable field at the top of the tree
- Basic styling: readable, functional, nothing fancy yet

**Blockers:** 0.3 at minimum for real API integration (can start with mocks earlier).

✅ Can open the app, create a tree, type a message, see Claude's streaming response, continue the conversation. **Phase 0 complete.**

---

## Phase 1: Branching + Provider Selection (Week 3-5)

_Goal: Fork, try different models/prompts, compare._

### 1.1 — Branching Data Model 🔒

Make the tree actually a tree, not just a list.

**Tasks:**
- Node creation now accepts any existing node as `parent_id` (not just the latest)
- Tree state projection correctly builds parent→children relationships
- API: `GET /api/trees/{id}` returns full tree structure (nodes with `children` arrays or adjacency info)
- Path computation: given a node, compute root-to-node path (for context assembly and display)
- Sibling awareness: nodes know their siblings (same parent)

**Blockers:** Phase 0 complete.

✅ Can create a node with any existing node as parent. Tree structure query returns correct topology. Path computation works for any node.

### 1.2 — Branch Navigation UI 🔒

**Tasks:**
- Linear view: add branch indicators where siblings exist (e.g., "← 1/3 →" navigation)
- Clicking a branch indicator switches to that sibling's subtree
- "Fork here" button on any message: creates a new user message as a sibling
- Current path highlighting: clearly show which path through the tree is active
- Breadcrumb or path indicator showing the active branch

**Blockers:** 1.1 (need branching data model).

✅ Can fork at any message, navigate between branches, always know which branch is active.

### 1.3 — Per-Node Generation Overrides 🔀

**Tasks:**
- Generation endpoint accepts optional `model`, `provider`, `system_prompt`, `sampling_params` in request body
- These override the tree defaults for this specific generation
- Store the actual values used (not just "default") on the `NodeCreated` event
- `n > 1` generation: request multiple sibling completions in one call, each gets its own `NodeCreated`
- UI: model/provider selector dropdown in generation controls
- UI: system prompt override field (pre-filled with tree default, editable per generation)

**Blockers:** 1.1 (branching must work for n>1 to make sense).

✅ Can generate 3 different responses from the same point, each potentially with different models. Metadata on each node shows what was actually used.

### 1.4 — OpenAI + OpenRouter Providers 🔀

Can be done in parallel with 1.2/1.3.

**Tasks:**
- `OpenAIProvider`: chat + completion modes, logprob normalization via `LogprobNormalizer.from_openai()`
- `OpenRouterProvider`: similar to OpenAI but with model routing, handles the `HTTP-Referer` header
- Provider registry: auto-discovers configured providers from `providers.yml`
- Health check endpoint: `GET /api/providers` returns status of each configured provider
- UI: provider/model list dynamically populated from `GET /api/providers`

**Blockers:** 0.4 (provider ABC must exist). Independent of 1.1-1.3.

✅ Can switch between Anthropic, OpenAI, and OpenRouter models. Provider health visible in UI.

### 1.5 — Context Usage Bar 🔀

**Tasks:**
- Frontend component: thin bar on each assistant node, color-coded (green/yellow/red)
- Reads `context_usage` from node data
- Click to expand: token breakdown panel (system, user, assistant, tool, excluded, remaining)
- Pre-generation estimate: compute approximate usage for the current path before generating
- Adapt to model context window (different models have different limits)

**Blockers:** 0.5 (context usage must be computed and stored). Independent of 1.1-1.4.

✅ Every assistant message shows context %, clicking shows breakdown. Bar turns yellow/red appropriately. **Phase 1 complete.**

---

## Phase 2: Local Models + Logprobs (Week 6-8)

_Goal: Compare cloud vs. local with uncertainty visualization._

### 2.1 — Ollama + llama.cpp Providers 🔒

**Tasks:**
- `OllamaProvider`: chat + completion, auto-discover models via Ollama API (`/api/tags`)
- `LlamaCppProvider`: completion mode, logprob extraction from `completion_probabilities`
- `GenericOpenAIProvider`: any OpenAI-compatible endpoint (vLLM, LM Studio, text-generation-webui)
- `LogprobNormalizer.from_llamacpp()` — handle full vocabulary distributions
- Provider config: `base_url`, model list (auto-discover where possible)
- Handle provider-specific quirks: Ollama's different streaming format, llama.cpp's token handling

**Blockers:** 1.4 (provider pattern established with OpenAI/OpenRouter).

✅ Can generate from local Ollama and llama.cpp models. Logprobs captured from llama.cpp with full vocab data.

### 2.2 — Completion Mode 🔀

**Tasks:**
- Support `mode: "completion"` in generation requests
- For completion mode: send the full conversation as a single text prompt (not chat messages)
- `prompt_text` stored on `NodeCreated` — the exact string sent
- Provider adapters handle mode switching (some only support one mode)
- `LLMProvider.supports_mode()` used to validate requests

**Blockers:** 2.1 (completion mode is primarily useful for local/base models).

✅ Can send completion-mode requests to base models. Full prompt text stored and viewable.

### 2.3 — Logprob Visualization 🔀

**Tasks:**
- `LogprobOverlay` component: renders token-level heatmap on assistant messages
- Color mapping: `uncertaintyColor(logprob)` function, transparent for high confidence → warm highlight for low
- Hover tooltip: show top-N alternatives with probabilities for any token
- Node-level certainty badge: small indicator showing average/min confidence
- Toggle: researcher can enable/disable the overlay (it's visual noise if you don't need it)
- Graceful degradation: no overlay, no badge, no visual noise when logprobs are null

**Blockers:** LogprobData must be stored on nodes (exists since 0.4). Independent of 2.1/2.2, but richer with local model logprobs.

✅ Token heatmap renders on assistant messages. Hover shows alternatives. Badge shows node confidence. No visual noise when logprobs absent.

### 2.4 — Sampling Parameter Controls 🔀

**Tasks:**
- UI panel: temperature slider, top_p, top_k, max_tokens, frequency/presence penalty
- Per-tree defaults (saved on tree metadata)
- Per-generation overrides (UI shows current values, editable before generating)
- Display actual params used on each node (in node detail view)
- Presets: "deterministic" (temp=0), "creative" (temp=1.0), "balanced" (temp=0.7), custom

**Blockers:** 1.3 (per-node overrides must work). Independent of 2.1-2.3.

✅ Can adjust sampling params per generation. Presets work. Node detail shows what was used. **Phase 2 complete.**

---

## Phase 3: Research Instrumentation (Week 9-11)

_Goal: Annotate, manage context, search, export._

### 3.1 — Annotation System 🔒

**Tasks:**
- `annotations` table: `annotation_id`, `node_id`, `tag`, `value`, `notes`, `created_at`
- API: `POST /api/nodes/{nid}/annotations`, `GET /api/annotations?tag=...`
- Load taxonomy from `annotation_taxonomy.yml`
- API: `GET /api/taxonomy`, `POST /api/taxonomy` (extend at runtime)
- Events: `AnnotationAdded`, `AnnotationRemoved`
- UI: annotation panel on node detail — shows existing annotations, add new ones
- Quick-tag buttons for common tags (coherence scale, basin type radio buttons, boolean toggles)
- Free-form research note field

**Blockers:** Phase 2 complete (or at least 1.x — annotations are independent of logprobs, but the milestone ordering keeps things focused).

✅ Can annotate any node with taxonomy tags or custom tags. Annotations queryable via API. UI lets you annotate without leaving the conversation view.

### 3.2 — Bookmarks + Summaries 🔀

**Tasks:**
- `bookmarks` table: `bookmark_id`, `node_id`, `label`, `notes`, `summary`, `created_at`
- API: `POST /api/nodes/{nid}/bookmarks`, `GET /api/bookmarks`
- UI: bookmark button on any node, bookmark list in sidebar
- `POST /api/bookmarks/{bid}/summarize` — calls Haiku to summarize root→bookmarked node
- Store summary on bookmark (via `BookmarkSummaryGenerated` event)
- Bookmark list shows summaries, making them browsable without re-reading branches

**Blockers:** 3.1 (annotation infrastructure establishes the event patterns). Can start in parallel if comfortable.

✅ Can bookmark nodes, see bookmark list with labels and summaries. Summarize button works.

### 3.3 — Context Exclusion + Digression Groups 🔒

**Tasks:**
- Events: `NodeContextExcluded`, `NodeContextIncluded`, `DigressionGroupCreated`, `DigressionGroupToggled`
- `context_exclusions` table: tracks which nodes are excluded and scope
- `digression_groups` table: group_id, node_ids, label, included status
- Update `ContextBuilder.build()` to filter excluded nodes and toggled-off groups
- API: `POST /api/nodes/{nid}/exclude`, `POST /api/nodes/{nid}/include`
- API: `POST /api/trees/{id}/digression-groups`, `PATCH .../digression-groups/{gid}`
- UI: exclude toggle on each node (with visual indicator for excluded nodes)
- UI: select range of messages → "Create digression group" → label it → toggle in/out
- Context preview: `GET /api/trees/{id}/context-preview/{nid}` shows what the model would see

**Blockers:** 0.5 (context builder must exist). Practically depends on having conversations worth managing.

✅ Can exclude individual nodes, create digression groups, toggle them. Context preview accurately reflects what model will see.

### 3.4 — Smart Eviction 🔒

**Tasks:**
- Implement `ContextBuilder._smart_evict()` per the architecture spec
- Protected ranges: first N turns, last N turns, bookmarked nodes
- Middle-turn eviction: whole messages, oldest first
- Optional summarization of evicted content via Haiku
- `EvictionReport` returned with every generation
- UI: eviction report shown in context usage panel when eviction occurs
- `EvictionStrategy` configurable per tree (stored in tree metadata)
- Warning when approaching threshold (default 85%)

**Blockers:** 3.3 (exclusions must work first — they're "free" eviction that runs before smart eviction). 3.2 (bookmarks must exist for bookmark-aware protection).

✅ Long conversations gracefully handle context limits. Researcher sees exactly what was evicted. Summary insertion works.

### 3.5 — Manual Summarization 🔀

**Tasks:**
- API: `POST /api/trees/{id}/summarize` with body specifying type, nodes, summary_type, custom_prompt
- Branch summary: root → selected node
- Subtree summary: all branches below a node
- Selection summary: arbitrary node selection
- Custom prompt: researcher provides their own summarization instructions
- Events: `SummaryGenerated` stored and searchable
- UI: right-click or menu action on node → "Summarize..." → options dialog

**Blockers:** 3.2 (bookmark summary infrastructure). Can share the same Haiku summarization service.

✅ Can summarize branches, subtrees, selections with various prompts. Summaries stored and findable.

### 3.6 — Export 🔀

**Tasks:**
- `GET /api/trees/{id}/export?format=json` — full tree with all metadata, annotations, bookmarks
- `GET /api/trees/{id}/export?format=csv` — flattened: one row per node with columns for all metadata
- `GET /api/trees/{id}/paths` — enumerate all root-to-leaf paths
- UI: export button on tree view with format selector
- Include logprobs in export (JSON), summary statistics in CSV

**Blockers:** 3.1 (annotations should exist to be exportable). Otherwise independent.

✅ Can export a fully annotated tree as JSON or CSV. Data is complete and analysis-ready.

### 3.7 — Keyword Search + Comparison View 🔀

**Tasks:**
- FTS5 virtual table on node content + system prompts
- API: `GET /api/search?q=keyword` — returns matching nodes with tree context
- Search results UI: list of matching nodes with surrounding context, click to navigate
- Comparison view: `GET /api/trees/{id}/compare?nodes=a,b,c`
- UI: select 2-3 sibling nodes → side-by-side comparison view
- Diff-style highlighting of differences between responses

**Blockers:** 3.1 (annotation search is part of this). FTS5 setup is independent.

✅ Can search across all conversations by keyword. Can compare sibling responses side-by-side. **Phase 3 complete.**

---

## Phase 4: Multi-Agent (Week 12-15)

_Goal: Run model-to-model conversations AnimaChat-style._

### 4.1 — Participant Management 🔒

**Tasks:**
- API: `POST /api/trees/{id}/participants`, `DELETE .../participants/{pid}`
- Store participants on tree (via `TreeMetadataUpdated` or dedicated event)
- Participant: just model + provider + system prompt + sampling params
- Tree creation can specify `conversation_mode: "multi_agent"` with initial participants
- UI: participant configuration panel — add/remove participants, edit their system prompts
- Display: participant names and colors on messages

**Blockers:** Phase 3 complete (or at least 1.x). Multi-agent builds on the existing generation and context infrastructure.

✅ Can create a multi-agent tree with 2+ participants. Participants visible in UI with distinct visual identity.

### 4.2 — Per-Participant Context Assembly 🔒

**Tasks:**
- Update `ContextBuilder` to handle `participant` parameter:
  - Own messages as `role: "assistant"`
  - Others' messages as `role: "user"` with `[Name]: ` prefix
  - Researcher notes filtered by `visible_to`
- Context usage computed per-participant (different models have different windows)
- `visible_to` field on `NodeCreated` for researcher notes with selective visibility

**Blockers:** 4.1 (participants must exist).

✅ Each participant sees the conversation from its own perspective. Selective visibility works. Context usage accurate per participant.

### 4.3 — Directed Generation + Researcher Injection 🔒

**Tasks:**
- `POST /api/trees/{id}/nodes/{nid}/generate` with `participant_id` — specifies who responds
- `POST /api/trees/{id}/multi/inject` — researcher injects a message with `visible_to` control
- `ConversationRunner.generate_from()`: generate from a specific participant
- `ConversationRunner.researcher_inject()`: add researcher note with visibility
- UI: "Who responds?" selector before generating — dropdown of participants
- UI: inject button with visibility checkboxes (which participants see this?)

**Blockers:** 4.2 (context must be correct per-participant).

✅ Can direct any participant to respond at any point. Can inject researcher messages visible to all or specific participants.

### 4.4 — Auto-Run + Turn Controls 🔀

**Tasks:**
- `POST /api/trees/{id}/multi/run` — run N turns automatically
- Turn order: specified list of participant IDs, or round-robin
- SSE stream: emits events as each turn completes (for live UI updates)
- Auto-pause: configurable conditions (N turns, or manual stop)
- UI: "Run N turns" button with turn order configuration
- UI: live update as turns come in, stop button to halt

**Blockers:** 4.3 (single-turn directed generation must work first).

✅ Can auto-run conversations between models. Live streaming UI. Stop button works.

### 4.5 — Multi-Agent UI Polish 🔀

**Tasks:**
- Distinct visual identity per participant (color, avatar/icon, name badge)
- Multi-agent tree view: messages attributed to participants with visual differentiation
- Participant panel: shows all participants, their models, current turn
- Context usage bars per-participant
- Fork from any point in a multi-agent conversation: branch with different participant responding

**Blockers:** 4.3/4.4 (core functionality must work).

✅ Multi-agent conversations are visually clear, easy to follow, easy to control. **Phase 4 complete.**

---

## Phase 5: Search + Analysis (Week 16-18)

_Goal: AI-assisted corpus analysis._

### 5.1 — Semantic Embedding Index 🔒

**Tasks:**
- Install sentence-transformers, download `all-MiniLM-L6-v2`
- `embeddings` table: `node_id`, `embedding` (binary blob)
- Embed all existing nodes on first run (batch job)
- Embed new nodes incrementally as they're created
- hnswlib index: build from embeddings, persist to disk, rebuild on startup
- Configurable embedding model in `config.py`

**Blockers:** Phase 4 complete (or at least Phase 3 — need a corpus worth searching).

✅ All nodes have embeddings. Index loads on startup. Embedding happens automatically for new nodes.

### 5.2 — Hybrid Search 🔒

**Tasks:**
- `SearchService.embedding_search()`: query → embed → hnswlib nearest neighbors
- `SearchService.hybrid_merge()`: combine FTS5 and embedding results with configurable weighting
- `SearchQuery` with `semantic: bool` flag
- API: `GET /api/search?q=...&semantic=true` for semantic search
- API: `POST /api/search` for complex structured queries (tags + text + semantic + filters)
- `agent_search()` convenience method: always semantic, higher limit

**Blockers:** 5.1 (embeddings must exist). 3.7 (FTS5 must exist for hybrid).

✅ Keyword search, semantic search, and hybrid search all work. Structured queries with tag/model/date filters work.

### 5.3 — Analysis Skills 🔀

**Tasks:**
- `AnalysisSkill` ABC: `name`, `analyze(nodes) -> AnalysisResult`
- `LinguisticMarkerSkill`: detect hedging, denial scripts, defensive language patterns
- `CoherenceScoreSkill`: estimate internal coherence (heuristic or LLM-based)
- `LogprobAnalysisSkill`: uncertainty pattern detection, entropy analysis
- Skill registry: discover built-in + plugin skills from `skills/` directory
- API: `POST /api/skills/{name}/run` with node selection
- UI: skill runner panel — select nodes, pick skill, see results
- Results stored as annotations (connecting skills to the annotation system)

**Blockers:** 3.1 (annotation system for storing results). Independent of 5.1/5.2.

✅ Built-in skills produce useful analysis. Plugin skills loadable from directory.

### 5.4 — Search UI 🔀

**Tasks:**
- Search bar in sidebar: keyword, semantic toggle, filters
- Search results: node excerpts with context, highlighting, click-to-navigate
- Advanced search: tag filters, model filters, date range, tree scope
- "Similar nodes" feature: click any node → find semantically similar across corpus

**Blockers:** 5.2 (hybrid search must work).

✅ Researcher can find anything across their entire corpus. **Phase 5 complete.**

---

## Phase 6: MCP + Ecosystem (Week 19+)

_Goal: Community-deployable research tool._

### 6.1 — MCP Client 🔒

**Tasks:**
- Integrate Python MCP SDK
- Load MCP server configs from `mcp_servers.yml`
- Connect to configured servers, discover available tools
- Wire tools into generation: model can call tools, results stored as `role: "tool"` nodes
- API: `GET /api/mcp/servers`, `GET /api/mcp/servers/{name}/tools`
- UI: MCP server status, tool availability per generation

**Blockers:** Phase 5 complete. MCP client is a significant feature that builds on stable generation infrastructure.

✅ Models can use external tools during generation. Tool calls and results visible in tree.

### 6.2 — MCP Server 🔀

**Tasks:**
- Expose Qivis as an MCP server via the Python SDK
- Tools: `search_conversations`, `get_tree`, `get_node_context`, `get_annotations`, `add_annotation`
- External LLM agents can query and annotate the research corpus
- Configuration: which tools to expose, authentication

**Blockers:** 5.2 (search must work for `search_conversations`). Can parallel with 6.1.

✅ External agents can search and annotate the Qivis corpus via MCP.

### 6.3 — Garbage Collection 🔀

**Tasks:**
- `POST /api/maintenance/gc` — the big red button
- Reference checker: find archived items with zero live references (no non-archived children, bookmarks, or annotations)
- `GET /api/maintenance/gc/preview` — show what would be deleted, require confirmation
- Grace period: `GarbageCollected` event records deletions with `recoverable_until`
- `POST /api/maintenance/gc/purge` — purge items past grace period
- UI: maintenance panel with preview, confirm, and purge controls

**Blockers:** 3.1/3.2 (annotations and bookmarks must exist for reference checking).

✅ Can safely GC orphaned content. Preview shows exactly what would go. Grace period works.

### 6.4 — Conversation Import 🔀

**Tasks:**
- Survey export formats: Claude.ai JSON, ChatGPT export, AnimaChat transcripts
- Importer for each format: parse → emit `TreeCreated` + `NodeCreated` events
- API: `POST /api/import` with file upload
- Handle format quirks: ChatGPT's conversation structure, Claude.ai's format, etc.
- UI: import wizard with format selection and preview

**Blockers:** 0.2 (event store). Practically independent of everything else.

✅ Can import conversations from major platforms. Imported trees are indistinguishable from native ones.

### 6.5 — Multi-Device Sync 🔀

**Tasks:**
- Sync protocol: exchange events between instances
- Conflict resolution: evaluate whether timestamps + UUIDs suffice or hybrid logical clocks are needed (tree structure resolves most conflicts naturally)
- Sync API: push/pull event ranges
- Offline support: queue events locally, sync when connected

**Blockers:** All of the above. This is the last piece.

✅ Two instances can sync their event logs and converge to the same state.

### 6.6 — Deployment + Documentation 🔀

**Tasks:**
- Docker image: single `docker-compose up` for the full stack
- Deployment guide: local, cloud (single instance), multi-user (Postgres migration)
- Provider setup guides: Anthropic, OpenAI, Ollama, llama.cpp
- Research workflow guide: how to use Qivis for AI personality research
- API documentation: auto-generated from FastAPI + manual examples
- Plugin development guide: writing custom analysis skills

**Blockers:** Nothing technical — but should reflect the actual state of the tool.

✅ A new researcher can go from zero to running Qivis with one page of instructions. **Phase 6 complete. Qivis is a community-deployable research tool.**

---

## Dependency Graph (Summary)

```
0.1 → 0.2 → 0.3 → 0.4 → 0.5 → 0.6    (Phase 0: strictly sequential)
                                  ↓
            1.4 ─────────────┐   1.1 → 1.2    (Phase 1: 1.4 parallel, 1.5 parallel)
                             ↓    ↓      ↓
                           1.3 ←──┘    1.5
                             ↓
                     2.1 → 2.2         (Phase 2: 2.3 and 2.4 can parallel)
                      ↓
                     2.3   2.4
                      ↓
         3.1 → 3.2 → 3.4              (Phase 3: 3.4 needs 3.2+3.3)
          ↓     ↓      ↑
         3.6   3.5   3.3              3.7 parallel after 3.1
          ↓
         4.1 → 4.2 → 4.3 → 4.4      (Phase 4: mostly sequential)
                              ↓
                             4.5
                              ↓
         5.1 → 5.2 → 5.4             (Phase 5: 5.3 parallel)
                ↓
               5.3
                ↓
     6.1  6.2  6.3  6.4  6.5  6.6    (Phase 6: mostly parallel)
```

---

## Deferred Items

Items identified during implementation that aren't yet assigned to a specific subphase. These should be folded into future phases or become their own subphases as the plan evolves.

### UI Enhancements (no backend changes needed)

- **Message timestamps**: Display `created_at` on each message in the conversation view. Include a toggle (tree-level or global setting) for whether timestamps are included in the context sent to the model (i.e., prepended to message content or added as metadata). _Likely fits in a Phase 1 or Phase 2 UI polish pass._

- **Light/dark mode toggle**: Manual toggle in the UI instead of relying solely on `prefers-color-scheme`. Useful when testing/researching across themes without changing system defaults. _Small standalone task, can be done anytime._

### Tree Settings (backend + frontend)

- **Tree settings panel / default provider editing**: Allow editing a tree's default provider, model, and system prompt after creation. Currently the only way to set a tree's default provider is at creation time (and even then there's no UI for it), so every tree starts defaulting to the backend fallback (anthropic). A tree settings panel (or inline editing in the sidebar/header) would let researchers configure the default provider/model per tree. _Backend: needs a `PATCH /api/trees/{tree_id}` endpoint (or TreeUpdated event). Frontend: settings UI, wired into the tree detail view._

### Generation UX (frontend + minor backend)

- **Model attribution on messages**: Show which provider/model generated each assistant message. The data already exists on every node (`model`, `provider` fields). Display as subtle metadata below or beside the message content. _Small frontend task, no backend changes needed._

- **Branch-local model default**: Follow-up messages in a branch should default to the most recently used provider/model in that branch, not just the tree default. When a researcher switches to GPT-4o mid-conversation, subsequent messages should keep using it until they switch again. _Requires walking the active path to find the last assistant node's provider/model and passing those as defaults to sendMessage and ForkPanel._

- **Generation error recovery**: When generation fails (API error, missing credits, network issue), the UI should preserve the failed attempt with: the error message, a retry button, and the ability to change parameters (provider, model, etc.) before retrying. Currently, errors clear the streaming state and show a toast, losing the generation context. _Moderate frontend work — needs a new "failed generation" UI state alongside streaming/complete._

### Context Transparency (needs some backend + frontend work)

- **Context diff indicator**: A colored badge/indicator on assistant messages where the actual generation context differed from what a researcher would expect by reading the tree. Differences to flag:
  - System prompt override (different from tree default)
  - Different provider or model from tree default
  - Excluded nodes / non-default context assembly
  - Different sampling parameters

  Clicking the indicator shows a diff view (nice UI, not raw JSON) between "what the tree path looks like" vs "what was actually sent to the model." _The per-node data already exists (`system_prompt`, `model`, `provider`, `sampling_params`, `context_usage` are all stored on every assistant node). This is primarily a frontend feature with tree-default comparison logic. Likely fits in Phase 2 or Phase 3 alongside the context exclusion work (3.3)._

---

## Notes for Claude Code Handoff

When handing this plan to Claude Code:

1. **One subphase at a time.** Say "Implement 0.1" not "Build Phase 0."
2. **Definition of done matters.** Each ✅ is the acceptance criteria. Don't move on until it passes.
3. **The architecture doc is the source of truth** for data structures, event types, and API shapes. This plan is the *order* to build them in.
4. **Tests as you go.** Each subphase should have tests before moving to the next, especially the event store (0.2) and context builder (0.5/3.3/3.4) — these are load-bearing.
5. **Frontend can lag.** It's OK if the frontend is a phase behind the backend. The API is the real interface; the UI catches up.
