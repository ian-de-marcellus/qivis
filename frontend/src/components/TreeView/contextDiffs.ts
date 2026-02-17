import type { NodeResponse, SamplingParams, TreeDetail } from '../../api/types.ts'
import { reconstructContext } from './contextReconstruction.ts'

export interface TreeDefaults {
  default_system_prompt: string | null
  default_model: string | null
  default_provider: string | null
  default_sampling_params: SamplingParams | null
}

// -- Diff Summary (lightweight, for badge) --

export interface DiffSummary {
  editedUpstream: number
  manualUpstream: number
  evictedCount: number
  systemPromptChanged: boolean
  modelChanged: boolean
  providerChanged: boolean
  samplingChanged: boolean
  thinkingInContextFlag: boolean
  timestampsFlag: boolean
  totalDivergences: number
}

function samplingParamsEqual(
  a: SamplingParams | null | undefined,
  b: SamplingParams | null | undefined,
): boolean {
  if (!a && !b) return true
  if (!a || !b) return false
  // Compare all fields that might be set
  return (
    (a.temperature ?? null) === (b.temperature ?? null) &&
    (a.top_p ?? null) === (b.top_p ?? null) &&
    (a.top_k ?? null) === (b.top_k ?? null) &&
    (a.max_tokens ?? null) === (b.max_tokens ?? null) &&
    (a.frequency_penalty ?? null) === (b.frequency_penalty ?? null) &&
    (a.presence_penalty ?? null) === (b.presence_penalty ?? null) &&
    (a.extended_thinking ?? false) === (b.extended_thinking ?? false) &&
    (a.thinking_budget ?? null) === (b.thinking_budget ?? null)
  )
}

/**
 * Lightweight divergence scan for the diff badge.
 * Walks the parent chain to count edits/prefills, compares metadata against tree defaults.
 */
export function computeDiffSummary(
  node: NodeResponse,
  pathToNode: NodeResponse[],
  treeDefaults: TreeDefaults,
): DiffSummary {
  // Walk parent chain up to (but not including) the target node
  const nodeIdx = pathToNode.findIndex((n) => n.node_id === node.node_id)
  const upstream = nodeIdx > 0 ? pathToNode.slice(0, nodeIdx) : []

  let editedUpstream = 0
  let manualUpstream = 0
  for (const n of upstream) {
    if (n.edited_content != null) editedUpstream++
    if (n.mode === 'manual') manualUpstream++
  }

  const evictedCount = node.context_usage?.excluded_count ?? 0

  const systemPromptChanged = (node.system_prompt ?? null) !== (treeDefaults.default_system_prompt ?? null)
  const modelChanged = (node.model ?? null) !== (treeDefaults.default_model ?? null)
  const providerChanged = (node.provider ?? null) !== (treeDefaults.default_provider ?? null)
  const samplingChanged = !samplingParamsEqual(node.sampling_params, treeDefaults.default_sampling_params)
  const thinkingInContextFlag = node.include_thinking_in_context
  const timestampsFlag = node.include_timestamps

  const totalDivergences =
    editedUpstream +
    manualUpstream +
    evictedCount +
    (systemPromptChanged ? 1 : 0) +
    (modelChanged ? 1 : 0) +
    (providerChanged ? 1 : 0) +
    (samplingChanged ? 1 : 0) +
    (thinkingInContextFlag ? 1 : 0) +
    (timestampsFlag ? 1 : 0)

  return {
    editedUpstream,
    manualUpstream,
    evictedCount,
    systemPromptChanged,
    modelChanged,
    providerChanged,
    samplingChanged,
    thinkingInContextFlag,
    timestampsFlag,
    totalDivergences,
  }
}

// -- Diff Rows (full alignment, for split view) --

export type DiffRowType =
  | 'match'
  | 'edited'
  | 'augmented'
  | 'prefill'
  | 'evicted'
  | 'non-api-role'
  | 'system-prompt'
  | 'metadata'

export interface DiffRow {
  type: DiffRowType
  nodeId: string | null
  role: string | null
  leftContent: string | null
  rightContent: string | null
  wasEdited: boolean
  wasManual: boolean
  thinkingPrefix: string | null
  timestampPrefix: string | null
}

/**
 * Build row-by-row alignment for the split view.
 * Left = researcher's truth (original content). Right = model's received context.
 */
