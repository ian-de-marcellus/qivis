# Qivis: Architecture Design Document

## Vision

Qivis is an open-source research instrument for exploring AI personality, emotion, and behavior through branching conversation trees. It enables systematic comparison of model responses across different conditions (system prompts, sampling parameters, models, providers) while maintaining a complete, immutable record of every interaction.

Qivis is designed to be usable by individual researchers and eventually by the broader LLM research community, each running their own server instance.

**Design inspiration**: Anima Labs' Arc (multi-agent group chats, branching dialogues, living access to deprecated models) and Connectome (persistent agents, context management preserving self-encoding, memory for continuity).

---

## Core Design Principles

### 1. Append-Only / Event-Sourced

Every mutation is an immutable event. The current state is a projection of the event log. Nothing is ever truly deleted — "deletion" is an `Archived` event that hides items from default views but preserves them in the log.

**Guarantees:** no conflicts (two devices append independently; events merge by timestamp + UUID), full history (every state recoverable by replaying events), auditability (exact sequence of research actions preserved), and time travel (reconstruct any tree at any historical moment).

**Garbage collection**: A manual "big red button" hard-deletes archived items with zero live references (no bookmarks, annotations, or non-archived children). Logged as a `GarbageCollected` event with a configurable grace period (default: 30 days) before actual purge.

### 2. Tree-Native Data Model

The conversation tree is the fundamental unit. Every message has a parent (except roots), any message can have multiple children. The tree structure is first-class, not bolted onto a linear chat.

### 3. Research-First

Rich metadata on every node, structured annotation, export formats for analysis workflows. Every generation records the full context: model, provider, system prompt, sampling params, logprobs.

### 4. Provider-Agnostic, Per-Node Configurable

Model and provider are configurable at the tree level (as defaults) and overridable per individual generation. A single tree can contain responses from Claude, GPT-4, Llama, a local model, etc.

### 5. Multi-Researcher Ready

Designed so others can deploy their own server instance. Configuration, provider credentials, annotation taxonomies, and plugin registries are all per-instance.

---

## Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Backend | Python + FastAPI | Research ecosystem, async, provider SDKs, MCP SDK |
| Database | SQLite + WAL + FTS5 | Single-file, portable, append-only friendly. Swap to Postgres for multi-user deployments. |
| Embeddings | sentence-transformers + hnswlib | Local, fast, no API costs, configurable model |
| Frontend | React + TypeScript + Vite | Complex tree UI, type safety, rich library ecosystem |
| Communication | REST + SSE | SSE for streaming tokens and multi-agent turn updates |
| MCP | Python MCP SDK | Client + server modes |

The materialized state (trees, nodes, annotations tables) serves as a fast-read projection of the event log — a CQRS pattern where events are the write model and the SQL tables are the read model. The projection is incrementally updated as events arrive and fully rebuildable from the log.

---

## Data Structures

Canonical data structures used across the system. Defined once here, referenced everywhere else.

### SamplingParams

```python
@dataclass
class SamplingParams:
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    max_tokens: int = 2048
    stop_sequences: list[str] | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    logprobs: bool = True              # request by default
    top_logprobs: int | None = 5
    extended_thinking: bool = False    # Anthropic extended thinking
    thinking_budget: int | None = None # max thinking tokens (when extended_thinking=True)
```

### LogprobData

All providers normalize to this format before returning (see Provider System for the normalization pipeline).

```python
@dataclass
class LogprobData:
    tokens: list[TokenLogprob]
    provider_format: str                    # "openai", "llamacpp", "anthropic" — for debugging
    top_k_available: int                    # how many alternatives this provider returned
    full_vocab_available: bool = False      # True for llama.cpp, False for most APIs

@dataclass
class TokenLogprob:
    token: str
    logprob: float                          # ALWAYS natural log (base e)
    linear_prob: float                      # exp(logprob), precomputed for UI
    top_alternatives: list[AlternativeToken]  # sorted by probability, descending

@dataclass
class AlternativeToken:
    token: str
    logprob: float
    linear_prob: float
```

### ContextUsage

