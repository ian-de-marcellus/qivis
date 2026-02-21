import { describe, expect, it } from 'vitest'
import type { NodeResponse } from '../../api/types.ts'
import type { ReconstructedContext } from './contextReconstruction.ts'
import {
  buildComparisonRows,
  buildOriginalContext,
  getPathToNode,
  type TreeDefaults,
} from './contextDiffs.ts'

// -- Helpers for building test fixtures --

function makeNode(overrides: Partial<NodeResponse> & { node_id: string; role: string }): NodeResponse {
  return {
    node_id: overrides.node_id,
    tree_id: 'tree-1',
    parent_id: overrides.parent_id ?? null,
    role: overrides.role,
    content: overrides.content ?? `content of ${overrides.node_id}`,
    model: overrides.model ?? null,
    provider: overrides.provider ?? null,
    system_prompt: overrides.system_prompt ?? null,
    sampling_params: overrides.sampling_params ?? null,
    mode: overrides.mode ?? 'chat',
    prefill_content: overrides.prefill_content ?? null,
    usage: overrides.usage ?? null,
    latency_ms: overrides.latency_ms ?? null,
    finish_reason: overrides.finish_reason ?? null,
    logprobs: overrides.logprobs ?? null,
    context_usage: overrides.context_usage ?? null,
    thinking_content: overrides.thinking_content ?? null,
    edited_content: overrides.edited_content ?? null,
    include_thinking_in_context: overrides.include_thinking_in_context ?? false,
    include_timestamps: overrides.include_timestamps ?? false,
    created_at: overrides.created_at ?? '2026-01-01T00:00:00Z',
    sibling_count: overrides.sibling_count ?? 1,
    sibling_index: overrides.sibling_index ?? 0,
    is_bookmarked: false,
    is_excluded: false,
    is_anchored: false,
    annotation_count: 0,
    note_count: 0,
    edit_count: 0,
    participant_id: overrides.participant_id ?? null,
    participant_name: overrides.participant_name ?? null,
    archived: overrides.archived ?? 0,
  }
}

const defaultTreeDefaults: TreeDefaults = {
  default_system_prompt: 'You are a helpful assistant.',
  default_model: 'test-model',
  default_provider: 'test-provider',
  default_sampling_params: null,
}

// Build a simple ReconstructedContext from a path and target node
function makeReconstructedContext(
  messages: { nodeId: string; role: string; content: string; isExcluded?: boolean; isEvicted?: boolean; wasEdited?: boolean }[],
  overrides?: Partial<ReconstructedContext>,
): ReconstructedContext {
  return {
    systemPrompt: overrides?.systemPrompt ?? 'You are a helpful assistant.',
    messages: messages.map((m) => ({
      role: m.role,
      content: m.content,
      baseContent: m.content,
      nodeId: m.nodeId,
      wasEdited: m.wasEdited ?? false,
      wasManual: false,
      hadThinkingPrepended: false,
      hadTimestampPrepended: false,
      thinkingPrefix: null,
      timestampPrefix: null,
      isExcluded: m.isExcluded ?? false,
      isEvicted: m.isEvicted ?? false,
    })),
    evictedCount: 0,
    evictedTokens: 0,
    excludedCount: 0,
    excludedTokens: 0,
    model: overrides?.model ?? 'test-model',
    provider: overrides?.provider ?? 'test-provider',
    samplingParams: overrides?.samplingParams ?? null,
    timestamp: '2026-01-01T00:00:00Z',
    latencyMs: null,
    usage: null,
    finishReason: null,
    contextUsage: null,
    thinkingContent: null,
    includeThinkingInContext: false,
    includeTimestamps: false,
    ...overrides,
  }
}

// ---- Tests ----

describe('getPathToNode', () => {
  it('walks parent chain root-first', () => {
    const nodes = [
      makeNode({ node_id: 'root', role: 'user', parent_id: null }),
      makeNode({ node_id: 'a1', role: 'assistant', parent_id: 'root' }),
      makeNode({ node_id: 'u2', role: 'user', parent_id: 'a1' }),
      makeNode({ node_id: 'a2', role: 'assistant', parent_id: 'u2' }),
    ]
    const target = nodes[3] // a2
    const path = getPathToNode(target, nodes)
    expect(path.map((n) => n.node_id)).toEqual(['root', 'a1', 'u2'])
  })

  it('returns empty for root node', () => {
    const nodes = [
      makeNode({ node_id: 'root', role: 'user', parent_id: null }),
    ]
    const path = getPathToNode(nodes[0], nodes)
    expect(path).toEqual([])
  })
})

