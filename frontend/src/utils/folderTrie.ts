import type { TreeSummary } from '../api/types.ts'

export interface FolderNode {
  name: string
  path: string
  children: FolderNode[]
  treeIds: string[]
}

export function buildFolderTrie(trees: TreeSummary[], extraFolders?: string[]): FolderNode[] {
  const root: FolderNode[] = []
  const nodeMap = new Map<string, FolderNode>()

  const allPaths = new Set<string>()

  for (const tree of trees) {
    for (const folder of tree.folders) {
      allPaths.add(folder)
    }
  }

  if (extraFolders) {
    for (const folder of extraFolders) {
      allPaths.add(folder)
    }
  }

  // Build trie from all unique folder paths
  for (const folder of allPaths) {
    const segments = folder.split('/')
    let currentPath = ''
    let currentChildren = root

    for (const segment of segments) {
      currentPath = currentPath ? `${currentPath}/${segment}` : segment
      let node = nodeMap.get(currentPath)
      if (!node) {
        node = { name: segment, path: currentPath, children: [], treeIds: [] }
        nodeMap.set(currentPath, node)
        currentChildren.push(node)
      }
      currentChildren = node.children
    }
  }

  // Assign trees to their deepest matching folder nodes
  for (const tree of trees) {
    for (const folder of tree.folders) {
      const leaf = nodeMap.get(folder)
      if (leaf && !leaf.treeIds.includes(tree.tree_id)) {
        leaf.treeIds.push(tree.tree_id)
      }
    }
  }

  return root
}

export function countTreesInFolder(node: FolderNode, treeMap: Map<string, TreeSummary>): number {
  let count = node.treeIds.filter(id => treeMap.has(id)).length
  for (const child of node.children) {
    count += countTreesInFolder(child, treeMap)
  }
  return count
}

/** Collect all tree IDs in a folder and its descendants. */
export function collectTreeIds(node: FolderNode): string[] {
  const ids = [...node.treeIds]
  for (const child of node.children) {
    ids.push(...collectTreeIds(child))
  }
  return ids
}

/** Find a FolderNode by path in the trie. */
export function findFolderNode(nodes: FolderNode[], path: string): FolderNode | null {
  for (const node of nodes) {
    if (node.path === path) return node
    const found = findFolderNode(node.children, path)
    if (found) return found
  }
  return null
}