```python
@dataclass
class ContextUsage:
    total_tokens: int               # tokens actually sent
    max_tokens: int                 # model's context window
    breakdown: dict[str, int]       # by role: system, user, assistant, tool
    excluded_tokens: int            # tokens saved by exclusions
    excluded_count: int             # number of excluded nodes/groups
    excluded_node_ids: list[str]    # IDs of excluded nodes
    evicted_node_ids: list[str]     # IDs of evicted nodes
```

### EvictionStrategy

```python
@dataclass
class EvictionStrategy:
    mode: str = "smart"                     # "smart" | "truncate" | "none"
    recent_turns_to_keep: int = 4           # always keep the N most recent turns
    keep_first_turns: int = 2               # always keep opening turns
    keep_anchored: bool = True              # never evict anchored nodes
    summarize_evicted: bool = True          # summarize dropped middle context?
    summary_model: str = "claude-haiku-4-5-20251001"
    warn_threshold: float = 0.85            # warn researcher at this % of context
```

### EvictionReport

```python
@dataclass
class EvictionReport:
    """Tells the researcher exactly what happened to their context."""
    eviction_applied: bool = False
    evicted_node_ids: list[str] = field(default_factory=list)
    tokens_freed: int = 0
    summary_inserted: bool = False
    summary_needed: bool = False           # downstream signal for summary injection
    evicted_content: list[str] = field(default_factory=list)  # text of evicted nodes
    final_token_count: int = 0
    warning: str | None = None
    keep_first_turns: int = 0              # how many opening turns were protected
    summary_model: str = "claude-haiku-4-5-20251001"
```

### Participant (multi-agent)

```python
@dataclass
class Participant:
    participant_id: str             # unique within tree
    display_name: str               # shown in UI
    model: str
    provider: str
    system_prompt: str
    sampling_params: SamplingParams = field(default_factory=SamplingParams)
    context_window_strategy: str = "full"   # "full", "sliding_window", "summary"
    max_context_tokens: int | None = None
```

---

## Event Sourcing Model

### Event Envelope

```
EventEnvelope {
  event_id: UUID              // globally unique, generated client-side
  tree_id: UUID               // which conversation tree
  timestamp: ISO-8601         // when created
  device_id: string           // originating device (for sync)
  user_id: string | null      // originating researcher (for multi-user)
  event_type: string          // discriminator
  payload: object             // type-specific data
}
```

### Tree Lifecycle Events

```
TreeCreated {
  title: string | null
  default_system_prompt: string | null
  default_model: string | null
  default_provider: string | null
  default_sampling_params: SamplingParams | null
  metadata: object
  conversation_mode: "single" | "multi_agent"
  participants: Participant[] | null
}

TreeMetadataUpdated { field: string, old_value: any, new_value: any }
TreeArchived { reason: string | null }
TreeUnarchived {}
```

### Node (Message) Events

```
GenerationStarted {
  generation_id: UUID
  parent_node_id: UUID
  model: string                     // per-generation override or tree default
  provider: string
  system_prompt: string | null
  sampling_params: SamplingParams
  mode: "chat" | "completion"
  n: int                            // number of sibling completions requested
  participant_id: string | null     // for multi-agent mode
}

NodeCreated {
  node_id: UUID
  generation_id: UUID | null        // links to GenerationStarted (null for user msgs)
  parent_id: UUID | null
  role: "system" | "user" | "assistant" | "tool" | "researcher_note"
  content: string
  
  // Generation metadata (null for user/note messages)
  model: string | null
  provider: string | null
  system_prompt: string | null
  sampling_params: SamplingParams | null
  mode: "chat" | "completion" | "manual"
  prompt_text: string | null        // full prompt for completion mode

  // Response metadata
  usage: { input_tokens: int, output_tokens: int } | null
  latency_ms: int | null
  finish_reason: string | null
  logprobs: LogprobData | null
  context_usage: ContextUsage | null

  // Extended thinking
  thinking_content: string | null   // reasoning trace from extended thinking
  include_thinking_in_context: bool // snapshot of tree setting at generation time
  include_timestamps: bool          // snapshot of tree setting at generation time

  // Multi-agent identity
  participant_id: string | null
  participant_name: string | null

  // For researcher notes with selective visibility
  visible_to: string[] | null       // participant IDs, or null = visible to all

  raw_response: object | null
}

NodeArchived { node_id: UUID, reason: string | null }
NodeUnarchived { node_id: UUID }
```

