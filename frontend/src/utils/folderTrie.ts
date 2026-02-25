import type { RhizomeSummary } from '../api/types.ts'

export interface FolderNode {
  name: string
  path: string
  children: FolderNode[]
  rhizomeIds: string[]
}

export function buildFolderTrie(trees: RhizomeSummary[], extraFolders?: string[]): FolderNode[] {
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
        node = { name: segment, path: currentPath, children: [], rhizomeIds: [] }
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
      if (leaf && !leaf.rhizomeIds.includes(tree.rhizome_id)) {
        leaf.rhizomeIds.push(tree.rhizome_id)
      }
    }
  }

  return root
}

export function countRhizomesInFolder(node: FolderNode, rhizomeMap: Map<string, RhizomeSummary>): number {
  let count = node.rhizomeIds.filter(id => rhizomeMap.has(id)).length
  for (const child of node.children) {
    count += countRhizomesInFolder(child, rhizomeMap)
  }
  return count
}

/** Collect all rhizome IDs in a folder and its descendants. */
export function collectRhizomeIds(node: FolderNode): string[] {
  const ids = [...node.rhizomeIds]
  for (const child of node.children) {
    ids.push(...collectRhizomeIds(child))
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
