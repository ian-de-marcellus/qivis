import { useState } from 'react'
import type { LogprobData, NodeResponse } from '../../api/types.ts'
import { BranchIndicator } from './BranchIndicator.tsx'
import { ContextBar } from './ContextBar.tsx'
import { LogprobOverlay, averageCertainty, uncertaintyColor } from './LogprobOverlay.tsx'
import { ThinkingSection } from './ThinkingSection.tsx'
import './MessageRow.css'

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
}

export function MessageRow({ node, siblings, onSelectSibling, onFork }: MessageRowProps) {
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
