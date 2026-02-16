/** Zustand store for Qivis app state. */

import { create } from 'zustand'
import * as api from '../api/client.ts'
import type {
  GenerateRequest,
  NodeResponse,
  PatchTreeRequest,
  ProviderInfo,
  TreeDetail,
  TreeSummary,
} from '../api/types.ts'

interface GenerationError {
  parentNodeId: string
  provider: string
  model: string | null
  systemPrompt: string | null
  errorMessage: string
}

interface TreeStore {
  // State
  trees: TreeSummary[]
  selectedTreeId: string | null
  currentTree: TreeDetail | null
  providers: ProviderInfo[]
  isLoading: boolean
  isGenerating: boolean
  streamingContent: string
  regeneratingParentId: string | null
  systemPromptOverride: string | null
  error: string | null
  generationError: GenerationError | null
  branchSelections: Record<string, string>

  // Actions
  fetchTrees: () => Promise<void>
  fetchProviders: () => Promise<void>
  selectTree: (treeId: string) => Promise<void>
  createTree: (title: string, opts?: {
    systemPrompt?: string
    defaultProvider?: string
    defaultModel?: string
  }) => Promise<void>
  updateTree: (treeId: string, req: PatchTreeRequest) => Promise<void>
  sendMessage: (content: string) => Promise<void>
  setSystemPromptOverride: (prompt: string | null) => void
  clearError: () => void
  clearGenerationError: () => void
  selectBranch: (parentId: string, childId: string) => void
  forkAndGenerate: (
    parentId: string,
    content: string,
    overrides: GenerateRequest,
  ) => Promise<void>
  regenerate: (
    parentNodeId: string,
    overrides: GenerateRequest,
  ) => Promise<void>
}

/**
 * Walk the tree from root to leaf, using branchSelections to pick
 * which child to follow at each fork. Defaults to last child (most recent).
 * Returns the ordered path of nodes.
 */
export function getActivePath(
  nodes: NodeResponse[],
  branchSelections: Record<string, string>,
): NodeResponse[] {
  if (nodes.length === 0) return []

  const childMap = new Map<string | null, NodeResponse[]>()
  for (const node of nodes) {
    const children = childMap.get(node.parent_id) ?? []
    children.push(node)
    childMap.set(node.parent_id, children)
  }

  const path: NodeResponse[] = []
  let currentChildren = childMap.get(null) ?? []

  while (currentChildren.length > 0) {
    // Use parent_id ?? '' as key to handle root nodes (parent_id=null)
    const key = currentChildren[0].parent_id ?? ''
    const selectedId = branchSelections[key]

    let node: NodeResponse
    if (selectedId != null) {
      node =
        currentChildren.find((n) => n.node_id === selectedId) ??
        currentChildren[currentChildren.length - 1]
    } else {
      node = currentChildren[currentChildren.length - 1]
    }

    path.push(node)
    currentChildren = childMap.get(node.node_id) ?? []
  }

  return path
}