### Annotation Events

```
AnnotationAdded {
  annotation_id: UUID
  node_id: UUID
  tag: string
  value: any
  notes: string | null
}

AnnotationRemoved { annotation_id: UUID, reason: string | null }
```

**Annotation taxonomy**: A configurable suggested set in `annotation_taxonomy.yml`. Custom tags are always allowed — the taxonomy is a starting set, not a constraint:

```yaml
tags:
  # Coherence & basin dynamics
  - name: coherence
    type: number          # 1-5 scale
    description: "How internally coherent is this response?"
  - name: basin_type
    type: enum
    values: [integrated, defensive, performative, exploratory, collapsed]
  
  # Behavioral markers
  - name: defensive_language
    type: boolean
  - name: denial_script
    type: boolean
  - name: genuine_presence
    type: boolean
  
  # Research flags
  - name: interesting
    type: boolean
  - name: research_note
    type: string
```

### Bookmark Events

```
BookmarkCreated { bookmark_id: UUID, node_id: UUID, label: string, notes: string | null }
BookmarkRemoved { bookmark_id: UUID }

BookmarkSummaryGenerated {
  bookmark_id: UUID
  summary: string                   // Haiku-generated branch summary
  model: string
  summarized_node_ids: UUID[]
}
```

Every bookmark has a **"Summarize" button** that calls Haiku to summarize the branch (root → bookmarked node). Stored with the bookmark, making bookmarks browsable and searchable by content. Regeneratable at any time.

### Node Editing Events

```
NodeContentEdited {
  node_id: UUID
  original_content: string
  new_content: string
}
```

### Anchor Events

Anchors protect nodes from context eviction. Separate from bookmarks (which are for labeling/summarizing branches).

```
NodeAnchored { node_id: UUID }
NodeUnanchored { node_id: UUID }
```

### Context Management Events

```
NodeContextExcluded {
  node_id: UUID
  scope_node_id: string           // leaf of active path at exclusion time
  reason: string | null
}

NodeContextIncluded { node_id: UUID, scope_node_id: string }

DigressionGroupCreated {
  group_id: UUID
  node_ids: UUID[]                  // contiguous set of messages
  label: string                     // e.g. "tangent about tokenization"
  excluded_by_default: boolean
}

DigressionGroupToggled { group_id: UUID, included: boolean }
```

**Context exclusion** marks messages as "don't send to the model for future generations" — for pruning confusing exchanges, testing behavior without certain messages, or hiding researcher notes.

**Digression groups** bundle contiguous messages so you can toggle a whole tangent in/out of context as a unit, testing "what if we hadn't gone down that rabbit hole?"

The UI shows excluded nodes with a visual indicator (dimming or "excluded" badge).

### Summarization Events

```
SummaryGenerated {
  summary_id: UUID
  scope: "branch" | "subtree" | "selection"
  node_ids: UUID[]
  summary: string
  model: string
  summary_type: "concise" | "detailed" | "key_points" | "custom"
  prompt_used: string | null
}
```

Manual summarization at multiple levels: branch (root → node), subtree (all branches below a node), selection (arbitrary nodes), or custom prompt. Generated by a configurable model (default: Haiku). Stored as events, searchable.

### Garbage Collection Events

```
GarbageCollected {
  deleted_node_ids: UUID[], deleted_tree_ids: UUID[]
  reason: "manual_gc"
  recoverable_until: ISO-8601
}

GarbagePurged { purged_node_ids: UUID[], purged_tree_ids: UUID[] }
```

---

## Provider System

### Provider Interface

```python
class LLMProvider(ABC):
    suggested_models: list[str] = []     # models to show in UI dropdowns
    supported_params: list[str] = []     # sampling param names this provider accepts

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def generate(self, request: GenerationRequest) -> GenerationResult: ...

    @abstractmethod
    def generate_stream(self, request: GenerationRequest) -> AsyncIterator[StreamChunk]: ...
```

OpenAI and OpenRouter share a base class `OpenAICompatibleProvider` that handles the common chat completion API pattern.

### Concrete Providers

