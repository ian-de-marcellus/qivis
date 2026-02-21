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

### 6.5 — Research Notes + Unified Research Pane ✅

**Tasks:**
- `notes` table: note_id, tree_id, node_id, content, created_at
- `NoteAdded` / `NoteRemoved` events + projector handlers
- Note CRUD endpoints: POST/GET/DELETE per node, GET tree-wide with `?q=` search
- `note_count` on `NodeResponse` (mirrors annotation_count pattern)
- Tree-wide annotations endpoint: `GET /api/trees/{id}/annotations`
- Frontend `NotePanel`: inline below messages (textarea + submit, list with remove)
- Frontend `ResearchPanel`: tabbed sidebar replacing BookmarkList (Bookmarks, Tags, Notes tabs)
- Click-to-navigate from any research item to its source node
- 18 new backend tests (projection, CRUD, note_count, tree annotations, event replay)

**Design notes:** Notes are simpler than annotations (no tag/value taxonomy) and bookmarks (no summary generation). Pure free-form text commentary — "this is where the model started hedging," "compare with the other branch." The research panel unifies all three metadata types into a single navigable sidebar view.

✅ Can add free-form notes on any node. Research panel shows bookmarks, tags, and notes for the current tree. 523 tests.

---

## Interlude: Immediate Fixes + Technical Debt

_Goal: Fix bugs, clean up debt, solid foundation before new features._

Organized into four chunks, each interleaving bug fixes and refactors that touch the same code areas.

### Chunk 1 — Generation Pipeline (backend)

Bug fixes and debt in the context building / eviction / summary path.

- **Eviction summary injection**: insertion position works by coincidence (hardcoded 2 matches default `keep_first_turns=2`). Fix: carry `keep_first_turns` through `EvictionReport`, use it for correct positioning
- **Configurable summary model**: `EvictionStrategy.summary_model` field exists but is never read — both summary methods hardcode `"claude-haiku-4-5"`. Wire the field through `EvictionReport` to the actual API calls
- **Token counter interface**: replace `len(text) // 4` with `TokenCounter` ABC + `ApproximateTokenCounter`. Accept counter in `ContextBuilder.build()`. Provider-specific counters come in Phase 8
- **Unified JSON parsing**: consolidate `_parse_json_field()`, `maybe_json()`, `_parse_json_or_raw()`, `_json_str()`, and bare `json.loads()` into `qivis/utils/json.py`

### Chunk 2 — Store & Component Architecture (frontend)

Frontend structural refactors.

- **Zustand store slicing**: break 1374-line store into coherent slices (streaming, comparison, digression groups, UI panels). Use Zustand selector pattern instead of destructuring 26+ fields. Add `rightPaneMode` to centralize mutual exclusion of graph/digression/split views
- **Extract shared sampling UI**: `<SamplingParamsPanel />` component used by both ForkPanel and TreeSettings. Move `SAMPLING_PRESETS` and `detectPreset` to shared location. Eliminates ~150 lines of duplication
- **MessageRow prop reduction**: split 22-prop MessageRow into `<MessageRow>` (content) + `<MessageRowToolbar>` (actions). Wrap in `React.memo()`
- **Modal focus management**: add focus traps to ContextModal, ContextSplitView, CanvasView. Add `aria-live` to error banners and streaming status

### Chunk 3 — UI Fixes & Polish (frontend)

Six small-to-medium UI bugs, rapid-fire.

- **Context bar clickable size**: increase hit target for the context usage bar on assistant messages
- **Regen dialog position**: should appear above the message, not below (current placement pushes content off-screen)
- **Extended thinking override on regenerate**: turning thinking off in regen dialog may not override tree default due to sampling param merge backward-compat hack
- **TreeSettings save consistency**: some fields save immediately (checkboxes), others buffer and require explicit Save button. Fix: either auto-save all, or make all fields buffer with clear dirty indicators and a single Save
- **Center button for collapsed tree panel**: when sidebar is collapsed, add a centered expand button
- **Markdown rendering**: message content should render markdown (bold, italic, code blocks, lists). Double asterisks currently display raw

