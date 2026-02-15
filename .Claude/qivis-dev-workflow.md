# Qivis: Development Workflow

How to implement each subphase of the build plan. This document governs the development process — the build plan says *what* to build and *when*, the architecture doc says *what it looks like*, and this doc says *how*.

---

## The Loop

Every subphase follows this sequence:

```
1. Write contract tests     — encode what the architecture doc promises
2. Write integration tests  — verify this subphase connects to previous ones
3. Implement                — make all tests pass WITHOUT changing tests
4. Cleanup                  — refactor, edge case tests, best practices
5. Full regression          — run the ENTIRE test suite, fix anything that broke
```

**Do not skip steps. Do not reorder steps.**

---

## Step 1: Contract Tests

Contract tests encode the promises made in the architecture document. They answer: "Does this component do what the spec says it does?"

**What to test:**
- Every public method on every new class or service introduced in this subphase
- The data structures going in and coming out match the spec
- Invariants that the architecture doc explicitly calls out

**Examples:**
- 0.2: "Appending a `TreeCreated` event projects into a row in the `trees` table with matching fields."
- 0.5: "The context builder never produces a messages array that omits the system prompt."
- 2.1: "`LogprobNormalizer.from_llamacpp()` returns `LogprobData` with `full_vocab_available=True` and all logprobs as natural log."
- 3.3: "A node in `excluded_ids` does not appear in the built messages array."
- 4.2: "A participant sees its own messages as `role: assistant` and others' as `role: user` with name prefix."

