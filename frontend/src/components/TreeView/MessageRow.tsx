import { useState } from 'react'
import type { LogprobData, NodeResponse, SamplingParams } from '../../api/types.ts'
import { BranchIndicator } from './BranchIndicator.tsx'
import { ContextBar } from './ContextBar.tsx'
import { LogprobOverlay, averageCertainty, uncertaintyColor } from './LogprobOverlay.tsx'
import { ThinkingSection } from './ThinkingSection.tsx'
import './MessageRow.css'

/** Short labels for sampling params that differ from defaults. */
function formatSamplingMeta(sp: SamplingParams | null | undefined): string[] {
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

function formatTimestamp(isoString: string): string {
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

interface MessageRowProps {
  node: NodeResponse
  siblings: NodeResponse[]
  onSelectSibling: (siblingId: string) => void
  onFork: () => void
  onCompare?: () => void
}

export function MessageRow({ node, siblings, onSelectSibling, onFork, onCompare }: MessageRowProps) {
  const [showLogprobs, setShowLogprobs] = useState(false)

  const roleLabel = node.role === 'researcher_note'
    ? 'Researcher Note'
    : node.role.charAt(0).toUpperCase() + node.role.slice(1)

  const logprobs: LogprobData | null = node.logprobs
  const avgCertainty = logprobs ? averageCertainty(logprobs) : null

  return (
    <div className={`message-row ${node.role}`}>
      <div className="message-header">
        <span className="message-role">{roleLabel}</span>
        {node.role === 'assistant' && node.model && (
          <span className="message-model">{node.model}</span>
        )}
        {node.sibling_count > 1 && (
          <BranchIndicator
            node={node}
            siblings={siblings}
            onSelect={onSelectSibling}
            onCompare={onCompare}
          />
        )}
        <button className="fork-btn" onClick={onFork} aria-label={node.role === 'assistant' ? 'Regenerate' : 'Fork'}>
          {node.role === 'assistant' ? 'Regen' : 'Fork'}
        </button>
      </div>
      {node.thinking_content && (
        <ThinkingSection thinkingContent={node.thinking_content} />
      )}
      <div className="message-content">
        {showLogprobs && logprobs ? (
          <LogprobOverlay logprobs={logprobs} />
        ) : (
          node.content
        )}
      </div>
      {node.role === 'assistant' && node.context_usage != null && (
        <ContextBar contextUsage={node.context_usage} />
      )}
      <div className="message-meta">
        {formatTimestamp(node.created_at)}
        {node.latency_ms != null && (
          <>
            {` \u00b7 ${(node.latency_ms / 1000).toFixed(1)}s`}
            {node.usage && ` \u00b7 ${node.usage.input_tokens.toLocaleString()}+${node.usage.output_tokens.toLocaleString()} tok`}
          </>
        )}
        {node.role === 'assistant' && formatSamplingMeta(node.sampling_params).map((label) => (
          <span key={label} className="sampling-meta">{` \u00b7 ${label}`}</span>
        ))}
        {avgCertainty != null && (
          <>
            {' \u00b7 '}
            <span
              className={`certainty-badge${showLogprobs ? ' active' : ''}`}
              onClick={() => setShowLogprobs(!showLogprobs)}
              title={showLogprobs ? 'Hide token probabilities' : 'Show token probabilities'}
            >
              <span
                className="certainty-dot"
                style={{ backgroundColor: uncertaintyColor(avgCertainty) === 'transparent'
                  ? 'var(--ctx-green)'
                  : uncertaintyColor(avgCertainty)
                }}
              />
              {(avgCertainty * 100).toFixed(0)}%
            </span>
          </>
        )}
      </div>
    </div>
  )
}
