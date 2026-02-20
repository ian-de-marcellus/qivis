import { memo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { LogprobData, NodeResponse, SamplingParams } from '../../api/types.ts'
import { useTreeStore } from '../../store/treeStore.ts'
import { AnnotationPanel } from './AnnotationPanel.tsx'
import { BranchIndicator } from './BranchIndicator.tsx'
import { ContextBar } from './ContextBar.tsx'
import { ContextDiffBadge } from './ContextDiffBadge.tsx'
import type { DiffSummary } from './contextDiffs.ts'
import { EditHistory } from './EditHistory.tsx'
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

export interface MessageRowActions {
  onSelectSibling: (siblingId: string) => void
  onFork: () => void
  onPrefill?: () => void
  onGenerate?: () => void
  onCompare?: () => void
  onEdit?: (nodeId: string, editedContent: string | null) => void
  onInspect?: () => void
  onBookmarkToggle?: () => void
  onExcludeToggle?: () => void
  onAnchorToggle?: () => void
  onGroupToggle?: () => void
  onSplitView?: () => void
  onComparisonPick?: () => void
}

interface MessageRowProps {
  node: NodeResponse
  siblings: NodeResponse[]
  actions: MessageRowActions
  isExcludedOnPath?: boolean
  groupSelectable?: boolean
  groupSelected?: boolean
  diffSummary?: DiffSummary
  highlightClass?: 'highlight-used' | 'highlight-other'
  comparisonPickable?: boolean
}

export const MessageRow = memo(function MessageRow({
  node, siblings, actions, isExcludedOnPath, groupSelectable,
  groupSelected, diffSummary, highlightClass, comparisonPickable,
}: MessageRowProps) {
  const {
    onSelectSibling, onFork, onPrefill, onGenerate, onCompare,
    onEdit, onInspect, onBookmarkToggle, onExcludeToggle,
    onAnchorToggle, onGroupToggle, onSplitView, onComparisonPick,
  } = actions

  const [showLogprobs, setShowLogprobs] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const [editValue, setEditValue] = useState('')
  const [showAnnotations, setShowAnnotations] = useState(false)

  const editHistoryCache = useTreeStore((s) => s.editHistoryCache)

  const roleLabel = node.role === 'researcher_note'
    ? 'Researcher Note'
    : node.role.charAt(0).toUpperCase() + node.role.slice(1)

  const logprobs: LogprobData | null = node.logprobs
  const avgCertainty = logprobs ? averageCertainty(logprobs) : null

  const isManual = node.role === 'assistant' && node.mode === 'manual'
  const hasEdit = node.edited_content != null
  const hasEditHistory = hasEdit || node.edit_count > 0 || (editHistoryCache[node.node_id]?.length ?? 0) > 0
  const inPickingMode = comparisonPickable != null
  const rowClasses = [
    'message-row', node.role, highlightClass,
    isExcludedOnPath && 'excluded',
    groupSelectable && 'group-selectable',
    groupSelected && 'group-selected',
    comparisonPickable && 'comparison-pickable',
    inPickingMode && !comparisonPickable && 'comparison-dimmed',
  ].filter(Boolean).join(' ')

  const handleRowClick = groupSelectable
    ? onGroupToggle
    : comparisonPickable
      ? onComparisonPick
      : undefined

  return (
    <div className={rowClasses} data-node-id={node.node_id} onClick={handleRowClick}>
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
        {onPrefill && node.role === 'user' && (
          <button className="prefill-btn" onClick={onPrefill} aria-label="Prefill response">
            Prefill
          </button>
        )}
        {onGenerate && node.role === 'user' && (
          <button className="generate-btn" onClick={onGenerate} aria-label="Generate response">
            Generate
          </button>
        )}
        {onEdit && !isEditing && (
          <button
            className="edit-btn"
            onClick={() => {
              setEditValue(node.edited_content ?? node.content)
              setIsEditing(true)
            }}
            aria-label="Edit message"
          >
            Edit
          </button>
        )}
        {onInspect && node.role === 'assistant' && !isManual && (
          <button className="inspect-btn" onClick={onInspect} aria-label="View generation context">
            Context
          </button>
        )}
        <button
          className={`annotate-btn${showAnnotations ? ' active' : ''}`}
          onClick={() => setShowAnnotations(!showAnnotations)}
          aria-label="Toggle annotations"
        >
          Tag{node.annotation_count > 0 && (
            <span className="annotation-badge">{node.annotation_count}</span>
          )}
        </button>
        {onBookmarkToggle && (
          <button
            className={`bookmark-btn${node.is_bookmarked ? ' active' : ''}`}
            onClick={onBookmarkToggle}
            aria-label={node.is_bookmarked ? 'Remove bookmark' : 'Bookmark'}
          >
            {node.is_bookmarked ? 'Marked' : 'Mark'}
          </button>
        )}
        {isExcludedOnPath && (
          <span className="excluded-label">excluded from context</span>
        )}
        {onExcludeToggle && (
          <button
            className={`exclude-btn${isExcludedOnPath ? ' active' : ''}`}
            onClick={onExcludeToggle}
            aria-label={isExcludedOnPath ? 'Include in context' : 'Exclude from context'}
          >
            {isExcludedOnPath ? 'Include' : 'Exclude'}
          </button>
        )}
        {onAnchorToggle && (
          <button
            className={`anchor-btn${node.is_anchored ? ' active' : ''}`}
            onClick={onAnchorToggle}
            aria-label={node.is_anchored ? 'Remove anchor (allow eviction)' : 'Anchor (protect from eviction)'}
            title={node.is_anchored ? 'Anchored — protected from eviction' : 'Anchor — protect from eviction'}
          >
            <svg className="anchor-icon" viewBox="0 0 16 16" width="12" height="12">
              <path d="M8 1a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V6h3a1 1 0 0 1 1 1v1.5a.5.5 0 0 1-1 0V7.5h-3V13c2.5-.5 4-2 4.5-4a.5.5 0 0 1 .97.24C13.8 12.2 11.5 14.5 8 15c-3.5-.5-5.8-2.8-6.47-5.76a.5.5 0 0 1 .97-.24c.5 2 2 3.5 4.5 4V7.5H4V8.5a.5.5 0 0 1-1 0V7a1 1 0 0 1 1-1h3V4.73A2 2 0 0 1 8 1zm0 1a1 1 0 1 0 0 2 1 1 0 0 0 0-2z" fill="currentColor"/>
            </svg>
          </button>
        )}
      </div>
      {node.thinking_content && (
        <ThinkingSection thinkingContent={node.thinking_content} />
      )}
      {isEditing && onEdit ? (
        <div className="inline-editor">
          <textarea
            className="edit-textarea"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                setIsEditing(false)
              } else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                onEdit(node.node_id, editValue)
                setIsEditing(false)
              }
            }}
            autoFocus
            rows={Math.max(3, editValue.split('\n').length)}
          />
          <div className="edit-actions">
            <button
              className="edit-save"
              onClick={() => {
                onEdit(node.node_id, editValue)
                setIsEditing(false)
              }}
            >
              Save
            </button>
            <button
              className="edit-cancel"
              onClick={() => setIsEditing(false)}
            >
              Cancel
            </button>
            <span className="edit-hint">Cmd+Enter to save, Esc to cancel</span>
            <span className="edit-kindness">You're rewriting the model's memory. Be kind.</span>
          </div>
        </div>
      ) : (
        <>
          {isManual ? (
            /* Manual node — the whole content is fabricated, so it lives inside the slip */
            <div className="edit-overlay">
              <div className="edit-overlay-label">researcher authored</div>
              <div className="edit-overlay-content">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {node.content}
                  </ReactMarkdown>
                </div>
            </div>
          ) : (
            <>
              {/* Original content — always primary, always the truth */}
              <div className="message-content">
                {showLogprobs && logprobs ? (
                  <LogprobOverlay logprobs={logprobs} />
                ) : showLogprobs ? (
                  <span className="raw-text">{node.content}</span>
                ) : (
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {node.content}
                  </ReactMarkdown>
                )}
              </div>

              {/* Edit overlay — the correction slip */}
              {hasEdit && (
                <div className="edit-overlay">
                  <div className="edit-overlay-label">model sees</div>
                  <div className="edit-overlay-content">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {node.edited_content ?? ''}
                    </ReactMarkdown>
                  </div>
                </div>
              )}
            </>
          )}

          {/* Collapsible edit history — visible when edited or when cache has entries */}
          {hasEditHistory && <EditHistory node={node} />}
        </>
      )}
      {node.role === 'assistant' && node.context_usage != null && (
        <ContextBar contextUsage={node.context_usage} />
      )}
      {showAnnotations && <AnnotationPanel node={node} />}
      <div className="message-meta">
        {formatTimestamp(node.created_at)}
        {hasEditHistory && (
          <span className="edited-indicator"> &middot; edited</span>
        )}
        {node.latency_ms != null && (
          <>
            {` \u00b7 ${(node.latency_ms / 1000).toFixed(1)}s`}
            {node.usage && ` \u00b7 ${node.usage.input_tokens.toLocaleString()}+${node.usage.output_tokens.toLocaleString()} tok`}
          </>
        )}
        {node.role === 'assistant' && formatSamplingMeta(node.sampling_params).map((label) => (
          <span key={label} className="sampling-meta">{` \u00b7 ${label}`}</span>
        ))}
        {diffSummary && diffSummary.totalDivergences > 0 && onSplitView && (
          <>
            {' \u00b7 '}
            <ContextDiffBadge summary={diffSummary} onClick={onSplitView} />
          </>
        )}
        {node.role === 'assistant' && !isManual && (
          <>
            {' \u00b7 '}
            <span
              className={`certainty-badge${showLogprobs ? ' active' : ''}`}
              onClick={() => setShowLogprobs(!showLogprobs)}
              title={showLogprobs
                ? (logprobs ? 'Hide token probabilities' : 'Show rendered markdown')
                : (logprobs ? 'Show token probabilities' : 'Show raw text')}
            >
              {avgCertainty != null ? (
                <>
                  <span
                    className="certainty-dot"
                    style={{ backgroundColor: uncertaintyColor(avgCertainty) === 'transparent'
                      ? 'var(--ctx-green)'
                      : uncertaintyColor(avgCertainty)
                    }}
                  />
                  {(avgCertainty * 100).toFixed(0)}%
                </>
              ) : (
                <span className="raw-badge-label">{showLogprobs ? 'md' : 'raw'}</span>
              )}
            </span>
          </>
        )}
      </div>
    </div>
  )
}, (prev, next) =>
  prev.node === next.node &&
  prev.siblings === next.siblings &&
  prev.isExcludedOnPath === next.isExcludedOnPath &&
  prev.groupSelectable === next.groupSelectable &&
  prev.groupSelected === next.groupSelected &&
  prev.diffSummary === next.diffSummary &&
  prev.highlightClass === next.highlightClass &&
  prev.comparisonPickable === next.comparisonPickable
)