describe('buildOriginalContext', () => {
  it('uses original content (not edited_content)', () => {
    const nodes = [
      makeNode({ node_id: 'root', role: 'user', content: 'original' }),
      makeNode({ node_id: 'a1', role: 'assistant', parent_id: 'root', content: 'response', edited_content: 'EDITED' }),
      makeNode({ node_id: 'u2', role: 'user', parent_id: 'a1', content: 'follow up' }),
      makeNode({ node_id: 'target', role: 'assistant', parent_id: 'u2', content: 'final' }),
    ]
    const ctx = buildOriginalContext(nodes[3], nodes, defaultTreeDefaults)

    // All messages use original content, not edited
    expect(ctx.messages.map((m) => m.content)).toEqual(['original', 'response', 'follow up'])
    expect(ctx.messages.every((m) => !m.wasEdited)).toBe(true)
  })

  it('uses tree-default system prompt', () => {
    const nodes = [
      makeNode({ node_id: 'root', role: 'user' }),
      makeNode({ node_id: 'target', role: 'assistant', parent_id: 'root', system_prompt: 'custom prompt' }),
    ]
    const ctx = buildOriginalContext(nodes[1], nodes, defaultTreeDefaults)
    expect(ctx.systemPrompt).toBe('You are a helpful assistant.')
  })

  it('marks nothing as excluded or evicted', () => {
    const nodes = [
      makeNode({ node_id: 'root', role: 'user' }),
      makeNode({ node_id: 'target', role: 'assistant', parent_id: 'root' }),
    ]
    const ctx = buildOriginalContext(nodes[1], nodes, defaultTreeDefaults)
    expect(ctx.messages.every((m) => !m.isExcluded && !m.isEvicted)).toBe(true)
    expect(ctx.excludedCount).toBe(0)
    expect(ctx.evictedCount).toBe(0)
  })

  it('filters to API roles only', () => {
    const nodes = [
      makeNode({ node_id: 'note', role: 'researcher_note' }),
      makeNode({ node_id: 'root', role: 'user', parent_id: 'note' }),
      makeNode({ node_id: 'target', role: 'assistant', parent_id: 'root' }),
    ]
    const ctx = buildOriginalContext(nodes[2], nodes, defaultTreeDefaults)
    expect(ctx.messages.map((m) => m.role)).toEqual(['user'])
  })
})

