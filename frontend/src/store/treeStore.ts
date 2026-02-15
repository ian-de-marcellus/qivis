/** Zustand store for Qivis app state. */

import { create } from 'zustand'
import * as api from '../api/client.ts'
import type { NodeResponse, TreeDetail, TreeSummary } from '../api/types.ts'

interface TreeStore {
  // State
  trees: TreeSummary[]
  selectedTreeId: string | null
  currentTree: TreeDetail | null
  isLoading: boolean
  isGenerating: boolean
  streamingContent: string
  systemPromptOverride: string | null
  error: string | null

  // Actions
  fetchTrees: () => Promise<void>
  selectTree: (treeId: string) => Promise<void>
  createTree: (title: string, systemPrompt?: string) => Promise<void>
  sendMessage: (content: string) => Promise<void>
  setSystemPromptOverride: (prompt: string | null) => void
  clearError: () => void
}

/**
 * Get the leaf node of the current linear path.
 * Walks from root following the last child at each level.
 */
function getLeafNode(nodes: NodeResponse[]): NodeResponse | null {
  if (nodes.length === 0) return null

  const childMap = new Map<string | null, NodeResponse[]>()
  for (const node of nodes) {
    const parentId = node.parent_id
    const children = childMap.get(parentId) ?? []
    children.push(node)
    childMap.set(parentId, children)
  }

  // Start from root (parent_id = null), follow last child
  let current: NodeResponse | null = null
  let nextChildren = childMap.get(null) ?? []

  while (nextChildren.length > 0) {
    // Pick the last child (most recently created)
    current = nextChildren[nextChildren.length - 1]
    nextChildren = childMap.get(current.node_id) ?? []
  }

  return current
}

export const useTreeStore = create<TreeStore>((set, get) => ({
  trees: [],
  selectedTreeId: null,
  currentTree: null,
  isLoading: false,
  isGenerating: false,
  streamingContent: '',
  systemPromptOverride: null,
  error: null,

  fetchTrees: async () => {
    set({ isLoading: true, error: null })
    try {
      const trees = await api.listTrees()
      set({ trees, isLoading: false })
    } catch (e) {
      set({ error: String(e), isLoading: false })
    }
  },

  selectTree: async (treeId: string) => {
    set({ isLoading: true, error: null, selectedTreeId: treeId, systemPromptOverride: null })
    try {
      const tree = await api.getTree(treeId)
      set({ currentTree: tree, isLoading: false })
    } catch (e) {
      set({ error: String(e), isLoading: false })
    }
  },

  createTree: async (title: string, systemPrompt?: string) => {
    set({ isLoading: true, error: null })
    try {
      const tree = await api.createTree({
        title,
        default_system_prompt: systemPrompt,
      })
      // Refresh list and select the new tree
      const trees = await api.listTrees()
      set({
        trees,
        selectedTreeId: tree.tree_id,
        currentTree: tree,
        isLoading: false,
        systemPromptOverride: null,
      })
    } catch (e) {
      set({ error: String(e), isLoading: false })
    }
  },

  sendMessage: async (content: string) => {
    const { currentTree, systemPromptOverride } = get()
    if (!currentTree) return

    const treeId = currentTree.tree_id
    set({ error: null })

    try {
      // Find the leaf node to use as parent
      const leafNode = getLeafNode(currentTree.nodes)
      const parentId = leafNode?.node_id

      // Create user node
      const userNode = await api.createNode(treeId, {
        content,
        role: 'user',
        parent_id: parentId,
      })

      // Optimistically add user node to current tree
      set((state) => ({
        currentTree: state.currentTree
          ? { ...state.currentTree, nodes: [...state.currentTree.nodes, userNode] }
          : null,
      }))

      // Start streaming generation
      set({ isGenerating: true, streamingContent: '' })

      const generateReq = {
        provider: 'anthropic',
        ...(systemPromptOverride != null ? { system_prompt: systemPromptOverride } : {}),
      }

      await api.generateStream(
        treeId,
        userNode.node_id,
        generateReq,
        // onDelta
        (text) => {
          set((state) => ({ streamingContent: state.streamingContent + text }))
        },
        // onComplete
        () => {
          // Refresh the tree to get the final node from the server
          set({ isGenerating: false, streamingContent: '' })
          api.getTree(treeId).then((tree) => {
            set({ currentTree: tree })
          })
          // Also refresh the tree list (updated_at changed)
          api.listTrees().then((trees) => {
            set({ trees })
          })
        },
        // onError
        (error) => {
          set({ isGenerating: false, streamingContent: '', error: String(error) })
        },
      )
    } catch (e) {
      set({ isGenerating: false, streamingContent: '', error: String(e) })
    }
  },

  setSystemPromptOverride: (prompt: string | null) => {
    set({ systemPromptOverride: prompt })
  },

  clearError: () => set({ error: null }),
}))
