import { memo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { LogprobData, NodeResponse, SamplingParams } from '../../api/types.ts'
import { useTreeStore } from '../../store/treeStore.ts'
import { ActionMenu, ActionMenuItem } from './ActionMenu.tsx'
import { AnnotationPanel } from './AnnotationPanel.tsx'
import { NotePanel } from './NotePanel.tsx'
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
  onSummarize?: () => void
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
    onSummarize,
  } = actions

  const [showLogprobs, setShowLogprobs] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const [editValue, setEditValue] = useState('')
  const [showAnnotations, setShowAnnotations] = useState(false)
  const [showNotes, setShowNotes] = useState(false)

  const editHistoryCache = useTreeStore((s) => s.editHistoryCache)

  const roleLabel = node.role === 'researcher_note'
    ? 'Researcher Note'
    : node.role.charAt(0).toUpperCase() + node.role.slice(1)

  const logprobs: LogprobData | null = node.logprobs
  const avgCertainty = logprobs ? averageCertainty(logprobs) : null

  const isManual = node.role === 'assistant' && node.mode === 'manual'
  const isPrefill = node.mode === 'prefill' && node.prefill_content != null
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
        {/* ---- Generation group ---- */}
        <ActionMenu
          pushRight
          triggerAriaLabel="Generation actions"
          trigger={
            <svg viewBox="0 0 16 16" width="11" height="11">
              <path d="M7 2a1 1 0 1 1 2 0v4.3l3.3 3.2a1 1 0 0 1 0 1.4l-.1.1a1 1 0 0 1-1.4 0L8 8.2 5.2 11a1 1 0 0 1-1.4 0l-.1-.1a1 1 0 0 1 0-1.4L7 6.3V2z" fill="currentColor"/>
            </svg>
          }
        >
          <ActionMenuItem onClick={onFork}>
            {node.role === 'assistant' ? 'Regenerate' : 'Fork'}
          </ActionMenuItem>
          {onPrefill && node.role === 'user' && (
            <ActionMenuItem onClick={onPrefill}>Prefill</ActionMenuItem>
          )}
          {onGenerate && node.role === 'user' && (
            <ActionMenuItem onClick={onGenerate}>Generate</ActionMenuItem>
          )}
        </ActionMenu>
        {onEdit && !isEditing && (
          <button
            className="hover-btn edit-btn"
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
          <button className="hover-btn inspect-btn" onClick={onInspect} aria-label="View generation context">
            Context
          </button>
        )}
        {/* ---- Research group (quill) ---- */}
        <ActionMenu
          triggerAriaLabel="Research actions"
          isActive={node.annotation_count > 0 || node.note_count > 0 || !!node.is_bookmarked}
          badge={(node.annotation_count || 0) + (node.note_count || 0)}
          trigger={
            <svg viewBox="0 0 16 16" width="11" height="11">
              <path d="M13.3 1.2c-.6 0-1.4.5-2.3 1.3C9 4.2 7 7 5.8 9.5L4.5 14l.7.5c1.2-1.4 3-3.5 4.5-5.5 1.3-1.8 2.5-4 3-5.6.2-.7.2-1.3 0-1.7-.1-.3-.3-.5-.4-.5zM4 14.5l-.5.5h1l-.5-.5z" fill="currentColor"/>
            </svg>
          }
          align="right"
        >
          <ActionMenuItem
            onClick={() => setShowAnnotations(!showAnnotations)}
            active={showAnnotations}
          >
            Tag{node.annotation_count > 0 && (
              <span className="badge annotation-badge">{node.annotation_count}</span>
            )}
          </ActionMenuItem>
          <ActionMenuItem
            onClick={() => setShowNotes(!showNotes)}
            active={showNotes}
          >
            Note{node.note_count > 0 && (
              <span className="badge annotation-badge">{node.note_count}</span>
            )}
          </ActionMenuItem>
          {onBookmarkToggle && (
            <ActionMenuItem onClick={onBookmarkToggle} active={!!node.is_bookmarked}>
              {node.is_bookmarked ? 'Marked' : 'Mark'}
            </ActionMenuItem>
          )}
          {onSummarize && (
            <ActionMenuItem onClick={onSummarize}>
              Summarize
            </ActionMenuItem>
          )}
        </ActionMenu>
        {/* ---- Context group ---- */}
        {(onExcludeToggle || onAnchorToggle) && (
          <ActionMenu
            triggerAriaLabel="Context actions"
            isActive={!!isExcludedOnPath || !!node.is_anchored}
            trigger={
              <svg viewBox="0 0 16 16" width="11" height="11">
                <path d="M8 3C4.5 3 1.5 8 1.5 8s3 5 6.5 5 6.5-5 6.5-5S11.5 3 8 3zm0 8.5a3.5 3.5 0 1 1 0-7 3.5 3.5 0 0 1 0 7zM8 6a2 2 0 1 0 0 4 2 2 0 0 0 0-4z" fill="currentColor"/>
              </svg>
            }
            align="right"
          >
            {onExcludeToggle && (
              <ActionMenuItem
                onClick={onExcludeToggle}
                active={!!isExcludedOnPath}
                className={isExcludedOnPath ? 'item-warn' : undefined}
              >
                {isExcludedOnPath ? 'Include' : 'Exclude'}
              </ActionMenuItem>
            )}
            {onAnchorToggle && (
              <ActionMenuItem onClick={onAnchorToggle} active={!!node.is_anchored}>
                {node.is_anchored ? 'Unanchor' : 'Anchor'}
              </ActionMenuItem>
            )}
          </ActionMenu>
        )}
        {isExcludedOnPath && (
          <span className="excluded-label">excluded from context</span>
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
          ) : isPrefill ? (
            /* Prefill node — show researcher's prefix and model's continuation separately */
            <>
              <div className="prefill-overlay">
                <div className="prefill-overlay-label">prefill</div>
                <div className="prefill-overlay-content">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {node.prefill_content!}
                  </ReactMarkdown>
                </div>
              </div>
              <div className="message-content">
                {showLogprobs && logprobs ? (
                  <LogprobOverlay logprobs={logprobs} />
                ) : showLogprobs ? (
                  <span className="raw-text">{node.content.slice(node.prefill_content!.length)}</span>
                ) : (
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {node.content.slice(node.prefill_content!.length)}
                  </ReactMarkdown>
                )}
              </div>
            </>
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
      {showNotes && <NotePanel node={node} />}
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
