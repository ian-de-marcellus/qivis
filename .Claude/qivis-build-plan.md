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

### 2.1 — Tree Settings ✅

Allow editing a tree's defaults after creation. `PATCH /api/trees/{id}` with `TreeMetadataUpdated` events (one per changed field, preserving old/new values). Projector handler with field allowlist. Settings panel UI: inline-editable title, gear icon expands provider/model/system prompt form. Provider/model selection on tree creation. 20 tests. 184 tests at completion.

### 2.2 — Generation UX ✅

Error recovery, smarter defaults, batch generation.

- **Error recovery**: `generationError` store state preserves failed attempt params (provider, model, system prompt, parent node ID, error message). Inline error panel at path leaf with Retry / Change settings / Dismiss. Retry uses saved params. Change settings opens ForkPanel in regenerate mode.
- **Branch-local model default**: Walk active path backwards to find last assistant node's provider/model. Use as defaults for `sendMessage`, ForkPanel, and regenerate. Falls back to tree defaults.
- **n>1 generation**: `n: int = Field(default=1, ge=1, le=10)` on `GenerateRequest`. `generate_n()` service method uses `asyncio.gather` for parallel generation. All N results share same `generation_id`. Router returns first node. Frontend: count input in ForkPanel settings, n>1 forces non-streaming. Streaming + n>1 rejected with 400.

12 new tests. 196 tests at completion.

### 2.2b — Simultaneous Streaming n>1 ✅

Stream all N responses simultaneously with live branch navigation.

- **Backend**: `generate_n_stream()` — `asyncio.Queue`-based merge of N concurrent `provider.generate_stream()` calls. Each stream task tags chunks with `completion_index`, emits `NodeCreated` independently on its final chunk. Sentinel `generation_complete` event when all N streams finish.
- **SSE protocol**: `completion_index` on `text_delta` and `message_stop` events for n>1. n=1 streaming untouched (no `completion_index`, backward compatible). `_stream_n_sse()` router handler for n>1.
- **Frontend**: `generateMultiStream()` client function routes events by `completion_index`. Store: `streamingContents` (per-index buffers), `streamingNodeIds`, `streamingTotal`, `activeStreamIndex`. LinearView: streaming branch nav (‹ 1 of 3 ›) with per-stream display and independent cursors. Single-stream path unchanged.

5 new backend tests (replace old 400-rejection tests). 201 tests at completion.

### 2.3 — Small Polish ✅

Two independent quality-of-life features.

- **Message timestamps**: `formatTimestamp()` helper in MessageRow — relative when recent ("2m ago"), absolute when older ("Feb 15, 2:30 PM"). Shown on all messages in hover-revealed `.message-meta`. Tree-level "Include timestamps in context" setting (stored in tree `metadata` JSON blob): when enabled, ContextBuilder prepends `[YYYY-MM-DD HH:MM]` to each message sent to the LLM. `metadata` added to `PatchTreeRequest` and projector `_UPDATABLE_TREE_FIELDS` allowlist. Checkbox in TreeSettings panel.
- **Theme toggle**: Three-state cycle button (system/light/dark) in sidebar toggle bar. `data-theme` attribute on `:root` + dual CSS selectors (`:root[data-theme="dark"]` for manual, `@media (prefers-color-scheme: dark)` with `:not()` guards for system). Persisted in `localStorage('qivis-theme')`. Unicode icons for modes.

10 new tests. 211 tests at completion. **Phase 2 complete.**

---

## Phase 3: Seeing Uncertainty

_Goal: See the model's process — token-level confidence, reasoning traces, parameter effects._

### 3.1 — Logprob Visualization ✅

The feature that makes Qivis a spectrometer.

Pure frontend — all backend logprob infrastructure was already complete (LogprobData, TokenLogprob, AlternativeToken models, LogprobNormalizer with OpenAI extraction, SamplingParams.logprobs defaulting to True, full event-sourcing pipeline).