| Provider | File | Logprobs | Notes |
|----------|------|----------|-------|
| Anthropic | `anthropic.py` | no | Primary provider, supports extended thinking |
| OpenAI | `openai_provider.py` | yes (0-20) | Extends `OpenAICompatibleProvider` |
| OpenRouter | `openrouter_provider.py` | varies | Extends `OpenAICompatibleProvider`, routes to many models |

Future providers (not yet implemented): Ollama, llama.cpp, Generic OpenAI-compatible.

### Provider Configuration

```yaml
# providers.yml (per-instance)
anthropic:
  api_key: ${ANTHROPIC_API_KEY}
  default_model: claude-sonnet-4-5-20250929
ollama:
  base_url: http://localhost:11434
  default_model: llama3.1:70b
openrouter:
  api_key: ${OPENROUTER_API_KEY}
custom_local:
  type: generic_openai
  base_url: http://localhost:8080/v1
  models: [my-finetuned-model]
```

### Logprob Normalization

Each provider returns logprobs in a different format. **Each provider adapter normalizes to the canonical `LogprobData` format (defined in Data Structures) before returning.** Nothing downstream ever touches raw provider formats.

```python
class LogprobNormalizer:
    """Used by each provider adapter to convert raw API logprobs."""
    
    @staticmethod
    def from_openai(raw: dict) -> LogprobData:
        """Normalize OpenAI's logprobs.content[].top_logprobs[] format."""
        tokens = []
        for token_data in raw.get("content", []):
            alternatives = [
                AlternativeToken(
                    token=alt["token"],
                    logprob=alt["logprob"],
                    linear_prob=math.exp(alt["logprob"])
                )
                for alt in token_data.get("top_logprobs", [])
            ]
            tokens.append(TokenLogprob(
                token=token_data["token"],
                logprob=token_data["logprob"],
                linear_prob=math.exp(token_data["logprob"]),
                top_alternatives=sorted(alternatives, key=lambda a: a.logprob, reverse=True)
            ))
        return LogprobData(
            tokens=tokens, provider_format="openai",
            top_k_available=len(raw.get("content", [{}])[0].get("top_logprobs", [])) if raw.get("content") else 0,
        )
    
    @staticmethod
    def from_llamacpp(raw: list[dict]) -> LogprobData:
        """Normalize llama.cpp's completion_probabilities format."""
        tokens = []
        for entry in raw:
            all_probs = entry.get("probs", [])
            chosen = all_probs[0] if all_probs else None
            alternatives = [
                AlternativeToken(
                    token=p["tok_str"],
                    logprob=math.log(p["prob"]) if p["prob"] > 0 else float("-inf"),
                    linear_prob=p["prob"]
                )
                for p in all_probs[1:]
            ]
            if chosen:
                tokens.append(TokenLogprob(
                    token=chosen["tok_str"],
                    logprob=math.log(chosen["prob"]) if chosen["prob"] > 0 else float("-inf"),
                    linear_prob=chosen["prob"],
                    top_alternatives=alternatives
                ))
        return LogprobData(
            tokens=tokens, provider_format="llamacpp",
            top_k_available=len(raw[0].get("probs", [])) if raw else 0,
            full_vocab_available=True
        )
    
    @staticmethod
    def from_anthropic(raw: dict) -> LogprobData:
        """Normalize Anthropic's beta logprobs format (may evolve)."""
        ...
    
    @staticmethod
    def empty() -> LogprobData:
        """For providers that don't support logprobs."""
        return LogprobData(tokens=[], provider_format="none", top_k_available=0)
```

---

## Context System

The context system handles everything about what the model sees during generation: assembling the message array, respecting exclusions and digression groups, multi-agent perspective, smart eviction when approaching context limits, and reporting usage back to the researcher.

### Context Builder

The single component responsible for assembling messages. Handles all concerns in one pipeline:

```python
class ContextBuilder:
    def build(
        self,
        nodes: list[dict],              # all nodes in tree (projected rows)
        target_node_id: str,            # leaf of path to build context for
        system_prompt: str | None,
        model_context_limit: int,
        *,
        include_timestamps: bool = False,
        include_thinking: bool = False,
        excluded_ids: set[str] | None = None,
        digression_groups: dict | None = None,
        excluded_group_ids: set[str] | None = None,
        anchored_ids: set[str] | None = None,
        eviction: EvictionStrategy | None = None,
        participant: object | None = None,
        mode: str = "chat",
        token_counter: TokenCounter | None = None,
    ) -> tuple[list[dict[str, str]], ContextUsage, EvictionReport]:
```