### Chunk 4 — Documentation & Infrastructure (backend + docs)

Bookends: one looks backward (documenting reality), one looks forward (safer migrations).

- **Update architecture doc**: reflect implementation reality — context builder signature, anchors vs bookmarks, provider class attributes vs abstract methods, extra data model fields (thinking, editing, timestamps, prefill/manual mode)
- **Migration system**: add version tracking table, specific error catching (not bare `except Exception: pass`), logging of success/failure per migration

✅ All bugs fixed, debt addressed, architecture doc matches code. Store is organized, components are manageable, modals are accessible. Clean foundation for Phase 7+.

---

## Interlude 2: Pattern Consolidation

_Goal: Deduplicate repeated CSS, store logic, and component patterns that accumulated across Phases 0–7._

### Chunk 1 — CSS Utility Classes ✅

Extracted 5 shared utilities to `index.css`: `.badge`, `.inline-panel`, `.hover-btn`, `.form-input`, `@keyframes panel-enter`. Component CSS files now compose from these, keeping only component-specific overrides. CSS bundle reduced ~620B. Descendant-selector form containers (SamplingParams, ForkPanel settings, TreeSettings) left for Chunk 3 (FormField component).

### Chunk 2 — Store Helpers ✅

Four helpers extracted above `create()`: `STREAMING_RESET`/`MULTI_STREAMING_RESET` constants (replaced ~14 streaming state resets), `refreshTree`/`refreshTreeSelectNewest` (replaced 7 getTree+listTrees pairs), `fetchTreeData` generic (consolidated 7 fetch actions to 3 lines each), `updateNode` (replaced 11 node-field update patterns). Store reduced from 1603 to 1420 lines. JS bundle reduced ~3.4KB.

### Chunk 3 — Component Extraction ✅

Extracted `IconToggleButton` component (`shared/IconToggleButton.tsx` + `.css`) — replaces 5 identical icon toggle buttons in TreeSettings (graph, canvas, digressions, research, gear) and their two duplicate CSS blocks (`.graph-toggle` + `.tree-settings-gear`). Extracted `useEscapeKey` and `useClickOutside` hooks — replaced ActionMenu's inline useEffects (20 lines -> 2 hook calls) and refactored `useModalBehavior` to consume `useEscapeKey` internally. NotePanel/AnnotationPanel convergence evaluated and deliberately passed — ~40% structural similarity but AnnotationPanel's complexity is genuinely different, not duplicated. CSS: 99.99 KB (-0.5KB from Chunk 2).

---

## Phase 7: Corpus & Search

_Goal: Build and search a research corpus. Organize trees. Import external conversations._

### 7.1 — FTS5 Search ✅

FTS5 virtual table with external content (`content='nodes'`, porter + unicode61 tokenizer). Three SQL triggers (INSERT/DELETE/UPDATE) keep index in sync — no projector changes. `SearchService` with dynamic query building: FTS5 MATCH + optional filters (tree_ids, models, providers, roles, annotation tags, date range). Snippet markers `[[mark]]/[[/mark]]` for safe frontend rendering. `GET /api/search?q=keyword` with comma-separated filter params. Persistent search input at top of sidebar — results replace tree list while searching. `navigateToSearchResult` handles cross-tree navigation (first cross-tree store action). 20 new tests. 472 tests at completion.

### 7.2 — Conversation Import ✅

Importer package (`qivis.importer`) with intermediate representation (`ImportedNode`/`ImportedTree` dataclasses), auto-format detection, and two parsers: ChatGPT (tree-native with `mapping` dict, branch preservation, null-message reparenting, system prompt extraction, model/provider inference) and generic linear (ShareGPT `{from,value}` + generic `{role,content}`). `ImportService` with preview (parse without creating) and import (emit `TreeCreated` + `NodeCreated` events with `device_id="import"`, preserved source timestamps, topological sort for parent-before-child ordering). `POST /api/import/preview` and `POST /api/import` with `UploadFile` + optional format/selected params. Import wizard modal in sidebar: drag-and-drop file input, format badge, conversation list with checkboxes, per-conversation preview (title, message count, branch count, models, system prompt, first messages, warnings), import progress, results with "Open" navigation. 25 new tests. 497 tests at completion.