describe('buildComparisonRows', () => {
  describe('same path (compare to Original)', () => {
    it('all match when contexts are identical', () => {
      const nodes = [
        makeNode({ node_id: 'u1', role: 'user', content: 'hello' }),
        makeNode({ node_id: 'a1', role: 'assistant', parent_id: 'u1', content: 'hi' }),
        makeNode({ node_id: 'u2', role: 'user', parent_id: 'a1', content: 'how are you' }),
        makeNode({ node_id: 'target', role: 'assistant', parent_id: 'u2', content: 'fine' }),
      ]
      const path = getPathToNode(nodes[3], nodes)
      const ctx = makeReconstructedContext([
        { nodeId: 'u1', role: 'user', content: 'hello' },
        { nodeId: 'a1', role: 'assistant', content: 'hi' },
        { nodeId: 'u2', role: 'user', content: 'how are you' },
      ])
      const original = makeReconstructedContext([
        { nodeId: 'u1', role: 'user', content: 'hello' },
        { nodeId: 'a1', role: 'assistant', content: 'hi' },
        { nodeId: 'u2', role: 'user', content: 'how are you' },
      ])

      const rows = buildComparisonRows(original, ctx, path, path)
      // System prompt match + 3 message matches
      const messageRows = rows.filter((r) => r.nodeId != null)
      expect(messageRows.every((r) => r.type === 'match')).toBe(true)
      expect(messageRows).toHaveLength(3)
    })

    it('detects edited content as content-differs', () => {
      const nodes = [
        makeNode({ node_id: 'u1', role: 'user', content: 'original' }),
        makeNode({ node_id: 'target', role: 'assistant', parent_id: 'u1' }),
      ]
      const path = getPathToNode(nodes[1], nodes)
      const original = makeReconstructedContext([
        { nodeId: 'u1', role: 'user', content: 'original' },
      ])
      const actual = makeReconstructedContext([
        { nodeId: 'u1', role: 'user', content: 'EDITED version', wasEdited: true },
      ])

      const rows = buildComparisonRows(original, actual, path, path)
      const editRow = rows.find((r) => r.nodeId === 'u1')
      expect(editRow?.type).toBe('content-differs')
      expect(editRow?.leftContent).toBe('original')
      expect(editRow?.rightContent).toBe('EDITED version')
    })

    it('detects exclusion status difference', () => {
      const nodes = [
        makeNode({ node_id: 'u1', role: 'user', content: 'hello' }),
        makeNode({ node_id: 'a1', role: 'assistant', parent_id: 'u1', content: 'hi' }),
        makeNode({ node_id: 'target', role: 'assistant', parent_id: 'a1' }),
      ]
      const path = getPathToNode(nodes[2], nodes)
      const original = makeReconstructedContext([
        { nodeId: 'u1', role: 'user', content: 'hello' },
        { nodeId: 'a1', role: 'assistant', content: 'hi' },
      ])
      const actual = makeReconstructedContext([
        { nodeId: 'u1', role: 'user', content: 'hello', isExcluded: true },
        { nodeId: 'a1', role: 'assistant', content: 'hi' },
      ])

      const rows = buildComparisonRows(original, actual, path, path)
      const u1Row = rows.find((r) => r.nodeId === 'u1')
      expect(u1Row?.type).toBe('status-differs')
      expect(u1Row?.leftStatus).toBe('in-context')
      expect(u1Row?.rightStatus).toBe('excluded')
    })
  })

  describe('cross-branch comparison', () => {
    it('shows shared prefix as match and divergent suffixes as fork-pairs', () => {
      // Shared: u1 -> a1
      // Branch A: a1 -> u2a -> targetA
      // Branch B: a1 -> u2b -> targetB
      const shared = [
        makeNode({ node_id: 'u1', role: 'user', content: 'hello' }),
        makeNode({ node_id: 'a1', role: 'assistant', parent_id: 'u1', content: 'hi' }),
      ]
      const branchA = [
        makeNode({ node_id: 'u2a', role: 'user', parent_id: 'a1', content: 'question A' }),
        makeNode({ node_id: 'targetA', role: 'assistant', parent_id: 'u2a' }),
      ]
      const branchB = [
        makeNode({ node_id: 'u2b', role: 'user', parent_id: 'a1', content: 'question B' }),
        makeNode({ node_id: 'targetB', role: 'assistant', parent_id: 'u2b' }),
      ]
      const allNodes = [...shared, ...branchA, ...branchB]

      const pathA = getPathToNode(branchA[1], allNodes) // u1, a1, u2a
      const pathB = getPathToNode(branchB[1], allNodes) // u1, a1, u2b

      const ctxA = makeReconstructedContext([
        { nodeId: 'u1', role: 'user', content: 'hello' },
        { nodeId: 'a1', role: 'assistant', content: 'hi' },
        { nodeId: 'u2a', role: 'user', content: 'question A' },
      ])
      const ctxB = makeReconstructedContext([
        { nodeId: 'u1', role: 'user', content: 'hello' },
        { nodeId: 'a1', role: 'assistant', content: 'hi' },
        { nodeId: 'u2b', role: 'user', content: 'question B' },
      ])

      const rows = buildComparisonRows(ctxA, ctxB, pathA, pathB)

      // System prompt match
      const sysRow = rows.find((r) => r.role === 'system')
      expect(sysRow?.type).toBe('match')

      // Shared messages
      const u1Row = rows.find((r) => r.nodeId === 'u1')
      const a1Row = rows.find((r) => r.nodeId === 'a1')
      expect(u1Row?.type).toBe('match')
      expect(a1Row?.type).toBe('match')

      // Fork point
      const forkRow = rows.find((r) => r.type === 'fork-point')
      expect(forkRow).toBeDefined()

      // Divergent messages are paired side by side
      const pairRow = rows.find((r) => r.type === 'fork-pair')
      expect(pairRow).toBeDefined()
      expect(pairRow?.nodeId).toBe('u2a')
      expect(pairRow?.rightNodeId).toBe('u2b')
      expect(pairRow?.leftContent).toBe('question A')
      expect(pairRow?.rightContent).toBe('question B')
    })

    it('handles no shared prefix (completely different branches)', () => {
      // Two root-level children diverging immediately
      const nodes = [
        makeNode({ node_id: 'u1a', role: 'user', content: 'branch A' }),
        makeNode({ node_id: 'targetA', role: 'assistant', parent_id: 'u1a' }),
        makeNode({ node_id: 'u1b', role: 'user', content: 'branch B' }),
        makeNode({ node_id: 'targetB', role: 'assistant', parent_id: 'u1b' }),
      ]

      const pathA = getPathToNode(nodes[1], nodes)  // [u1a]
      const pathB = getPathToNode(nodes[3], nodes)  // [u1b]

      const ctxA = makeReconstructedContext([
        { nodeId: 'u1a', role: 'user', content: 'branch A' },
      ])
      const ctxB = makeReconstructedContext([
        { nodeId: 'u1b', role: 'user', content: 'branch B' },
      ])

      const rows = buildComparisonRows(ctxA, ctxB, pathA, pathB)

      // Should have fork point and a fork-pair (both suffixes have 1 msg)
      const forkRow = rows.find((r) => r.type === 'fork-point')
      expect(forkRow).toBeDefined()

      const pairRow = rows.find((r) => r.type === 'fork-pair')
      expect(pairRow).toBeDefined()
      expect(pairRow?.leftContent).toBe('branch A')
      expect(pairRow?.rightContent).toBe('branch B')
    })

    it('shows left-only tail when left branch is longer', () => {
      const nodes = [
        makeNode({ node_id: 'u1a', role: 'user', content: 'A msg 1' }),
        makeNode({ node_id: 'a1a', role: 'assistant', parent_id: 'u1a', content: 'A reply 1' }),
        makeNode({ node_id: 'u2a', role: 'user', parent_id: 'a1a', content: 'A msg 2' }),
        makeNode({ node_id: 'targetA', role: 'assistant', parent_id: 'u2a' }),
        makeNode({ node_id: 'u1b', role: 'user', content: 'B msg 1' }),
        makeNode({ node_id: 'targetB', role: 'assistant', parent_id: 'u1b' }),
      ]

      const pathA = getPathToNode(nodes[3], nodes)  // [u1a, a1a, u2a]
      const pathB = getPathToNode(nodes[5], nodes)  // [u1b]

      const ctxA = makeReconstructedContext([
        { nodeId: 'u1a', role: 'user', content: 'A msg 1' },
        { nodeId: 'a1a', role: 'assistant', content: 'A reply 1' },
        { nodeId: 'u2a', role: 'user', content: 'A msg 2' },
      ])
      const ctxB = makeReconstructedContext([
        { nodeId: 'u1b', role: 'user', content: 'B msg 1' },
      ])

      const rows = buildComparisonRows(ctxA, ctxB, pathA, pathB)

      // First zipped pair
      const pairRow = rows.find((r) => r.type === 'fork-pair')
      expect(pairRow?.leftContent).toBe('A msg 1')
      expect(pairRow?.rightContent).toBe('B msg 1')

      // Remaining left-only tail
      const leftOnlyRows = rows.filter((r) => r.type === 'left-only')
      expect(leftOnlyRows).toHaveLength(2) // a1a, u2a
    })
  })

  describe('metadata comparison', () => {
    it('emits metadata row when model differs', () => {
      const nodes = [
        makeNode({ node_id: 'u1', role: 'user' }),
        makeNode({ node_id: 'target', role: 'assistant', parent_id: 'u1' }),
      ]
      const path = getPathToNode(nodes[1], nodes)
      const ctxA = makeReconstructedContext(
        [{ nodeId: 'u1', role: 'user', content: 'hello' }],
        { model: 'gpt-4', provider: 'openai' },
      )
      const ctxB = makeReconstructedContext(
        [{ nodeId: 'u1', role: 'user', content: 'hello' }],
        { model: 'claude-3', provider: 'anthropic' },
      )

      const rows = buildComparisonRows(ctxA, ctxB, path, path)
      const metaRow = rows.find((r) => r.type === 'metadata')
      expect(metaRow).toBeDefined()
      expect(metaRow?.leftContent).toContain('gpt-4')
      expect(metaRow?.rightContent).toContain('claude-3')
    })

    it('omits metadata row when model/provider/params are same', () => {
      const nodes = [
        makeNode({ node_id: 'u1', role: 'user' }),
        makeNode({ node_id: 'target', role: 'assistant', parent_id: 'u1' }),
      ]
      const path = getPathToNode(nodes[1], nodes)
      const ctx = makeReconstructedContext(
        [{ nodeId: 'u1', role: 'user', content: 'hello' }],
        { model: 'same-model', provider: 'same-provider' },
      )

      const rows = buildComparisonRows(ctx, ctx, path, path)
      const metaRow = rows.find((r) => r.type === 'metadata')
      expect(metaRow).toBeUndefined()
    })
  })

  describe('system prompt comparison', () => {
    it('shows match when system prompts are identical', () => {
      const path: NodeResponse[] = []
      const ctxA = makeReconstructedContext([], { systemPrompt: 'same prompt' })
      const ctxB = makeReconstructedContext([], { systemPrompt: 'same prompt' })

      const rows = buildComparisonRows(ctxA, ctxB, path, path)
      const sysRow = rows.find((r) => r.role === 'system')
      expect(sysRow?.type).toBe('match')
    })

    it('shows system-prompt when they differ', () => {
      const path: NodeResponse[] = []
      const ctxA = makeReconstructedContext([], { systemPrompt: 'prompt A' })
      const ctxB = makeReconstructedContext([], { systemPrompt: 'prompt B' })

      const rows = buildComparisonRows(ctxA, ctxB, path, path)
      const sysRow = rows.find((r) => r.role === 'system')
      expect(sysRow?.type).toBe('system-prompt')
      expect(sysRow?.leftContent).toBe('prompt A')
      expect(sysRow?.rightContent).toBe('prompt B')
    })
  })
})