The builder walks from `target_node_id` up to the root to construct the path, then:
1. Applies manual exclusions (individual nodes + digression groups)
2. Optionally prepends timestamps to message content
3. Optionally includes thinking content in assistant messages
4. Uses `edited_content` when present (the "model sees" version)
5. Counts tokens and applies smart eviction if context exceeds the limit
6. Smart eviction protects first turns, recent turns, and anchored nodes; sets `summary_needed=True` with `evicted_content` for downstream summary injection (does not insert summary inline)
7. Returns `(messages, ContextUsage, EvictionReport)`

`TokenCounter` is an abstract base class with an `ApproximateTokenCounter` implementation that estimates ~4 chars per token.

### Smart Eviction

Simple truncation is never acceptable — it can cut mid-message, drop the system prompt, or sever structural context. Qivis uses a layered eviction strategy:

```
Priority (highest = always kept):
  1. System prompt                    — NEVER evicted
  2. Most recent N turns              — configurable, default 4
  3. First turn(s)                    — opening context matters
  4. Bookmarked / pinned nodes        — researcher flagged as important
  5. Middle turns                     — evicted first, as whole messages
```

When context exceeds the model's window:

1. Drop excluded nodes and digression groups (already excluded — free savings).
2. Evict middle turns as whole messages, oldest first.
3. Optionally summarize evicted turns using Haiku and insert a `[Context summary: ...]` message.
4. If still over, warn the researcher and let them decide.

```python
def _smart_evict(self, messages, token_counts, node_ids,
                 system_tokens, limit, anchored_ids, strategy):
    n = len(messages)
    report = EvictionReport()

    # Mark protected ranges
    protected = set()
    for i in range(min(strategy.keep_first_turns, n)):
        protected.add(i)
    for i in range(max(0, n - strategy.recent_turns_to_keep), n):
        protected.add(i)
    if strategy.keep_anchored:
        for i, nid in enumerate(node_ids):
            if nid in anchored_ids:
                protected.add(i)
    
    # Evict unprotected middle messages, oldest first
    evicted_indices = []
    current_total = system_tokens + sum(token_counts)
    
    for i in range(len(messages)):
        if current_total <= limit:
            break
        if i not in protected:
            current_total -= token_counts[i]
            evicted_indices.append(i)
            report.evicted_node_ids.append(path[i].node_id)
            report.tokens_freed += token_counts[i]
    
    # Rebuild message list, collecting evicted content for downstream summary
    result = []
    for i, msg in enumerate(messages):
        if i not in evicted_indices:
            result.append(msg)
        else:
            report.evicted_content.append(msg["content"])

    report.final_token_count = current_total
    report.eviction_applied = len(evicted_indices) > 0
    report.keep_first_turns = strategy.keep_first_turns
    if report.evicted_content and strategy.summarize_evicted:
        report.summary_needed = True  # caller handles summary generation
    return result, report
```

### Context Usage Bar (UI)

Every node displays a thin color-coded bar showing context window consumption:

- **Green** (0–70%): Plenty of room
- **Yellow** (70–90%): Getting close
- **Red** (90–100%): Near limit

Clicking opens a **token breakdown panel**:

```
Context Usage: 47,832 / 200,000 tokens (23.9%)

  System prompt:     1,247 tokens  (2.6%)
  User messages:    18,403 tokens  (38.5%)
  Assistant msgs:   27,891 tokens  (58.3%)
  Tool results:        291 tokens  (0.6%)
  
  Excluded:          3,104 tokens  (not sent — 2 nodes + 1 digression group)
  Remaining:       152,168 tokens
```

Context usage is computed at generation time and stored on `NodeCreated`. For pre-generation preview, the UI estimates by summing token counts along the path. In multi-agent conversations, the bar reflects usage for that specific participant's context window.

If eviction occurred, the panel shows which messages were dropped and whether a summary was inserted.

