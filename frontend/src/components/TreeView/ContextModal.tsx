import { Fragment, useEffect, useRef } from 'react'
import type { ReconstructedContext } from './contextReconstruction.ts'
import { formatSamplingParams } from './contextReconstruction.ts'
import './ContextModal.css'

interface ContextModalProps {
  context: ReconstructedContext
  onDismiss: () => void
}

function formatTimestamp(isoString: string): string {
  const date = new Date(isoString)
  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }) + ' at ' + date.toLocaleTimeString(undefined, {
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
  })
}

export function ContextModal({ context, onDismiss }: ContextModalProps) {
  const modalRef = useRef<HTMLDivElement>(null)

  // Esc to dismiss + focus trap
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onDismiss()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [onDismiss])

  // Click outside to dismiss
  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      onDismiss()
    }
  }

  const samplingItems = formatSamplingParams(context.samplingParams)

  return (
    <div className="context-modal-backdrop" onClick={handleBackdropClick}>
      <div className="context-modal" ref={modalRef} role="dialog" aria-label="Generation context">

        {/* Header: model + provider + close */}
        <div className="context-modal-header">
          <div>
            <span className="context-modal-title">{context.model ?? 'Unknown model'}</span>
            {context.provider && (
              <span className="context-modal-provider">via {context.provider}</span>
            )}
          </div>
          <button className="context-modal-close" onClick={onDismiss}>Close</button>
        </div>

        {/* Metadata row */}
        <div className="context-modal-meta">
          <span className="context-modal-meta-item">
            {formatTimestamp(context.timestamp)}
          </span>
          {context.latencyMs != null && (
            <span className="context-modal-meta-item">
              <strong>{(context.latencyMs / 1000).toFixed(1)}s</strong>
            </span>
          )}
          {context.usage && (
            <span className="context-modal-meta-item">
              <strong>{context.usage.input_tokens?.toLocaleString()}</strong> in + <strong>{context.usage.output_tokens?.toLocaleString()}</strong> out tokens
            </span>
          )}
          {context.finishReason && (
            <span className="context-modal-meta-item">
              finish: <strong>{context.finishReason}</strong>
            </span>
          )}
          {context.includeThinkingInContext && (
            <span className="context-modal-meta-item context-modal-meta-flag">
              thinking in context
            </span>
          )}
          {context.includeTimestamps && (
            <span className="context-modal-meta-item context-modal-meta-flag">
              timestamps in context
            </span>
          )}
        </div>

        {/* System prompt */}
        {context.systemPrompt && (
          <div className="context-modal-section">
            <div className="context-modal-section-label">System prompt</div>
            <div className="context-modal-system-prompt">{context.systemPrompt}</div>
          </div>
        )}

        {/* Messages */}
        <div className="context-modal-section">
          <div className="context-modal-section-label">
            Messages ({context.messages.length})
          </div>

          {context.evictedCount > 0 && (
            <div className="context-modal-evicted">
              {context.evictedCount} message{context.evictedCount !== 1 ? 's' : ''} evicted from context
              {context.evictedTokens > 0 && ` (${context.evictedTokens.toLocaleString()} tokens)`}
            </div>
          )}

          {context.messages.map((msg) => (
            <div key={msg.nodeId} className="context-modal-message">
              <div className="context-modal-message-header">
                <span className="context-modal-message-role">{msg.role}</span>
                {msg.wasEdited && (
                  <span className="context-modal-tag context-modal-tag-edited">edited</span>
                )}
                {msg.wasManual && (
                  <span className="context-modal-tag context-modal-tag-manual">manual</span>
                )}
                {msg.hadTimestampPrepended && (
                  <span className="context-modal-tag context-modal-tag-augmented">+timestamp</span>
                )}
                {msg.hadThinkingPrepended && (
                  <span className="context-modal-tag context-modal-tag-augmented">+thinking</span>
                )}
              </div>
              <div className="context-modal-message-content">
                {msg.thinkingPrefix && (
                  <span className="context-augmented-thinking">{msg.thinkingPrefix}</span>
                )}
                {msg.timestampPrefix && (
                  <span className="context-augmented-timestamp">{msg.timestampPrefix}</span>
                )}
                {msg.thinkingPrefix || msg.timestampPrefix
                  ? msg.baseContent
                  : msg.content
                }
              </div>
            </div>
          ))}
        </div>

        {/* Response thinking */}
        {context.thinkingContent && (
          <div className="context-modal-section">
            <div className="context-modal-section-label">Extended thinking</div>
            <div className="context-modal-thinking">{context.thinkingContent}</div>
          </div>
        )}

        {/* Sampling parameters */}
        {samplingItems.length > 0 && (
          <div className="context-modal-section">
            <div className="context-modal-section-label">Sampling parameters</div>
            <div className="context-modal-params">
              {samplingItems.map((item) => (
                <Fragment key={item.label}>
                  <span className="context-modal-param-label">{item.label}</span>
                  <span className="context-modal-param-value">{item.value}</span>
                </Fragment>
              ))}
            </div>
          </div>
        )}

        {/* Context usage */}
        {context.contextUsage && (
          <div className="context-modal-section">
            <div className="context-modal-section-label">
              Context usage: {context.contextUsage.total_tokens.toLocaleString()} / {context.contextUsage.max_tokens.toLocaleString()} tokens
            </div>
            <div className="context-modal-usage">
              {Object.entries(context.contextUsage.breakdown).map(([role, tokens]) => (
                <Fragment key={role}>
                  <span className="context-modal-usage-role">{role}</span>
                  <span className="context-modal-usage-tokens">{tokens.toLocaleString()}</span>
                </Fragment>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
