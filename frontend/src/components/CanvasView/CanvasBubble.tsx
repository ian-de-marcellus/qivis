import type { EraCell } from './eraComputation.ts'
import './CanvasBubble.css'

interface CanvasBubbleProps {
  cell: EraCell
  isFirstEra: boolean
}

export function CanvasBubble({ cell, isFirstEra }: CanvasBubbleProps) {
  // Absent cells: the void
  if (cell.type === 'absent') {
    return <div className="canvas-cell canvas-absent" />
  }

  // Pregnant space: unchanged from the last era that showed this row.
  // Horizontal rule — compact, intentional silence.
  if (!cell.isChanged) {
    return (
      <div className="canvas-cell canvas-match">
        <span className="canvas-match-rule" />
      </div>
    )
  }

  // Active content: full message, no truncation
  const roleClass = cell.role ?? 'user'
  const isEdited = cell.type === 'edited'
  const isSystem = cell.type === 'system-prompt'

  return (
    <div
      className={
        'canvas-cell canvas-content' +
        ` role-${roleClass}` +
        (isEdited ? ' edited' : '') +
        (isSystem ? ' system' : '') +
        (cell.isExcluded ? ' excluded' : '') +
        (!isFirstEra ? ' changed' : '')
      }
    >
      {isEdited && <span className="canvas-tag edited">edited</span>}
      {cell.isExcluded && <span className="canvas-tag excluded-tag">excluded</span>}
      {isSystem && !isFirstEra && <span className="canvas-tag system-tag">system prompt</span>}
      <div className="canvas-text">{cell.content}</div>
    </div>
  )
}