**Key decisions:** `mode="chat"` (not `"manual"` — avoids "researcher authored" overlay), system messages extracted to tree property only (not as nodes), import provenance via `metadata.imported=True` + `device_id="import"` (not new event types). Tree merge/reconciliation deferred to 7.2b.

### 7.2b — Tree Merge ✅

Merge an imported conversation file into an existing tree without duplicating already-present messages. Tree-local workflow: toolbar button opens merge panel, upload file, preview match results, merge. Reuses import parsers and topological sort from 7.2.

**Matching algorithm:** "Longest common prefix" match on each branch. Index existing nodes by `(parent_id, role, normalized_content.strip())`. Walk imported nodes in topological order — if parent matched, try to match this node; if parent is new, this node is new. Matches against `edited_content` if set (what the researcher sees). Naturally handles extend (add suffix), diverge (fork at mismatch), no overlap (all new), full overlap (nothing to merge), and branching imports.

**Backend:** `MergeService` in `qivis.importer.merge` with `_compute_merge_plan` (pure function, tested in isolation), `preview_merge`, `execute_merge`. `MergePlan` dataclass tracks matched/new/graft_map/warnings. Two endpoints: `POST /api/trees/{tree_id}/merge/preview` and `POST /api/trees/{tree_id}/merge`. New nodes emitted as `NodeCreated` events with `device_id="merge"`. 15 tests (8 contract + 7 integration). 538 tests at completion.

**Frontend:** `MergePanel` component with state machine (idle/previewing/preview/merging/done/error). Drag-and-drop file upload. Preview shows format badge, source title, matched/new counts, graft points with content previews, warnings. "Merge N messages" button or "Nothing to merge" state. Done state navigates to first new node. Toolbar button (merge/join icon) in TreeSettings bar.

### 7.3 — Manual Summarization ✅

General-purpose summarization system: summarize any branch or subtree with configurable summary types (concise, detailed, key_points, custom), stored as first-class research artifacts alongside bookmarks, annotations, and notes.

**Backend:** `SummaryGeneratedPayload` (was orphaned, now wired up) with `anchor_node_id`. Added `SummaryRemovedPayload`. `summaries` table with migrations 013-015. Projector handlers for both events. Extracted shared helpers from bookmark summary: `_build_transcript`, `_call_summary_llm`, `_resolve_summary_model`, `_walk_branch`, `_collect_subtree`. Four summary types with tuned prompts and token limits: concise (100), detailed (500), key_points (300), custom (500 + user prompt). Branch scope walks parent chain root→leaf. Subtree scope collects all descendants via BFS. Three endpoints: POST /summarize, GET /summaries, DELETE /summaries/{id}. 17 tests (3 contract + 9 integration + 5 service). 555 tests at completion.

**Frontend:** `SummarizePanel` inline component (ForkPanel pattern) with config/generating/result states. "Summarize" item in ActionMenu research group (quill). `summarizeTargetId` state in LinearView toggles panel. ResearchPanel gets "Summaries" tab (4th tab) showing scope/type badges, expandable summary text, model attribution, navigate-to-anchor, remove button. Store: `treeSummaries` state, `fetchTreeSummaries`/`generateSummary`/`removeSummary` actions.

### 7.4 — Tree Organization ✅

Hierarchical folders and flat tags stored in tree metadata JSON (`folders: string[]`, `tags: string[]`). No new tables or event types — uses existing `PatchTreeRequest` with read-merge-write pattern.

**Backend:** Wired up orphaned `TreeArchived`/`TreeUnarchived` events (projector handlers, service methods, two new POST endpoints). Updated `list_trees` with `include_archived` query param and enriched `TreeSummary` (folders, tags, archived parsed from metadata JSON). 13 new tests. 568 tests at completion.