**Rules:**
- These tests must be implementable *before* the production code exists (they will fail — that's the point).
- They should reference the architecture doc's data structures and behavior descriptions directly.
- They should be independent of implementation details — test the *what*, not the *how*.

---

## Step 2: Integration Tests

Integration tests verify that the new subphase connects correctly to everything built before it. They answer: "Does the system still work as a whole with this new piece?"

**What to test:**
- The API endpoint(s) introduced in this subphase, end-to-end
- The event flow: action → event emitted → state projected → queryable via API
- Cross-subphase interactions (e.g., after 0.5, test that generation uses the context builder, not just that the context builder works in isolation)

**Examples:**
- 0.4: "POST /api/trees/{id}/nodes/{nid}/generate returns a new node with role=assistant. GET /api/trees/{id} includes both the user message and the assistant response."
- 1.3: "Generate with `model` override stores the override model on the node, not the tree default."
- 3.4: "In a conversation that exceeds context limits, the generation still succeeds, the response is coherent, and the `EvictionReport` shows which nodes were evicted."

**Rules:**
- Integration tests from previous subphases must still pass. If they don't, the new code broke something — fix it before proceeding.
- Integration tests should use the actual API (TestClient/httpx), not call service methods directly.
- Each subphase adds to the integration test suite — it never shrinks.

---

## Step 3: Implement

Write production code that makes all tests from Steps 1 and 2 pass.

**Rules:**

- **Do not modify tests to make them pass.** If a test seems wrong, stop and flag it. The only acceptable reasons to change a test are:
  1. The test has a genuine bug (typo, wrong assertion, setup error)
  2. The architecture doc was ambiguous and the test made an incorrect assumption
  - In both cases: explain the issue, propose the fix, and wait for confirmation before changing the test.

- **Implement the minimum code to pass tests.** Don't build ahead. If the tests for this subphase don't cover something, it belongs in a later subphase.

- **Follow the architecture doc's structure.** Put code in the modules the file structure specifies. Use the class names and method signatures from the spec. Don't invent new abstractions unless the tests require them.

---

## Step 4: Cleanup

With all tests green, refactor for quality.

**Tasks:**
- Remove dead code, unused imports
- Ensure consistent naming conventions
- Add docstrings to public methods
- Add type hints everywhere
- Check for error handling gaps — add edge case tests for anything discovered
- Ensure logging at appropriate levels (info for events, warning for degraded operation, error for failures)
- Check for any hardcoded values that should be configurable

**Edge case tests written here are the exception to the "tests first" rule.** During implementation, you discover edges you didn't anticipate. Write tests for them now:
- What happens when the input is empty? Null? Absurdly large?
- What happens when an external service (Anthropic API, Ollama) is unreachable?
- What happens when the database is corrupted or the schema is wrong?
- What happens at the boundaries of context limits?

---

## Step 5: Full Regression

Run every test from every previous subphase. All of them.

```bash
pytest tests/ -v
```

**If anything fails, fix it before moving on.** Regressions compound — catching them immediately is cheap, catching them three subphases later is expensive.

---

## Test Infrastructure

### Fixtures (shared across all subphases)

Build a `tests/fixtures.py` module from the start. Each subphase can add fixtures, and later subphases reuse them.

```python
# tests/fixtures.py — grows over time

async def create_test_tree(client, title="Test Tree", system_prompt="You are helpful."):
    """Create a tree and return its ID. Available from 0.3 onward."""
    ...

async def create_tree_with_messages(client, n_messages=4):
    """Create a tree with N alternating user/assistant messages. Available from 0.4 onward."""
    ...

async def create_branching_tree(client):
    """Create a tree with branches: root → A → B, root → A → C. Available from 1.1 onward."""
    ...

async def create_tree_at_context_limit(client, model_limit=4096):
    """Create a tree that's near or over context limit. Available from 0.5 onward."""
    ...

async def create_multi_agent_tree(client, n_participants=2):
    """Create a multi-agent tree with participants. Available from 4.1 onward."""
    ...
```

### Test Directory Structure

```
tests/
├── conftest.py              # pytest fixtures: test database, test client, cleanup
├── fixtures.py              # shared helpers (create_test_tree, etc.)
│
├── phase0/
│   ├── test_event_store.py          # 0.2 — THE canary test (must never break)
│   ├── test_projector.py            # 0.2
│   ├── test_tree_crud.py            # 0.3
│   ├── test_anthropic_provider.py   # 0.4
│   ├── test_generation.py           # 0.4
│   └── test_context_builder.py      # 0.5
│
├── phase1/
│   ├── test_branching.py            # 1.1
│   ├── test_overrides.py            # 1.3
│   ├── test_openai_provider.py      # 1.4
│   └── test_context_usage.py        # 1.5
│
├── phase2/
│   ├── test_ollama_provider.py      # 2.1
│   ├── test_llamacpp_provider.py    # 2.1
│   ├── test_logprob_normalizer.py   # 2.1 (all provider formats)
│   └── test_completion_mode.py      # 2.2
│
├── phase3/
│   ├── test_annotations.py          # 3.1
│   ├── test_bookmarks.py            # 3.2
│   ├── test_context_exclusion.py    # 3.3
│   ├── test_digression_groups.py    # 3.3
│   ├── test_smart_eviction.py       # 3.4
│   ├── test_summarization.py        # 3.5
│   ├── test_export.py               # 3.6
│   └── test_search_fts.py           # 3.7
│
├── phase4/
│   ├── test_participants.py         # 4.1
│   ├── test_multi_agent_context.py  # 4.2
│   ├── test_directed_generation.py  # 4.3
│   └── test_auto_run.py             # 4.4
│
├── phase5/
│   ├── test_embeddings.py           # 5.1
│   ├── test_semantic_search.py      # 5.2
│   ├── test_hybrid_search.py        # 5.2
│   └── test_skills.py               # 5.3
│
├── phase6/
│   ├── test_mcp_client.py           # 6.1
│   ├── test_mcp_server.py           # 6.2
│   ├── test_gc.py                   # 6.3
│   └── test_import.py               # 6.4
│
└── integration/
    ├── test_full_workflow.py         # end-to-end: create → chat → branch → annotate → export
    └── test_regression.py            # cross-phase regression scenarios
```

### The Canary Test

The event store round-trip test written in subphase 0.2 is special. It should be the **first test ever written** and it should **never break for the entire lifetime of the project**:

```python
# tests/phase0/test_event_store.py

async def test_event_roundtrip():
    """THE CANARY. If this fails, something fundamental is broken."""
    store = EventStore(":memory:")
    
    event = TreeCreated(
        tree_id=uuid4(),
        title="Test",
        default_model="claude-sonnet-4-5-20250929",
        ...
    )
    
    await store.append(event)
    events = await store.get_events(event.tree_id)
    
    assert len(events) == 1
    assert events[0].event_type == "TreeCreated"
    assert events[0].payload["title"] == "Test"

async def test_projection_roundtrip():
    """THE OTHER CANARY. Events in, projected state out."""
    store = EventStore(":memory:")
    projector = StateProjector(store)
    
    tree_id = uuid4()
    await store.append(TreeCreated(tree_id=tree_id, title="Test", ...))
    await projector.project()
    
    tree = await projector.get_tree(tree_id)
    assert tree is not None
    assert tree.title == "Test"
```

If either of these fails at any point during development, stop everything and investigate. It means the foundation has cracked.

---

## External Service Mocking

For tests that involve LLM providers (Anthropic, OpenAI, Ollama, etc.):

- **Contract tests**: Mock the HTTP responses. Use `respx` or `httpx_mock` to simulate provider API responses. This makes tests fast, deterministic, and runnable without API keys.
- **Integration tests**: Also mock by default. Optionally support a `--live` flag for running against real APIs (useful for verifying mock accuracy, but not required for CI).
- **Keep mock responses realistic.** Copy actual API response shapes from provider docs. When logprob formats change, update mocks to match.

```python
# Example mock for Anthropic
@pytest.fixture
def mock_anthropic(httpx_mock):
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        json={
            "content": [{"type": "text", "text": "Hello! How can I help you?"}],
            "model": "claude-sonnet-4-5-20250929",
            "usage": {"input_tokens": 25, "output_tokens": 10},
            "stop_reason": "end_turn"
        }
    )
```

---

## Frontend Testing

Frontend subphases (0.6, 1.2, 1.5, 2.3, 2.4, etc.) are **exempt from test-first discipline** for React components. Instead:

- **Do write tests for:** API client functions, state management logic (zustand stores), utility functions (tree traversal, logprob color mapping, token counting)
- **Don't write tests for:** Component rendering, layout, styling, DOM structure
- **Acceptance criteria are manual:** The ✅ in the build plan is the acceptance test. "Can I create a tree, type a message, and see a streaming response?" — verify by using the app.
- **API contract tests (backend side) protect the frontend.** If the backend response shape matches what the frontend types expect, the integration works. TypeScript's type system catches the rest at compile time.

---

## When to Break the Rules

There are exactly three situations where deviating from this workflow is acceptable:

1. **The architecture doc has a gap.** The test requires a decision the spec doesn't make. Stop, make the decision (document it), then write the test.

2. **A test is genuinely wrong.** The test encodes an incorrect assumption. Flag it, explain why it's wrong, propose a fix, get confirmation before changing.

3. **An external dependency behaves differently than expected.** The mock was based on outdated docs, or the provider API has changed. Update the mock to match reality, note the discrepancy.

In all three cases: document what happened and why, so the decision trail is preserved.