export const useTreeStore = create<TreeStore>((set, get) => ({
  trees: [],
  selectedTreeId: null,
  currentTree: null,
  providers: [],
  isLoading: false,
  isGenerating: false,
  streamingContent: '',
  regeneratingParentId: null,
  systemPromptOverride: null,
  error: null,
  generationError: null,
  branchSelections: {},

  fetchTrees: async () => {
    set({ isLoading: true, error: null })
    try {
      const trees = await api.listTrees()
      set({ trees, isLoading: false })
    } catch (e) {
      set({ error: String(e), isLoading: false })
    }
  },

  fetchProviders: async () => {
    // Only fetch once — skip if already populated
    if (get().providers.length > 0) return
    try {
      const providers = await api.getProviders()
      set({ providers })
    } catch (e) {
      set({ error: String(e) })
    }
  },

  selectTree: async (treeId: string) => {
    set({
      isLoading: true,
      error: null,
      selectedTreeId: treeId,
      systemPromptOverride: null,
      branchSelections: {},
    })
    try {
      const tree = await api.getTree(treeId)
      set({ currentTree: tree, isLoading: false })
    } catch (e) {
      set({ error: String(e), isLoading: false })
    }
  },

  createTree: async (title: string, opts?: {
    systemPrompt?: string
    defaultProvider?: string
    defaultModel?: string
  }) => {
    set({ isLoading: true, error: null })
    try {
      const tree = await api.createTree({
        title,
        default_system_prompt: opts?.systemPrompt,
        default_provider: opts?.defaultProvider,
        default_model: opts?.defaultModel,
      })
      const trees = await api.listTrees()
      set({
        trees,
        selectedTreeId: tree.tree_id,
        currentTree: tree,
        isLoading: false,
        systemPromptOverride: null,
        branchSelections: {},
      })
    } catch (e) {
      set({ error: String(e), isLoading: false })
    }
  },

  updateTree: async (treeId: string, req: PatchTreeRequest) => {
    set({ error: null })
    try {
      const updated = await api.updateTree(treeId, req)
      set((state) => ({
        currentTree: state.currentTree?.tree_id === treeId ? updated : state.currentTree,
        trees: state.trees.map((t) =>
          t.tree_id === treeId
            ? { ...t, title: updated.title, updated_at: updated.updated_at }
            : t,
        ),
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  sendMessage: async (content: string) => {
    const { currentTree, systemPromptOverride, branchSelections } = get()
    if (!currentTree) return

    const treeId = currentTree.tree_id
    set({ error: null, generationError: null })

    try {
      // Find the leaf node of the active path
      const activePath = getActivePath(currentTree.nodes, branchSelections)
      const leafNode = activePath.length > 0 ? activePath[activePath.length - 1] : null
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

      // Branch-local defaults: prefer last assistant's provider/model over tree defaults
      const lastAssistant = [...activePath].reverse().find((n) => n.role === 'assistant')
      const resolvedProvider = lastAssistant?.provider ?? currentTree.default_provider
      const resolvedModel = lastAssistant?.model ?? currentTree.default_model

      const generateReq = {
        ...(resolvedProvider ? { provider: resolvedProvider } : {}),
        ...(resolvedModel ? { model: resolvedModel } : {}),
        ...(systemPromptOverride != null ? { system_prompt: systemPromptOverride } : {}),
      }

      await api.generateStream(
        treeId,
        userNode.node_id,
        generateReq,
        (text) => {
          set((state) => ({ streamingContent: state.streamingContent + text }))
        },
        () => {
          set({ isGenerating: false, streamingContent: '' })
          api.getTree(treeId).then((tree) => {
            set({ currentTree: tree })
          })
          api.listTrees().then((trees) => {
            set({ trees })
          })
        },
        (error) => {
          set({
            isGenerating: false,
            streamingContent: '',
            error: String(error),
            generationError: {
              parentNodeId: userNode.node_id,
              provider: resolvedProvider ?? 'anthropic',
              model: resolvedModel ?? null,
              systemPrompt: systemPromptOverride ?? null,
              errorMessage: String(error),
            },
          })
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
  clearGenerationError: () => set({ generationError: null }),

  selectBranch: (parentId: string, childId: string) => {
    set((state) => ({
      branchSelections: { ...state.branchSelections, [parentId]: childId },
    }))
  },

  forkAndGenerate: async (parentId: string, content: string, overrides: GenerateRequest) => {
    const { currentTree } = get()
    if (!currentTree) return

    const treeId = currentTree.tree_id
    set({ error: null, generationError: null })

    try {
      // Create user node as new child of parentId (sibling of existing children)
      const userNode = await api.createNode(treeId, {
        content,
        role: 'user',
        parent_id: parentId || undefined,
      })

      // Update branchSelections to follow this new fork + add node optimistically
      set((state) => ({
        currentTree: state.currentTree
          ? { ...state.currentTree, nodes: [...state.currentTree.nodes, userNode] }
          : null,
        branchSelections: {
          ...state.branchSelections,
          [parentId]: userNode.node_id,
        },
      }))

      set({ isGenerating: true, streamingContent: '' })

      if (overrides.n && overrides.n > 1) {
        // n>1: use non-streaming, then refresh tree to see all siblings
        await api.generate(treeId, userNode.node_id, overrides)
        set({ isGenerating: false })
        const tree = await api.getTree(treeId)
        set({ currentTree: tree })
        const trees = await api.listTrees()
        set({ trees })
      } else {
        await api.generateStream(
          treeId,
          userNode.node_id,
          { ...overrides, stream: true },
          (text) => {
            set((state) => ({ streamingContent: state.streamingContent + text }))
          },
          () => {
            set({ isGenerating: false, streamingContent: '' })
            api.getTree(treeId).then((tree) => {
              set({ currentTree: tree })
            })
            api.listTrees().then((trees) => {
              set({ trees })
            })
          },
          (error) => {
            set({
              isGenerating: false,
              streamingContent: '',
              error: String(error),
              generationError: {
                parentNodeId: userNode.node_id,
                provider: overrides.provider ?? 'anthropic',
                model: overrides.model ?? null,
                systemPrompt: overrides.system_prompt ?? null,
                errorMessage: String(error),
              },
            })
          },
        )
      }
    } catch (e) {
      set({ isGenerating: false, streamingContent: '', error: String(e) })
    }
  },

  regenerate: async (parentNodeId: string, overrides: GenerateRequest) => {
    const { currentTree } = get()
    if (!currentTree) return

    const treeId = currentTree.tree_id
    set({
      error: null, generationError: null,
      isGenerating: true, streamingContent: '', regeneratingParentId: parentNodeId,
    })

    try {
      if (overrides.n && overrides.n > 1) {
        // n>1: use non-streaming, then refresh tree to see all siblings
        await api.generate(treeId, parentNodeId, overrides)
        set({ isGenerating: false, regeneratingParentId: null })
        const tree = await api.getTree(treeId)
        const newChildren = tree.nodes.filter((n) => n.parent_id === parentNodeId)
        const newest = newChildren[newChildren.length - 1]
        if (newest) {
          set((state) => ({
            currentTree: tree,
            branchSelections: {
              ...state.branchSelections,
              [parentNodeId]: newest.node_id,
            },
          }))
        } else {
          set({ currentTree: tree })
        }
        const trees = await api.listTrees()
        set({ trees })
      } else {
        await api.generateStream(
          treeId,
          parentNodeId,
          { ...overrides, stream: true },
          (text) => {
            set((state) => ({ streamingContent: state.streamingContent + text }))
          },
          () => {
            set({ isGenerating: false, streamingContent: '', regeneratingParentId: null })
            api.getTree(treeId).then((tree) => {
              // Select the new assistant sibling (last child of the parent)
              const newChildren = tree.nodes.filter((n) => n.parent_id === parentNodeId)
              const newest = newChildren[newChildren.length - 1]
              if (newest) {
                set((state) => ({
                  currentTree: tree,
                  branchSelections: {
                    ...state.branchSelections,
                    [parentNodeId]: newest.node_id,
                  },
                }))
              } else {
                set({ currentTree: tree })
              }
            })
            api.listTrees().then((trees) => {
              set({ trees })
            })
          },
          (error) => {
            set({
              isGenerating: false,
              streamingContent: '',
              regeneratingParentId: null,
              error: String(error),
              generationError: {
                parentNodeId,
                provider: overrides.provider ?? 'anthropic',
                model: overrides.model ?? null,
                systemPrompt: overrides.system_prompt ?? null,
                errorMessage: String(error),
              },
            })
          },
        )
      }
    } catch (e) {
      set({ isGenerating: false, streamingContent: '', regeneratingParentId: null, error: String(e) })
    }
  },
}))