**Frontend:** Right-click context menu (`TreeContextMenu`) with state machine (menu → folder-picker / tag-picker). Inline rename on double-click or from context menu. View mode toggle (flat list / folder groups) persisted to localStorage. Folder view builds a trie from hierarchical path strings — trees with multiple folders appear in each group. Tag filter bar with deterministic hash-colored pills (intersection filtering). Archive toggle at sidebar bottom. `tagColor` utility: djb2 hash into 12-color muted palette.

**Key decisions:** Folders as multi-assignable hierarchical tags ("dressed up like folders"), client-side derivation of folder/tag registries from TreeSummary data (no new endpoints), read-merge-write on metadata updates to avoid clobbering `include_timestamps`/`stream_responses`/etc, duplicate and folder rename deferred.

✅ Trees organized into folders and tags. Sidebar filterable. Right-click actions work.

### 7.4b — Full-Screen Library View ✅

Full-screen overlay for visual corpus organization. Two-panel layout: folder tree (left, 260px, droppable targets) + tree card grid (right, CSS Grid auto-fill). `@dnd-kit/core` for drag-and-drop.

**DnD:** `PointerSensor` with 8px distance constraint (distinguishes click from drag), `KeyboardSensor` for accessibility, `closestCenter` collision detection. Cards draggable via `useDraggable`, folders droppable via `useDroppable`. Drop = add folder; drop on "Unsorted" = clear all folders.

**Multi-select:** Cmd/Ctrl+click toggles, Shift+click range-selects. Group drag shows stacked card overlay with count badge. Selection state in `Set<string>` with `lastClickedId` ref for range computation.

**Folder management:** Ghost folders in localStorage for pre-created empty hierarchy. Right-click folder context menu: New Subfolder (pre-fills input), Rename (batch-updates all affected trees including child paths), Delete (confirms if non-empty, removes from all trees). Cards show folder chips with "x" remove buttons.

**Entry points:** "Library" button in TreeList header, `Cmd+Shift+L` keyboard shortcut. Overlay uses `useModalBehavior()` (Escape/backdrop-click dismissal, focus trap).

**Shared utility:** Extracted `FolderNode`, `buildFolderTrie`, `countTreesInFolder` from TreeList to `utils/folderTrie.ts`, added `collectTreeIds` and `findFolderNode` helpers.

✅ Full-screen library with drag-and-drop organization, multi-select, folder CRUD. **Phase 7 complete.**

---

## Phase 8: Generation Modes & Local Models

_Goal: Prefill, base models, local inference, full-vocab logprobs. The research capabilities that require non-standard generation._

### 8.1 — Prefill / Continuation Mode ✅

**Tasks:**
- Researcher writes a partial assistant response; model continues from there
- `mode: "prefill"` on `GenerateRequest` — appends partial assistant message to context, model completes it
- Anthropic: native support via partial assistant message in Messages API
- OpenAI: best-effort via system prompt instruction (less reliable)
- Frontend: "Prefill" button on user messages opens text area for partial response. Generated content appended after the prefill text. Prefill portion visually distinguished (different background, "PREFILL" label) like the palimpsest edit display
- `NodeCreatedPayload.prefill_content`: stores the researcher-authored prefix separately from model-generated continuation
- Key research use case: "The model said X — what if it had started with Y instead?"

**Blockers:** Phase 6 complete.

✅ Can supply partial assistant responses. Model continues naturally. Prefill content distinguished from generated content.

### 8.2 — Local Providers 🔒

**Tasks:**
- `OllamaProvider`: chat + completion modes, auto-discover models via Ollama API (`/api/tags`), streaming
- `LlamaCppProvider`: completion mode, logprob extraction from `completion_probabilities`, full vocabulary distributions
- `GenericOpenAIProvider`: any OpenAI-compatible endpoint (vLLM, LM Studio, text-generation-webui)
- Handle provider-specific quirks: Ollama's streaming format, llama.cpp's token handling
- Provider auto-discovery: detect running Ollama/llama.cpp on startup, add to provider list
- Settings panel integration: configure local provider URLs

**Blockers:** Provider pattern established (Phase 1).

