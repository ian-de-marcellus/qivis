/** How node metadata reads in the conversation views. */

import type { SamplingParams } from '../../api/types.ts'

/** Short labels for sampling params that differ from defaults. */
export function formatSamplingMeta(sp: SamplingParams | null | undefined): string[] {
  if (!sp) return []
  const parts: string[] = []
  if (sp.temperature != null) parts.push(`temp ${sp.temperature}`)
  if (sp.top_p != null) parts.push(`top_p ${sp.top_p}`)
  if (sp.top_k != null) parts.push(`top_k ${sp.top_k}`)
  if (sp.max_tokens != null && sp.max_tokens !== 2048) parts.push(`max_tok ${sp.max_tokens}`)
  if (sp.frequency_penalty != null) parts.push(`freq_pen ${sp.frequency_penalty}`)
  if (sp.presence_penalty != null) parts.push(`pres_pen ${sp.presence_penalty}`)
  if (sp.extended_thinking) parts.push('thinking')
  return parts
}

export function formatTimestamp(isoString: string): string {
  const date = new Date(isoString)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMin = Math.floor(diffMs / 60_000)

  if (diffMin < 1) return 'just now'
  if (diffMin < 60) return `${diffMin}m ago`

  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`

  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  }) + ', ' + date.toLocaleTimeString(undefined, {
    hour: 'numeric',
    minute: '2-digit',
  })
}

/**
 * How many of a reply's tokens make up its saved text. The rest were chosen
 * too (in a steered reply: the handover to the next speaker, or an end-of-
 * turn token) but trimmed from the text; they show as one end-of-turn mark.
 */
export function textTokenCount(tokens: { token: string }[], content: string): number {
  const target = content.trimStart().length
  if (target === 0) return tokens.length
  let text = ''
  for (let i = 0; i < tokens.length; i++) {
    text += tokens[i].token
    if (text.trimStart().length >= target) return i + 1
  }
  return tokens.length
}
