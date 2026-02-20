/** Zustand store for Qivis app state. */

import { create } from 'zustand'
import * as api from '../api/client.ts'
import type {
  AnnotationResponse,
  BookmarkResponse,
  CreateDigressionGroupRequest,
  DigressionGroupResponse,
  EditHistoryEntry,
  GenerateRequest,
  NodeExclusionResponse,
  NodeResponse,
  PatchTreeRequest,
  ProviderInfo,
  TaxonomyResponse,
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
  comparisonHoveredNodeId: string | null
  selectedEditVersion: { nodeId: string; entry: EditHistoryEntry | null } | null
  editHistoryCache: Record<string, EditHistoryEntry[]>
  inspectedNodeId: string | null
  splitViewNodeId: string | null
  canvasOpen: boolean
  nodeAnnotations: Record<string, AnnotationResponse[]>
  taxonomy: TaxonomyResponse | null
  bookmarks: BookmarkResponse[]
  bookmarksLoading: boolean
  exclusions: NodeExclusionResponse[]
  digressionGroups: DigressionGroupResponse[]
  digressionPanelOpen: boolean
  groupSelectionMode: boolean
  selectedGroupNodeIds: string[]
  comparisonNodeId: string | null
  comparisonPickingMode: boolean
  comparisonPickingSourceId: string | null

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
  sendMessageOnly: (content: string) => Promise<void>
  setSystemPromptOverride: (prompt: string | null) => void
  clearError: () => void
  clearGenerationError: () => void
  setActiveStreamIndex: (index: number) => void
  selectBranch: (parentId: string, childId: string) => void
  navigateToNode: (nodeId: string) => void
  setComparisonHoveredNodeId: (nodeId: string | null) => void
  editNodeContent: (nodeId: string, editedContent: string | null) => Promise<void>
  setSelectedEditVersion: (nodeId: string, entry: EditHistoryEntry | null) => void
  cacheEditHistory: (nodeId: string, entries: EditHistoryEntry[]) => void
  setInspectedNodeId: (nodeId: string | null) => void
  setSplitViewNodeId: (nodeId: string | null) => void
  setCanvasOpen: (open: boolean) => void
  forkAndGenerate: (
    parentId: string,
    content: string,
    overrides: GenerateRequest,
  ) => Promise<void>
  regenerate: (
    parentNodeId: string,
    overrides: GenerateRequest,
  ) => Promise<void>
  prefillAssistant: (parentId: string, content: string) => Promise<void>
  addAnnotation: (nodeId: string, tag: string, value?: unknown, notes?: string) => Promise<void>
  removeAnnotation: (nodeId: string, annotationId: string) => Promise<void>
  fetchNodeAnnotations: (nodeId: string) => Promise<void>
  fetchTaxonomy: () => Promise<void>
  fetchBookmarks: () => Promise<void>
  addBookmark: (nodeId: string, label: string, notes?: string) => Promise<void>
  removeBookmark: (bookmarkId: string) => Promise<void>
  summarizeBookmark: (bookmarkId: string) => Promise<void>
  navigateToBookmark: (bookmark: BookmarkResponse) => void
  fetchExclusions: () => Promise<void>
  excludeNode: (nodeId: string, scopeNodeId: string, reason?: string) => Promise<void>
  includeNode: (nodeId: string, scopeNodeId: string) => Promise<void>
  fetchDigressionGroups: () => Promise<void>
  createDigressionGroup: (req: CreateDigressionGroupRequest) => Promise<boolean>
  toggleDigressionGroup: (groupId: string, included: boolean) => Promise<void>
  deleteDigressionGroup: (groupId: string) => Promise<void>
  setDigressionPanelOpen: (open: boolean) => void
  setGroupSelectionMode: (active: boolean) => void
  toggleGroupNodeSelection: (nodeId: string) => void
  toggleAnchor: (nodeId: string) => Promise<void>
  anchorGroup: (groupId: string) => Promise<void>
  setComparisonNodeId: (nodeId: string | null) => void
  enterComparisonPicking: () => void
  pickComparisonTarget: (nodeId: string) => void
  cancelComparisonPicking: () => void
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
  comparisonHoveredNodeId: null,
  selectedEditVersion: null,
  editHistoryCache: {},
  inspectedNodeId: null,
  splitViewNodeId: null,
  canvasOpen: false,
  nodeAnnotations: {},
  taxonomy: null,
  bookmarks: [],
  bookmarksLoading: false,
  exclusions: [],
  digressionGroups: [],
  digressionPanelOpen: false,
  groupSelectionMode: false,
  selectedGroupNodeIds: [],
  comparisonNodeId: null,
  comparisonPickingMode: false,
  comparisonPickingSourceId: null,

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
      inspectedNodeId: null,
      splitViewNodeId: null,
      canvasOpen: false,
      nodeAnnotations: {},
      taxonomy: null,
      bookmarks: [],
      bookmarksLoading: false,
      exclusions: [],
      digressionGroups: [],
      digressionPanelOpen: false,
      groupSelectionMode: false,
      selectedGroupNodeIds: [],
      comparisonNodeId: null,
      comparisonPickingMode: false,
      comparisonPickingSourceId: null,
    })
    try {
      const tree = await api.getTree(treeId)
      set({ currentTree: tree, isLoading: false })
      // Fetch bookmarks and exclusions for the new tree in the background
      api.getTreeBookmarks(treeId).then((bookmarks) => {
        set({ bookmarks })
      }).catch(() => {/* ignore bookmark fetch errors */})
      api.getExclusions(treeId).then((exclusions) => {
        set({ exclusions })
      }).catch(() => {/* ignore exclusion fetch errors */})
      api.getDigressionGroups(treeId).then((digressionGroups) => {
        set({ digressionGroups })
      }).catch(() => {/* ignore group fetch errors */})
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

  sendMessageOnly: async (content: string) => {
    const { currentTree, branchSelections } = get()
    if (!currentTree) return

    const treeId = currentTree.tree_id
    set({ error: null })

    try {
      const activePath = getActivePath(currentTree.nodes, branchSelections)
      const leafNode = activePath.length > 0 ? activePath[activePath.length - 1] : null
      const parentId = leafNode?.node_id

      const userNode = await api.createNode(treeId, {
        content,
        role: 'user',
        parent_id: parentId,
      })

      set((state) => ({
        currentTree: state.currentTree
          ? { ...state.currentTree, nodes: [...state.currentTree.nodes, userNode] }
          : null,
      }))
    } catch (e) {
      set({ error: String(e) })
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

  navigateToNode: (nodeId: string) => {
    const { currentTree } = get()
    if (!currentTree) return
    const nodeMap = new Map(currentTree.nodes.map((n) => [n.node_id, n]))
    const selections: Record<string, string> = {}
    let current = nodeMap.get(nodeId)
    while (current) {
      const parentKey = current.parent_id ?? ''
      selections[parentKey] = current.node_id
      current = current.parent_id ? nodeMap.get(current.parent_id) : undefined
    }
    set({ branchSelections: selections })
  },

  setComparisonHoveredNodeId: (nodeId: string | null) => {
    set({ comparisonHoveredNodeId: nodeId })
  },

  editNodeContent: async (nodeId: string, editedContent: string | null) => {
    const { currentTree } = get()
    if (!currentTree) return

    try {
      const updated = await api.editNodeContent(currentTree.tree_id, nodeId, editedContent)
      // Update node in tree, then re-fetch edit history so the section stays visible
      // even after restoring to original (edited_content=null but history exists)
      set((state) => ({
        currentTree: state.currentTree
          ? {
              ...state.currentTree,
              nodes: state.currentTree.nodes.map((n) =>
                n.node_id === nodeId ? { ...n, edited_content: updated.edited_content } : n,
              ),
            }
          : null,
      }))
      // Re-fetch edit history in background to keep cache populated
      api.getEditHistory(currentTree.tree_id, nodeId).then((history) => {
        set((state) => ({
          editHistoryCache: { ...state.editHistoryCache, [nodeId]: history.entries },
        }))
      }).catch(() => {/* ignore */})
    } catch (e) {
      set({ error: String(e) })
    }
  },

  setSelectedEditVersion: (nodeId: string, entry: EditHistoryEntry | null) => {
    const current = get().selectedEditVersion
    if (entry === null && current?.nodeId === nodeId) {
      // Deselect
      set({ selectedEditVersion: null })
    } else {
      set({ selectedEditVersion: { nodeId, entry } })
    }
  },

  cacheEditHistory: (nodeId: string, entries: EditHistoryEntry[]) => {
    set((state) => ({
      editHistoryCache: { ...state.editHistoryCache, [nodeId]: entries },
    }))
  },

  setInspectedNodeId: (nodeId: string | null) => {
    set({ inspectedNodeId: nodeId })
  },

  setSplitViewNodeId: (nodeId: string | null) => {
    set({ splitViewNodeId: nodeId })
  },

  setCanvasOpen: (open: boolean) => {
    set({ canvasOpen: open })
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

  prefillAssistant: async (parentId: string, content: string) => {
    const { currentTree } = get()
    if (!currentTree) return

    const treeId = currentTree.tree_id
    set({ error: null })

    try {
      const node = await api.createNode(treeId, {
        content,
        role: 'assistant',
        parent_id: parentId || undefined,
        mode: 'manual',
      })

      set((state) => ({
        currentTree: state.currentTree
          ? { ...state.currentTree, nodes: [...state.currentTree.nodes, node] }
          : null,
        branchSelections: {
          ...state.branchSelections,
          [parentId]: node.node_id,
        },
      }))
    } catch (err: unknown) {
      set({ error: err instanceof Error ? err.message : String(err) })
    }
  },

  addAnnotation: async (nodeId: string, tag: string, value?: unknown, notes?: string) => {
    const { currentTree } = get()
    if (!currentTree) return

    try {
      const annotation = await api.addAnnotation(currentTree.tree_id, nodeId, {
        tag,
        value,
        notes,
      })
      set((state) => ({
        nodeAnnotations: {
          ...state.nodeAnnotations,
          [nodeId]: [...(state.nodeAnnotations[nodeId] ?? []), annotation],
        },
        // Increment annotation_count on the node
        currentTree: state.currentTree
          ? {
              ...state.currentTree,
              nodes: state.currentTree.nodes.map((n) =>
                n.node_id === nodeId
                  ? { ...n, annotation_count: n.annotation_count + 1 }
                  : n,
              ),
            }
          : null,
        // Add tag to taxonomy used_tags if not already there
        taxonomy: state.taxonomy
          ? {
              ...state.taxonomy,
              used_tags: state.taxonomy.used_tags.includes(tag)
                ? state.taxonomy.used_tags
                : [...state.taxonomy.used_tags, tag],
            }
          : null,
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  removeAnnotation: async (nodeId: string, annotationId: string) => {
    const { currentTree } = get()
    if (!currentTree) return

    try {
      await api.removeAnnotation(currentTree.tree_id, annotationId)
      set((state) => ({
        nodeAnnotations: {
          ...state.nodeAnnotations,
          [nodeId]: (state.nodeAnnotations[nodeId] ?? []).filter(
            (a) => a.annotation_id !== annotationId,
          ),
        },
        // Decrement annotation_count on the node
        currentTree: state.currentTree
          ? {
              ...state.currentTree,
              nodes: state.currentTree.nodes.map((n) =>
                n.node_id === nodeId
                  ? { ...n, annotation_count: Math.max(0, n.annotation_count - 1) }
                  : n,
              ),
            }
          : null,
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  fetchNodeAnnotations: async (nodeId: string) => {
    const { currentTree } = get()
    if (!currentTree) return

    try {
      const annotations = await api.getNodeAnnotations(currentTree.tree_id, nodeId)
      set((state) => ({
        nodeAnnotations: { ...state.nodeAnnotations, [nodeId]: annotations },
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  fetchTaxonomy: async () => {
    const { currentTree } = get()
    if (!currentTree) return

    try {
      const taxonomy = await api.getTreeTaxonomy(currentTree.tree_id)
      set({ taxonomy })
    } catch (e) {
      set({ error: String(e) })
    }
  },

  fetchBookmarks: async () => {
    const { currentTree } = get()
    if (!currentTree) return

    set({ bookmarksLoading: true })
    try {
      const bookmarks = await api.getTreeBookmarks(currentTree.tree_id)
      set({ bookmarks, bookmarksLoading: false })
    } catch (e) {
      set({ error: String(e), bookmarksLoading: false })
    }
  },

  addBookmark: async (nodeId: string, label: string, notes?: string) => {
    const { currentTree } = get()
    if (!currentTree) return

    try {
      const bookmark = await api.addBookmark(currentTree.tree_id, nodeId, { label, notes })
      set((state) => ({
        bookmarks: [...state.bookmarks, bookmark],
        currentTree: state.currentTree
          ? {
              ...state.currentTree,
              nodes: state.currentTree.nodes.map((n) =>
                n.node_id === nodeId ? { ...n, is_bookmarked: true } : n,
              ),
            }
          : null,
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  removeBookmark: async (bookmarkId: string) => {
    const { currentTree, bookmarks } = get()
    if (!currentTree) return

    const bookmark = bookmarks.find((b) => b.bookmark_id === bookmarkId)
    if (!bookmark) return

    try {
      await api.removeBookmark(currentTree.tree_id, bookmarkId)
      const remaining = bookmarks.filter((b) => b.bookmark_id !== bookmarkId)
      // Only set is_bookmarked=false if no other bookmarks reference the same node
      const nodeStillBookmarked = remaining.some((b) => b.node_id === bookmark.node_id)
      set((state) => ({
        bookmarks: remaining,
        currentTree: state.currentTree
          ? {
              ...state.currentTree,
              nodes: state.currentTree.nodes.map((n) =>
                n.node_id === bookmark.node_id && !nodeStillBookmarked
                  ? { ...n, is_bookmarked: false }
                  : n,
              ),
            }
          : null,
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  summarizeBookmark: async (bookmarkId: string) => {
    const { currentTree } = get()
    if (!currentTree) return

    try {
      const updated = await api.summarizeBookmark(currentTree.tree_id, bookmarkId)
      set((state) => ({
        bookmarks: state.bookmarks.map((b) =>
          b.bookmark_id === bookmarkId ? updated : b,
        ),
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  navigateToBookmark: (bookmark: BookmarkResponse) => {
    get().navigateToNode(bookmark.node_id)
  },

  fetchExclusions: async () => {
    const { currentTree } = get()
    if (!currentTree) return

    try {
      const exclusions = await api.getExclusions(currentTree.tree_id)
      set({ exclusions })
    } catch (e) {
      set({ error: String(e) })
    }
  },

  excludeNode: async (nodeId: string, scopeNodeId: string, reason?: string) => {
    const { currentTree } = get()
    if (!currentTree) return

    try {
      const exclusion = await api.excludeNode(currentTree.tree_id, nodeId, scopeNodeId, reason)
      set((state) => ({
        exclusions: [...state.exclusions, exclusion],
        currentTree: state.currentTree
          ? {
              ...state.currentTree,
              nodes: state.currentTree.nodes.map((n) =>
                n.node_id === nodeId ? { ...n, is_excluded: true } : n,
              ),
            }
          : null,
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  includeNode: async (nodeId: string, scopeNodeId: string) => {
    const { currentTree } = get()
    if (!currentTree) return

    try {
      await api.includeNode(currentTree.tree_id, nodeId, scopeNodeId)
      set((state) => {
        const remaining = state.exclusions.filter(
          (ex) => !(ex.node_id === nodeId && ex.scope_node_id === scopeNodeId),
        )
        // Node is only fully un-excluded if no exclusion records remain for it
        const stillExcluded = remaining.some((ex) => ex.node_id === nodeId)
        return {
          exclusions: remaining,
          currentTree: state.currentTree
            ? {
                ...state.currentTree,
                nodes: state.currentTree.nodes.map((n) =>
                  n.node_id === nodeId ? { ...n, is_excluded: stillExcluded } : n,
                ),
              }
            : null,
        }
      })
    } catch (e) {
      set({ error: String(e) })
    }
  },

  fetchDigressionGroups: async () => {
    const { currentTree } = get()
    if (!currentTree) return

    try {
      const digressionGroups = await api.getDigressionGroups(currentTree.tree_id)
      set({ digressionGroups })
    } catch (e) {
      set({ error: String(e) })
    }
  },

  createDigressionGroup: async (req: CreateDigressionGroupRequest) => {
    const { currentTree } = get()
    if (!currentTree) return false

    try {
      const group = await api.createDigressionGroup(currentTree.tree_id, req)
      set((state) => ({
        digressionGroups: [...state.digressionGroups, group],
      }))
      return true
    } catch (e) {
      const msg = String(e)
      // Extract user-friendly message from API errors
      if (msg.includes('not contiguous')) {
        set({ error: 'Selected messages must be contiguous (no gaps between them).' })
      } else {
        const detailMatch = msg.match(/"detail"\s*:\s*"([^"]+)"/)
        set({ error: detailMatch ? detailMatch[1] : msg })
      }
      return false
    }
  },

  toggleDigressionGroup: async (groupId: string, included: boolean) => {
    const { currentTree } = get()
    if (!currentTree) return

    try {
      const updated = await api.toggleDigressionGroup(currentTree.tree_id, groupId, included)
      set((state) => ({
        digressionGroups: state.digressionGroups.map((g) =>
          g.group_id === groupId ? updated : g,
        ),
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  deleteDigressionGroup: async (groupId: string) => {
    const { currentTree } = get()
    if (!currentTree) return

    try {
      await api.deleteDigressionGroup(currentTree.tree_id, groupId)
      set((state) => ({
        digressionGroups: state.digressionGroups.filter((g) => g.group_id !== groupId),
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  setDigressionPanelOpen: (open: boolean) => set({ digressionPanelOpen: open }),

  setGroupSelectionMode: (active: boolean) => set({
    groupSelectionMode: active,
    selectedGroupNodeIds: active ? [] : [],
  }),

  toggleGroupNodeSelection: (nodeId: string) => set((state) => ({
    selectedGroupNodeIds: state.selectedGroupNodeIds.includes(nodeId)
      ? state.selectedGroupNodeIds.filter((id) => id !== nodeId)
      : [...state.selectedGroupNodeIds, nodeId],
  })),

  toggleAnchor: async (nodeId: string) => {
    const { currentTree } = get()
    if (!currentTree) return

    try {
      const result = await api.toggleAnchor(currentTree.tree_id, nodeId)
      set((state) => ({
        currentTree: state.currentTree
          ? {
              ...state.currentTree,
              nodes: state.currentTree.nodes.map((n) =>
                n.node_id === nodeId ? { ...n, is_anchored: result.is_anchored } : n,
              ),
            }
          : null,
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  anchorGroup: async (groupId: string) => {
    const { currentTree, digressionGroups } = get()
    if (!currentTree) return

    const group = digressionGroups.find((g) => g.group_id === groupId)
    if (!group) return

    try {
      // If all nodes in the group are already anchored, unanchor all; otherwise anchor all
      const allAnchored = group.node_ids.every((nid) => {
        const node = currentTree.nodes.find((n) => n.node_id === nid)
        return node?.is_anchored ?? false
      })
      const anchor = !allAnchored
      await api.bulkAnchor(currentTree.tree_id, group.node_ids, anchor)
      // Update local state
      const anchoredSet = new Set(group.node_ids)
      set((state) => ({
        currentTree: state.currentTree
          ? {
              ...state.currentTree,
              nodes: state.currentTree.nodes.map((n) =>
                anchoredSet.has(n.node_id) ? { ...n, is_anchored: anchor } : n,
              ),
            }
          : null,
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  setComparisonNodeId: (nodeId: string | null) => {
    set({ comparisonNodeId: nodeId })
  },

  enterComparisonPicking: () => {
    const { splitViewNodeId } = get()
    set({
      comparisonPickingMode: true,
      comparisonPickingSourceId: splitViewNodeId,
      splitViewNodeId: null,
    })
  },

  pickComparisonTarget: (nodeId: string) => {
    const { comparisonPickingSourceId } = get()
    // Guard: don't compare a node to itself
    if (nodeId === comparisonPickingSourceId) return
    set({
      comparisonNodeId: nodeId,
      comparisonPickingMode: false,
      splitViewNodeId: comparisonPickingSourceId,
      comparisonPickingSourceId: null,
    })
  },

  cancelComparisonPicking: () => {
    const { comparisonPickingSourceId } = get()
    set({
      comparisonPickingMode: false,
      splitViewNodeId: comparisonPickingSourceId,
      comparisonPickingSourceId: null,
    })
  },
}))