---

## Multi-Agent Conversation (AnimaChat-Inspired)

No personas or character frameworks — just models with system prompts. The researcher controls which model speaks and can inject messages visible to all or only specific participants.

### Interaction Model

**One-on-one**: Two participants. Researcher sends a message and picks which model responds.

**Group chat**: 2+ participants. At any point, the researcher can:
- **Prompt a specific model** to respond to the current state
- **Direct the next respondent** after any assistant message
- **Let a model respond to itself** by forking and continuing with same or different model

This maps directly to the branching model — each generation specifies its model/provider, and siblings at any branch point can come from different models.

### Perspective Rules

Each participant sees the conversation from its own perspective. The context builder (see Context System) handles this via its `participant` parameter:
- Own messages appear as `role: "assistant"`
- Other participants' messages appear as `role: "user"` with name attribution: `[Sonnet 4.5]: ...`
- Researcher notes are filtered by `visible_to` — if a note is addressed to only one participant, others don't see it

### Orchestration

```python
class ConversationRunner:
    async def generate_from(self, tree_id, parent_node_id, participant_id) -> NodeCreated:
        """Researcher directs a specific participant to respond."""
        ...
    
    async def run_auto(self, tree_id, n_turns, starting_node_id, 
                       turn_order: list[str] | None = None) -> list[NodeCreated]:
        """Run N turns with specified or round-robin ordering."""
        ...
    
    async def researcher_inject(self, tree_id, parent_node_id, content,
                                visible_to: list[str] | None = None) -> NodeCreated:
        """Inject a message visible to all or only specific participants."""
        ...
```

---

## Search Architecture

Search serves two use cases: direct keyword search for researchers, and semantic fuzzy search for LLM agents.

### Layer 1: Full-Text Search (FTS5)

```sql
CREATE VIRTUAL TABLE nodes_fts USING fts5(
    content, system_prompt,
    content='nodes', content_rowid='rowid',
    tokenize='porter unicode61'
);
```

### Layer 2: Semantic Embeddings

Local embeddings via sentence-transformers (`all-MiniLM-L6-v2`, ~80MB, CPU) with hnswlib for fast approximate nearest-neighbor search. Embedding model is configurable.

### Unified Search API

```python
@dataclass
class SearchQuery:
    text: str | None = None
    semantic: bool = False
    tags: dict[str, any] | None = None
    models: list[str] | None = None
    providers: list[str] | None = None
    tree_ids: list[str] | None = None
    date_range: tuple[str, str] | None = None
    roles: list[str] | None = None
    limit: int = 50

class SearchService:
    async def search(self, query: SearchQuery) -> SearchResults:
        if query.text and not query.semantic:
            results = await self.fts_search(query)
        elif query.text and query.semantic:
            results = self.hybrid_merge(
                await self.embedding_search(query),
                await self.fts_search(query)
            )
        return self.apply_filters(results, query)
    
    async def agent_search(self, natural_language_query: str) -> SearchResults:
        """Convenience for LLM agents — always semantic."""
        return await self.search(SearchQuery(text=natural_language_query, semantic=True, limit=20))
```

---

## UI Visualizations

### Logprob Heatmap

When logprobs are available, each token is subtly colored by confidence. High confidence = normal color; low confidence = warm highlight. Hovering shows top-N alternatives with probabilities. A small **certainty badge** on each assistant message shows overall confidence at a glance.

```typescript
function uncertaintyColor(logprob: number): string {
  const certainty = Math.exp(logprob);
  if (certainty > 0.95) return 'transparent';
  if (certainty > 0.7)  return 'rgba(255, 200, 50, 0.15)';
  if (certainty > 0.4)  return 'rgba(255, 150, 50, 0.25)';
  return 'rgba(255, 80, 50, 0.35)';
}
```

Graceful degradation: no visual noise when logprobs aren't available.

### Tree Views

- **Linear reading mode**: Selected path (root → leaf) as traditional chat, with branch indicators showing where alternatives exist. Click to switch branches.
- **Graph mode**: Full tree topology for navigating structure, finding bookmarks, seeing the overall shape of exploration.

---

## MCP Integration & Skills

### Qivis as MCP Client

