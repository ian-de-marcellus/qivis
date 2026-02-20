import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { DigressionGroupResponse, EvictionStrategy, NodeResponse } from '../../api/types.ts'
import { getActivePath, useTreeStore } from '../../store/treeStore.ts'
import { computeTreeLayout, type LayoutNode } from './treeLayout.ts'
import { useZoomPan } from './useZoomPan.ts'
import './GraphView.css'

const NODE_RADIUS = 8
const ACTIVE_RADIUS = 10
const COLLAPSE_THRESHOLD = 3 // collapse runs of 3+ boring interior nodes

// Cycling palette for digression group hulls — very subtle fills, soft borders
const GROUP_COLORS = [
  { fill: 'rgba(99, 155, 255, 0.035)', stroke: 'rgba(99, 155, 255, 0.18)' },
  { fill: 'rgba(255, 155, 99, 0.035)', stroke: 'rgba(255, 155, 99, 0.18)' },
  { fill: 'rgba(99, 220, 155, 0.035)', stroke: 'rgba(99, 220, 155, 0.18)' },
  { fill: 'rgba(200, 130, 255, 0.035)', stroke: 'rgba(200, 130, 255, 0.18)' },
  { fill: 'rgba(255, 200, 80, 0.035)', stroke: 'rgba(255, 200, 80, 0.18)' },
  { fill: 'rgba(255, 120, 160, 0.035)', stroke: 'rgba(255, 120, 160, 0.18)' },
]

const ROLE_LABELS: Record<string, string> = {
  user: 'U',
  assistant: 'A',
  system: 'S',
  researcher_note: 'N',
  tool: 'T',
}

// ---------------------------------------------------------------------------
// Chain collapsing: hide boring linear runs in the graph
// ---------------------------------------------------------------------------

interface CollapsedSegment {
  hiddenNodeIds: string[]
  count: number
}

/**
 * Collapse long linear chains in the graph to save vertical space.
 * A node is "boring" (collapsible) if it has exactly 1 child, its parent
 * has exactly 1 child, and it has no interesting metadata (anchored, excluded,
 * bookmarked, annotated, at a group boundary).
 */
