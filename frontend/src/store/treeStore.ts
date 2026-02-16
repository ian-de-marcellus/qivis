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
  streamingThinkingContent: string
  streamingContents: Record<number, string>
  streamingThinkingContents: Record<number, string>
  streamingNodeIds: Record<number, string>
  streamingTotal: number
  activeStreamIndex: number
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
    metadata?: Record<string, unknown>
  }) => Promise<void>
  updateTree: (treeId: string, req: PatchTreeRequest) => Promise<void>
  sendMessage: (content: string) => Promise<void>
  setSystemPromptOverride: (prompt: string | null) => void
  clearError: () => void
  clearGenerationError: () => void
  setActiveStreamIndex: (index: number) => void
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
  streamingThinkingContent: '',
  streamingContents: {},
  streamingThinkingContents: {},
  streamingNodeIds: {},
  streamingTotal: 0,
  activeStreamIndex: 0,
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
    metadata?: Record<string, unknown>
  }) => {
    set({ isLoading: true, error: null })
    try {
      let tree = await api.createTree({
        title,
        default_system_prompt: opts?.systemPrompt,
        default_provider: opts?.defaultProvider,
        default_model: opts?.defaultModel,
      })
      if (opts?.metadata) {
        tree = await api.updateTree(tree.tree_id, { metadata: opts.metadata })
      }
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

      set({ isGenerating: true, streamingContent: '', streamingThinkingContent: '' })

      // Branch-local defaults: prefer last assistant's provider/model over tree defaults
      const lastAssistant = [...activePath].reverse().find((n) => n.role === 'assistant')
      const resolvedProvider = lastAssistant?.provider ?? currentTree.default_provider
      const resolvedModel = lastAssistant?.model ?? currentTree.default_model

      // Backend handles merge resolution: tree defaults > base
      // Only pass explicit overrides here (provider, model, system_prompt)
      const generateReq: GenerateRequest = {
        ...(resolvedProvider ? { provider: resolvedProvider } : {}),
        ...(resolvedModel ? { model: resolvedModel } : {}),
        ...(systemPromptOverride != null ? { system_prompt: systemPromptOverride } : {}),
      }

      const shouldStream = currentTree.metadata?.stream_responses !== false

      if (shouldStream) {
        await api.generateStream(
          treeId,
          userNode.node_id,
          generateReq,
          (text) => {
            set((state) => ({ streamingContent: state.streamingContent + text }))
          },
          () => {
            set({ isGenerating: false, streamingContent: '', streamingThinkingContent: '' })
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
              streamingThinkingContent: '',
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
          (thinking) => {
            set((state) => ({
              streamingThinkingContent: state.streamingThinkingContent + thinking,
            }))
          },
        )
      } else {
        try {
          await api.generate(treeId, userNode.node_id, generateReq)
          set({ isGenerating: false, streamingContent: '', streamingThinkingContent: '' })
          const tree = await api.getTree(treeId)
          set({ currentTree: tree })
          const trees = await api.listTrees()
          set({ trees })
        } catch (error) {
          set({
            isGenerating: false,
            streamingContent: '',
            streamingThinkingContent: '',
            error: String(error),
            generationError: {
              parentNodeId: userNode.node_id,
              provider: resolvedProvider ?? 'anthropic',
              model: resolvedModel ?? null,
              systemPrompt: systemPromptOverride ?? null,
              errorMessage: String(error),
            },
          })
        }
      }
    } catch (e) {
      set({ isGenerating: false, streamingContent: '', streamingThinkingContent: '', error: String(e) })
    }
  },

  setSystemPromptOverride: (prompt: string | null) => {
    set({ systemPromptOverride: prompt })
  },

  clearError: () => set({ error: null }),
  clearGenerationError: () => set({ generationError: null }),
  setActiveStreamIndex: (index: number) => set({ activeStreamIndex: index }),

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

      const n = overrides.n ?? 1
      const shouldStream = overrides.stream !== false

      if (shouldStream && n > 1) {
        set({
          isGenerating: true,
          streamingContent: '',
          streamingThinkingContent: '',
          streamingContents: {},
          streamingThinkingContents: {},
          streamingNodeIds: {},
          streamingTotal: n,
          activeStreamIndex: 0,
        })
        await api.generateMultiStream(
          treeId,
          userNode.node_id,
          overrides,
          (text, idx) => {
            set((state) => ({
              streamingContents: {
                ...state.streamingContents,
                [idx]: (state.streamingContents[idx] ?? '') + text,
              },
            }))
          },
          (event) => {
            if (event.node_id != null && event.completion_index != null) {
              set((state) => ({
                streamingNodeIds: {
                  ...state.streamingNodeIds,
                  [event.completion_index!]: event.node_id!,
                },
              }))
            }
          },
          () => {
            set({
              isGenerating: false,
              streamingContent: '',
              streamingThinkingContent: '',
              streamingContents: {},
              streamingThinkingContents: {},
              streamingNodeIds: {},
              streamingTotal: 0,
              activeStreamIndex: 0,
            })
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
              streamingThinkingContent: '',
              streamingContents: {},
              streamingThinkingContents: {},
              streamingNodeIds: {},
              streamingTotal: 0,
              activeStreamIndex: 0,
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
          (thinking, idx) => {
            set((state) => ({
              streamingThinkingContents: {
                ...state.streamingThinkingContents,
                [idx]: (state.streamingThinkingContents[idx] ?? '') + thinking,
              },
            }))
          },
        )
      } else if (shouldStream) {
        set({ isGenerating: true, streamingContent: '', streamingThinkingContent: '' })
        await api.generateStream(
          treeId,
          userNode.node_id,
          { ...overrides, stream: true },
          (text) => {
            set((state) => ({ streamingContent: state.streamingContent + text }))
          },
          () => {
            set({ isGenerating: false, streamingContent: '', streamingThinkingContent: '' })
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
              streamingThinkingContent: '',
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
          (thinking) => {
            set((state) => ({
              streamingThinkingContent: state.streamingThinkingContent + thinking,
            }))
          },
        )
      } else {
        set({ isGenerating: true, streamingContent: '', streamingThinkingContent: '' })
        try {
          await api.generate(treeId, userNode.node_id, { ...overrides, n })
          set({ isGenerating: false, streamingContent: '', streamingThinkingContent: '' })
          const tree = await api.getTree(treeId)
          set({ currentTree: tree })
          const trees = await api.listTrees()
          set({ trees })
        } catch (error) {
          set({
            isGenerating: false,
            streamingContent: '',
            streamingThinkingContent: '',
            error: String(error),
            generationError: {
              parentNodeId: userNode.node_id,
              provider: overrides.provider ?? 'anthropic',
              model: overrides.model ?? null,
              systemPrompt: overrides.system_prompt ?? null,
              errorMessage: String(error),
            },
          })
        }
      }
    } catch (e) {
      set({ isGenerating: false, streamingContent: '', streamingThinkingContent: '', error: String(e) })
    }
  },

  regenerate: async (parentNodeId: string, overrides: GenerateRequest) => {
    const { currentTree } = get()
    if (!currentTree) return

    const treeId = currentTree.tree_id
    set({
      error: null, generationError: null,
      isGenerating: true, streamingContent: '', streamingThinkingContent: '',
      regeneratingParentId: parentNodeId,
    })

    const n = overrides.n ?? 1
    const shouldStream = overrides.stream !== false

    try {
      if (shouldStream && n > 1) {
        set({
          streamingContents: {},
          streamingThinkingContents: {},
          streamingNodeIds: {},
          streamingTotal: n,
          activeStreamIndex: 0,
        })
        await api.generateMultiStream(
          treeId,
          parentNodeId,
          overrides,
          (text, idx) => {
            set((state) => ({
              streamingContents: {
                ...state.streamingContents,
                [idx]: (state.streamingContents[idx] ?? '') + text,
              },
            }))
          },
          (event) => {
            if (event.node_id != null && event.completion_index != null) {
              set((state) => ({
                streamingNodeIds: {
                  ...state.streamingNodeIds,
                  [event.completion_index!]: event.node_id!,
                },
              }))
            }
          },
          () => {
            set({
              isGenerating: false,
              streamingContent: '',
              streamingThinkingContent: '',
              streamingContents: {},
              streamingThinkingContents: {},
              streamingNodeIds: {},
              streamingTotal: 0,
              activeStreamIndex: 0,
              regeneratingParentId: null,
            })
            api.getTree(treeId).then((tree) => {
              const newChildren = tree.nodes.filter((nd) => nd.parent_id === parentNodeId)
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
              streamingThinkingContent: '',
              streamingContents: {},
              streamingThinkingContents: {},
              streamingNodeIds: {},
              streamingTotal: 0,
              activeStreamIndex: 0,
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
          (thinking, idx) => {
            set((state) => ({
              streamingThinkingContents: {
                ...state.streamingThinkingContents,
                [idx]: (state.streamingThinkingContents[idx] ?? '') + thinking,
              },
            }))
          },
        )
      } else if (shouldStream) {
        await api.generateStream(
          treeId,
          parentNodeId,
          { ...overrides, stream: true },
          (text) => {
            set((state) => ({ streamingContent: state.streamingContent + text }))
          },
          () => {
            set({
              isGenerating: false, streamingContent: '', streamingThinkingContent: '',
              regeneratingParentId: null,
            })
            api.getTree(treeId).then((tree) => {
              const newChildren = tree.nodes.filter((nd) => nd.parent_id === parentNodeId)
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
              streamingThinkingContent: '',
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
          (thinking) => {
            set((state) => ({
              streamingThinkingContent: state.streamingThinkingContent + thinking,
            }))
          },
        )
      } else {
        try {
          await api.generate(treeId, parentNodeId, { ...overrides, n })
          set({
            isGenerating: false, streamingContent: '', streamingThinkingContent: '',
            regeneratingParentId: null,
          })
          const tree = await api.getTree(treeId)
          const newChildren = tree.nodes.filter((nd) => nd.parent_id === parentNodeId)
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
        } catch (error) {
          set({
            isGenerating: false,
            streamingContent: '',
            streamingThinkingContent: '',
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
        }
      }
    } catch (e) {
      set({
        isGenerating: false, streamingContent: '', streamingThinkingContent: '',
        regeneratingParentId: null, error: String(e),
      })
    }
  },
}))