**What was built:**
- TypeScript types: `LogprobData`, `TokenLogprob`, `AlternativeToken` — `NodeResponse.logprobs` typed from `Record<string, unknown>` to `LogprobData | null`
- `LogprobOverlay` component: token-level heatmap rendering each `TokenLogprob.token` as a `<span>` with continuous HSLA color from `uncertaintyColor(linear_prob)` — transparent for high confidence (>0.95), warm sienna highlight for low
- `TokenTooltip`: hover reveals chosen token probability + top alternatives with percentages, positioned below token span
- Per-message certainty badge in `.message-meta`: average `linear_prob` as percentage with color-coded dot, click toggles overlay on/off for that message
- Graceful degradation: null logprobs (Anthropic, older nodes) → no badge, no overlay, message renders identically to before

No backend changes, 211 tests unchanged.

### 3.2 — Thinking Tokens ✅

See the model's reasoning process.

**What was built:**
- `SamplingParams`: `extended_thinking: bool`, `thinking_budget: int | None` — opt-in per generation
- `GenerationResult.thinking_content`, `StreamChunk.thinking` — carrier types for thinking data
- `NodeCreatedPayload.thinking_content` → stored in `thinking_content TEXT` column (with migration for existing DBs)
- **Anthropic provider**: `_build_params` adds `thinking` parameter + forces `temperature=1` when extended thinking enabled. `_extract_thinking()` collects thinking blocks. Streaming: tracks `current_block_type` via `content_block_start`/`content_block_stop`, yields `thinking_delta` chunks for thinking blocks
- **OpenAI provider**: `_extract_reasoning_tokens()` safely extracts `reasoning_tokens` count from `usage.completion_tokens_details` (content not exposed by API)
- **SSE protocol**: `thinking_delta` events stream thinking content to frontend. `message_stop` includes full `thinking_content`
- **Context builder**: `include_thinking` parameter prepends `[Model thinking: ...]` to assistant messages when tree-level `include_thinking_in_context` is enabled
- **Frontend**: `ThinkingSection` component — collapsible display with expand/collapse toggle, word count badge, monospace rendering. Auto-expanded during streaming with cursor. Two-phase streaming in LinearView (thinking phase → text phase). Extended thinking checkbox + budget input in ForkPanel. Tree-level settings: "Extended thinking by default", "Thinking budget", "Include thinking in context"
- Graceful degradation: no ThinkingSection when `thinking_content` is null. Existing nodes unaffected.

35 new tests. 246 tests at completion.

### 3.3 — Sampling Controls ✅

The dials on the spectrometer.

