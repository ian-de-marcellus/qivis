import { useState } from 'react'
import type { ContextUsage } from '../../api/types.ts'
import './ContextBar.css'

interface ContextBarProps {
  contextUsage: ContextUsage
}

export function ContextBar({ contextUsage }: ContextBarProps) {
  const [expanded, setExpanded] = useState(false)
  const { total_tokens, max_tokens, breakdown, excluded_tokens, excluded_count } = contextUsage

  const percent = max_tokens > 0 ? (total_tokens / max_tokens) * 100 : 0
  const colorClass = percent >= 90 ? 'ctx-red' : percent >= 70 ? 'ctx-yellow' : 'ctx-green'

  return (
    <div className="context-bar-wrapper">
      <button
        className={`context-bar ${colorClass}`}
        onClick={() => setExpanded(!expanded)}
        title={`Context: ${total_tokens.toLocaleString()} / ${max_tokens.toLocaleString()} tokens (${percent.toFixed(1)}%)`}
        aria-label="Toggle context usage breakdown"
      >
        <div
          className="context-bar-fill"
          style={{ width: `${Math.min(percent, 100)}%` }}
        />
      </button>

      {expanded && (
        <div className="context-breakdown">
          <div className="context-breakdown-header">
            Context: {total_tokens.toLocaleString()} / {max_tokens.toLocaleString()} tokens ({percent.toFixed(1)}%)
          </div>
          <div className="context-breakdown-items">
            {Object.entries(breakdown).map(([role, tokens]) => (
              <div key={role} className="context-breakdown-row">
                <span className="context-breakdown-role">{role}</span>
                <span className="context-breakdown-tokens">
                  {tokens.toLocaleString()} tokens
                </span>
              </div>
            ))}
            {excluded_count > 0 && (
              <div className="context-breakdown-row excluded">
                <span className="context-breakdown-role">
                  excluded ({excluded_count} messages)
                </span>
                <span className="context-breakdown-tokens">
                  {excluded_tokens.toLocaleString()} tokens
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
