# Qivis: Build Plan

Detailed breakdown of the architecture document's build phases into discrete, implementable subphases. Each subphase has clear inputs, outputs, blockers, and a definition of done.

**Conventions**: 🔒 = blocker (must be done before next step), 🔀 = can be parallelized with adjacent subphases, ✅ = definition of done.

---

## Completed Phases

### Phase 0: Foundation ✅

_Goal: Talk to Claude through your own tool._

All subphases (0.1–0.6) complete. Event sourcing with CQRS, SQLite/WAL, tree/node CRUD, Anthropic provider with streaming, basic context builder with boundary-safe truncation, minimal React frontend with Zustand state management. 115 tests at completion.

**What was built:**
- Event store (append-only, sequence numbers, JSON payloads)
- State projector (incremental materialization of events into trees/nodes tables)
- Pydantic models for all event types and canonical data structures
- FastAPI routes: tree CRUD, node creation, generation with SSE streaming
- `AnthropicProvider` implementing `LLMProvider` ABC
- `ContextBuilder.build()` with boundary-safe truncation and `ContextUsage` tracking
- React frontend: tree list, linear chat view, message input, system prompt input, streaming display

### Phase 1: Branching + Provider Selection ✅

_Goal: Fork, try different models/prompts, compare._

Sibling metadata (sibling_count/sibling_index), branch navigation UI with fork/regenerate, per-node generation overrides (provider, model, system prompt, temperature), context usage bar with token breakdown, OpenAI + OpenRouter providers (`OpenAICompatibleProvider` base class), provider selection UI (dropdown + datalist for models). 164 tests at completion.

**What was built:**
- Sibling awareness: nodes know their position among siblings
- Branch navigation: `branchSelections` map preserving position at every fork independently
- Fork panel on user messages: creates alternative sibling + generates with configurable params
- Regenerate on assistant messages: re-generates with different provider/model/system prompt/temperature
- Context usage bar: color-coded (green/yellow/red) with expandable token breakdown
- `OpenAIProvider` and `OpenRouterProvider` with `LogprobNormalizer.from_openai()`
- `GET /api/providers` endpoint with auto-discovery from environment variables
- Provider dropdown + model datalist in fork/regen panel

**Deviations from original plan:** Context usage bar implemented alongside branch navigation (not separate). n>1 generation deferred. Provider selection UI added as 1.5 (not in original plan).

### Phase 1b: Frontend Aesthetic Overhaul ✅

_Goal: The conversation as published text._

Editorial/typographic redesign. Newsreader (display), Source Serif 4 (body), DM Sans (UI), JetBrains Mono (code). Warm paper/ink palette with sienna/copper accents, system-adaptive light/dark via `prefers-color-scheme`. No chat bubbles — messages are typographic units with role labels. Breathing streaming cursor. Collapsible sidebar. Model attribution on assistant messages. 164 tests (no backend changes).

---

## Phase 2: Essentials

_Goal: Make the existing tool properly usable._

The gaps identified during Phase 1 manual testing. Small phase, focused on filling holes before building new features.

### 2.1 — Tree Settings 🔒

Allow editing a tree's defaults after creation.

**Tasks:**
- `PATCH /api/trees/{id}` endpoint accepting partial updates (default_provider, default_model, default_system_prompt, default_sampling_params, title)
- `TreeMetadataUpdated` events for each changed field (preserving old/new values)
- Projector handler for `TreeMetadataUpdated`
- Settings panel UI — accessible from tree header or sidebar, edits default provider/model/system prompt
- Wire provider dropdown + model datalist (reuse from ForkPanel) into settings panel

**Blockers:** Phase 1 complete.

✅ Can change a tree's default provider, model, and system prompt after creation. Changes reflected in subsequent generations.

### 2.2 — Generation UX 🔒

Error recovery, smarter defaults, batch generation.