function collapseLinearChains(
  nodes: NodeResponse[],
  digressionGroups: DigressionGroupResponse[],
): { displayNodes: NodeResponse[]; collapsedMap: Map<string, CollapsedSegment> } {
  const empty = { displayNodes: nodes, collapsedMap: new Map<string, CollapsedSegment>() }
  if (nodes.length < COLLAPSE_THRESHOLD + 2) return empty

  const nodeMap = new Map(nodes.map((n) => [n.node_id, n]))

  // Build child map: parent_id → child node_ids
  const childMap = new Map<string | null, string[]>()
  for (const n of nodes) {
    const children = childMap.get(n.parent_id) ?? []
    children.push(n.node_id)
    childMap.set(n.parent_id, children)
  }

  // Group boundary node IDs (first and last of each group)
  const groupBoundaryIds = new Set<string>()
  for (const g of digressionGroups) {
    if (g.node_ids.length > 0) {
      groupBoundaryIds.add(g.node_ids[0])
      groupBoundaryIds.add(g.node_ids[g.node_ids.length - 1])
    }
  }

  // A node is "boring" if it can be hidden in a collapsed segment
  function isBoring(nodeId: string): boolean {
    const node = nodeMap.get(nodeId)
    if (!node || node.parent_id == null) return false
    const children = childMap.get(nodeId) ?? []
    if (children.length !== 1) return false
    const parentChildren = childMap.get(node.parent_id) ?? []
    if (parentChildren.length !== 1) return false
    if (node.is_anchored || node.is_excluded || node.is_bookmarked) return false
    if (node.annotation_count > 0) return false
    if (groupBoundaryIds.has(nodeId)) return false
    return true
  }

  // Find all boring node IDs
  const boringIds = new Set<string>()
  for (const n of nodes) {
    if (isBoring(n.node_id)) boringIds.add(n.node_id)
  }
  if (boringIds.size < COLLAPSE_THRESHOLD) return empty

  // Group consecutive boring nodes into maximal runs
  const visited = new Set<string>()
  const runs: string[][] = []

  for (const n of nodes) {
    if (!boringIds.has(n.node_id) || visited.has(n.node_id)) continue

    // Walk backward to find start of this run
    let startId = n.node_id
    while (true) {
      const node = nodeMap.get(startId)!
      if (node.parent_id && boringIds.has(node.parent_id) && !visited.has(node.parent_id)) {
        startId = node.parent_id
      } else {
        break
      }
    }

    // Walk forward to collect the run
    const run: string[] = []
    let currentId: string | null = startId
    while (currentId && boringIds.has(currentId) && !visited.has(currentId)) {
      visited.add(currentId)
      run.push(currentId)
      const children: string[] = childMap.get(currentId) ?? []
      const nextId: string | null = children.length === 1 ? children[0] : null
      currentId = nextId && boringIds.has(nextId) ? nextId : null
    }

    if (run.length >= COLLAPSE_THRESHOLD) {
      runs.push(run)
    }
  }

  if (runs.length === 0) return empty

  // Build collapsed result
  const hiddenIds = new Set<string>()
  const collapsedMap = new Map<string, CollapsedSegment>()
  const syntheticNodes: NodeResponse[] = []
  const parentIdOverrides = new Map<string, string>()

  for (let i = 0; i < runs.length; i++) {
    const run = runs[i]
    const firstHidden = nodeMap.get(run[0])!
    const lastHidden = nodeMap.get(run[run.length - 1])!
    const syntheticId = `__collapsed_${i}`

    for (const id of run) hiddenIds.add(id)

    collapsedMap.set(syntheticId, {
      hiddenNodeIds: run,
      count: run.length,
    })

    // Synthetic node takes the place of the whole run
    syntheticNodes.push({
      node_id: syntheticId,
      parent_id: firstHidden.parent_id,
      role: 'collapsed',
    } as unknown as NodeResponse)

    // The child of the last hidden node should point to the synthetic node
    const lastChildren = childMap.get(lastHidden.node_id) ?? []
    if (lastChildren.length === 1) {
      parentIdOverrides.set(lastChildren[0], syntheticId)
    }
  }

  // Build display nodes: filter hidden, apply parent overrides, add synthetics
  const displayNodes: NodeResponse[] = []
  for (const n of nodes) {
    if (hiddenIds.has(n.node_id)) continue
    if (parentIdOverrides.has(n.node_id)) {
      displayNodes.push({ ...n, parent_id: parentIdOverrides.get(n.node_id)! })
    } else {
      displayNodes.push(n)
    }
  }
  displayNodes.push(...syntheticNodes)

  return { displayNodes, collapsedMap }
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
  const { currentTree, branchSelections, navigateToNode, comparisonHoveredNodeId, digressionGroups } = useTreeStore()
  const containerRef = useRef<HTMLDivElement>(null)
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null)
  const [tooltip, setTooltip] = useState<{
    node: NodeResponse
    x: number
    y: number
  } | null>(null)

  const { transform, wheelRef, handlers, fitToContent, isPanning } = useZoomPan()

  const nodes = currentTree?.nodes ?? []

  // Collapse long linear chains for a more compact graph
  const { displayNodes, collapsedMap } = useMemo(
    () => collapseLinearChains(nodes, digressionGroups),
    [nodes, digressionGroups],
  )

  // Compute layout from collapsed display nodes
  const layout = useMemo(() => computeTreeLayout(displayNodes), [displayNodes])

  // Build lookup maps
  const layoutMap = useMemo(() => {
    const m = new Map<string, LayoutNode>()
    for (const ln of layout.nodes) m.set(ln.nodeId, ln)
    return m
  }, [layout])

  // nodeMap uses real nodes (for tooltip, click handling)
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

  // Collapsed synthetic nodes that sit on the active path
  const collapsedActiveIds = useMemo(() => {
    const ids = new Set<string>()
    for (const [syntheticId, segment] of collapsedMap) {
      if (segment.hiddenNodeIds.some((id) => activeNodeIds.has(id))) {
        ids.add(syntheticId)
      }
    }
    return ids
  }, [collapsedMap, activeNodeIds])

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

  // Eviction protection zones: first N, last N, anchored, evicted
  const evictionZones = useMemo(() => {
    const es = currentTree?.metadata?.eviction_strategy as EvictionStrategy | undefined
    if (!es || es.mode !== 'smart') return null
    const path = getActivePath(nodes, branchSelections)
    const sendable = path.filter((n) =>
      n.role === 'user' || n.role === 'assistant' || n.role === 'tool',
    )
    const firstProtected = new Set(
      sendable.slice(0, es.keep_first_turns).map((n) => n.node_id),
    )
    const lastProtected = new Set(
      sendable.slice(-es.recent_turns_to_keep).map((n) => n.node_id),
    )
    // Anchored nodes on the active path
    const anchoredProtected = new Set(
      sendable.filter((n) => n.is_anchored).map((n) => n.node_id),
    )
    // Evicted node IDs from most recent assistant's context_usage
    const lastAssistant = [...path].reverse().find((n) => n.role === 'assistant')
    const evictedIds = new Set(lastAssistant?.context_usage?.evicted_node_ids ?? [])
    return { firstProtected, lastProtected, anchoredProtected, evictedIds }
  }, [currentTree, nodes, branchSelections])

  // Digression group hulls: bounding boxes for each group's nodes
  const groupHulls = useMemo(() => {
    if (digressionGroups.length === 0) return []
    const pad = NODE_RADIUS + 10
    return digressionGroups.map((group, idx) => {
      const positions = group.node_ids
        .map((id) => layoutMap.get(id))
        .filter((ln): ln is LayoutNode => ln != null)
      if (positions.length === 0) return null
      const minX = Math.min(...positions.map((p) => p.x)) - pad
      const maxX = Math.max(...positions.map((p) => p.x)) + pad
      const minY = Math.min(...positions.map((p) => p.y)) - pad
      const maxY = Math.max(...positions.map((p) => p.y)) + pad
      const color = GROUP_COLORS[idx % GROUP_COLORS.length]
      return {
        groupId: group.group_id,
        label: group.label,
        included: group.included,
        x: minX,
        y: minY,
        width: maxX - minX,
        height: maxY - minY,
        color,
      }
    }).filter(Boolean) as {
      groupId: string; label: string; included: boolean
      x: number; y: number; width: number; height: number
      color: { fill: string; stroke: string }
    }[]
  }, [digressionGroups, layoutMap])

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
      const childActive = activeNodeIds.has(ln.nodeId) || collapsedActiveIds.has(ln.nodeId)
      const parentActive = activeNodeIds.has(ln.parentId) || collapsedActiveIds.has(ln.parentId)
      const isActive = childActive && parentActive
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
          {/* Digression group hulls — bottommost layer */}
          {groupHulls.map((hull) => (
            <g key={`group-${hull.groupId}`}>
              <rect
                className={`graph-group-hull${hull.included ? '' : ' excluded'}`}
                x={hull.x}
                y={hull.y}
                width={hull.width}
                height={hull.height}
                rx={6}
                fill={hull.color.fill}
                stroke={hull.color.stroke}
              />
              <text
                className="graph-group-label"
                x={hull.x + 6}
                y={hull.y - 4}
              >
                {hull.label}
              </text>
            </g>
          ))}

          {/* Protection zone halos — behind everything */}
          {evictionZones && edges.map((edge) => {
            if (!edge.active) return null
            const allProtected = evictionZones.firstProtected.has(edge.parentId) ||
              evictionZones.firstProtected.has(edge.childId) ||
              evictionZones.lastProtected.has(edge.parentId) ||
              evictionZones.lastProtected.has(edge.childId)
            if (!allProtected) return null
            const parent = layoutMap.get(edge.parentId)
            const child = layoutMap.get(edge.childId)
            if (!parent || !child) return null
            return (
              <path
                key={`halo-${edge.parentId}-${edge.childId}`}
                className="graph-zone-halo"
                d={edgePath(parent.x, parent.y, child.x, child.y)}
              />
            )
          })}

          {/* Edges */}
          {edges.map((edge) => {
            const parent = layoutMap.get(edge.parentId)
            const child = layoutMap.get(edge.childId)
            if (!parent || !child) return null
            const isEvicted = evictionZones != null && (
              evictionZones.evictedIds.has(edge.parentId) || evictionZones.evictedIds.has(edge.childId)
            )
            const cls = `graph-edge${edge.active ? ' active' : ''}${edge.hovered ? ' hovered' : ''}${edge.comparison ? ' comparison' : ''}${isEvicted ? ' evicted' : ''}`
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
            const node = nodeMap.get(ln.nodeId)

            // Collapsed chain — render as vertical ellipsis capsule
            const collapsed = collapsedMap.get(ln.nodeId)
            if (collapsed) {
              const isOnActivePath = collapsedActiveIds.has(ln.nodeId)
              return (
                <g
                  key={ln.nodeId}
                  className={`graph-node-group graph-collapsed${isOnActivePath ? ' active' : ''}`}
                  onClick={() => {
                    const lastId = collapsed.hiddenNodeIds[collapsed.hiddenNodeIds.length - 1]
                    handleNodeClick(lastId)
                  }}
                  onMouseEnter={(e) => {
                    if (isPanning.current) return
                    setHoveredNodeId(ln.nodeId)
                    if (containerRef.current) {
                      const rect = containerRef.current.getBoundingClientRect()
                      setTooltip({
                        node: {
                          node_id: ln.nodeId,
                          role: 'collapsed',
                          content: `${collapsed.count} messages hidden (linear chain)`,
                        } as NodeResponse,
                        x: e.clientX - rect.left + 12,
                        y: e.clientY - rect.top + 12,
                      })
                    }
                  }}
                  onMouseMove={(e) => {
                    if (hoveredNodeId === ln.nodeId && containerRef.current) {
                      const rect = containerRef.current.getBoundingClientRect()
                      setTooltip((prev) =>
                        prev
                          ? { ...prev, x: e.clientX - rect.left + 12, y: e.clientY - rect.top + 12 }
                          : null,
                      )
                    }
                  }}
                  onMouseLeave={() => handleNodeHover(null)}
                >
                  <circle className="graph-node-hit" cx={ln.x} cy={ln.y} r={14} fill="transparent" stroke="none" />
                  <ellipse
                    className="graph-collapsed-capsule"
                    cx={ln.x}
                    cy={ln.y}
                    rx={5}
                    ry={10}
                  />
                  <circle className="graph-collapsed-dot" cx={ln.x} cy={ln.y - 4} r={1.2} />
                  <circle className="graph-collapsed-dot" cx={ln.x} cy={ln.y} r={1.2} />
                  <circle className="graph-collapsed-dot" cx={ln.x} cy={ln.y + 4} r={1.2} />
                  <text
                    className={`graph-node-label${isOnActivePath ? ' active' : ''}`}
                    x={ln.x}
                    y={ln.y + 22}
                  >
                    {collapsed.count}
                  </text>
                </g>
              )
            }

            const isActive = activeNodeIds.has(ln.nodeId)
            const isHovered = hoveredPathIds.has(ln.nodeId)
            const isComparison = comparisonPathIds.has(ln.nodeId)
            const r = isActive ? ACTIVE_RADIUS : NODE_RADIUS
            const roleClass = `role-${ln.role}`
            const nodeCls = `graph-node ${roleClass}${isActive ? ' active' : ''}${isHovered && !isActive ? ' hovered' : ''}${isComparison && !isActive && !isHovered ? ' comparison' : ''}`
            const labelCls = `graph-node-label${isActive ? ' active' : ''}`
            const isAnchored = node?.is_anchored ?? false
            const isExcluded = node?.is_excluded ?? false
            const isEvicted = evictionZones?.evictedIds.has(ln.nodeId) ?? false

            return (
              <g
                key={ln.nodeId}
                className={`graph-node-group${isEvicted ? ' evicted' : ''}`}
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
                {/* Exclusion mark — diagonal strikethrough */}
                {isExcluded && (
                  <line
                    className="graph-exclusion-mark"
                    x1={ln.x - r * 0.65}
                    y1={ln.y - r * 0.65}
                    x2={ln.x + r * 0.65}
                    y2={ln.y + r * 0.65}
                  />
                )}
                {/* Anchor pin — small anchor icon above-right */}
                {isAnchored && (
                  <g
                    className={`graph-anchor-pin${isActive ? ' active' : ''}`}
                    transform={`translate(${ln.x + r - 1}, ${ln.y - r - 7})`}
                  >
                    <circle cx={0} cy={0} r={1.8} fill="none" strokeWidth={0.9} />
                    <line x1={0} y1={1.8} x2={0} y2={6} strokeWidth={0.9} />
                    <line x1={-2.5} y1={4.2} x2={2.5} y2={4.2} strokeWidth={0.9} />
                  </g>
                )}
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
          {(tooltip.node.is_anchored || tooltip.node.is_excluded || tooltip.node.annotation_count > 0) && (
            <div className="graph-tooltip-pills">
              {tooltip.node.is_anchored && (
                <span className="graph-tooltip-pill anchored">Anchored</span>
              )}
              {tooltip.node.is_excluded && (
                <span className="graph-tooltip-pill excluded">Excluded</span>
              )}
              {tooltip.node.annotation_count > 0 && (
                <span className="graph-tooltip-pill annotations">
                  {tooltip.node.annotation_count} annotation{tooltip.node.annotation_count !== 1 ? 's' : ''}
                </span>
              )}
            </div>
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
