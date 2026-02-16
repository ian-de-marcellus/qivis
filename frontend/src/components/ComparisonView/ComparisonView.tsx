import { useEffect, useMemo } from 'react'
import type { NodeResponse } from '../../api/types.ts'
import { useTreeStore } from '../../store/treeStore.ts'
import { ComparisonCard } from './ComparisonCard.tsx'
import { computeWordDiff } from './wordDiff.ts'
import './ComparisonView.css'

interface ComparisonViewProps {
  siblings: NodeResponse[]
  selectedNodeId: string
  onSelect: (nodeId: string) => void
  onDismiss: () => void
}

export function ComparisonView({ siblings, selectedNodeId, onSelect, onDismiss }: ComparisonViewProps) {
  const setComparisonHoveredNodeId = useTreeStore((s) => s.setComparisonHoveredNodeId)

  // Clear comparison hover when unmounted (e.g. dismiss while hovering a card)
  useEffect(() => {
    return () => setComparisonHoveredNodeId(null)
  }, [setComparisonHoveredNodeId])

  const selectedNode = siblings.find((s) => s.node_id === selectedNodeId)
  const baseContent = selectedNode?.content ?? ''

  // Compute diffs for each non-selected sibling against the selected one
  const diffs = useMemo(() => {
    const map = new Map<string, ReturnType<typeof computeWordDiff>>()
    for (const sib of siblings) {
      if (sib.node_id !== selectedNodeId) {
        map.set(sib.node_id, computeWordDiff(baseContent, sib.content))
      }
    }
    return map
  }, [siblings, selectedNodeId, baseContent])

  // Order: selected first, then remaining by sibling_index
  const ordered = useMemo(() => {
    const selected = siblings.filter((s) => s.node_id === selectedNodeId)
    const rest = siblings
      .filter((s) => s.node_id !== selectedNodeId)
      .sort((a, b) => a.sibling_index - b.sibling_index)
    return [...selected, ...rest]
  }, [siblings, selectedNodeId])

  return (
    <div className="comparison-view">
      <div className="comparison-header">
        <span className="comparison-title">
          Comparing {siblings.length} responses
        </span>
        <button
          className="comparison-dismiss"
          onClick={onDismiss}
          aria-label="Dismiss comparison"
        >
          &#x2715;
        </button>
      </div>
      <div className="comparison-grid">
        {ordered.map((node) => (
          <ComparisonCard
            key={node.node_id}
            node={node}
            isSelected={node.node_id === selectedNodeId}
            diffSegments={diffs.get(node.node_id)}
            onSelect={onSelect}
          />
        ))}
      </div>
    </div>
  )
}