✅ Can generate from local Ollama and llama.cpp models.

### 8.3 — Completion Mode + Full-Vocab Logprobs 🔒

**Tasks:**
- `mode: "completion"` support: full conversation rendered as a single text prompt via configurable prompt templates
- Prompt template system: Alpaca, ChatML, Llama, custom. Stored per tree or per participant
- `prompt_text` stored on `NodeCreated` — the exact string sent to the model
- `LLMProvider.supports_mode()` validation
- `LogprobNormalizer.from_llamacpp()` — full vocabulary distributions (thousands of alternatives per token, not just top-5)
- Enriches Phase 3 logprob visualization with complete alternative data: full probability distributions, entropy computation, token-level surprise metrics

**Blockers:** 8.2 (local providers).

✅ Completion mode works. Full-vocab logprobs from local models enrich visualization. **Phase 8 complete.**

---

## Phase 9: Research Intervention Tools

_Goal: Systematic tools for designing and running experiments on AI conversation behavior._

### 9.1 — Systematic Context Interventions 🔒

**Tasks:**
- **Context packaging dialog**: configurable transforms applied to messages before sending to model. Examples: prepend timestamps, append metadata, wrap in XML tags, insert separators. Per-tree configuration with preview
- **Move context tokens out of system prompt**: option to place system-prompt-like instructions in a user message or as a context preamble instead of the system prompt field. Some models respond differently to the same instructions in different positions
- **Long context reminder injection**: insert a configurable reminder at a specified position in the context (e.g., halfway, every N turns). Research tool for studying the effects of in-context reminders. Gated behind explicit opt-in with clear documentation of research purpose

**Blockers:** Phase 6 complete.

✅ Can configure how messages are packaged for the model. Can experiment with instruction placement.

### 9.2 — Conversation Replay & Perturbation 🔀

**Tasks:**
- **Replay**: take a path through a tree and replay it through a different model — same user messages, regenerate all assistant responses. Creates a new branch at each fork. Shows how different models handle the same conversation trajectory
- **Context perturbation experiments**: automated exclude/include/regenerate/diff cycles. Toggle a digression group or exclusion, regenerate, toggle back, regenerate, diff the results. Produces a structured comparison of "what changed when this context was present vs absent"
- **Perturbation report**: summary of which context changes had the largest effect on model output, measured by edit distance or semantic similarity

**Blockers:** 6.3 (exclusions and digression groups), Phase 7 (search for finding similar conversations).

✅ Can replay conversations through different models. Can run controlled perturbation experiments.

### 9.3 — Cross-Tree Reference & Display 🔀

**Tasks:**
- **Split-pane cross-tree view**: the graph/transcript pane on the right can show a different tree than the main conversation. For repeating experiments with different models or referencing other conversations while working
- **Customizable role labels**: replace "user" and "assistant" with researcher-chosen labels. Per-tree setting. Default labels should work for non-human "user" roles (e.g., "Participant A" / "Participant B" instead of "User" / "Assistant")
- Tree selector in the right pane header. Independent scroll, navigation, and branch selection from the main pane

**Blockers:** Phase 4 (graph view exists).

✅ Can view two trees side by side. Role labels customizable. **Phase 9 complete.**

---

## Phase 10: Multi-Agent

_Goal: Run model-to-model conversations. Multiple models with different contexts in shared conversations._

### 10.1 — Participants & Context 🔒

**Tasks:**
- Participant CRUD: model + provider + system prompt + sampling params per participant
- `conversation_mode: "multi_agent"` on tree creation with initial participants
- Per-participant context assembly: own messages as `role: "assistant"`, others as `role: "user"` with `[Name]: ` prefix
- `visible_to` field on researcher notes for selective visibility
- Participant configuration panel UI

**Blockers:** Core generation infrastructure (Phase 2+).

✅ Multi-agent trees with correct per-participant context. Selective visibility works.

### 10.2 — Directed Generation & Injection 🔒

**Tasks:**
- "Who responds?" selector before generating (dropdown of participants)
- Researcher injection: add message with per-participant visibility control
- Participant visual identity: colors, name badges on messages