export function buildDiffRows(
  targetNode: NodeResponse,
  allNodes: NodeResponse[],
  treeDefaults: TreeDefaults,
): DiffRow[] {
  const rows: DiffRow[] = []
  const nodeMap = new Map(allNodes.map((n) => [n.node_id, n]))

  // Walk parent chain from target's parent to root
  const pathNodes: NodeResponse[] = []
  let currentId = targetNode.parent_id
  while (currentId != null) {
    const node = nodeMap.get(currentId)
    if (!node) break
    pathNodes.push(node)
    currentId = node.parent_id
  }
  pathNodes.reverse()

  // Get reconstructed context (model's view)
  const ctx = reconstructContext(targetNode, allNodes)
  const reconstructedByNodeId = new Map(
    ctx.messages.map((m) => [m.nodeId, m]),
  )

  // System prompt row
  if (ctx.systemPrompt) {
    const treeDefault = treeDefaults.default_system_prompt
    const changed = (ctx.systemPrompt ?? null) !== (treeDefault ?? null)
    rows.push({
      type: 'system-prompt',
      nodeId: null,
      role: 'system',
      leftContent: changed ? (treeDefault ?? null) : null,
      rightContent: ctx.systemPrompt,
      wasEdited: false,
      wasManual: false,
      thinkingPrefix: null,
      timestampPrefix: null,
    })
  }

  // Track API-sendable messages for eviction
  const apiRoles = new Set(['user', 'assistant', 'tool'])
  const evictedCount = targetNode.context_usage?.excluded_count ?? 0

  let apiIndex = 0
  for (const node of pathNodes) {
    if (!apiRoles.has(node.role)) {
      // Non-API role (system, researcher_note) — exists in researcher's truth, void on right
      rows.push({
        type: 'non-api-role',
        nodeId: node.node_id,
        role: node.role,
        leftContent: node.content,
        rightContent: null,
        wasEdited: false,
        wasManual: false,
        thinkingPrefix: null,
        timestampPrefix: null,
      })
      continue
    }

    // API-sendable message
    if (apiIndex < evictedCount) {
      // Evicted — exists in researcher's truth, void on right
      rows.push({
        type: 'evicted',
        nodeId: node.node_id,
        role: node.role,
        leftContent: node.content,
        rightContent: null,
        wasEdited: node.edited_content != null,
        wasManual: node.mode === 'manual',
        thinkingPrefix: null,
        timestampPrefix: null,
      })
      apiIndex++
      continue
    }

    // In-context message — pair with reconstructed message
    const reconstructed = reconstructedByNodeId.get(node.node_id)
    apiIndex++

    if (!reconstructed) {
      // Shouldn't happen, but handle gracefully
      rows.push({
        type: 'match',
        nodeId: node.node_id,
        role: node.role,
        leftContent: node.content,
        rightContent: node.content,
        wasEdited: false,
        wasManual: false,
        thinkingPrefix: null,
        timestampPrefix: null,
      })
      continue
    }

    const isEdited = node.edited_content != null
    const isManual = node.mode === 'manual'
    const hasThinking = reconstructed.hadThinkingPrepended
    const hasTimestamp = reconstructed.hadTimestampPrepended

    if (isEdited) {
      rows.push({
        type: 'edited',
        nodeId: node.node_id,
        role: node.role,
        leftContent: node.content,
        rightContent: reconstructed.content,
        wasEdited: true,
        wasManual: isManual,
        thinkingPrefix: reconstructed.thinkingPrefix,
        timestampPrefix: reconstructed.timestampPrefix,
      })
    } else if (isManual) {
      rows.push({
        type: 'prefill',
        nodeId: node.node_id,
        role: node.role,
        leftContent: node.content,
        rightContent: reconstructed.content,
        wasEdited: false,
        wasManual: true,
        thinkingPrefix: reconstructed.thinkingPrefix,
        timestampPrefix: reconstructed.timestampPrefix,
      })
    } else if (hasThinking || hasTimestamp) {
      rows.push({
        type: 'augmented',
        nodeId: node.node_id,
        role: node.role,
        leftContent: node.content,
        rightContent: reconstructed.content,
        wasEdited: false,
        wasManual: false,
        thinkingPrefix: reconstructed.thinkingPrefix,
        timestampPrefix: reconstructed.timestampPrefix,
      })
    } else {
      rows.push({
        type: 'match',
        nodeId: node.node_id,
        role: node.role,
        leftContent: node.content,
        rightContent: reconstructed.content,
        wasEdited: false,
        wasManual: false,
        thinkingPrefix: null,
        timestampPrefix: null,
      })
    }
  }

  // Metadata row if model/provider/params differ from tree defaults
  const metaDiffs: string[] = []
  if ((targetNode.model ?? null) !== (treeDefaults.default_model ?? null)) {
    metaDiffs.push(`model: ${targetNode.model ?? 'none'}`)
  }
  if ((targetNode.provider ?? null) !== (treeDefaults.default_provider ?? null)) {
    metaDiffs.push(`provider: ${targetNode.provider ?? 'none'}`)
  }
  if (!samplingParamsEqual(targetNode.sampling_params, treeDefaults.default_sampling_params)) {
    metaDiffs.push('sampling params differ')
  }

  if (metaDiffs.length > 0) {
    const treeMetaLines: string[] = []
    if (treeDefaults.default_model) treeMetaLines.push(`model: ${treeDefaults.default_model}`)
    if (treeDefaults.default_provider) treeMetaLines.push(`provider: ${treeDefaults.default_provider}`)

    const nodeMetaLines: string[] = []
    if (targetNode.model) nodeMetaLines.push(`model: ${targetNode.model}`)
    if (targetNode.provider) nodeMetaLines.push(`provider: ${targetNode.provider}`)

    rows.push({
      type: 'metadata',
      nodeId: null,
      role: null,
      leftContent: treeMetaLines.join('\n') || null,
      rightContent: nodeMetaLines.join('\n') || null,
      wasEdited: false,
      wasManual: false,
      thinkingPrefix: null,
      timestampPrefix: null,
    })
  }

  return rows
}

/** Extract tree defaults from a TreeDetail for use with diff functions. */
export function getTreeDefaults(tree: TreeDetail): TreeDefaults {
  return {
    default_system_prompt: tree.default_system_prompt,
    default_model: tree.default_model,
    default_provider: tree.default_provider,
    default_sampling_params: tree.default_sampling_params,
  }
}