**Tasks:**
- **Error recovery**: When generation fails, preserve the failed attempt as a UI state with: error message text, retry button, ability to change provider/model/params before retry. Currently errors vanish into a toast.
- **Branch-local model default**: Walk the active path to find the last assistant node's provider/model. Use those as defaults for the next generation and in ForkPanel, falling back to tree defaults. Researcher switches to GPT-4o mid-branch, subsequent messages keep using it.
- **n>1 generation**: Backend `n` parameter on generate endpoint, fan-out to create multiple sibling `NodeCreated` events. Frontend UI to request N completions. Sibling navigator already handles display. Originally scoped for Phase 1.3.

**Blockers:** 2.1 (tree settings must work for defaults to make sense).

✅ Failed generations show error with retry. Branch defaults follow the most recent model. Can generate 3+ responses from the same point in one action.

### 2.3 — Small Polish 🔀

Standalone improvements that don't depend on each other.

**Tasks:**
- **Message timestamps**: Display `created_at` on each message. Include a toggle (tree-level setting) for whether timestamps are prepended to message content in the context sent to the model.
- **Light/dark mode toggle**: Manual override in the UI (light / dark / system). Persisted in localStorage. Overrides `prefers-color-scheme` when set.

**Blockers:** None — can be done alongside 2.1 or 2.2.

✅ Timestamps visible. Theme manually switchable. **Phase 2 complete.**

---

## Phase 3: Seeing Uncertainty

_Goal: See the model's process — token-level confidence, reasoning traces, parameter effects._

### 3.1 — Logprob Visualization 🔒

The feature that makes Qivis a spectrometer.