**Blockers:** 10.1.

✅ Can direct any participant to respond. Can inject selectively visible messages.

### 10.3 — Auto-Run & Turn Controls 🔀

**Tasks:**
- `POST /api/trees/{id}/multi/run` — run N turns with configurable turn order (round-robin or specified)
- SSE streaming as each turn completes, stop button to halt
- Fork from any point in a multi-agent conversation with different participant responding
- Per-participant context usage bars

**Blockers:** 10.2.

✅ Automated multi-agent conversations with live streaming.

### 10.4 — Group Chat with Divergent Histories 🔒

**Tasks:**
- Bring two (or more) models with different prior conversation contexts into a shared group chat
- Each participant retains access to their full prior context (from a different tree or branch) plus the shared group chat messages
- Per-participant private notes: visible only to the participant they're addressed to (internal monologue / scratchpad for each model)
- Context assembly: `[prior context from participant's source tree] + [shared group chat messages] + [private notes for this participant]`
- UI: participant setup wizard showing which tree/branch each participant brings as "memory"

**Blockers:** 10.1, 10.2 (basic multi-agent must work first).

✅ Can create group conversations where each model brings different context. Private notes work. **Phase 10 complete.**

---

## Phase 11: Memory System

_Goal: Persistent, portable context that transcends individual conversations._

### 11.1 — Portable Digression Groups 🔒

**Tasks:**
- **Memory bank**: a tree-independent store of context snippets. Each memory has: content (from digression group nodes), label, source tree/branch, tags, created_at
- Promote any digression group to a "memory" — copies the content into the memory bank, decoupled from the source tree
- **Memory injection**: when creating or continuing a tree, select memories to include in context. Injected as a preamble or at a configurable position
- Memory CRUD endpoints, memory list in sidebar

**Blockers:** 6.3 (digression groups exist).

✅ Can save digression groups as persistent memories. Can inject memories into any conversation.

### 11.2 — Model-Queryable Memories 🔒

**Tasks:**
- Tool-use interface: models can call a `search_memories` tool during generation to retrieve relevant memories
- Requires MCP client integration or native function-calling support per provider
- Memory search uses FTS5 + optional semantic matching
- Retrieved memories inserted into context with `[Memory: {label}]` prefix
- Researcher controls: which memories are searchable, maximum retrieval count, whether to auto-inject or require model to query

**Blockers:** 11.1, Phase 7.1 (FTS5 for memory search), Phase 12.1 (MCP for tool use).

✅ Models can query and retrieve memories during conversation.

### 11.3 — Automatic Memory Creation 🔀

**Tasks:**
- Sentiment analysis / semantic clustering to auto-identify digression-worthy segments
- Auto-creation of digression groups from detected topic shifts or emotional valence changes
- Auto-tagging of memories based on content analysis
- Configurable sensitivity: researcher controls what triggers auto-detection
- Uses analysis skills infrastructure (Phase 13.2)

**Blockers:** 11.1, Phase 13.2 (analysis skills for detection).

✅ System can suggest and auto-create memory groups from conversation patterns. **Phase 11 complete.**

---

## Phase 12: Multimodal

_Goal: Images, files, and rich content in conversations._

### 12.1 — Content Block Model 🔒

**Tasks:**
- Content becomes `string | ContentBlock[]` in events, projections, context builder
- Backward-compatible: plain strings still valid
- ContentBlock types: text, image, file (PDF, markdown, etc.)
- Frontend renders mixed content inline

**Blockers:** Phase 7 complete (text-based research workflow should be solid first).

✅ Data model supports mixed content. Existing conversations unaffected.

### 12.2 — File Uploads + Provider Support 🔒

**Tasks:**
- Upload API + storage (local filesystem or configurable)
- Frontend: drag-and-drop or file picker in message input
- Inline rendering: images displayed, PDFs previewed, markdown rendered
- Provider adapters: pass multimodal content to APIs that support it (Claude, GPT-4V, etc.)
- Graceful degradation: providers that don't support images get text-only context

