import { useEffect, useRef } from 'react'
import type { ReconstructedContext } from './contextReconstruction.ts'
import { formatSamplingParams } from './contextReconstruction.ts'
import type { DiffRow, DiffSummary } from './contextDiffs.ts'
import './ContextSplitView.css'

interface ContextSplitViewProps {
  rows: DiffRow[]
  summary: DiffSummary
  context: ReconstructedContext
  responseContent: string
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
  })
}

function roleLabel(role: string | null): string {
  if (!role) return ''
  if (role === 'researcher_note') return 'researcher note'
  return role
}

export function ContextSplitView({ rows, summary, context, responseContent, onDismiss }: ContextSplitViewProps) {
  const modalRef = useRef<HTMLDivElement>(null)

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

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      onDismiss()
    }
  }

  // Build summary chips
  const chips: string[] = []
  if (summary.editedUpstream > 0) chips.push(`${summary.editedUpstream} edited`)
  if (summary.manualUpstream > 0) chips.push(`${summary.manualUpstream} prefilled`)
  if (summary.evictedCount > 0) chips.push(`${summary.evictedCount} evicted`)
  if (summary.systemPromptChanged) chips.push('system prompt')
  if (summary.modelChanged) chips.push('model')
  if (summary.providerChanged) chips.push('provider')
  if (summary.samplingChanged) chips.push('params')
  if (summary.thinkingInContextFlag) chips.push('thinking in ctx')
  if (summary.timestampsFlag) chips.push('timestamps')

  const samplingItems = formatSamplingParams(context.samplingParams)

  return (
    <div className="split-view-backdrop" onClick={handleBackdropClick}>
      <div className="split-view" ref={modalRef} role="dialog" aria-label="Context comparison">

        {/* Header */}
        <div className="split-view-header">
          <div className="split-view-header-left">
            <span className="split-view-title">{context.model ?? 'Unknown model'}</span>
            {context.provider && (
              <span className="split-view-provider">via {context.provider}</span>
            )}
            <span className="split-view-timestamp">{formatTimestamp(context.timestamp)}</span>
          </div>
          <div className="split-view-header-right">
            <div className="split-view-chips">
              {chips.map((chip) => (
                <span key={chip} className="split-view-chip">{chip}</span>
              ))}
            </div>
            <button className="split-view-close" onClick={onDismiss}>Close</button>
          </div>
        </div>

        {/* Column labels */}
        <div className="split-view-grid split-view-labels">
          <div className="split-view-col-label">Researcher's truth</div>
          <div className="split-view-col-label">Model received</div>
        </div>

        {/* Rows */}
        <div className="split-view-body">
          {rows.map((row, i) => (
            <SplitRow key={row.nodeId ?? `meta-${i}`} row={row} />
          ))}

          {/* Response — what came out of this context */}
          <div className="split-view-grid split-row response-row">
            <div className="split-row-cell split-row-left match">
              <span className="split-row-pregnant-rule" />
              <span className="split-row-pregnant-label">response</span>
            </div>
            <div className="split-row-cell split-row-right">
              <div className="split-row-section-label">Response</div>
              {context.thinkingContent && (
                <div className="split-row-response-thinking">{context.thinkingContent}</div>
              )}
              <div className="split-row-content">{responseContent}</div>
              {context.latencyMs != null && context.usage && (
                <div className="split-row-response-meta">
                  {(context.latencyMs / 1000).toFixed(1)}s
                  {' \u00b7 '}
                  {context.usage.output_tokens?.toLocaleString()} tokens
                  {context.finishReason && ` \u00b7 ${context.finishReason}`}
                </div>
              )}
            </div>
          </div>

          {/* Sampling params if any */}
          {samplingItems.length > 0 && (
            <div className="split-view-grid split-view-footer-row">
              <div className="split-row-cell split-row-left match">
                <span className="split-row-pregnant-rule" />
                <span className="split-row-pregnant-label">params</span>
              </div>
              <div className="split-row-cell split-row-right">
                <div className="split-row-section-label">Sampling parameters</div>
                <div className="split-row-params">
                  {samplingItems.map((item) => (
                    <div key={item.label} className="split-row-param">
                      <span className="split-row-param-label">{item.label}</span>
                      <span className="split-row-param-value">{item.value}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function SplitRow({ row }: { row: DiffRow }) {
  switch (row.type) {
    case 'match':
      return (
        <div className="split-view-grid split-row match">
          {/* Left: pregnant space */}
          <div className="split-row-cell split-row-left match">
            <span className="split-row-pregnant-rule" />
            <span className="split-row-pregnant-label">{roleLabel(row.role)}</span>
          </div>
          {/* Right: full content */}
          <div className="split-row-cell split-row-right">
            <div className="split-row-role">{roleLabel(row.role)}</div>
            <div className="split-row-content">{row.rightContent}</div>
          </div>
        </div>
      )

    case 'edited':
      return (
        <div className="split-view-grid split-row edited">
          <div className="split-row-cell split-row-left divergent">
            <div className="split-row-role">{roleLabel(row.role)}</div>
            <div className="split-row-content">{row.leftContent}</div>
          </div>
          <div className="split-row-cell split-row-right divergent">
            <div className="split-row-role-line">
              <span className="split-row-role">{roleLabel(row.role)}</span>
              <span className="split-row-tag edited">edited</span>
              {row.timestampPrefix && <span className="split-row-tag augmented">+timestamp</span>}
              {row.thinkingPrefix && <span className="split-row-tag augmented">+thinking</span>}
            </div>
            <div className="split-row-content">
              {row.thinkingPrefix && (
                <span className="split-row-augmented-thinking">{row.thinkingPrefix}</span>
              )}
              {row.timestampPrefix && (
                <span className="split-row-augmented-timestamp">{row.timestampPrefix}</span>
              )}
              {row.rightContent && !row.timestampPrefix && !row.thinkingPrefix
                ? row.rightContent
                : row.rightContent?.replace(row.timestampPrefix ?? '', '').replace(row.thinkingPrefix ?? '', '')
              }
            </div>
          </div>
        </div>
      )

    case 'augmented':
      return (
        <div className="split-view-grid split-row augmented">
          {/* Left: pregnant space — base content is the same, only packaging differs */}
          <div className="split-row-cell split-row-left match">
            <span className="split-row-pregnant-rule" />
            <span className="split-row-pregnant-label">{roleLabel(row.role)}</span>
          </div>
          {/* Right: full content with augmented prefixes */}
          <div className="split-row-cell split-row-right divergent">
            <div className="split-row-role-line">
              <span className="split-row-role">{roleLabel(row.role)}</span>
              {row.timestampPrefix && <span className="split-row-tag augmented">+timestamp</span>}
              {row.thinkingPrefix && <span className="split-row-tag augmented">+thinking</span>}
            </div>
            <div className="split-row-content">
              {row.thinkingPrefix && (
                <span className="split-row-augmented-thinking">{row.thinkingPrefix}</span>
              )}
              {row.timestampPrefix && (
                <span className="split-row-augmented-timestamp">{row.timestampPrefix}</span>
              )}
              {row.leftContent}
            </div>
          </div>
        </div>
      )

    case 'prefill':
      return (
        <div className="split-view-grid split-row prefill">
          <div className="split-row-cell split-row-left divergent">
            <div className="split-row-role-line">
              <span className="split-row-role">{roleLabel(row.role)}</span>
              <span className="split-row-tag prefill">researcher authored</span>
            </div>
            <div className="split-row-content">{row.leftContent}</div>
          </div>
          <div className="split-row-cell split-row-right divergent">
            <div className="split-row-role-line">
              <span className="split-row-role">{roleLabel(row.role)}</span>
              <span className="split-row-tag prefill">manual</span>
            </div>
            <div className="split-row-content">{row.rightContent}</div>
          </div>
        </div>
      )

    case 'evicted':
      return (
        <div className="split-view-grid split-row evicted">
          <div className="split-row-cell split-row-left">
            <div className="split-row-role">{roleLabel(row.role)}</div>
            <div className="split-row-content">{row.leftContent}</div>
          </div>
          <div className="split-row-cell split-row-right void">
            <span className="split-row-void-label">not in context</span>
          </div>
        </div>
      )

    case 'non-api-role':
      return (
        <div className="split-view-grid split-row non-api-role">
          <div className="split-row-cell split-row-left">
            <div className="split-row-role">{roleLabel(row.role)}</div>
            <div className="split-row-content">{row.leftContent}</div>
          </div>
          <div className="split-row-cell split-row-right void">
            <span className="split-row-void-label">not sent to API</span>
          </div>
        </div>
      )

    case 'system-prompt':
      return (
        <div className="split-view-grid split-row system-prompt">
          <div className="split-row-cell split-row-left">
            {row.leftContent ? (
              <>
                <div className="split-row-section-label">Tree default</div>
                <div className="split-row-system-prompt">{row.leftContent}</div>
              </>
            ) : (
              <>
                <span className="split-row-pregnant-rule" />
                <span className="split-row-pregnant-label">system</span>
              </>
            )}
          </div>
          <div className="split-row-cell split-row-right">
            <div className="split-row-section-label">System prompt</div>
            <div className="split-row-system-prompt">{row.rightContent}</div>
          </div>
        </div>
      )

    case 'metadata':
      return (
        <div className="split-view-grid split-row metadata">
          <div className="split-row-cell split-row-left divergent">
            <div className="split-row-section-label">Tree defaults</div>
            <div className="split-row-metadata-content">{row.leftContent ?? 'none set'}</div>
          </div>
          <div className="split-row-cell split-row-right divergent">
            <div className="split-row-section-label">This generation</div>
            <div className="split-row-metadata-content">{row.rightContent ?? 'none set'}</div>
          </div>
        </div>
      )

    default:
      return null
  }
}
