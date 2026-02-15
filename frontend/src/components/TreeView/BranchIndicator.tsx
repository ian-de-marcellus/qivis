import type { NodeResponse } from '../../api/types.ts'

interface BranchIndicatorProps {
  node: NodeResponse
  siblings: NodeResponse[]
  onSelect: (siblingId: string) => void
}

export function BranchIndicator({ node, siblings, onSelect }: BranchIndicatorProps) {
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
        &#9664;
      </button>
      <span className="branch-label">
        {currentIndex + 1}/{count}
      </span>
      <button
        className="branch-arrow"
        onClick={() => onSelect(siblings[currentIndex + 1].node_id)}
        disabled={currentIndex >= count - 1}
        aria-label="Next branch"
      >
        &#9654;
      </button>
    </span>
  )
}
