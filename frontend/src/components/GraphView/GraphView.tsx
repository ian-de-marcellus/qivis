import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { NodeResponse } from '../../api/types.ts'
import { getActivePath, useTreeStore } from '../../store/treeStore.ts'
import { computeTreeLayout, type LayoutNode } from './treeLayout.ts'
import { useZoomPan } from './useZoomPan.ts'
import './GraphView.css'

const NODE_RADIUS = 8
const ACTIVE_RADIUS = 10

const ROLE_LABELS: Record<string, string> = {
  user: 'U',
  assistant: 'A',
  system: 'S',
  researcher_note: 'N',
  tool: 'T',
}

function truncate(text: string, max: number): string {
  if (text.length <= max) return text
  return text.slice(0, max).trimEnd() + '\u2026'
}

/** Cubic bezier edge from parent to child. */
function edgePath(px: number, py: number, cx: number, cy: number): string {
  const midY = (py + cy) / 2
  return `M ${px} ${py} C ${px} ${midY}, ${cx} ${midY}, ${cx} ${cy}`
}

export function GraphView() {
  const { currentTree, branchSelections, navigateToNode, comparisonHoveredNodeId } = useTreeStore()
  const containerRef = useRef<HTMLDivElement>(null)
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null)
  const [tooltip, setTooltip] = useState<{
    node: NodeResponse
    x: number
    y: number
  } | null>(null)

  const { transform, wheelRef, handlers, fitToContent, isPanning } = useZoomPan()

  const nodes = currentTree?.nodes ?? []

  // Compute layout
  const layout = useMemo(() => computeTreeLayout(nodes), [nodes])

  // Build lookup maps
  const layoutMap = useMemo(() => {
    const m = new Map<string, LayoutNode>()
    for (const ln of layout.nodes) m.set(ln.nodeId, ln)
    return m
  }, [layout])

  const nodeMap = useMemo(() => {
    const m = new Map<string, NodeResponse>()
    for (const n of nodes) m.set(n.node_id, n)
    return m
  }, [nodes])

  // Active path
  const activeNodeIds = useMemo(() => {
    const path = getActivePath(nodes, branchSelections)
    return new Set(path.map((n) => n.node_id))
  }, [nodes, branchSelections])

  // Hovered path: all nodes from root to hovered node
  const hoveredPathIds = useMemo(() => {
    if (!hoveredNodeId) return new Set<string>()
    const ids = new Set<string>()
    let current = nodeMap.get(hoveredNodeId)
    while (current) {
      ids.add(current.node_id)
      current = current.parent_id ? nodeMap.get(current.parent_id) : undefined
    }
    return ids
  }, [hoveredNodeId, nodeMap])

  // Comparison hover path: from root to node being hovered in ComparisonView
  const comparisonPathIds = useMemo(() => {
    if (!comparisonHoveredNodeId) return new Set<string>()
    const ids = new Set<string>()
    let current = nodeMap.get(comparisonHoveredNodeId)
    while (current) {
      ids.add(current.node_id)
      current = current.parent_id ? nodeMap.get(current.parent_id) : undefined
    }
    return ids
  }, [comparisonHoveredNodeId, nodeMap])

  // Fit to content on mount and when tree changes
  useEffect(() => {
    if (layout.width <= 0 || !containerRef.current) return
    const rect = containerRef.current.getBoundingClientRect()
    fitToContent(layout.width, layout.height, rect.width, rect.height)
  }, [layout.width, layout.height, fitToContent])

  // Count branches for stats
  const branchCount = useMemo(() => {
    const childMap = new Map<string, number>()
    for (const n of nodes) {
      if (n.parent_id) {
        childMap.set(n.parent_id, (childMap.get(n.parent_id) ?? 0) + 1)
      }
    }
    return [...childMap.values()].filter((c) => c > 1).length
  }, [nodes])

  const handleNodeClick = useCallback(
    (nodeId: string) => {
      navigateToNode(nodeId)
    },
    [navigateToNode],
  )

  const handleNodeHover = useCallback(
    (nodeId: string | null, e?: React.MouseEvent) => {
      if (isPanning.current) return
      setHoveredNodeId(nodeId)
      if (nodeId && e && containerRef.current) {
        const node = nodeMap.get(nodeId)
        if (node) {
          const rect = containerRef.current.getBoundingClientRect()
          setTooltip({
            node,
            x: e.clientX - rect.left + 12,
            y: e.clientY - rect.top + 12,
          })
        }
      } else {
        setTooltip(null)
      }
    },
    [nodeMap, isPanning],
  )

  if (nodes.length === 0) {
    return (
      <div className="graph-view">
        <div className="graph-empty">No nodes yet</div>
      </div>
    )
  }

  // Build edges
  const edges: { parentId: string; childId: string; active: boolean; hovered: boolean; comparison: boolean }[] = []
  for (const ln of layout.nodes) {
    if (ln.parentId) {
      const isActive = activeNodeIds.has(ln.nodeId) && activeNodeIds.has(ln.parentId)
      const isHovered =
        !isActive && hoveredPathIds.has(ln.nodeId) && hoveredPathIds.has(ln.parentId)
      const isComparison =
        !isActive && !isHovered && comparisonPathIds.has(ln.nodeId) && comparisonPathIds.has(ln.parentId)
      edges.push({
        parentId: ln.parentId,
        childId: ln.nodeId,
        active: isActive,
        hovered: isHovered,
        comparison: isComparison,
      })
    }
  }

  // Sort edges: inactive first, comparison/hovered middle, active last (on top)
  edges.sort((a, b) => {
    const priority = (e: typeof a) => (e.active ? 3 : e.hovered ? 2 : e.comparison ? 1 : 0)
    return priority(a) - priority(b)
  })

  return (
    <div className="graph-view" ref={containerRef}>
      <svg
        className="graph-svg"
        ref={wheelRef}
        {...handlers}
      >
        <g
          transform={`translate(${transform.translateX}, ${transform.translateY}) scale(${transform.scale})`}
        >
          {/* Edges */}
          {edges.map((edge) => {
            const parent = layoutMap.get(edge.parentId)
            const child = layoutMap.get(edge.childId)
            if (!parent || !child) return null
            const cls = `graph-edge${edge.active ? ' active' : ''}${edge.hovered ? ' hovered' : ''}${edge.comparison ? ' comparison' : ''}`
            return (
              <path
                key={`${edge.parentId}-${edge.childId}`}
                className={cls}
                d={edgePath(parent.x, parent.y, child.x, child.y)}
              />
            )
          })}

          {/* Nodes */}
          {layout.nodes.map((ln) => {
            const isActive = activeNodeIds.has(ln.nodeId)
            const isHovered = hoveredPathIds.has(ln.nodeId)
            const isComparison = comparisonPathIds.has(ln.nodeId)
            const r = isActive ? ACTIVE_RADIUS : NODE_RADIUS
            const roleClass = `role-${ln.role}`
            const nodeCls = `graph-node ${roleClass}${isActive ? ' active' : ''}${isHovered && !isActive ? ' hovered' : ''}${isComparison && !isActive && !isHovered ? ' comparison' : ''}`
            const labelCls = `graph-node-label${isActive ? ' active' : ''}`

            return (
              <g
                key={ln.nodeId}
                className="graph-node-group"
                onClick={() => handleNodeClick(ln.nodeId)}
                onMouseEnter={(e) => handleNodeHover(ln.nodeId, e)}
                onMouseMove={(e) => {
                  if (hoveredNodeId === ln.nodeId && containerRef.current) {
                    const rect = containerRef.current.getBoundingClientRect()
                    setTooltip((prev) =>
                      prev
                        ? {
                            ...prev,
                            x: e.clientX - rect.left + 12,
                            y: e.clientY - rect.top + 12,
                          }
                        : null,
                    )
                  }
                }}
                onMouseLeave={() => handleNodeHover(null)}
              >
                {/* Hit area — larger invisible circle for easier clicking */}
                <circle
                  className="graph-node-hit"
                  cx={ln.x}
                  cy={ln.y}
                  r={r + 6}
                  fill="transparent"
                  stroke="none"
                />
                {/* Fork ring for branching nodes */}
                {ln.childCount > 1 && (
                  <circle
                    className={`graph-fork-ring${isActive ? ' active' : ''}`}
                    cx={ln.x}
                    cy={ln.y}
                    r={r + 4}
                  />
                )}
                {/* Node circle */}
                <circle
                  className={nodeCls}
                  cx={ln.x}
                  cy={ln.y}
                  r={r}
                />
                {/* Role label */}
                <text
                  className={labelCls}
                  x={ln.x}
                  y={ln.y + r + 11}
                >
                  {ROLE_LABELS[ln.role] ?? '?'}
                </text>
              </g>
            )
          })}
        </g>
      </svg>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="graph-tooltip"
          style={{ left: tooltip.x, top: tooltip.y }}
        >
          <div className="graph-tooltip-role">
            {tooltip.node.role === 'researcher_note' ? 'Note' : tooltip.node.role}
          </div>
          <div className="graph-tooltip-content">
            {truncate(tooltip.node.content, 120)}
          </div>
          {tooltip.node.model && (
            <div className="graph-tooltip-model">{tooltip.node.model}</div>
          )}
        </div>
      )}

      {/* Stats */}
      <div className="graph-stats">
        {nodes.length} nodes{branchCount > 0 ? ` \u00b7 ${branchCount} forks` : ''}
      </div>
    </div>
  )
}
