import type { NodeResponse, SamplingParams, TreeDetail } from '../../api/types.ts'
import { reconstructContext } from './contextReconstruction.ts'
import type { ReconstructedContext, ReconstructedMessage } from './contextReconstruction.ts'

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
  excludedCount: number
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

  const evictedCount = node.context_usage?.evicted_node_ids?.length ?? 0
  const excludedCount = node.context_usage?.excluded_count ?? 0

  // Only flag a divergence when the tree has an explicit default AND the node
  // used something different. A null tree default means "no override" — the
  // node having any value is expected, not a divergence.
  const systemPromptChanged =
    treeDefaults.default_system_prompt != null &&
    (node.system_prompt ?? null) !== treeDefaults.default_system_prompt
  const modelChanged =
    treeDefaults.default_model != null &&
    (node.model ?? null) !== treeDefaults.default_model
  const providerChanged =
    treeDefaults.default_provider != null &&
    (node.provider ?? null) !== treeDefaults.default_provider
  const samplingChanged =
    treeDefaults.default_sampling_params != null &&
    !samplingParamsEqual(node.sampling_params, treeDefaults.default_sampling_params)
  const thinkingInContextFlag = node.include_thinking_in_context
  const timestampsFlag = node.include_timestamps

  const totalDivergences =
    editedUpstream +
    manualUpstream +
    evictedCount +
    excludedCount +
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
    excludedCount,
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
  | 'excluded'
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

  // Build sets for evicted and excluded node IDs
  const apiRoles = new Set(['user', 'assistant', 'tool'])
  const evictedNodeIds = new Set(targetNode.context_usage?.evicted_node_ids ?? [])
  const excludedNodeIds = new Set(targetNode.context_usage?.excluded_node_ids ?? [])

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

    // Evicted — truncated from context due to window limits
    if (evictedNodeIds.has(node.node_id)) {
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
      continue
    }

    // Excluded — user/group exclusion from context
    if (excludedNodeIds.has(node.node_id)) {
      rows.push({
        type: 'excluded',
        nodeId: node.node_id,
        role: node.role,
        leftContent: node.content,
        rightContent: null,
        wasEdited: node.edited_content != null,
        wasManual: node.mode === 'manual',
        thinkingPrefix: null,
        timestampPrefix: null,
      })
      continue
    }

    // In-context message — pair with reconstructed message
    const reconstructed = reconstructedByNodeId.get(node.node_id)

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
  // Only flag when tree has an explicit default and node used something different
  const metaDiffs: string[] = []
  if (treeDefaults.default_model != null && (targetNode.model ?? null) !== treeDefaults.default_model) {
    metaDiffs.push(`model: ${targetNode.model ?? 'none'}`)
  }
  if (treeDefaults.default_provider != null && (targetNode.provider ?? null) !== treeDefaults.default_provider) {
    metaDiffs.push(`provider: ${targetNode.provider ?? 'none'}`)
  }
  if (treeDefaults.default_sampling_params != null && !samplingParamsEqual(targetNode.sampling_params, treeDefaults.default_sampling_params)) {
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

// -- Comparison Rows (generalized, for cross-node context comparison) --

export type ComparisonRowType =
  | 'match'           // same content + status on both sides
  | 'content-differs' // same node, content differs (edit, augmentation, etc.)
  | 'status-differs'  // same node, one excluded/evicted, other in-context
  | 'left-only'       // message only in left context (tail of longer branch)
  | 'right-only'      // message only in right context (tail of longer branch)
  | 'fork-pair'       // paired messages from divergent branches (side by side)
  | 'fork-point'      // visual divider where paths diverge
  | 'system-prompt'   // system prompt comparison
  | 'metadata'        // model/provider/params comparison

export type MessageStatus = 'in-context' | 'excluded' | 'evicted' | 'non-api'

export interface ComparisonRow {
  type: ComparisonRowType
  nodeId: string | null
  rightNodeId: string | null    // for fork-pair rows (different node on each side)
  role: string | null
  rightRole: string | null      // for fork-pair rows (may differ from left role)
  leftContent: string | null
  rightContent: string | null
  leftStatus: MessageStatus | null
  rightStatus: MessageStatus | null
  leftTags: string[]
  rightTags: string[]
}

/**
 * Walk parent chain from a node's parent to root, returning nodes root-first.
 * Shared helper to avoid duplicating the walk logic.
 */
export function getPathToNode(
  targetNode: NodeResponse,
  allNodes: NodeResponse[],
): NodeResponse[] {
  const nodeMap = new Map(allNodes.map((n) => [n.node_id, n]))
  const path: NodeResponse[] = []
  let currentId = targetNode.parent_id
  while (currentId != null) {
    const node = nodeMap.get(currentId)
    if (!node) break
    path.push(node)
    currentId = node.parent_id
  }
  path.reverse()
  return path
}

/**
 * Build a synthetic ReconstructedContext representing the "Original" baseline:
 * no edits, no exclusions, no augmentation, tree-default system prompt/metadata.
 */
export function buildOriginalContext(
  targetNode: NodeResponse,
  allNodes: NodeResponse[],
  treeDefaults: TreeDefaults,
): ReconstructedContext {
  const pathNodes = getPathToNode(targetNode, allNodes)

  const apiNodes = pathNodes.filter((n) =>
    n.role === 'user' || n.role === 'assistant' || n.role === 'tool',
  )

  const messages: ReconstructedMessage[] = apiNodes.map((node) => ({
    role: node.role,
    content: node.content,
    baseContent: node.content,
    nodeId: node.node_id,
    wasEdited: false,
    wasManual: node.mode === 'manual',
    hadThinkingPrepended: false,
    hadTimestampPrepended: false,
    thinkingPrefix: null,
    timestampPrefix: null,
    isExcluded: false,
    isEvicted: false,
  }))

  return {
    systemPrompt: treeDefaults.default_system_prompt,
    messages,
    evictedCount: 0,
    evictedTokens: 0,
    excludedCount: 0,
    excludedTokens: 0,
    model: treeDefaults.default_model,
    provider: treeDefaults.default_provider,
    samplingParams: treeDefaults.default_sampling_params,
    timestamp: targetNode.created_at,
    latencyMs: null,
    usage: null,
    finishReason: null,
    contextUsage: null,
    thinkingContent: null,
    includeThinkingInContext: false,
    includeTimestamps: false,
  }
}

function messageStatus(msg: ReconstructedMessage): MessageStatus {
  if (msg.isExcluded) return 'excluded'
  if (msg.isEvicted) return 'evicted'
  return 'in-context'
}

function messageTags(msg: ReconstructedMessage): string[] {
  const tags: string[] = []
  if (msg.wasEdited) tags.push('edited')
  if (msg.wasManual) tags.push('manual')
  if (msg.hadTimestampPrepended) tags.push('+timestamp')
  if (msg.hadThinkingPrepended) tags.push('+thinking')
  if (msg.isExcluded) tags.push('excluded')
  if (msg.isEvicted) tags.push('evicted')
  return tags
}

/**
 * Build comparison rows between two reconstructed contexts.
 *
 * Finds the shared prefix (nodes on both paths by ID), then emits
 * left-only and right-only rows for the divergent suffixes.
 */
export function buildComparisonRows(
  contextA: ReconstructedContext,
  contextB: ReconstructedContext,
  pathA: NodeResponse[],
  pathB: NodeResponse[],
): ComparisonRow[] {
  const rows: ComparisonRow[] = []

  // Index messages by nodeId for quick lookup
  const messagesA = new Map(contextA.messages.map((m) => [m.nodeId, m]))
  const messagesB = new Map(contextB.messages.map((m) => [m.nodeId, m]))

  // Build ordered nodeId lists for both paths (all roles, not just API)
  const pathAIds = pathA.map((n) => n.node_id)
  const pathBIds = pathB.map((n) => n.node_id)
  // Find the shared prefix length (nodes in both paths in same order)
  let sharedLength = 0
  while (
    sharedLength < pathAIds.length &&
    sharedLength < pathBIds.length &&
    pathAIds[sharedLength] === pathBIds[sharedLength]
  ) {
    sharedLength++
  }

  // System prompt comparison
  const sysA = contextA.systemPrompt
  const sysB = contextB.systemPrompt
  if (sysA || sysB) {
    rows.push({
      type: sysA === sysB ? 'match' : 'system-prompt',
      nodeId: null,
      rightNodeId: null,
      role: 'system',
      rightRole: null,
      leftContent: sysA,
      rightContent: sysB,
      leftStatus: null,
      rightStatus: null,
      leftTags: [],
      rightTags: [],
    })
  }

  // Shared prefix: nodes on both paths
  const apiRoles = new Set(['user', 'assistant', 'tool'])
  for (let i = 0; i < sharedLength; i++) {
    const node = pathA[i]
    const msgA = messagesA.get(node.node_id)
    const msgB = messagesB.get(node.node_id)

    // Non-API role: show spanning (same on both sides)
    if (!apiRoles.has(node.role)) {
      rows.push({
        type: 'match',
        nodeId: node.node_id,
        rightNodeId: null,
        role: node.role,
        rightRole: null,
        leftContent: node.content,
        rightContent: node.content,
        leftStatus: 'non-api',
        rightStatus: 'non-api',
        leftTags: [],
        rightTags: [],
      })
      continue
    }

    // Both contexts should have this message (shared path, API role)
    if (!msgA && !msgB) continue

    const statusA = msgA ? messageStatus(msgA) : null
    const statusB = msgB ? messageStatus(msgB) : null
    const contentA = msgA?.content ?? null
    const contentB = msgB?.content ?? null
    const tagsA = msgA ? messageTags(msgA) : []
    const tagsB = msgB ? messageTags(msgB) : []

    // Determine row type
    let type: ComparisonRowType
    if (statusA !== statusB) {
      type = 'status-differs'
    } else if (contentA !== contentB) {
      type = 'content-differs'
    } else {
      type = 'match'
    }

    rows.push({
      type,
      nodeId: node.node_id,
      rightNodeId: null,
      role: node.role,
      rightRole: null,
      leftContent: contentA,
      rightContent: contentB,
      leftStatus: statusA,
      rightStatus: statusB,
      leftTags: tagsA,
      rightTags: tagsB,
    })
  }

  // If paths diverge, emit fork point + paired divergent rows
  const leftSuffix = pathA.slice(sharedLength)
  const rightSuffix = pathB.slice(sharedLength)

  if (leftSuffix.length > 0 || rightSuffix.length > 0) {
    rows.push({
      type: 'fork-point',
      nodeId: null,
      rightNodeId: null,
      role: null,
      rightRole: null,
      leftContent: null,
      rightContent: null,
      leftStatus: null,
      rightStatus: null,
      leftTags: [],
      rightTags: [],
    })

    // Zip the two suffixes side by side
    const maxLen = Math.max(leftSuffix.length, rightSuffix.length)
    for (let i = 0; i < maxLen; i++) {
      const leftNode = leftSuffix[i] ?? null
      const rightNode = rightSuffix[i] ?? null
      const leftMsg = leftNode ? messagesA.get(leftNode.node_id) ?? null : null
      const rightMsg = rightNode ? messagesB.get(rightNode.node_id) ?? null : null

      if (leftNode && rightNode) {
        // Both sides have a message at this position
        rows.push({
          type: 'fork-pair',
          nodeId: leftNode.node_id,
          rightNodeId: rightNode.node_id,
          role: leftNode.role,
          rightRole: rightNode.role,
          leftContent: leftMsg?.content ?? leftNode.content,
          rightContent: rightMsg?.content ?? rightNode.content,
          leftStatus: !apiRoles.has(leftNode.role) ? 'non-api' : leftMsg ? messageStatus(leftMsg) : 'in-context',
          rightStatus: !apiRoles.has(rightNode.role) ? 'non-api' : rightMsg ? messageStatus(rightMsg) : 'in-context',
          leftTags: leftMsg ? messageTags(leftMsg) : [],
          rightTags: rightMsg ? messageTags(rightMsg) : [],
        })
      } else if (leftNode) {
        rows.push({
          type: 'left-only',
          nodeId: leftNode.node_id,
          rightNodeId: null,
          role: leftNode.role,
          rightRole: null,
          leftContent: leftMsg?.content ?? leftNode.content,
          rightContent: null,
          leftStatus: !apiRoles.has(leftNode.role) ? 'non-api' : leftMsg ? messageStatus(leftMsg) : 'in-context',
          rightStatus: null,
          leftTags: leftMsg ? messageTags(leftMsg) : [],
          rightTags: [],
        })
      } else if (rightNode) {
        rows.push({
          type: 'right-only',
          nodeId: null,
          rightNodeId: rightNode.node_id,
          role: null,
          rightRole: rightNode.role,
          leftContent: null,
          rightContent: rightMsg?.content ?? rightNode.content,
          leftStatus: null,
          rightStatus: !apiRoles.has(rightNode.role) ? 'non-api' : rightMsg ? messageStatus(rightMsg) : 'in-context',
          leftTags: [],
          rightTags: rightMsg ? messageTags(rightMsg) : [],
        })
      }
    }
  }

  // Metadata comparison
  const metaA: string[] = []
  const metaB: string[] = []
  if (contextA.model) metaA.push(`model: ${contextA.model}`)
  if (contextA.provider) metaA.push(`provider: ${contextA.provider}`)
  if (contextB.model) metaB.push(`model: ${contextB.model}`)
  if (contextB.provider) metaB.push(`provider: ${contextB.provider}`)

  const metaLeftStr = metaA.join('\n') || null
  const metaRightStr = metaB.join('\n') || null
  const paramsEqual = samplingParamsEqual(contextA.samplingParams, contextB.samplingParams)

  if (metaLeftStr !== metaRightStr || !paramsEqual) {
    if (!paramsEqual) {
      metaA.push('sampling params differ')
      metaB.push('sampling params differ')
    }
    rows.push({
      type: 'metadata',
      nodeId: null,
      rightNodeId: null,
      role: null,
      rightRole: null,
      leftContent: metaA.join('\n') || null,
      rightContent: metaB.join('\n') || null,
      leftStatus: null,
      rightStatus: null,
      leftTags: [],
      rightTags: [],
    })
  }

  return rows
}
