/**
 * Pure tree layout algorithm for positioning conversation nodes.
 * Simplified Reingold-Tilford: bottom-up subtree widths, top-down x assignment.
 */

import type { NodeResponse } from '../../api/types.ts'

export interface LayoutNode {
  nodeId: string
  parentId: string | null
  role: string
  x: number
  y: number
  depth: number
  childCount: number
}

export interface LayoutResult {
  nodes: LayoutNode[]
  width: number
  height: number
}

interface InternalNode {
  id: string
  parentId: string | null
  role: string
  children: InternalNode[]
  subtreeWidth: number
  depth: number
  x: number
  y: number
}

const DEFAULT_SPACING_X = 50
const DEFAULT_SPACING_Y = 70

export function computeTreeLayout(
  nodes: NodeResponse[],
  options?: { nodeSpacingX?: number; nodeSpacingY?: number },
): LayoutResult {
  if (nodes.length === 0) return { nodes: [], width: 0, height: 0 }

  const spacingX = options?.nodeSpacingX ?? DEFAULT_SPACING_X
  const spacingY = options?.nodeSpacingY ?? DEFAULT_SPACING_Y

  // Build parent -> children map
  const childMap = new Map<string | null, NodeResponse[]>()
  for (const node of nodes) {
    const children = childMap.get(node.parent_id) ?? []
    children.push(node)
    childMap.set(node.parent_id, children)
  }

  // Build internal tree recursively
  function buildTree(nodeResp: NodeResponse, depth: number): InternalNode {
    const childResps = childMap.get(nodeResp.node_id) ?? []
    const children = childResps.map((c) => buildTree(c, depth + 1))
    return {
      id: nodeResp.node_id,
      parentId: nodeResp.parent_id,
      role: nodeResp.role,
      children,
      subtreeWidth: 0,
      depth,
      x: 0,
      y: depth * spacingY,
    }
  }

  // Handle roots (parent_id === null)
  const roots = (childMap.get(null) ?? []).map((r) => buildTree(r, 0))
  if (roots.length === 0) return { nodes: [], width: 0, height: 0 }

  // Bottom-up: compute subtree widths
  function computeWidths(node: InternalNode): number {
    if (node.children.length === 0) {
      node.subtreeWidth = 1
      return 1
    }
    const childWidths = node.children.map(computeWidths)
    node.subtreeWidth = childWidths.reduce((a, b) => a + b, 0) + (node.children.length - 1) * 0.5
    return node.subtreeWidth
  }

  // Top-down: assign x positions
  function assignPositions(node: InternalNode, leftX: number): void {
    // Center this node over its subtree
    node.x = leftX + (node.subtreeWidth * spacingX) / 2

    // Position children
    let childLeft = leftX
    for (const child of node.children) {
      assignPositions(child, childLeft)
      childLeft += child.subtreeWidth * spacingX + spacingX * 0.5
    }
  }

  // Layout each root tree side by side
  let currentLeft = 0
  for (const root of roots) {
    computeWidths(root)
    assignPositions(root, currentLeft)
    currentLeft += root.subtreeWidth * spacingX + spacingX
  }

  // Flatten to output
  const result: LayoutNode[] = []
  let maxX = 0
  let maxY = 0

  function flatten(node: InternalNode): void {
    result.push({
      nodeId: node.id,
      parentId: node.parentId,
      role: node.role,
      x: node.x,
      y: node.y,
      depth: node.depth,
      childCount: node.children.length,
    })
    if (node.x > maxX) maxX = node.x
    if (node.y > maxY) maxY = node.y
    for (const child of node.children) flatten(child)
  }

  for (const root of roots) flatten(root)

  return {
    nodes: result,
    width: maxX + spacingX,
    height: maxY + spacingY,
  }
}