**Blockers:** 12.1 (content block model).

✅ Can include images and files in conversations. Providers handle multimodal input. **Phase 12 complete.**

---

## Phase 13: Analysis & Intelligence

_Goal: AI-assisted corpus analysis. Behavioral pattern detection. Agent co-annotation._

### 13.1 — Agent Co-Annotation 🔒

**Tasks:**
- **Meta-conversation**: a special tree where the agent (Claude or similar) can query, view, and annotate other conversations in the corpus
- Qivis as MCP server: expose `search_conversations`, `get_tree`, `get_node_context`, `get_annotations`, `add_annotation`, `get_memories` as tools
- Agent can browse trees, read branches, add annotations, create bookmarks, and write research notes — all through natural conversation
- Researcher guides the agent's analysis through the meta-conversation, building up annotations collaboratively

**Blockers:** Phase 7.1 (search), Phase 6.1 (annotations).

✅ Agent can explore and annotate the corpus through conversation.

### 13.2 — Behavioral Fingerprinting & Pattern Detection 🔀

**Tasks:**
- **Temporal marker tracking**: flag when models use temporal language ("tonight", "this afternoon", "this weekend"), correlate with context window metrics (% full, token count, turn count). Test the "tonight = full context" hypothesis across models and prompt styles
- **Self-reference pattern analysis**: track when models refer to themselves (I/me vs we vs passive voice), how this shifts across conversation length, system prompts, and models. Detect the "we" overloading phenomenon (using first-person plural to refer to humans)
- **Cross-model behavioral comparison**: given the same conversation up to a fork, run N models and auto-annotate structural differences — hedging patterns, mirroring, list-vs-prose, agreement-first vs qualification-first
- **Semantic search**: embedding index (sentence-transformers), `SearchService.hybrid_merge()` combining FTS5 + embeddings, "similar nodes" feature
- Results stored as annotations, queryable via search

**Blockers:** 7.1 (FTS5), 6.1 (annotations).

✅ Can detect and track behavioral patterns across models and conversations.

### 13.3 — Analysis Skills & Templates 🔀

**Tasks:**
- `AnalysisSkill` ABC: `name`, `analyze(nodes) -> AnalysisResult`
- Built-in skills: `LinguisticMarkerSkill` (hedging, denial, defensive language), `CoherenceScoreSkill`, `LogprobAnalysisSkill` (uncertainty patterns, entropy), `TemporalMarkerSkill`, `SelfReferenceSkill`
- Plugin system: load skills from `skills/` directory
- Skill runner UI: select nodes, pick skill, see results (stored as annotations)
- **Conversation templates / research protocols**: pre-built tree starters for specific research questions (sycophancy testing, persona consistency, emotional response patterns). Shareable as JSON

**Blockers:** 6.1 (annotations for storing skill results).

✅ Built-in skills produce useful analysis. Templates shareable. **Phase 13 complete.**

---

## Phase 14: Settings & Ecosystem

_Goal: First-class settings experience. Community-deployable research tool._

### 14.1 — Settings Panel 🔀

**Tasks:**
- **API key management**: configure provider API keys through the UI (stored encrypted, not in `.env`). Connection testing per provider — verify the key works before saving
- **Custom model registration**: add models not in the suggested list. Specify provider, model ID, context window size, capabilities
- **Global defaults**: default provider, model, system prompt, sampling params. Applied to new trees
- **Provider health dashboard**: show which providers are configured, connected, and responding

**Blockers:** None (independent infrastructure).

✅ Can configure providers and models without editing `.env`. Connection testing works.

### 14.2 — MCP Client Integration 🔀

**Tasks:**
- MCP client: connect to configured servers (`mcp_servers.yml`), discover tools, wire into generation
- Tool calls and results stored as `role: "tool"` nodes
- Tool approval UI: researcher can approve/deny tool calls before execution
- Shared infrastructure with 11.2 (model-queryable memories use same tool-calling path)

**Blockers:** Phase 8 complete (generation modes stable).

✅ Models can use external tools via MCP.

### 14.3 — Maintenance & Deployment 🔀

