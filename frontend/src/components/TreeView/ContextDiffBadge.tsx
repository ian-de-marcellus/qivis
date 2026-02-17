import type { DiffSummary } from './contextDiffs.ts'
import './ContextDiffBadge.css'

interface ContextDiffBadgeProps {
  summary: DiffSummary
  onClick: () => void
}

export function ContextDiffBadge({ summary, onClick }: ContextDiffBadgeProps) {
  const hasContentChanges =
    summary.editedUpstream > 0 ||
    summary.manualUpstream > 0 ||
    summary.evictedCount > 0

  const count = summary.totalDivergences

  return (
    <span
      className={`diff-badge${hasContentChanges ? ' content-change' : ''}`}
      onClick={onClick}
      title="View context comparison"
    >
      <span className="diff-badge-dot" />
      {count} {count === 1 ? 'diff' : 'diffs'}
    </span>
  )
}