**Tasks:**
- `LogprobOverlay` component: renders token-level heatmap on assistant messages
- Color mapping: `uncertaintyColor(logprob)` — transparent for high confidence, warm highlight for low
- Hover tooltip: top-N alternative tokens with probabilities for any token
- Per-message certainty badge: average/min confidence indicator
- Toggle: enable/disable the overlay (visual noise when you don't need it)
- Graceful degradation: no overlay, no badge, no visual noise when logprobs are null
- Works with existing OpenAI logprobs; Anthropic logprobs used when/if available

**Blockers:** Phase 2 complete (stable generation UX needed).

✅ Token heatmap renders on assistant messages with logprob data. Hover shows alternatives. Badge shows node confidence. No visual noise when logprobs absent.

### 3.2 — Thinking Tokens 🔀

See the model's reasoning process.

**Tasks:**
- Provider-layer support: request extended thinking (Anthropic), reasoning tokens (OpenAI)
- New fields on `NodeCreated`: `thinking_content`, `thinking_tokens` (count)
- Projector + API: expose thinking content on node responses
- Frontend: collapsible "Thinking" section on assistant messages (collapsed by default)
- Context builder: configurable whether thinking content is included in subsequent context (tree-level or per-generation setting)
- Graceful degradation: no thinking section when thinking content is null

**Blockers:** None — can parallel with 3.1.

✅ Thinking tokens captured from providers that support them. Collapsible display. Researcher controls whether thinking is in context.

### 3.3 — Sampling Controls 🔀

The dials on the spectrometer.

**Tasks:**
- UI panel: temperature, top_p, top_k, max_tokens, frequency/presence penalty sliders
- Per-tree defaults (stored in tree metadata via `TreeMetadataUpdated` events)
- Per-generation overrides (pre-filled with current defaults, editable before generating)
- Presets: "deterministic" (temp=0), "creative" (temp=1.0), "balanced" (temp=0.7), custom
- Display actual params used on each node (in metadata, visible on hover or in detail view)

**Blockers:** 2.1 (tree settings must support sampling params). Can parallel with 3.1/3.2.

✅ Can adjust sampling params per generation. Presets work. Node detail shows what was used. **Phase 3 complete.**

---

## Phase 4: Seeing Structure

_Goal: See the tree as a tree. Compare branches side by side._

### 4.1 — Graph View 🔒

The tree topology made visible.

**Tasks:**
- Tree layout algorithm (d3-hierarchy or custom) for positioning nodes
- SVG or canvas rendering with zoom/pan
- Node display: truncated content preview, role indicator, model badge
- Click-to-navigate: clicking a node in graph view navigates the linear view to that path
- Branch highlighting: active path visually distinct, hover highlights full branch
- Visual density indicators: where did the researcher branch most? Dead ends vs. active branches
- Toggle between linear view and graph view (or side-by-side split)

**Blockers:** Phase 3 complete (want the reading experience solid before adding a new view mode).

✅ Can see the full tree topology. Click any node to navigate there. Visual structure reveals patterns of exploration.

### 4.2 — Side-by-Side Comparison 🔀

Hold two responses up next to each other.

**Tasks:**
- Select 2–3 sibling nodes from the branch navigator (multi-select mode)
- Split pane opens inline within the tree view (not a separate page)
- Diff highlighting: text differences between responses
- Metadata comparison: model, provider, latency, token usage side by side
- Logprob comparison (if available): certainty badges, heatmap differences
- Dismiss to return to single-branch view

**Blockers:** 3.1 (logprob visualization enriches comparison). Can start alongside 4.1.

✅ Can compare sibling responses side by side with diff highlighting. **Phase 4 complete.**

---

## Phase 5: Context Transparency

_Goal: See — and control — the gap between what happened and what the model knows._

### 5.1 — Message Editing 🔒

Retroactive edits as research interventions.

**Tasks:**
- `NodeContentEdited` event: stores node_id, original_content, new_content, timestamp
- `PATCH /api/trees/{id}/nodes/{nid}/content` endpoint
- Projector: node stores both `content` (original, always primary) and `edited_content` (current edit, null if unedited)
- Context builder: uses `edited_content` when present, falls back to `content`
- Frontend: edit button on any message, inline editor, save/cancel
- **Original message always remains the primary display** in the conversation view; subtle "edited" indicator when an edit exists
- For downstream messages: edit persists in context. "Restore" button reverts to original for future context. "Edit" button to change to something else. Both available per-node alongside the message.

**Blockers:** Phase 4 complete.

✅ Can edit any message. Original preserved and always primary in the conversation view. Model sees edited version. Edits restorable per-node.

### 5.2 — "What the Model Saw" 🔒

The overlay that reveals the model's reality.

**Tasks:**
- Per-message or per-conversation toggle: "what did the model see?"
- In this mode: original message dimmed, edited content shown prominently (different color/style)
- Context diff badge on assistant messages: lights up when generation context differed from expectations (system prompt override, different model/provider, different params, edited upstream messages)
- Click badge to see specifics: what was different, what the model actually received
- Edited messages upstream shown with their edited content highlighted
- Unedited messages shown normally
- When context exclusion lands (Phase 6.3): excluded nodes ghosted in this view

**Blockers:** 5.1 (editing must work for the view to have content to show).

✅ Can see exactly what any model saw during generation. Edits, overrides, and differences all visible. **Phase 5 complete.**

---

## Phase 6: Research Instrumentation

_Goal: Annotate, bookmark, manage context, export._

### 6.1 — Annotation System 🔒

**Tasks:**
- `annotations` table: annotation_id, node_id, tag, value, notes, created_at
- `AnnotationAdded` / `AnnotationRemoved` events, API endpoints
- Taxonomy loaded from `annotation_taxonomy.yml` (coherence scale, basin type, behavioral markers)
- Runtime taxonomy extension via API
- Frontend: annotation panel on nodes, quick-tag buttons, free-form research notes

**Blockers:** Phase 5 complete.

✅ Can annotate any node with taxonomy tags or custom tags. Annotations queryable via API. UI lets you annotate without leaving the conversation view.

### 6.2 — Bookmarks + Summaries 🔀

**Tasks:**
- `bookmarks` table, `BookmarkCreated` / `BookmarkRemoved` events, API endpoints
- Bookmark button on any node, bookmark list in sidebar
- Haiku-generated branch summaries (root to bookmarked node), stored on bookmark, regeneratable
- Bookmarks browsable and searchable by summary content

**Blockers:** 6.1 (annotation infrastructure establishes event patterns). Can start in parallel if comfortable.

✅ Can bookmark nodes, browse bookmarks with summaries. Summarize button works.

### 6.3 — Context Exclusion + Digression Groups 🔒

**Tasks:**
- `NodeContextExcluded` / `NodeContextIncluded` events, `DigressionGroupCreated` / `DigressionGroupToggled` events
- Context builder respects exclusions and toggled-off groups
- Exclude toggle on each node, visual indicator for excluded nodes
- Select message range, create digression group, label it, toggle in/out
- Context preview: `GET /api/trees/{id}/context-preview/{nid}` shows what the model would see
- **Extends Phase 5.2**: excluded nodes ghosted in "what the model saw" view

**Blockers:** 5.2 (context transparency view to extend). 6.1 (annotation infrastructure).

✅ Can exclude nodes, create digression groups, toggle them. Context preview accurate. Excluded nodes visible in transparency view.

### 6.4 — Smart Eviction + Export 🔀

**Tasks:**
- **Smart eviction**: Protected ranges (first N turns, last N turns, bookmarked nodes), middle-turn eviction as whole messages, optional Haiku summarization of evicted content, `EvictionReport` in context panel, configurable `EvictionStrategy` per tree, warning at threshold
- **Export**: `GET /api/trees/{id}/export?format=json|csv`, full tree with all metadata, annotations, bookmarks, logprobs. CSV flattened (one row per node). `GET /api/trees/{id}/paths` enumerates all root-to-leaf paths.

**Blockers:** 6.2 (bookmarks for bookmark-aware protection), 6.3 (exclusions run before eviction).

✅ Long conversations gracefully handle context limits. Researcher sees what was evicted. Full export works. **Phase 6 complete.**

---

## Phase 7: Corpus & Search

_Goal: Build and search a research corpus._

### 7.1 — FTS5 Search 🔒

**Tasks:**
- FTS5 virtual table on node content + system prompts (porter tokenizer + unicode61)
- `GET /api/search?q=keyword` — matching nodes with tree context
- Search UI: bar in sidebar, results with surrounding context and highlighting, click-to-navigate
- Advanced filters: model, provider, date range, tree scope, role

**Blockers:** Phase 6 complete (annotations should be searchable).

✅ Can search across all conversations by keyword with filters.

### 7.2 — Conversation Import 🔀

**Tasks:**
- Parsers for Claude.ai JSON export and ChatGPT export format
- `POST /api/import` with file upload
- Graceful handling of missing fields (no logprobs, no context_usage, approximate timestamps)
- Events emitted as if the conversation happened natively (`TreeCreated` + `NodeCreated`)
- Import wizard UI with format selection and preview
- Stress-tests data model with "information not available" patterns

**Blockers:** 6.1 (imported conversations should be annotatable). Can parallel with 7.1.

✅ Can import conversations from Claude.ai and ChatGPT. Imported trees fully functional.

### 7.3 — Manual Summarization 🔀

**Tasks:**
- Branch / subtree / selection summaries with configurable prompts and summary types (concise, detailed, key points, custom)
- `SummaryGenerated` events, stored and searchable
- UI: right-click or menu on node, "Summarize..." with options
- Shares summarization infrastructure with bookmark summaries (6.2)

**Blockers:** 6.2 (bookmark summary infrastructure).

✅ Can summarize branches, subtrees, selections with various prompts. **Phase 7 complete.**

---

## Phase 8: Multimodal

_Goal: Images, files, and rich content in conversations._

### 8.1 — Content Block Model 🔒

**Tasks:**
- Content becomes `string | ContentBlock[]` in events, projections, context builder
- Backward-compatible: plain strings still valid
- ContentBlock types: text, image, file (PDF, markdown, etc.)
- Frontend renders mixed content inline

**Blockers:** Phase 7 complete (text-based research workflow should be solid first).

✅ Data model supports mixed content. Existing conversations unaffected.

### 8.2 — File Uploads + Provider Support 🔒

**Tasks:**
- Upload API + storage (local filesystem or configurable)
- Frontend: drag-and-drop or file picker in message input
- Inline rendering: images displayed, PDFs previewed, markdown rendered
- Provider adapters: pass multimodal content to APIs that support it (Claude, GPT-4V, etc.)
- Graceful degradation: providers that don't support images get text-only context

**Blockers:** 8.1 (content block model).

✅ Can include images and files in conversations. Providers handle multimodal input. **Phase 8 complete.**

---

## Phase 9: Multi-Agent

_Goal: Run model-to-model conversations AnimaChat-style._

### 9.1 — Participants + Context 🔒

**Tasks:**
- Participant CRUD: model + provider + system prompt + sampling params per participant
- `conversation_mode: "multi_agent"` on tree creation with initial participants
- Per-participant context assembly: own messages as `role: "assistant"`, others as `role: "user"` with `[Name]: ` prefix
- `visible_to` field on researcher notes for selective visibility
- Participant configuration panel UI

**Blockers:** Core generation infrastructure (Phase 2+).

✅ Multi-agent trees with correct per-participant context. Selective visibility works.

### 9.2 — Directed Generation + Injection 🔒

**Tasks:**
- "Who responds?" selector before generating (dropdown of participants)
- Researcher injection: add message with per-participant visibility control
- Participant visual identity: colors, name badges on messages

**Blockers:** 9.1.

✅ Can direct any participant to respond. Can inject selectively visible messages.

### 9.3 — Auto-Run + Turn Controls 🔀

**Tasks:**
- `POST /api/trees/{id}/multi/run` — run N turns with configurable turn order (round-robin or specified)
- SSE streaming as each turn completes, stop button to halt
- Fork from any point in a multi-agent conversation with different participant responding
- Per-participant context usage bars

**Blockers:** 9.2.

✅ Automated multi-agent conversations with live streaming. **Phase 9 complete.**

---

## Phase 10: Local Models

_Goal: Local inference with rich logprob data._

### 10.1 — Local Providers 🔒

**Tasks:**
- `OllamaProvider`: chat + completion, auto-discover models via Ollama API (`/api/tags`)
- `LlamaCppProvider`: completion mode, logprob extraction from `completion_probabilities`
- `GenericOpenAIProvider`: any OpenAI-compatible endpoint (vLLM, LM Studio, text-generation-webui)
- Handle provider-specific quirks: Ollama's streaming format, llama.cpp's token handling

**Blockers:** Provider pattern established (Phase 1). Independent of Phases 2–9.

✅ Can generate from local Ollama and llama.cpp models.

### 10.2 — Completion Mode + Full-Vocab Logprobs 🔒

**Tasks:**
- `mode: "completion"` support: full conversation as single text prompt
- `prompt_text` stored on `NodeCreated` — the exact string sent
- `LLMProvider.supports_mode()` validation
- `LogprobNormalizer.from_llamacpp()` — full vocabulary distributions
- Enriches Phase 3 logprob visualization with complete alternative data

**Blockers:** 10.1.

✅ Completion mode works. Full-vocab logprobs from llama.cpp enrich visualization. **Phase 10 complete.**

---

## Phase 11: Analysis & Intelligence

_Goal: AI-assisted corpus analysis._

### 11.1 — Semantic Search 🔒

**Tasks:**
- Embedding index: sentence-transformers (`all-MiniLM-L6-v2`), hnswlib, incremental embedding of new nodes
- `SearchService.hybrid_merge()`: combine FTS5 + embedding results with configurable weighting
- `SearchQuery` with `semantic: bool` flag
- Structured queries: tags + text + semantic + model/date filters
- "Similar nodes" feature: click any node, find semantically similar across corpus
- `agent_search()` convenience method for LLM agents

**Blockers:** 7.1 (FTS5 must exist for hybrid search).

✅ Keyword, semantic, and hybrid search all work.

### 11.2 — Analysis Skills + Templates 🔀

**Tasks:**
- `AnalysisSkill` ABC: `name`, `analyze(nodes) -> AnalysisResult`
- Built-in skills: `LinguisticMarkerSkill` (hedging, denial, defensive language), `CoherenceScoreSkill`, `LogprobAnalysisSkill` (uncertainty patterns, entropy)
- Plugin system: load skills from `skills/` directory
- Skill runner UI: select nodes, pick skill, see results (stored as annotations)
- **Conversation templates / research protocols**: pre-built tree starters for specific research questions (sycophancy testing, persona consistency, emotional response patterns). Shareable as JSON.

**Blockers:** 6.1 (annotations for storing skill results).

✅ Built-in skills produce useful analysis. Templates shareable. **Phase 11 complete.**

---

## Phase 12: Ecosystem

_Goal: Community-deployable research tool._

### 12.1 — MCP 🔀

**Tasks:**
- MCP client: connect to configured servers (`mcp_servers.yml`), discover tools, wire into generation. Tool calls and results stored as `role: "tool"` nodes.
- MCP server: expose Qivis as MCP server. Tools: `search_conversations`, `get_tree`, `get_node_context`, `get_annotations`, `add_annotation`.

**Blockers:** 11.1 (search for MCP server's `search_conversations` tool).

✅ Models can use external tools. External agents can query and annotate the Qivis corpus.

### 12.2 — Maintenance + Deployment 🔀

**Tasks:**
- Garbage collection: `POST /api/maintenance/gc` with preview, confirmation, and grace period before purge. Logged as `GarbageCollected` events.
- Multi-device sync: event exchange between instances, conflict resolution (tree structure resolves most conflicts naturally)
- Docker image: single `docker-compose up` for the full stack
- Deployment guide, provider setup guides, research workflow guide, API documentation

**Blockers:** Everything else should be stable.

✅ A new researcher can go from zero to running Qivis with one page of instructions. **Phase 12 complete. Qivis is a community-deployable research tool.**

---

## Future Ideas

Ideas noted for consideration beyond the current roadmap:

- **Image generation**: Support for models with image output (DALL-E, future Claude image generation). Fundamentally different generation mode — nodes would store image outputs alongside or instead of text.
- **Conversation templates marketplace**: Community-contributed shareable research protocols beyond local templates.
- **Real-time collaboration**: Multiple researchers on the same tree simultaneously. Event sourcing makes this architecturally straightforward to add later.
- **Postgres migration**: For multi-user deployments. SQLite is single-researcher; Postgres enables shared instances.

---

## Dependency Graph

```
Phase 0 ✅ → Phase 1 ✅ → Phase 1b ✅
                                ↓
                          Phase 2 (Essentials)
                             ↓        ↘
                          Phase 3      2.3 (parallel)
                        (Uncertainty)
                             ↓
                          Phase 4
                        (Structure)
                             ↓
                          Phase 5
                       (Transparency)
                             ↓
                          Phase 6
                     (Instrumentation)
                        ↓       ↘
                     Phase 7    6.4 (parallel)
                  (Corpus/Search)
                        ↓
                     Phase 8
                   (Multimodal)
                        ↓
                     Phase 9
                   (Multi-Agent)

  Phase 10 (Local Models) ─── independent, do whenever hardware available
  Phase 11 (Analysis) ─────── needs Phase 6 + 7
  Phase 12 (Ecosystem) ────── needs everything stable
```

**Parallelism notes:**
- Phase 10 (Local Models) is independent of Phases 2–9. Can be done whenever hardware is available.
- Phase 4 subphases (graph view, comparison) are pure frontend and could theoretically be pulled forward.
- Within phases, 🔀 subphases can be parallelized.
- UX polish ("b" phases) can be interjected between any phases as needed.

---

## Notes for Claude Code Handoff

When handing this plan to Claude Code:

1. **One subphase at a time.** Say "Implement 2.1" not "Build Phase 2."
2. **Definition of done matters.** Each ✅ is the acceptance criteria. Don't move on until it passes.
3. **The architecture doc is the source of truth** for data structures, event types, and API shapes. This plan is the *order* to build them in.
4. **Tests as you go.** Each subphase should have tests before moving to the next, especially event store, context builder, and new event types — these are load-bearing.
5. **Frontend can lag.** It's OK if the frontend is a phase behind the backend. The API is the real interface; the UI catches up.
6. **Frontend components are exempt from test-first.** Backend follows contract tests → integration tests → implement → cleanup → regression. Frontend React components are manually tested.
7. **Subphase sizing matters.** Keep subphases large enough for real design decisions and discovery, not mechanical fill-in.
