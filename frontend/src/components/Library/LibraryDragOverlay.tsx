import type { RhizomeSummary } from '../../api/types.ts'

interface Props {
  rhizomes: RhizomeSummary[]
}

export function LibraryDragOverlay({ rhizomes }: Props) {
  if (rhizomes.length === 0) return null

  const primary = rhizomes[0]

  if (rhizomes.length === 1) {
    return (
      <div className="library-drag-overlay">
        <span className="library-drag-overlay-title">{primary.title || 'Untitled'}</span>
      </div>
    )
  }

  // Group drag: stacked cards with count badge
  return (
    <div className="library-drag-overlay-stack">
      <div className="library-drag-overlay">
        <span className="library-drag-overlay-title">{primary.title || 'Untitled'}</span>
        <span className="library-drag-overlay-badge">{rhizomes.length}</span>
      </div>
      <div className="library-drag-overlay" />
      {rhizomes.length > 2 && <div className="library-drag-overlay" />}
    </div>
  )
}
