import type { NodeResponse } from '../../api/types.ts'

interface BranchIndicatorProps {
  node: NodeResponse
  siblings: NodeResponse[]
  onSelect: (siblingId: string) => void
  onCompare?: () => void
}

export function BranchIndicator({ node, siblings, onSelect, onCompare }: BranchIndicatorProps) {
  const currentIndex = siblings.findIndex((s) => s.node_id === node.node_id)
  const count = siblings.length

  return (
    <span className="branch-indicator">
      <button
        className="branch-arrow"
        onClick={() => onSelect(siblings[currentIndex - 1].node_id)}
        disabled={currentIndex <= 0}
        aria-label="Previous branch"
      >
        &#8249;
      </button>
      <span className="branch-label">
        {currentIndex + 1} of {count}
      </span>
      <button
        className="branch-arrow"
        onClick={() => onSelect(siblings[currentIndex + 1].node_id)}
        disabled={currentIndex >= count - 1}
        aria-label="Next branch"
      >
        &#8250;
      </button>
      {onCompare && (
        <button
          className="compare-btn"
          onClick={(e) => { e.stopPropagation(); onCompare() }}
          aria-label="Compare siblings"
        >
          Compare
        </button>
      )}
    </span>
  )
}