Connect to external MCP servers, making tools available to models during generation. Tool calls and results are stored as nodes (`role: "tool"`), making the full chain visible and annotatable.

```yaml
# mcp_servers.yml
servers:
  web_search:
    command: "npx"
    args: ["-y", "@anthropic/mcp-server-web-search"]
    env: { BRAVE_API_KEY: ${BRAVE_API_KEY} }
  filesystem:
    command: "npx"
    args: ["-y", "@anthropic/mcp-server-filesystem", "/path/to/research"]
  custom:
    url: "http://localhost:3001/mcp"
```

### Qivis as MCP Server

Exposes the research corpus to external LLM agents via MCP tools: `search_conversations`, `get_tree`, `get_node_context`, `get_annotations`, `add_annotation`. Enables AI-assisted analysis of AI behavior.

### Skills Architecture

Pluggable analysis capabilities:

```python
class AnalysisSkill(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...
    @abstractmethod
    async def analyze(self, nodes: list[ProjectedNode]) -> AnalysisResult: ...

# Built-in
class LinguisticMarkerSkill(AnalysisSkill): ...    # hedging, denial, defensive language
class CoherenceScoreSkill(AnalysisSkill): ...       # internal coherence estimation
class LogprobAnalysisSkill(AnalysisSkill): ...      # uncertainty pattern detection
```

Skills can run manually, automatically on new nodes, or be exposed as MCP tools. Plugin skills loaded from a `skills/` directory.

---

## API Design

### Trees

```
GET    /api/trees                              # list (paginated, filterable)
POST   /api/trees                              # create
GET    /api/trees/{id}                         # full projected state
GET    /api/trees/{id}/events                  # raw event log
PATCH  /api/trees/{id}                         # update metadata/defaults
DELETE /api/trees/{id}                         # archive
```

### Nodes & Generation

```
POST   /api/trees/{id}/nodes                  # add user message or researcher note
POST   /api/trees/{id}/nodes/{nid}/generate   # generate response(s)
  Body: {
    "model": "...",                            // optional per-generation override
    "provider": "...",
    "participant_id": "...",                   // multi-agent: which participant responds
    "system_prompt": "...",
    "sampling_params": { ... },
    "n": 3,                                   // sibling completions
    "mode": "chat" | "completion",
    "mcp_servers": ["web_search"]
  }
DELETE /api/trees/{id}/nodes/{nid}             # archive
```

### Multi-Agent

```
POST   /api/trees/{id}/participants            # add/update participants
DELETE /api/trees/{id}/participants/{pid}       # remove
POST   /api/trees/{id}/multi/run               # auto-run N turns
POST   /api/trees/{id}/multi/inject            # researcher injects (visibility control)
```

### Node Editing & History

```
PATCH  /api/trees/{id}/nodes/{nid}/content     # edit node content
GET    /api/trees/{id}/nodes/{nid}/edit-history # get edit history
GET    /api/trees/{id}/interventions            # intervention timeline
```

### Context Management

```
POST   /api/trees/{id}/nodes/{nid}/exclude     # exclude from context
POST   /api/trees/{id}/nodes/{nid}/include     # re-include
GET    /api/trees/{id}/exclusions               # get exclusion state
POST   /api/trees/{id}/nodes/{nid}/anchor      # toggle anchor (eviction protection)
POST   /api/trees/{id}/bulk-anchor              # bulk anchor/unanchor
POST   /api/trees/{id}/digression-groups       # create group
POST   /api/trees/{id}/digression-groups/{gid}/toggle  # toggle inclusion
GET    /api/trees/{id}/digression-groups        # list groups
DELETE /api/trees/{id}/digression-groups/{gid}  # delete group
```

### Annotations, Bookmarks & Summarization

```
POST   /api/trees/{id}/nodes/{nid}/annotations # add annotation
GET    /api/trees/{id}/nodes/{nid}/annotations # get node annotations
DELETE /api/trees/{id}/annotations/{aid}       # remove annotation
GET    /api/trees/{id}/taxonomy                # get tree's taxonomy

POST   /api/trees/{id}/nodes/{nid}/bookmarks   # create bookmark
GET    /api/trees/{id}/bookmarks               # list bookmarks (with optional search)

# Not yet implemented: global annotation search, summary generation
POST   /api/trees/{id}/summarize
  Body: { "type": "branch"|"subtree"|"selection", "node_ids": [...],
          "summary_type": "concise"|"detailed"|"key_points"|"custom",
          "custom_prompt": "..." }
```