**What was built:**
- **Backend merge resolution**: `merge_sampling_params()` with three-layer merge: request overrides > tree `default_sampling_params` > `SamplingParams()` base. Uses Pydantic's `model_fields_set` to only apply explicitly-set request fields, preserving tree defaults for the rest. `_parse_json_field()` utility handles JSON strings, dicts, and malformed data gracefully.
- **Backward compatibility**: Trees with `metadata.extended_thinking` (the old hack) still work when no `default_sampling_params` set. TreeSettings migrates metadata thinking to `default_sampling_params` on save and cleans up the old metadata keys.
- **Typed `SamplingParams` interface**: Frontend TypeScript interface matching backend model. `NodeResponse.sampling_params`, `TreeDetail.default_sampling_params`, `GenerateRequest.sampling_params`, `PatchTreeRequest.default_sampling_params` all typed.
- **Presets**: Deterministic (temp=0, top_p=1), Balanced (temp=0.7), Creative (temp=1.0, top_p=0.95). `detectPreset()` auto-detects current preset from form state. Shared between ForkPanel and TreeSettings.
- **ForkPanel**: Full sampling controls — temperature, top_p, top_k, max_tokens, frequency_penalty, presence_penalty. Paired layout for compact display. Preset dropdown. Extended thinking + budget. All initialized from `samplingDefaults` prop (tree's `default_sampling_params`).
- **TreeSettings**: "Sampling defaults" section with preset dropdown, paired number inputs for all params, extended thinking toggle + budget. Saves to `default_sampling_params` via PATCH. Change detection includes sampling params.
- **Node params display**: `formatSamplingMeta()` on assistant messages shows non-default params in the meta line (temp, top_p, top_k, max_tok, freq_pen, pres_pen, thinking). Monospace font, subtle tertiary color.
- **Store cleanup**: `sendMessage` no longer constructs `sampling_params` from metadata — backend merge resolution handles it.

15 new tests. 261 tests at completion. **Phase 3 complete.**

### 3.4 — Provider-Aware Sampling Controls ✅

Honest annotation of which dials actually work on which provider.

**What was built:**
- **Backend `supported_params`**: `LLMProvider.supported_params: list[str] = []` class attribute. Anthropic declares temperature, top_p, top_k, max_tokens, stop_sequences, extended_thinking, thinking_budget. OpenAI-compatible declares temperature, top_p, max_tokens, stop_sequences, frequency_penalty, presence_penalty, logprobs, top_logprobs.
- **API surface**: `GET /api/providers` includes `supported_params` list per provider.
- **Frontend `ProviderInfo`**: `supported_params: string[]` added to type.
- **ForkPanel + TreeSettings**: Each sampling control checks `isSupported(param)` against the selected provider's `supported_params`. Unsupported controls get `disabled` attribute, `opacity: 0.35`, `cursor: not-allowed`, and tooltip explaining "Not supported by {provider}". Extended thinking also gets an "unsupported" text hint. When no provider is selected (TreeSettings with provider=""), all controls are enabled (backend resolves provider).
- No behavioral change — unsupported params were already silently dropped. This is purely about researcher awareness.

2 new tests. 263 tests at completion.

---

## Phase 4: Seeing Structure

_Goal: See the tree as a tree. Compare branches side by side._

### 4.1 — Graph View ✅

The tree topology made visible.

**What was built:**
- **Custom tree layout algorithm** (`treeLayout.ts`): simplified Reingold-Tilford — bottom-up subtree width computation, top-down x assignment. No external dependencies. Handles asymmetric trees, multiple roots, any depth. ~110 lines.
- **Custom zoom/pan hook** (`useZoomPan.ts`): pointer events for drag-to-pan, wheel for cursor-centered zoom (0.15x to 3x), `fitToContent()` for auto-fitting tree to viewport. ~100 lines.
- **SVG rendering** (`GraphView.tsx`): layered rendering — bezier curve edges, role-colored node circles, fork rings for branching points, single-letter role labels. Active path highlighted in warm sienna, off-path nodes ghosted at 30% opacity. Hover highlights the full path from root to hovered node.
- **Split pane layout**: linear view on left, graph on right. Draggable divider with 200px minimum, 60% maximum. Subtle dot-grid background on graph pane evoking scientific precision. Stats badge (node count, fork count) in bottom-right corner.
- **Click-to-navigate**: `navigateToNode(nodeId)` store action walks backward from target to root, builds complete `branchSelections` map, sets it in one call. LinearView and GraphView both react instantly. Replaces (not merges) selections — clicking is a full path commitment.
- **Toggle button**: 28x28 branching-tree SVG icon in TreeSettings bar, same visual vocabulary as the gear icon. Active state with accent highlight when graph is open.
- **Tooltip**: hover reveals content preview (~120 chars), role label, model name. Paper-colored overlay with editorial typography.
- **Design**: scientific-diagram aesthetic within the existing editorial palette. Dot-grid background, organic bezier edges, warm glow on active path, ghostly off-path branches. Consistent with light/dark theme.

No backend changes. 263 tests unchanged. Pure frontend.

### 4.2 — Side-by-Side Comparison ✅

Hold all sibling responses up next to each other.

**What was built:**
- **Word-level diff algorithm** (`wordDiff.ts`): LCS-based word diff between base (currently selected) and each sibling. Tokenizes on whitespace, computes LCS with DP, produces `DiffSegment[]` (common/added/removed), merges adjacent segments. ~110 lines.
- **ComparisonCard** (`ComparisonCard.tsx`): Individual sibling card with role/model header, diff-highlighted content, always-visible metadata footer (latency, tokens, certainty badge, sampling params). Selected card gets accent left-border + "current" badge.
- **ComparisonView** (`ComparisonView.tsx`): CSS grid container for all sibling cards. Computes word diffs against selected sibling. Responsive grid (280px min-width). Header with dismiss button. Panel-enter animation.
- **Compare button**: Added to BranchIndicator (hidden until hover, like Fork). Threaded through MessageRow. Toggle behavior — click again to dismiss.
- **LinearView integration**: `comparingAtParent` local state. ComparisonView renders inline below the message. Click a card to select that branch + dismiss comparison.
- **Diff styling**: Added text gets `var(--accent-muted)` background highlight. Removed text gets line-through + reduced opacity.
- **Design decisions**: Show ALL siblings (no multi-select picker). Diff against current selection. Local state not store. Metadata always visible (not hover-gated). Smaller font than MessageRow for density.

No backend changes. 263 tests unchanged. Pure frontend.

**Phase 4 complete.**

---

## Phase 5: Context Transparency

_Goal: See — and control — the gap between what happened and what the model knows._

### 5.1 — Message Editing ✅

Retroactive edits as research interventions with palimpsest display and version correlation.

**What was built:**
- `NodeContentEditedPayload` event type: `node_id`, `original_content`, `new_content` (null = restore)
- Schema migration: `edited_content TEXT` column on nodes table
- Projector handler: `NodeContentEdited` → UPDATE nodes SET edited_content
- Context builder: single-line change — `node.get("edited_content") or node["content"]`
- `PATCH /api/trees/{id}/nodes/{nid}/content` endpoint with normalization (empty → null, same-as-original → null)
- `PatchNodeContentRequest` schema, `NodeNotFoundError` exception, `edit_node_content` service method
- `EventStore.get_events_by_type(tree_id, event_type)` — filtered event query for edit history reconstruction
- `GET /api/trees/{id}/nodes/{nid}/edit-history` endpoint: `EditHistoryResponse` with `original_content`, `current_content`, and ordered `EditHistoryEntry[]` (event_id, sequence_num, timestamp, new_content)
- `get_edit_history` service method: queries event log, filters by node_id, returns complete edit timeline
- Frontend: `editNodeContent` API client + Zustand action (in-place node update, no tree re-fetch)
- MessageRow: Edit/Restore buttons (hover-reveal), inline textarea editor (Cmd+Enter save, Esc cancel), "(edited)" indicator in meta line
- **Palimpsest display**: original content stays in primary reading position with normal styling (the truth); edit appears below as an "overlay block" with thin accent left-border, faint bg-secondary background, and "MODEL SEES" label — visually "placed here" like a correction slip on a manuscript
- **EditHistory component**: collapsible panel (follows ThinkingSection pattern), lazy-loads history on first expand, renders all versions as clickable rows with version number, truncated preview, relative timestamp. Synthetic "Original" (v0) entry. Click to select → highlights downstream assistants
- **Version correlation highlights**: `useMemo` in LinearView computes timestamp-based windows from edit history entries. When a version is selected, assistant messages generated during that version's window get `highlight-used` (accent left-border + muted background), others get `highlight-other` (dimmed opacity)
- Store: `selectedEditVersion`, `editHistoryCache`, `setSelectedEditVersion`, `cacheEditHistory` actions. Cache invalidated on edit.
- 29 tests (5 contract, 6 context builder, 8 API integration, 3 EventStore, 7 edit history). 292 total passing.

### 5.2 — "What the Model Saw" ✅

Context modal + per-node generation flag tracking.

**What was built:**
- `reconstructContext(targetNode, allNodes)` utility: walks parent chain, applies edits, computes eviction, builds ordered message list matching what ContextBuilder sent
- `ReconstructedMessage` with part-split fields: `thinkingPrefix`, `timestampPrefix`, `baseContent` for distinct rendering of augmented content
- `ContextModal` component: centered dialog showing system prompt, messages (with edited/manual/+timestamp/+thinking tags), sampling params, context usage, extended thinking section
- "Context" button on assistant messages (hover-reveal, same pattern as Fork/Edit)
- Per-node context flag tracking: `include_thinking_in_context` and `include_timestamps` snapshotted on `NodeCreatedPayload` at generation time, persisted through event sourcing pipeline, surfaced in `NodeResponse`
- Backend: schema migration (2 new columns), projector INSERT, service _node_from_row, generation service threading through all 4 _emit_node_created call sites
- Frontend context reconstruction: timestamps only prepended on user/tool messages (not assistant — prevents model mirroring), thinking prepended on assistant messages
- Flag badges in modal metadata row
- 6 new tests (contract, projection, API). 304 total passing.

### 5.3 — Context Diff Badge + Asymmetric Split View ✅

Per-assistant diff badge + asymmetric split view comparing researcher's truth vs. model's received context.

**What was built:**
- `contextDiffs.ts`: `computeDiffSummary(node, path, treeDefaults)` for lightweight badge data, `buildDiffRows(node, allNodes, treeDefaults)` for full row-by-row alignment, `getTreeDefaults(tree)` helper
- `ContextDiffBadge.tsx`: inline badge (colored dot + count) in assistant message meta line. Accent dot for content changes, muted for metadata-only
- `ContextSplitView.tsx`: asymmetric split view modal (1100px, 2fr/3fr grid). Right column = model's received context fully rendered. Left column = pregnant space (thin rule + role label) for matches, actual content at divergence points, voids where researcher's truth has content the model didn't see
- Row types: match, edited, augmented, prefill, evicted, non-api-role, system-prompt, metadata
- Response section at bottom: thinking block + response content + latency/tokens/finish reason
- Store: `splitViewNodeId` state for toggle

**Design decisions:**
- Augmented rows (thinking/timestamps prepended) use pregnant space on left — base content matches, only packaging differs
- Response section completes the story: "here's what went in, here's what came out"
- Badge in meta line (not header) — it's metadata about the generation, not an action

304 tests at completion (no backend changes). Pure frontend.

### 5.4 — 2D Canvas View ✅

Era-based 2D research artifact viewer for the full intervention history.

**What was built:**
- **Backend**: `GET /api/trees/{tree_id}/interventions` endpoint. `InterventionEntry` + `InterventionTimelineResponse` schemas. `get_intervention_timeline()` service method merges `NodeContentEdited` events + `TreeMetadataUpdated` events (filtered to `default_system_prompt` only), sorts by `sequence_num`. 7 new tests.
- **Frontend types**: `InterventionEntry`, `InterventionTimelineResponse` in types.ts. `getInterventions()` API client.
- **Era computation** (`eraComputation.ts`): `computeCanvasGrid(pathNodes, interventions, treeDefaults)` → `CanvasGrid` with `Era[]` and `RowLabel[]`. Cumulative edit state across eras. `lastActiveRow` computed per-era based on which messages existed before the next intervention.
- **CanvasBubble**: compact cells with role-colored backgrounds, 3-line content clamp, hover popover for full message. Pregnant space (centered dot) for unchanged cells. Accent left-border for edited cells. Absent cells for messages that didn't exist in an era.
- **CanvasView**: full-screen overlay modal (95vw × 90vh). CSS Grid with sticky row labels (left) and era headers (top). Fetches interventions on mount. Dismiss via Esc/backdrop/close button.
- **Store**: `canvasOpen: boolean`, `setCanvasOpen(open)`. Canvas toggle button in TreeSettings (grid icon). `CanvasView` rendered as overlay in App.tsx.

**Era model:**
- Columns = temporal epochs between interventions, not categories
- Era boundaries: `NodeContentEdited` + system prompt `TreeMetadataUpdated` events
- NOT boundaries: model/provider/param changes (stay vertical)
- Each era inherits all previous eras' edits cumulatively
- Multiple edits to same message = multiple eras
- Vertical extent differs: earlier eras are shorter (fewer messages existed)

7 new backend tests. 311 tests at completion. **Phase 5 complete.**

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
- **Prefill / continuation mode**: Let the researcher supply a partial assistant response and see where the model takes it. Anthropic Messages API supports this natively (partial assistant message). OpenAI chat API doesn't reliably continue from a prefill. Completion APIs (llama.cpp, Phase 10.2) support it perfectly with full logprobs. A lighter version using Anthropic prefill could land before Phase 10. Key research use case: "the model said X — but what if it had started with Y instead?"

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
                       Phase 5.1–5.2
                       (Transparency)
                             ↓
                         Phase 5.3
                    (Full Context Compare)
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
