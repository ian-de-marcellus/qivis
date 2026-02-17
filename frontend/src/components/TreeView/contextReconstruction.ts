import type { ContextUsage, NodeResponse, SamplingParams } from '../../api/types.ts'

export interface ReconstructedMessage {
  role: string
  /** The full content string as sent to the API (with all prefixes baked in). */
  content: string
  nodeId: string
  wasEdited: boolean
  wasManual: boolean
  hadThinkingPrepended: boolean
  hadTimestampPrepended: boolean
  /** The thinking prefix, if prepended (for separate rendering). */
  thinkingPrefix: string | null
  /** The timestamp prefix, if prepended (for separate rendering). */
  timestampPrefix: string | null
  /** The base content without any prefixes. */
  baseContent: string
  /** True if this message was excluded from context (user/group exclusion). */
  isExcluded: boolean
  /** True if this message was evicted due to context window truncation. */
  isEvicted: boolean
}

export interface ReconstructedContext {
  systemPrompt: string | null
  /** All messages on the path (including excluded and evicted, with flags). */
  messages: ReconstructedMessage[]
  evictedCount: number
  evictedTokens: number
  excludedCount: number
  excludedTokens: number
  model: string | null
  provider: string | null
  samplingParams: SamplingParams | null
  timestamp: string
  latencyMs: number | null
  usage: Record<string, number> | null
  finishReason: string | null
  contextUsage: ContextUsage | null
  thinkingContent: string | null
  includeThinkingInContext: boolean
  includeTimestamps: boolean
}

/**
 * Reconstruct the API request context for a given assistant node.
 * Walks the parent chain to build the ordered message list,
 * applies edits (uses edited_content where present), and marks
 * excluded and evicted messages using stored node ID lists.
 */
export function reconstructContext(
  targetNode: NodeResponse,
  allNodes: NodeResponse[],
): ReconstructedContext {
  const nodeMap = new Map(allNodes.map((n) => [n.node_id, n]))

  // Walk parent chain from targetNode's parent up to root
  const pathNodes: NodeResponse[] = []
  let currentId = targetNode.parent_id
  while (currentId != null) {
    const node = nodeMap.get(currentId)
    if (!node) break
    pathNodes.push(node)
    currentId = node.parent_id
  }
  // Reverse to get root-first order
  pathNodes.reverse()

  // Determine excluded and evicted node IDs from stored context_usage
  const excludedNodeIds = new Set(targetNode.context_usage?.excluded_node_ids ?? [])
  const evictedNodeIds = new Set(targetNode.context_usage?.evicted_node_ids ?? [])

  // Build messages matching what the backend ContextBuilder actually sent.
  // Only API-sendable roles (user, assistant, tool) — same filter as backend.
  // When include_timestamps was on: prepends [YYYY-MM-DD HH:MM] to content.
  // When include_thinking_in_context was on: prepends [Model thinking: ...] to assistant content.
  const thinkingInContext = targetNode.include_thinking_in_context
  const timestampsInContext = targetNode.include_timestamps
  const apiNodes = pathNodes.filter((n) =>
    n.role === 'user' || n.role === 'assistant' || n.role === 'tool',
  )
  const messages: ReconstructedMessage[] = apiNodes.map((node) => {
    const baseContent = node.edited_content ?? node.content
    let content = baseContent
    let hadTimestamp = false
    let hadThinking = false
    let timestampPrefix: string | null = null
    let thinkingPrefix: string | null = null

    // Timestamps on user/tool messages only (not assistant — prevents model mirroring)
    if (timestampsInContext && node.role !== 'assistant' && node.created_at) {
      try {
        const dt = new Date(node.created_at)
        const y = dt.getFullYear()
        const mo = String(dt.getMonth() + 1).padStart(2, '0')
        const d = String(dt.getDate()).padStart(2, '0')
        const h = String(dt.getHours()).padStart(2, '0')
        const mi = String(dt.getMinutes()).padStart(2, '0')
        timestampPrefix = `[${y}-${mo}-${d} ${h}:${mi}] `
        content = timestampPrefix + content
        hadTimestamp = true
      } catch {
        // skip on parse failure, same as backend
      }
    }

    // Thinking prepend: backend prepends [Model thinking: ...] to assistant content
    if (thinkingInContext && node.role === 'assistant' && node.thinking_content) {
      thinkingPrefix = `[Model thinking: ${node.thinking_content}]\n\n`
      content = thinkingPrefix + content
      hadThinking = true
    }

    return {
      role: node.role,
      content,
      baseContent,
      nodeId: node.node_id,
      wasEdited: node.edited_content != null,
      wasManual: node.mode === 'manual',
      hadThinkingPrepended: hadThinking,
      hadTimestampPrepended: hadTimestamp,
      thinkingPrefix,
      timestampPrefix,
      isExcluded: excludedNodeIds.has(node.node_id),
      isEvicted: evictedNodeIds.has(node.node_id),
    }
  })

  // Counts for summary banners
  const excludedCount = targetNode.context_usage?.excluded_count ?? 0
  const excludedTokens = targetNode.context_usage?.excluded_tokens ?? 0
  const evictedCount = evictedNodeIds.size
  const evictedTokens = 0  // Not tracked separately yet

  return {
    systemPrompt: targetNode.system_prompt,
    messages,
    evictedCount,
    evictedTokens,
    excludedCount,
    excludedTokens,
    model: targetNode.model,
    provider: targetNode.provider,
    samplingParams: targetNode.sampling_params,
    timestamp: targetNode.created_at,
    latencyMs: targetNode.latency_ms,
    usage: targetNode.usage,
    finishReason: targetNode.finish_reason,
    contextUsage: targetNode.context_usage,
    thinkingContent: targetNode.thinking_content,
    includeThinkingInContext: targetNode.include_thinking_in_context,
    includeTimestamps: targetNode.include_timestamps,
  }
}

/** Format sampling params into human-readable labels, only showing non-default values. */
export function formatSamplingParams(sp: SamplingParams | null): { label: string; value: string }[] {
  if (!sp) return []
  const items: { label: string; value: string }[] = []
  if (sp.temperature != null) items.push({ label: 'Temperature', value: String(sp.temperature) })
  if (sp.top_p != null) items.push({ label: 'Top P', value: String(sp.top_p) })
  if (sp.top_k != null) items.push({ label: 'Top K', value: String(sp.top_k) })
  if (sp.max_tokens != null) items.push({ label: 'Max tokens', value: sp.max_tokens.toLocaleString() })
  if (sp.frequency_penalty != null) items.push({ label: 'Freq penalty', value: String(sp.frequency_penalty) })
  if (sp.presence_penalty != null) items.push({ label: 'Pres penalty', value: String(sp.presence_penalty) })
  if (sp.extended_thinking) {
    items.push({ label: 'Extended thinking', value: 'on' })
    if (sp.thinking_budget != null) items.push({ label: 'Thinking budget', value: sp.thinking_budget.toLocaleString() })
  }
  return items
}
