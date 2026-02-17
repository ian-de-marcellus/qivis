import { useEffect, useRef } from 'react'
import type { ReconstructedContext } from './contextReconstruction.ts'
import { formatSamplingParams } from './contextReconstruction.ts'
import type { ComparisonRow, ComparisonRowType } from './contextDiffs.ts'
import type { DiffSummary } from './contextDiffs.ts'
import './ContextSplitView.css'

interface ContextSplitViewProps {
  rows: ComparisonRow[]
  summary: DiffSummary | null
  contextA: ReconstructedContext
  contextB: ReconstructedContext
  responseContentA: string | null
  responseContentB: string
  comparisonMode: 'original' | 'node'
  onDismiss: () => void
  onCompareToOther: () => void
  onCompareToOriginal: () => void
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

export function ContextSplitView({
  rows,
  summary,
  contextA,
  contextB,
  responseContentA,
  responseContentB,
  comparisonMode,
  onDismiss,
  onCompareToOther,
  onCompareToOriginal,
}: ContextSplitViewProps) {
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

  // Build summary chips (only in original mode)
  const chips: string[] = []
  if (summary) {
    if (summary.editedUpstream > 0) chips.push(`${summary.editedUpstream} edited`)
    if (summary.manualUpstream > 0) chips.push(`${summary.manualUpstream} prefilled`)
    if (summary.evictedCount > 0) chips.push(`${summary.evictedCount} evicted`)
    if (summary.excludedCount > 0) chips.push(`${summary.excludedCount} excluded`)
    if (summary.systemPromptChanged) chips.push('system prompt')
    if (summary.modelChanged) chips.push('model')
    if (summary.providerChanged) chips.push('provider')
    if (summary.samplingChanged) chips.push('params')
    if (summary.thinkingInContextFlag) chips.push('thinking in ctx')
    if (summary.timestampsFlag) chips.push('timestamps')
  }

  const samplingItemsB = formatSamplingParams(contextB.samplingParams)

  // Column labels
  const leftLabel = comparisonMode === 'original'
    ? 'Original'
    : `${contextA.model ?? 'Unknown'} \u00b7 ${formatTimestamp(contextA.timestamp)}`
  const rightLabel = comparisonMode === 'original'
    ? 'Model received'
    : `${contextB.model ?? 'Unknown'} \u00b7 ${formatTimestamp(contextB.timestamp)}`

  return (
    <div className="split-view-backdrop" onClick={handleBackdropClick}>
      <div className="split-view" ref={modalRef} role="dialog" aria-label="Context comparison">

        {/* Header */}
        <div className="split-view-header">
          {comparisonMode === 'node' ? (
            <div className="split-view-header-left split-view-header-comparison">
              <div className="split-view-comparison-side">
                <span className="split-view-comparison-label">A</span>
                <span className="split-view-title">{contextA.model ?? 'Unknown'}</span>
                {contextA.provider && (
                  <span className="split-view-provider">via {contextA.provider}</span>
                )}
                <span className="split-view-timestamp">{formatTimestamp(contextA.timestamp)}</span>
              </div>
              <span className="split-view-comparison-vs">vs</span>
              <div className="split-view-comparison-side">
                <span className="split-view-comparison-label">B</span>
                <span className="split-view-title">{contextB.model ?? 'Unknown'}</span>
                {contextB.provider && (
                  <span className="split-view-provider">via {contextB.provider}</span>
                )}
                <span className="split-view-timestamp">{formatTimestamp(contextB.timestamp)}</span>
              </div>
            </div>
          ) : (
            <div className="split-view-header-left">
              <span className="split-view-title">{contextB.model ?? 'Unknown model'}</span>
              {contextB.provider && (
                <span className="split-view-provider">via {contextB.provider}</span>
              )}
              <span className="split-view-timestamp">{formatTimestamp(contextB.timestamp)}</span>
            </div>
          )}
          <div className="split-view-header-right">
            {chips.length > 0 && (
              <div className="split-view-chips">
                {chips.map((chip) => (
                  <span key={chip} className="split-view-chip">{chip}</span>
                ))}
              </div>
            )}
            {comparisonMode === 'original' ? (
              <button className="split-view-compare-btn" onClick={onCompareToOther}>
                Compare to...
              </button>
            ) : (
              <button className="split-view-compare-btn" onClick={onCompareToOriginal}>
                Compare to Original
              </button>
            )}
            <button className="split-view-close" onClick={onDismiss}>Close</button>
          </div>
        </div>

        {/* Scrollable area: labels + rows */}
        <div className="split-view-scroll">

        {/* Column labels */}
        <div className="split-view-grid split-view-labels">
          <div className="split-view-col-label">{leftLabel}</div>
          <div className="split-view-col-label">{rightLabel}</div>
        </div>

        {/* Rows */}
        <div className="split-view-body">
          {rows.map((row, i) => (
            <SplitRow key={row.nodeId ? `${row.nodeId}-${row.rightNodeId ?? ''}` : `meta-${row.type}-${i}`} row={row} />
          ))}

          {/* Response section */}
          <div className={`split-view-grid split-row response-row${comparisonMode === 'node' ? ' two-responses' : ''}`}>
            {comparisonMode === 'node' && responseContentA != null ? (
              <>
                <div className="split-row-cell split-row-left">
                  <div className="split-row-section-label">Response</div>
                  {contextA.thinkingContent && (
                    <div className="split-row-response-thinking">{contextA.thinkingContent}</div>
                  )}
                  <div className="split-row-content">{responseContentA}</div>
                  {contextA.latencyMs != null && contextA.usage && (
                    <div className="split-row-response-meta">
                      {(contextA.latencyMs / 1000).toFixed(1)}s
                      {' \u00b7 '}
                      {contextA.usage.output_tokens?.toLocaleString()} tokens
                      {contextA.finishReason && ` \u00b7 ${contextA.finishReason}`}
                    </div>
                  )}
                </div>
                <div className="split-row-cell split-row-right">
                  <div className="split-row-section-label">Response</div>
                  {contextB.thinkingContent && (
                    <div className="split-row-response-thinking">{contextB.thinkingContent}</div>
                  )}
                  <div className="split-row-content">{responseContentB}</div>
                  {contextB.latencyMs != null && contextB.usage && (
                    <div className="split-row-response-meta">
                      {(contextB.latencyMs / 1000).toFixed(1)}s
                      {' \u00b7 '}
                      {contextB.usage.output_tokens?.toLocaleString()} tokens
                      {contextB.finishReason && ` \u00b7 ${contextB.finishReason}`}
                    </div>
                  )}
                </div>
              </>
            ) : (
              <>
                <div className="split-row-cell split-row-left match">
                  <span className="split-row-pregnant-rule" />
                  <span className="split-row-pregnant-label">response</span>
                </div>
                <div className="split-row-cell split-row-right">
                  <div className="split-row-section-label">Response</div>
                  {contextB.thinkingContent && (
                    <div className="split-row-response-thinking">{contextB.thinkingContent}</div>
                  )}
                  <div className="split-row-content">{responseContentB}</div>
                  {contextB.latencyMs != null && contextB.usage && (
                    <div className="split-row-response-meta">
                      {(contextB.latencyMs / 1000).toFixed(1)}s
                      {' \u00b7 '}
                      {contextB.usage.output_tokens?.toLocaleString()} tokens
                      {contextB.finishReason && ` \u00b7 ${contextB.finishReason}`}
                    </div>
                  )}
                </div>
              </>
            )}
          </div>

          {/* Sampling params if any */}
          {samplingItemsB.length > 0 && (
            <div className="split-view-grid split-view-footer-row">
              <div className="split-row-cell split-row-left match">
                <span className="split-row-pregnant-rule" />
                <span className="split-row-pregnant-label">params</span>
              </div>
              <div className="split-row-cell split-row-right">
                <div className="split-row-section-label">Sampling parameters</div>
                <div className="split-row-params">
                  {samplingItemsB.map((item) => (
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
    </div>
  )
}

function SplitRow({ row }: { row: ComparisonRow }) {
  const type: ComparisonRowType = row.type

  switch (type) {
    case 'match':
      return (
        <div className="split-row match spanning">
          <div className="split-row-cell split-row-spanning">
            <div className="split-row-role">{roleLabel(row.role)}</div>
            <div className="split-row-content">{row.rightContent}</div>
          </div>
        </div>
      )

    case 'content-differs':
      return (
        <div className="split-view-grid split-row content-differs">
          <div className="split-row-cell split-row-left divergent">
            <div className="split-row-role-line">
              <span className="split-row-role">{roleLabel(row.role)}</span>
              {row.leftTags.map((tag) => (
                <span key={tag} className={`split-row-tag ${tagClass(tag)}`}>{tag}</span>
              ))}
            </div>
            <div className="split-row-content">{row.leftContent}</div>
          </div>
          <div className="split-row-cell split-row-right divergent">
            <div className="split-row-role-line">
              <span className="split-row-role">{roleLabel(row.role)}</span>
              {row.rightTags.map((tag) => (
                <span key={tag} className={`split-row-tag ${tagClass(tag)}`}>{tag}</span>
              ))}
            </div>
            <div className="split-row-content">{row.rightContent}</div>
          </div>
        </div>
      )

    case 'status-differs':
      return (
        <div className="split-view-grid split-row status-differs">
          {row.leftStatus === 'in-context' ? (
            <div className="split-row-cell split-row-left">
              <div className="split-row-role-line">
                <span className="split-row-role">{roleLabel(row.role)}</span>
                {row.leftTags.map((tag) => (
                  <span key={tag} className={`split-row-tag ${tagClass(tag)}`}>{tag}</span>
                ))}
              </div>
              <div className="split-row-content">{row.leftContent}</div>
            </div>
          ) : (
            <div className="split-row-cell split-row-left void">
              <span className="split-row-void-label">{statusLabel(row.leftStatus)}</span>
            </div>
          )}
          {row.rightStatus === 'in-context' ? (
            <div className="split-row-cell split-row-right">
              <div className="split-row-role-line">
                <span className="split-row-role">{roleLabel(row.role)}</span>
                {row.rightTags.map((tag) => (
                  <span key={tag} className={`split-row-tag ${tagClass(tag)}`}>{tag}</span>
                ))}
              </div>
              <div className="split-row-content">{row.rightContent}</div>
            </div>
          ) : (
            <div className="split-row-cell split-row-right void">
              <span className="split-row-void-label">{statusLabel(row.rightStatus)}</span>
            </div>
          )}
        </div>
      )

    case 'left-only':
      return (
        <div className="split-view-grid split-row left-only">
          <div className="split-row-cell split-row-left">
            <div className="split-row-role-line">
              <span className="split-row-role">{roleLabel(row.role)}</span>
              {row.leftTags.map((tag) => (
                <span key={tag} className={`split-row-tag ${tagClass(tag)}`}>{tag}</span>
              ))}
            </div>
            <div className="split-row-content">{row.leftContent}</div>
          </div>
          <div className="split-row-cell split-row-right void">
            <span className="split-row-void-label">not on this path</span>
          </div>
        </div>
      )

    case 'right-only':
      return (
        <div className="split-view-grid split-row right-only">
          <div className="split-row-cell split-row-left void">
            <span className="split-row-void-label">not on this path</span>
          </div>
          <div className="split-row-cell split-row-right">
            <div className="split-row-role-line">
              <span className="split-row-role">{roleLabel(row.role)}</span>
              {row.rightTags.map((tag) => (
                <span key={tag} className={`split-row-tag ${tagClass(tag)}`}>{tag}</span>
              ))}
            </div>
            <div className="split-row-content">{row.rightContent}</div>
          </div>
        </div>
      )

    case 'fork-point':
      return (
        <div className="split-view-grid split-row fork-point">
          <div className="split-row-fork-divider">
            <span className="split-row-fork-label">paths diverge</span>
          </div>
        </div>
      )

    case 'fork-pair':
      return (
        <div className="split-view-grid split-row fork-pair">
          <div className="split-row-cell split-row-left">
            <div className="split-row-role-line">
              <span className="split-row-role">{roleLabel(row.role)}</span>
              {row.leftTags.map((tag) => (
                <span key={tag} className={`split-row-tag ${tagClass(tag)}`}>{tag}</span>
              ))}
            </div>
            <div className="split-row-content">{row.leftContent}</div>
          </div>
          <div className="split-row-cell split-row-right">
            <div className="split-row-role-line">
              <span className="split-row-role">{roleLabel(row.rightRole ?? row.role)}</span>
              {row.rightTags.map((tag) => (
                <span key={tag} className={`split-row-tag ${tagClass(tag)}`}>{tag}</span>
              ))}
            </div>
            <div className="split-row-content">{row.rightContent}</div>
          </div>
        </div>
      )

    case 'system-prompt':
      return (
        <div className="split-view-grid split-row system-prompt">
          <div className="split-row-cell split-row-left">
            {row.leftContent ? (
              <>
                <div className="split-row-section-label">System prompt</div>
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
            <div className="split-row-section-label">Configuration</div>
            <div className="split-row-metadata-content">{row.leftContent ?? 'none set'}</div>
          </div>
          <div className="split-row-cell split-row-right divergent">
            <div className="split-row-section-label">Configuration</div>
            <div className="split-row-metadata-content">{row.rightContent ?? 'none set'}</div>
          </div>
        </div>
      )

    default:
      return null
  }
}

function tagClass(tag: string): string {
  if (tag === 'edited') return 'edited'
  if (tag === 'manual') return 'prefill'
  if (tag.startsWith('+')) return 'augmented'
  if (tag === 'excluded' || tag === 'evicted') return 'status-tag'
  return ''
}

function statusLabel(status: string | null): string {
  if (status === 'excluded') return 'excluded'
  if (status === 'evicted') return 'not in context'
  if (status === 'non-api') return 'not sent to API'
  return ''
}
