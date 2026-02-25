/**
 * CompletionNode — renders a completion-mode response.
 *
 * Key differences from MessageRow:
 * - Logprob heatmap ON by default (the heatmap IS the content)
 * - No markdown rendering — raw text when heatmap is toggled off
 * - Model name as header, not "Assistant" role label
 * - Collapsible prompt text section
 * - Prominent standalone FULL VOCAB badge
 * - Simplified action menu (no edit, no split view, no comparison)
 */

import { memo, useState } from 'react'
import type { LogprobData, NodeResponse } from '../../api/types.ts'
import { useTreeStore } from '../../store/treeStore.ts'
import { ActionMenu, ActionMenuItem } from './ActionMenu.tsx'
import { AnnotationPanel } from './AnnotationPanel.tsx'
import { BranchIndicator } from './BranchIndicator.tsx'
import { ContextBar } from './ContextBar.tsx'
import { LogprobOverlay, averageCertainty, uncertaintyColor } from './LogprobOverlay.tsx'
import { NotePanel } from './NotePanel.tsx'
import { PromptTextViewer } from './PromptTextViewer.tsx'
import { ThinkingSection } from './ThinkingSection.tsx'
import { formatTimestamp, formatSamplingMeta } from './MessageRow.tsx'
import './CompletionNode.css'

export interface CompletionNodeActions {
  onSelectSibling: (siblingId: string) => void
  onFork: () => void
  onGenerate?: () => void
  onBookmarkToggle?: () => void
  onExcludeToggle?: () => void
  onAnchorToggle?: () => void
  onSummarize?: () => void
}

interface CompletionNodeProps {
  node: NodeResponse
  siblings: NodeResponse[]
  actions: CompletionNodeActions
  isExcludedOnPath?: boolean
}

export const CompletionNode = memo(function CompletionNode({
  node, siblings, actions, isExcludedOnPath,
}: CompletionNodeProps) {
  const {
    onSelectSibling, onFork, onGenerate,
    onBookmarkToggle, onExcludeToggle, onAnchorToggle, onSummarize,
  } = actions

  // Logprobs ON by default for completion nodes — inverted from MessageRow
  const logprobs: LogprobData | null = node.logprobs
  const [showLogprobs, setShowLogprobs] = useState(logprobs != null)
  const [showAnnotations, setShowAnnotations] = useState(false)
  const [showNotes, setShowNotes] = useState(false)

  const editHistoryCache = useTreeStore((s) => s.editHistoryCache)

  const avgCertainty = logprobs ? averageCertainty(logprobs) : null
  const hasEditHistory = node.edited_content != null || node.edit_count > 0
    || (editHistoryCache[node.node_id]?.length ?? 0) > 0

  const rowClasses = [
    'message-row', 'completion-node',
    isExcludedOnPath && 'excluded',
  ].filter(Boolean).join(' ')

  return (
    <div className={rowClasses} data-node-id={node.node_id}>
      <div className="completion-header">
        {/* Model name as primary label instead of "Assistant" */}
        <span className="completion-model">{node.model ?? 'completion'}</span>

        {node.sibling_count > 1 && (
          <BranchIndicator
            node={node}
            siblings={siblings}
            onSelect={onSelectSibling}
          />
        )}

        {/* Generation actions */}
        <ActionMenu
          pushRight
          triggerAriaLabel="Generation actions"
          trigger={
            <svg viewBox="0 0 16 16" width="11" height="11">
              <path d="M7 2a1 1 0 1 1 2 0v4.3l3.3 3.2a1 1 0 0 1 0 1.4l-.1.1a1 1 0 0 1-1.4 0L8 8.2 5.2 11a1 1 0 0 1-1.4 0l-.1-.1a1 1 0 0 1 0-1.4L7 6.3V2z" fill="currentColor"/>
            </svg>
          }
        >
          <ActionMenuItem onClick={onFork}>Regenerate</ActionMenuItem>
          {onGenerate && (
            <ActionMenuItem onClick={onGenerate}>Generate</ActionMenuItem>
          )}
        </ActionMenu>

        {/* Research actions */}
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

        {/* Context actions */}
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

      {/* FULL VOCAB badge — standalone, prominent */}
      {logprobs?.full_vocab_available && (
        <div className="full-vocab-standalone">FULL VOCAB</div>
      )}

      {node.thinking_content && (
        <ThinkingSection thinkingContent={node.thinking_content} />
      )}

      {/* Content: heatmap primary, raw text secondary */}
      <div className="message-content">
        {showLogprobs && logprobs ? (
          <LogprobOverlay logprobs={logprobs} />
        ) : (
          <span className="raw-text">{node.content}</span>
        )}
      </div>

      {/* Prompt text — collapsible */}
      {node.prompt_text && (
        <PromptTextViewer
          promptText={node.prompt_text}
          inputTokens={node.usage?.input_tokens}
        />
      )}

      {node.context_usage != null && (
        <ContextBar contextUsage={node.context_usage} />
      )}

      {showAnnotations && <AnnotationPanel node={node} />}
      {showNotes && <NotePanel node={node} />}

      {/* Meta line */}
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
        {formatSamplingMeta(node.sampling_params).map((label) => (
          <span key={label} className="sampling-meta">{` \u00b7 ${label}`}</span>
        ))}
        {/* Certainty toggle — clicking toggles heatmap off */}
        <span> &middot; </span>
        <span
          className={`certainty-badge${showLogprobs ? ' active' : ''}`}
          onClick={() => setShowLogprobs(!showLogprobs)}
          title={showLogprobs
            ? (logprobs ? 'Hide token probabilities' : 'Show rendered text')
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
            <span className="raw-badge-label">{showLogprobs ? 'text' : 'raw'}</span>
          )}
        </span>
      </div>
    </div>
  )
}, (prev, next) =>
  prev.node === next.node &&
  prev.siblings === next.siblings &&
  prev.isExcludedOnPath === next.isExcludedOnPath
)
