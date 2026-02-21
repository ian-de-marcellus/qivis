import type { TreeSummary } from '../../api/types.ts'

interface Props {
  trees: TreeSummary[]
}

export function LibraryDragOverlay({ trees }: Props) {
  if (trees.length === 0) return null

  const primary = trees[0]

  if (trees.length === 1) {
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
        <span className="library-drag-overlay-badge">{trees.length}</span>
      </div>
      <div className="library-drag-overlay" />
      {trees.length > 2 && <div className="library-drag-overlay" />}
    </div>
  )
}