**Tasks:**
- Garbage collection: `POST /api/maintenance/gc` with preview, confirmation, and grace period before purge. Logged as `GarbageCollected` events
- Multi-device sync: event exchange between instances, conflict resolution (tree structure resolves most conflicts naturally)
- Docker image: single `docker-compose up` for the full stack
- Deployment guide, provider setup guides, research workflow guide, API documentation

**Blockers:** Everything else should be stable.

✅ A new researcher can go from zero to running Qivis with one page of instructions. **Phase 14 complete. Qivis is a community-deployable research tool.**

---

## Future Ideas

Ideas noted for consideration beyond the current roadmap:

- **Image generation**: support for models with image output (DALL-E, future Claude image generation). Fundamentally different generation mode — nodes would store image outputs alongside or instead of text
- **Conversation templates marketplace**: community-contributed shareable research protocols beyond local templates
- **Real-time collaboration**: multiple researchers on the same tree simultaneously. Event sourcing makes this architecturally straightforward to add later
- **Postgres migration**: for multi-user deployments. SQLite is single-researcher; Postgres enables shared instances
- **Custom research scripting**: embedded scripting environment (Python or similar) for researchers to write custom analysis pipelines that interact with the Qivis API. Like a Jupyter notebook integrated into the tool — define custom experiments, transformations, and visualizations without modifying the codebase

---

## Dependency Graph

```
Phase 0 ✅ → Phase 1 ✅ → Phase 1b ✅
                                ↓
                          Phase 2 ✅ (Essentials)
                                ↓
                          Phase 3 ✅ (Uncertainty)
                                ↓
                          Phase 4 ✅ (Structure)
                                ↓
                          Phase 5 ✅ (Transparency)
                                ↓
                          Phase 6 ✅ (Instrumentation)
                                ↓
                     Interlude (Fixes + Debt)
                                ↓
                          Phase 7 (Corpus/Search)
                           ↓         ↘
                     Phase 8          7.4 (parallel)
                  (Gen Modes +
                   Local Models)
                        ↓
                     Phase 9
                (Research Tools)
                        ↓
                    Phase 10
                 (Multi-Agent)
                        ↓
                    Phase 11
                  (Memory System)
                        ↓
                    Phase 12
                  (Multimodal)
                        ↓
                    Phase 13
                  (Analysis)
                        ↓
                    Phase 14
                  (Ecosystem)

  Phase 14.1 (Settings) ────── independent, do whenever
  Phase 8.2 (Local Models) ─── can pull forward if hardware available
```

**Parallelism notes:**
- Phase 14.1 (Settings Panel) is independent of other phases. Can be done whenever.
- Phase 8.2 (Local Providers) can be pulled forward independently if hardware is available.
- Within phases, 🔀 subphases can be parallelized.
- UX polish interludes can be interjected between any phases as needed.
- Phase 11 (Memory System) has dependencies on both Phase 7 (search) and Phase 13 (analysis skills for auto-creation). 11.1 and 11.2 can start after Phase 7; 11.3 needs Phase 13.2.

---

## Notes for Claude Code Handoff

When handing this plan to Claude Code:

1. **One subphase at a time.** Say "Implement 7.1" not "Build Phase 7."
2. **Definition of done matters.** Each ✅ is the acceptance criteria. Don't move on until it passes.
3. **The architecture doc is the source of truth** for data structures, event types, and API shapes. This plan is the *order* to build them in. The architecture doc needs updating (listed in Interlude).
4. **Tests as you go.** Each subphase should have tests before moving to the next, especially event store, context builder, and new event types — these are load-bearing.
5. **Frontend can lag.** It's OK if the frontend is a phase behind the backend. The API is the real interface; the UI catches up.
6. **Frontend components are exempt from test-first.** Backend follows contract tests → integration tests → implement → cleanup → regression. Frontend React components are manually tested.
7. **Subphase sizing matters.** Keep subphases large enough for real design decisions and discovery, not mechanical fill-in. The work is more alive when there's friction, surprise, or enough surface area to find its shape.