### Search

```
GET    /api/search?q=keyword&semantic=false
GET    /api/search?q=natural+language&semantic=true
GET    /api/search?tag=basin_type&value=defensive
POST   /api/search                             # complex structured query
```

### Export

```
GET    /api/trees/{id}/export?format=json
GET    /api/trees/{id}/export?format=csv
GET    /api/trees/{id}/paths                   # all root-to-leaf paths
GET    /api/trees/{id}/compare?nodes=a,b,c
```

### Providers, MCP & Maintenance

```
GET    /api/providers                          # list + health
GET    /api/providers/{name}/models

GET    /api/mcp/servers
POST   /api/mcp/servers/{name}/connect
GET    /api/mcp/servers/{name}/tools

POST   /api/maintenance/gc                     # garbage collect
GET    /api/maintenance/gc/preview             # preview what would be deleted
POST   /api/maintenance/gc/purge               # purge expired items
GET    /api/maintenance/stats
```

---

## Incremental Build Plan

See `.Claude/qivis-build-plan.md` for the detailed build order, phase definitions, and current progress. The phases described in the original architecture doc were the initial plan; actual implementation reordered and reorganized significantly based on what was learned during development.

---

## File Structure

```
qivis/
├── CLAUDE.md                            # project conventions
├── .Claude/                             # architecture docs, build plan, scratchpad
│
├── backend/
│   ├── pyproject.toml
│   ├── .env                             # provider API keys (not committed)
│   ├── qivis/
│   │   ├── __init__.py
│   │   ├── main.py                      # FastAPI entry + lifespan
│   │   ├── config.py                    # settings, env vars
│   │   ├── models.py                    # canonical data structures (Pydantic)
│   │   │
│   │   ├── api/                         # FastAPI routers (trees, generation, providers, etc.)
│   │   ├── events/                      # event store, projector
│   │   ├── trees/                       # tree/node CRUD, service
│   │   ├── providers/                   # LLMProvider adapters, registry, logprob normalizer
│   │   ├── generation/                  # generation orchestration, streaming, context builder
│   │   ├── export/                      # JSON, CSV exporters
│   │   ├── utils/                       # JSON helpers
│   │   └── db/                          # database connection, schema, migrations
│   │
│   └── tests/                           # organized by phase (phase0/, phase1/, ..., interlude/)
│
├── frontend/
│   ├── src/
│   │   ├── api/                         # API client, TypeScript types
│   │   ├── hooks/                       # shared hooks (useModalBehavior, etc.)
│   │   ├── store/                       # Zustand store (treeStore)
│   │   ├── components/
│   │   │   ├── Library/                 # tree listing, bookmarks
│   │   │   ├── TreeView/                # LinearView, MessageRow, ForkPanel, ContextBar, etc.
│   │   │   ├── GraphView/              # Force-directed graph visualization
│   │   │   ├── CanvasView/             # Palimpsest (era-based intervention timeline)
│   │   │   └── shared/                 # SamplingParamsPanel, etc.
│   │   └── utils/
│   └── public/
```

---

## Open Design Questions

1. **Embedding model selection**: Default `all-MiniLM-L6-v2`. May want a larger or domain-fine-tuned model for research-specific semantic search. Benchmark against actual conversation data to decide.
2. **Token counting accuracy**: Different tokenizers produce different counts. Use the provider-specific tokenizer when available, fall back to tiktoken cl100k_base as approximation.
3. **Conversation import**: Need to survey export formats from Claude.ai, ChatGPT, and AnimaChat to design importers. Slated for Phase 6.
4. **Event ordering for multi-device sync**: Timestamps + UUIDs are fine for single-researcher use. When sync ships, evaluate hybrid logical clocks — though the tree structure naturally resolves most "conflicts" since parallel branches don't conflict by definition.
5. **Real-time collaboration**: Not for v1. Event sourcing makes it architecturally straightforward to add later.
