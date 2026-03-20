/** Zustand store for Qivis app state. */

import { create } from 'zustand'
import { useShallow } from 'zustand/react/shallow'
import * as api from '../api/client.ts'
import type {
  AnnotationResponse,
  BookmarkResponse,
  CreateDigressionGroupRequest,
  CreateSummaryRequest,
  CrossModelTarget,
  DigressionGroupResponse,
  EditHistoryEntry,
  GenerateRequest,
  InterventionTypeInfo,
  NodeExclusionResponse,
  NodeResponse,
  NoteResponse,
  PatchRhizomeRequest,
  PerturbationConfig,
  PerturbationReportResponse,
  ProviderInfo,
  SamplingParams,
  SearchResultItem,
  SummaryResponse,
  TaxonomyResponse,
  RhizomeDetail,
  RhizomeSummary,
} from '../api/types.ts'

interface GenerationError {
  parentNodeId: string
  provider: string
  model: string | null
  systemPrompt: string | null
  errorMessage: string
}

interface RhizomeStore {
  // State
  rhizomes: RhizomeSummary[]
  selectedRhizomeId: string | null
  currentRhizome: RhizomeDetail | null
  providers: ProviderInfo[]
  interventionTypes: InterventionTypeInfo[]
  isLoading: boolean
  isGenerating: boolean
  _abortController: AbortController | null
  streamingContent: string
  streamingThinkingContent: string
  streamingContents: Record<number, string>
  streamingThinkingContents: Record<number, string>
  streamingNodeIds: Record<number, string>
  streamingTotal: number
  activeStreamIndex: number
  regeneratingParentId: string | null
  streamingParentId: string | null
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
  libraryOpen: boolean
  nodeAnnotations: Record<string, AnnotationResponse[]>
  taxonomy: TaxonomyResponse | null
  bookmarks: BookmarkResponse[]
  bookmarksLoading: boolean
  exclusions: NodeExclusionResponse[]
  digressionGroups: DigressionGroupResponse[]
  nodeNotes: Record<string, NoteResponse[]>
  rhizomeNotes: NoteResponse[]
  rhizomeAnnotations: AnnotationResponse[]
  rhizomeSummaries: SummaryResponse[]
  researchPaneTab: 'bookmarks' | 'tags' | 'notes' | 'summaries' | 'experiments'
  rightPaneMode: 'graph' | 'digressions' | 'research' | null
  groupSelectionMode: boolean
  selectedGroupNodeIds: string[]
  comparisonNodeId: string | null
  comparisonPickingMode: boolean
  comparisonPickingSourceId: string | null
  searchQuery: string
  searchResults: SearchResultItem[]
  searchLoading: boolean
  scrollToNodeId: string | null
  replayState: {
    active: boolean
    step: number
    total: number
    streamingText: string
    createdNodeIds: string[]
  } | null
  perturbationState: {
    active: boolean
    step: number
    total: number
    currentLabel: string
    stepContents: Record<number, string>
  } | null
  perturbationReports: PerturbationReportResponse[]

  // Actions
  fetchRhizomes: (includeArchived?: boolean) => Promise<void>
  fetchProviders: () => Promise<void>
  fetchInterventionTypes: () => Promise<void>
  selectRhizome: (rhizomeId: string) => Promise<void>
  createRhizome: (title: string, opts?: {
    systemPrompt?: string
    defaultProvider?: string
    defaultModel?: string
    metadata?: Record<string, unknown>
  }) => Promise<void>
  updateRhizome: (rhizomeId: string, req: PatchRhizomeRequest) => Promise<void>
  sendMessage: (content: string) => Promise<void>
  sendMessageOnly: (content: string) => Promise<void>
  stopGeneration: () => void
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
  setLibraryOpen: (open: boolean) => void
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
  prefillAndGenerate: (parentId: string, prefillContent: string, overrides: GenerateRequest) => Promise<void>
  addAnnotation: (nodeId: string, tag: string, value?: unknown, notes?: string) => Promise<void>
  removeAnnotation: (nodeId: string, annotationId: string) => Promise<void>
  fetchNodeAnnotations: (nodeId: string) => Promise<void>
  fetchTaxonomy: () => Promise<void>
  addNote: (nodeId: string, content: string) => Promise<void>
  removeNote: (nodeId: string, noteId: string) => Promise<void>
  fetchNodeNotes: (nodeId: string) => Promise<void>
  fetchRhizomeNotes: () => Promise<void>
  fetchRhizomeAnnotations: () => Promise<void>
  setResearchPaneTab: (tab: 'bookmarks' | 'tags' | 'notes' | 'summaries' | 'experiments') => void
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
  setRightPaneMode: (mode: 'graph' | 'digressions' | 'research' | null) => void
  setGroupSelectionMode: (active: boolean) => void
  toggleGroupNodeSelection: (nodeId: string) => void
  toggleAnchor: (nodeId: string) => Promise<void>
  anchorGroup: (groupId: string) => Promise<void>
  setComparisonNodeId: (nodeId: string | null) => void
  enterComparisonPicking: () => void
  pickComparisonTarget: (nodeId: string) => void
  cancelComparisonPicking: () => void
  setSearchQuery: (query: string) => void
  clearSearch: () => void
  navigateToSearchResult: (rhizomeId: string, nodeId: string) => Promise<void>
  clearScrollToNode: () => void
  archiveRhizome: (rhizomeId: string) => Promise<void>
  unarchiveRhizome: (rhizomeId: string) => Promise<void>
  fetchRhizomeSummaries: () => Promise<void>
  generateSummary: (nodeId: string, req: CreateSummaryRequest) => Promise<SummaryResponse | null>
  removeSummary: (summaryId: string) => Promise<void>
  startReplay: (
    pathNodeIds: string[],
    provider: string,
    model: string | undefined,
    mode: 'context_faithful' | 'trajectory',
    systemPrompt?: string,
    samplingParams?: SamplingParams,
  ) => Promise<void>
  generateCrossModel: (
    nodeId: string,
    targets: CrossModelTarget[],
    systemPrompt?: string,
    samplingParams?: SamplingParams,
  ) => Promise<void>
  runPerturbation: (
    nodeId: string,
    perturbations: PerturbationConfig[],
    provider: string,
    model?: string,
    samplingParams?: SamplingParams,
    includeControl?: boolean,
  ) => Promise<void>
  fetchPerturbationReports: () => Promise<void>
  deletePerturbationReport: (reportId: string) => Promise<void>
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

// ---- Helpers ----

type SetFn = (
  partial: Partial<RhizomeStore> | ((state: RhizomeStore) => Partial<RhizomeStore>),
) => void

const STREAMING_RESET = {
  isGenerating: false,
  streamingContent: '',
  streamingThinkingContent: '',
  streamingParentId: null,
  _abortController: null,
} as const

const MULTI_STREAMING_RESET = {
  ...STREAMING_RESET,
  streamingContents: {} as Record<number, string>,
  streamingThinkingContents: {} as Record<number, string>,
  streamingNodeIds: {} as Record<number, string>,
  streamingTotal: 0,
  activeStreamIndex: 0,
} as const

function refreshRhizome(rhizomeId: string, set: SetFn) {
  api.getRhizome(rhizomeId).then((rhizome) => set({ currentRhizome: rhizome }))
  api.listRhizomes().then((rhizomes) => set({ rhizomes }))
}

function refreshRhizomeSelectNewest(
  rhizomeId: string,
  parentNodeId: string,
  set: SetFn,
) {
  api.getRhizome(rhizomeId).then((rhizome) => {
    const newChildren = rhizome.nodes.filter(
      (nd) => nd.parent_id === parentNodeId,
    )
    const newest = newChildren[newChildren.length - 1]
    if (newest) {
      set((state) => ({
        currentRhizome: rhizome,
        branchSelections: {
          ...state.branchSelections,
          [parentNodeId]: newest.node_id,
        },
      }))
    } else {
      set({ currentRhizome: rhizome })
    }
  })
  api.listRhizomes().then((rhizomes) => set({ rhizomes }))
}

async function fetchRhizomeData<T>(
  get: () => RhizomeStore,
  set: SetFn,
  apiFn: (rhizomeId: string) => Promise<T>,
  onSuccess: (data: T, state: RhizomeStore) => Partial<RhizomeStore>,
) {
  const { currentRhizome } = get()
  if (!currentRhizome) return
  try {
    const data = await apiFn(currentRhizome.rhizome_id)
    set((state) => onSuccess(data, state))
  } catch (e) {
    set({ error: String(e) })
  }
}

function updateNode(
  rhizome: RhizomeDetail | null,
  nodeId: string,
  update:
    | Partial<NodeResponse>
    | ((node: NodeResponse) => Partial<NodeResponse>),
): RhizomeDetail | null {
  if (!rhizome) return null
  return {
    ...rhizome,
    nodes: rhizome.nodes.map((n) =>
      n.node_id === nodeId
        ? { ...n, ...(typeof update === 'function' ? update(n) : update) }
        : n,
    ),
  }
}

export const useRhizomeStore = create<RhizomeStore>((set, get) => ({
  rhizomes: [],
  selectedRhizomeId: null,
  currentRhizome: null,
  providers: [],
  interventionTypes: [],
  isLoading: false,
  isGenerating: false,
  _abortController: null,
  streamingContent: '',
  streamingThinkingContent: '',
  streamingContents: {},
  streamingThinkingContents: {},
  streamingNodeIds: {},
  streamingTotal: 0,
  activeStreamIndex: 0,
  regeneratingParentId: null,
  streamingParentId: null,
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
  libraryOpen: false,
  nodeAnnotations: {},
  taxonomy: null,
  bookmarks: [],
  bookmarksLoading: false,
  exclusions: [],
  digressionGroups: [],
  nodeNotes: {},
  rhizomeNotes: [],
  rhizomeAnnotations: [],
  rhizomeSummaries: [],
  researchPaneTab: 'bookmarks',
  rightPaneMode: null,
  groupSelectionMode: false,
  selectedGroupNodeIds: [],
  comparisonNodeId: null,
  comparisonPickingMode: false,
  comparisonPickingSourceId: null,
  searchQuery: '',
  searchResults: [],
  searchLoading: false,
  scrollToNodeId: null,
  replayState: null,
  perturbationState: null,
  perturbationReports: [],

  stopGeneration: () => {
    const {
      _abortController,
      streamingContent,
      streamingParentId,
      streamingContents,
      streamingNodeIds,
      streamingTotal,
      currentRhizome,
    } = get()

    if (_abortController) {
      _abortController.abort()
    }

    // Clear all streaming state
    set({ ...MULTI_STREAMING_RESET, regeneratingParentId: null })

    const rhizomeId = currentRhizome?.rhizome_id
    if (!rhizomeId || !streamingParentId) {
      if (rhizomeId) refreshRhizome(rhizomeId, set)
      return
    }

    // Collect partial content to save
    const partials: string[] = []

    if (streamingTotal > 0) {
      // Multi-stream: save uncompleted streams
      for (const [idxStr, content] of Object.entries(streamingContents)) {
        const idx = Number(idxStr)
        if (streamingNodeIds[idx]) continue // Already completed server-side
        if (content.trim()) partials.push(content)
      }
    } else if (streamingContent.trim()) {
      // Single stream
      partials.push(streamingContent)
    }

    if (partials.length === 0) {
      refreshRhizome(rhizomeId, set)
      return
    }

    // Save partial content as assistant nodes, then refresh
    Promise.allSettled(
      partials.map((content) =>
        api.createNode(rhizomeId, {
          content,
          role: 'assistant',
          parent_id: streamingParentId,
          mode: 'chat',
        }),
      ),
    ).then(() => {
      refreshRhizome(rhizomeId, set)
    })
  },

  fetchRhizomes: async (includeArchived?: boolean) => {
    set({ isLoading: true, error: null })
    try {
      const rhizomes = await api.listRhizomes(includeArchived)
      set({ rhizomes, isLoading: false })
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

  fetchInterventionTypes: async () => {
    if (get().interventionTypes.length > 0) return
    try {
      const interventionTypes = await api.getInterventionTypes()
      set({ interventionTypes })
    } catch {
      // Non-critical — intervention types are informational
    }
  },

  selectRhizome: async (rhizomeId: string) => {
    set({
      isLoading: true,
      error: null,
      selectedRhizomeId: rhizomeId,
      systemPromptOverride: null,
      branchSelections: {},
      inspectedNodeId: null,
      splitViewNodeId: null,
      canvasOpen: false,
      libraryOpen: false,
      nodeAnnotations: {},
      taxonomy: null,
      bookmarks: [],
      bookmarksLoading: false,
      exclusions: [],
      digressionGroups: [],
      nodeNotes: {},
      rhizomeNotes: [],
      rhizomeAnnotations: [],
      rhizomeSummaries: [],
      rightPaneMode: null,
      groupSelectionMode: false,
      selectedGroupNodeIds: [],
      comparisonNodeId: null,
      comparisonPickingMode: false,
      comparisonPickingSourceId: null,
      perturbationState: null,
      perturbationReports: [],
    })
    try {
      const rhizome = await api.getRhizome(rhizomeId)
      set({ currentRhizome: rhizome, isLoading: false })
      // Fetch bookmarks, exclusions, etc. for the new rhizome in the background
      api.getRhizomeBookmarks(rhizomeId).then((bookmarks) => {
        set({ bookmarks })
      }).catch(() => {/* ignore bookmark fetch errors */})
      api.getExclusions(rhizomeId).then((exclusions) => {
        set({ exclusions })
      }).catch(() => {/* ignore exclusion fetch errors */})
      api.getDigressionGroups(rhizomeId).then((digressionGroups) => {
        set({ digressionGroups })
      }).catch(() => {/* ignore group fetch errors */})
      api.getRhizomeNotes(rhizomeId).then((rhizomeNotes) => {
        set({ rhizomeNotes })
      }).catch(() => {/* ignore */})
      api.getRhizomeAnnotations(rhizomeId).then((rhizomeAnnotations) => {
        set({ rhizomeAnnotations })
      }).catch(() => {/* ignore */})
      api.getRhizomeSummaries(rhizomeId).then((rhizomeSummaries) => {
        set({ rhizomeSummaries })
      }).catch(() => {/* ignore */})
    } catch (e) {
      set({ error: String(e), isLoading: false })
    }
  },

  createRhizome: async (title: string, opts?: {
    systemPrompt?: string
    defaultProvider?: string
    defaultModel?: string
    metadata?: Record<string, unknown>
  }) => {
    set({ isLoading: true, error: null })
    try {
      let rhizome = await api.createRhizome({
        title,
        default_system_prompt: opts?.systemPrompt,
        default_provider: opts?.defaultProvider,
        default_model: opts?.defaultModel,
      })
      if (opts?.metadata) {
        rhizome = await api.updateRhizome(rhizome.rhizome_id, { metadata: opts.metadata })
      }
      const rhizomes = await api.listRhizomes()
      set({
        rhizomes,
        selectedRhizomeId: rhizome.rhizome_id,
        currentRhizome: rhizome,
        isLoading: false,
        systemPromptOverride: null,
        branchSelections: {},
      })
    } catch (e) {
      set({ error: String(e), isLoading: false })
    }
  },

  updateRhizome: async (rhizomeId: string, req: PatchRhizomeRequest) => {
    set({ error: null })
    try {
      const updated = await api.updateRhizome(rhizomeId, req)
      const meta = updated.metadata ?? {}
      set((state) => ({
        currentRhizome: state.currentRhizome?.rhizome_id === rhizomeId ? updated : state.currentRhizome,
        rhizomes: state.rhizomes.map((t) =>
          t.rhizome_id === rhizomeId
            ? {
                ...t,
                title: updated.title,
                updated_at: updated.updated_at,
                folders: (meta.folders as string[]) ?? [],
                tags: (meta.tags as string[]) ?? [],
              }
            : t,
        ),
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  sendMessage: async (content: string) => {
    const { currentRhizome, systemPromptOverride, branchSelections } = get()
    if (!currentRhizome) return

    const rhizomeId = currentRhizome.rhizome_id
    set({ error: null, generationError: null })

    try {
      // Find the leaf node of the active path
      const activePath = getActivePath(currentRhizome.nodes, branchSelections)
      const leafNode = activePath.length > 0 ? activePath[activePath.length - 1] : null
      const parentId = leafNode?.node_id

      // Create user node
      const userNode = await api.createNode(rhizomeId, {
        content,
        role: 'user',
        parent_id: parentId,
      })

      // Optimistically add user node to current rhizome
      set((state) => ({
        currentRhizome: state.currentRhizome
          ? { ...state.currentRhizome, nodes: [...state.currentRhizome.nodes, userNode] }
          : null,
      }))

      const ac = new AbortController()
      set({ ...STREAMING_RESET, isGenerating: true, _abortController: ac, streamingParentId: userNode.node_id })

      // Branch-local defaults: prefer last assistant's provider/model over rhizome defaults
      const lastAssistant = [...activePath].reverse().find((n) => n.role === 'assistant')
      const resolvedProvider = lastAssistant?.provider ?? currentRhizome.default_provider
      const resolvedModel = lastAssistant?.model ?? currentRhizome.default_model

      // Backend handles merge resolution: rhizome defaults > base
      // Only pass explicit overrides here (provider, model, system_prompt)
      const generateReq: GenerateRequest = {
        ...(resolvedProvider ? { provider: resolvedProvider } : {}),
        ...(resolvedModel ? { model: resolvedModel } : {}),
        ...(systemPromptOverride != null ? { system_prompt: systemPromptOverride } : {}),
      }

      const shouldStream = currentRhizome.metadata?.stream_responses !== false

      if (shouldStream) {
        await api.generateStream(
          rhizomeId,
          userNode.node_id,
          generateReq,
          (text) => {
            set((state) => ({ streamingContent: state.streamingContent + text }))
          },
          () => {
            set({ ...STREAMING_RESET })
            refreshRhizome(rhizomeId, set)
          },
          (error) => {
            set({
              ...STREAMING_RESET,
              error: error instanceof Error ? error.message : String(error),
              generationError: {
                parentNodeId: userNode.node_id,
                provider: resolvedProvider ?? 'anthropic',
                model: resolvedModel ?? null,
                systemPrompt: systemPromptOverride ?? null,
                errorMessage: error instanceof Error ? error.message : String(error),
              },
            })
          },
          (thinking) => {
            set((state) => ({
              streamingThinkingContent: state.streamingThinkingContent + thinking,
            }))
          },
          ac.signal,
        )
      } else {
        try {
          await api.generate(rhizomeId, userNode.node_id, generateReq)
          set({ ...STREAMING_RESET })
          refreshRhizome(rhizomeId, set)
        } catch (error) {
          set({
            ...STREAMING_RESET,
            error: error instanceof Error ? error.message : String(error),
            generationError: {
              parentNodeId: userNode.node_id,
              provider: resolvedProvider ?? 'anthropic',
              model: resolvedModel ?? null,
              systemPrompt: systemPromptOverride ?? null,
              errorMessage: error instanceof Error ? error.message : String(error),
            },
          })
        }
      }
    } catch (e) {
      set({ ...STREAMING_RESET, error: String(e) })
    }
  },

  sendMessageOnly: async (content: string) => {
    const { currentRhizome, branchSelections } = get()
    if (!currentRhizome) return

    const rhizomeId = currentRhizome.rhizome_id
    set({ error: null })

    try {
      const activePath = getActivePath(currentRhizome.nodes, branchSelections)
      const leafNode = activePath.length > 0 ? activePath[activePath.length - 1] : null
      const parentId = leafNode?.node_id

      const userNode = await api.createNode(rhizomeId, {
        content,
        role: 'user',
        parent_id: parentId,
      })

      set((state) => ({
        currentRhizome: state.currentRhizome
          ? { ...state.currentRhizome, nodes: [...state.currentRhizome.nodes, userNode] }
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
    const { currentRhizome } = get()
    if (!currentRhizome) return
    const nodeMap = new Map(currentRhizome.nodes.map((n) => [n.node_id, n]))
    const selections: Record<string, string> = {}
    let current = nodeMap.get(nodeId)
    while (current) {
      const parentKey = current.parent_id ?? ''
      selections[parentKey] = current.node_id
      current = current.parent_id ? nodeMap.get(current.parent_id) : undefined
    }
    set({ branchSelections: selections, scrollToNodeId: nodeId })
  },

  setComparisonHoveredNodeId: (nodeId: string | null) => {
    set({ comparisonHoveredNodeId: nodeId })
  },

  editNodeContent: async (nodeId: string, editedContent: string | null) => {
    const { currentRhizome } = get()
    if (!currentRhizome) return

    try {
      const updated = await api.editNodeContent(currentRhizome.rhizome_id, nodeId, editedContent)
      // Update node in rhizome, then re-fetch edit history so the section stays visible
      // even after restoring to original (edited_content=null but history exists)
      set((state) => ({
        currentRhizome: updateNode(state.currentRhizome, nodeId, {
          edited_content: updated.edited_content,
        }),
      }))
      // Re-fetch edit history in background to keep cache populated
      api.getEditHistory(currentRhizome.rhizome_id, nodeId).then((history) => {
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

  setLibraryOpen: (open: boolean) => {
    set({ libraryOpen: open })
  },

  forkAndGenerate: async (parentId: string, content: string, overrides: GenerateRequest) => {
    const { currentRhizome } = get()
    if (!currentRhizome) return

    const rhizomeId = currentRhizome.rhizome_id
    set({ error: null, generationError: null })

    try {
      // Create user node as new child of parentId (sibling of existing children)
      const userNode = await api.createNode(rhizomeId, {
        content,
        role: 'user',
        parent_id: parentId || undefined,
      })

      // Update branchSelections to follow this new fork + add node optimistically
      set((state) => ({
        currentRhizome: state.currentRhizome
          ? { ...state.currentRhizome, nodes: [...state.currentRhizome.nodes, userNode] }
          : null,
        branchSelections: {
          ...state.branchSelections,
          [parentId]: userNode.node_id,
        },
      }))

      const n = overrides.n ?? 1
      const shouldStream = overrides.stream !== false

      const ac = new AbortController()

      if (shouldStream && n > 1) {
        set({ ...MULTI_STREAMING_RESET, isGenerating: true, streamingTotal: n, _abortController: ac, streamingParentId: userNode.node_id })
        await api.generateMultiStream(
          rhizomeId,
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
            set({ ...MULTI_STREAMING_RESET })
            refreshRhizome(rhizomeId, set)
          },
          (error) => {
            set({
              ...MULTI_STREAMING_RESET,
              error: error instanceof Error ? error.message : String(error),
              generationError: {
                parentNodeId: userNode.node_id,
                provider: overrides.provider ?? 'anthropic',
                model: overrides.model ?? null,
                systemPrompt: overrides.system_prompt ?? null,
                errorMessage: error instanceof Error ? error.message : String(error),
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
          ac.signal,
        )
      } else if (shouldStream) {
        set({ ...STREAMING_RESET, isGenerating: true, _abortController: ac, streamingParentId: userNode.node_id })
        await api.generateStream(
          rhizomeId,
          userNode.node_id,
          { ...overrides, stream: true },
          (text) => {
            set((state) => ({ streamingContent: state.streamingContent + text }))
          },
          () => {
            set({ ...STREAMING_RESET })
            refreshRhizome(rhizomeId, set)
          },
          (error) => {
            set({
              ...STREAMING_RESET,
              error: error instanceof Error ? error.message : String(error),
              generationError: {
                parentNodeId: userNode.node_id,
                provider: overrides.provider ?? 'anthropic',
                model: overrides.model ?? null,
                systemPrompt: overrides.system_prompt ?? null,
                errorMessage: error instanceof Error ? error.message : String(error),
              },
            })
          },
          (thinking) => {
            set((state) => ({
              streamingThinkingContent: state.streamingThinkingContent + thinking,
            }))
          },
          ac.signal,
        )
      } else {
        set({ ...STREAMING_RESET, isGenerating: true })
        try {
          await api.generate(rhizomeId, userNode.node_id, { ...overrides, n })
          set({ ...STREAMING_RESET })
          refreshRhizome(rhizomeId, set)
        } catch (error) {
          set({
            ...STREAMING_RESET,
            error: error instanceof Error ? error.message : String(error),
            generationError: {
              parentNodeId: userNode.node_id,
              provider: overrides.provider ?? 'anthropic',
              model: overrides.model ?? null,
              systemPrompt: overrides.system_prompt ?? null,
              errorMessage: error instanceof Error ? error.message : String(error),
            },
          })
        }
      }
    } catch (e) {
      set({ ...STREAMING_RESET, error: String(e) })
    }
  },

  regenerate: async (parentNodeId: string, overrides: GenerateRequest) => {
    const { currentRhizome } = get()
    if (!currentRhizome) return

    const rhizomeId = currentRhizome.rhizome_id
    const ac = new AbortController()
    set({
      error: null, generationError: null,
      ...STREAMING_RESET, isGenerating: true,
      _abortController: ac,
      regeneratingParentId: parentNodeId,
      streamingParentId: parentNodeId,
    })

    const n = overrides.n ?? 1
    const shouldStream = overrides.stream !== false
    const regenError = (error: unknown) => ({
      parentNodeId,
      provider: overrides.provider ?? 'anthropic',
      model: overrides.model ?? null,
      systemPrompt: overrides.system_prompt ?? null,
      errorMessage: error instanceof Error ? error.message : String(error),
    })

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
          rhizomeId,
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
            set({ ...MULTI_STREAMING_RESET, regeneratingParentId: null })
            refreshRhizomeSelectNewest(rhizomeId, parentNodeId, set)
          },
          (error) => {
            set({
              ...MULTI_STREAMING_RESET,
              regeneratingParentId: null,
              error: error instanceof Error ? error.message : String(error),
              generationError: regenError(error),
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
          ac.signal,
        )
      } else if (shouldStream) {
        await api.generateStream(
          rhizomeId,
          parentNodeId,
          { ...overrides, stream: true },
          (text) => {
            set((state) => ({ streamingContent: state.streamingContent + text }))
          },
          () => {
            set({ ...STREAMING_RESET, regeneratingParentId: null })
            refreshRhizomeSelectNewest(rhizomeId, parentNodeId, set)
          },
          (error) => {
            set({
              ...STREAMING_RESET,
              regeneratingParentId: null,
              error: error instanceof Error ? error.message : String(error),
              generationError: regenError(error),
            })
          },
          (thinking) => {
            set((state) => ({
              streamingThinkingContent: state.streamingThinkingContent + thinking,
            }))
          },
          ac.signal,
        )
      } else {
        try {
          await api.generate(rhizomeId, parentNodeId, { ...overrides, n })
          set({ ...STREAMING_RESET, regeneratingParentId: null })
          refreshRhizomeSelectNewest(rhizomeId, parentNodeId, set)
        } catch (error) {
          set({
            ...STREAMING_RESET,
            regeneratingParentId: null,
            error: error instanceof Error ? error.message : String(error),
            generationError: regenError(error),
          })
        }
      }
    } catch (e) {
      set({ ...STREAMING_RESET, regeneratingParentId: null, error: String(e) })
    }
  },

  prefillAssistant: async (parentId: string, content: string) => {
    const { currentRhizome } = get()
    if (!currentRhizome) return

    const rhizomeId = currentRhizome.rhizome_id
    set({ error: null })

    try {
      const node = await api.createNode(rhizomeId, {
        content,
        role: 'assistant',
        parent_id: parentId || undefined,
        mode: 'manual',
      })

      set((state) => ({
        currentRhizome: state.currentRhizome
          ? { ...state.currentRhizome, nodes: [...state.currentRhizome.nodes, node] }
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

  prefillAndGenerate: async (parentId: string, prefillContent: string, overrides: GenerateRequest) => {
    const { currentRhizome } = get()
    if (!currentRhizome) return

    const rhizomeId = currentRhizome.rhizome_id
    set({ error: null, generationError: null })

    const shouldStream = overrides.stream !== false
    const reqWithPrefill: GenerateRequest = { ...overrides, prefill_content: prefillContent }

    const ac = new AbortController()

    try {
      if (shouldStream) {
        // Initialize streaming content with the prefill text so it appears immediately
        set({ ...STREAMING_RESET, isGenerating: true, streamingContent: prefillContent, _abortController: ac, streamingParentId: parentId })
        await api.generateStream(
          rhizomeId,
          parentId,
          { ...reqWithPrefill, stream: true },
          (text) => {
            set((state) => ({ streamingContent: state.streamingContent + text }))
          },
          () => {
            set({ ...STREAMING_RESET })
            refreshRhizomeSelectNewest(rhizomeId, parentId, set)
          },
          (error) => {
            set({
              ...STREAMING_RESET,
              error: error instanceof Error ? error.message : String(error),
              generationError: {
                parentNodeId: parentId,
                provider: overrides.provider ?? 'anthropic',
                model: overrides.model ?? null,
                systemPrompt: overrides.system_prompt ?? null,
                errorMessage: error instanceof Error ? error.message : String(error),
              },
            })
          },
          (thinking) => {
            set((state) => ({
              streamingThinkingContent: state.streamingThinkingContent + thinking,
            }))
          },
          ac.signal,
        )
      } else {
        set({ ...STREAMING_RESET, isGenerating: true })
        try {
          await api.generate(rhizomeId, parentId, reqWithPrefill)
          set({ ...STREAMING_RESET })
          refreshRhizomeSelectNewest(rhizomeId, parentId, set)
        } catch (error) {
          set({
            ...STREAMING_RESET,
            error: error instanceof Error ? error.message : String(error),
            generationError: {
              parentNodeId: parentId,
              provider: overrides.provider ?? 'anthropic',
              model: overrides.model ?? null,
              systemPrompt: overrides.system_prompt ?? null,
              errorMessage: error instanceof Error ? error.message : String(error),
            },
          })
        }
      }
    } catch (e) {
      set({ ...STREAMING_RESET, error: String(e) })
    }
  },

  addAnnotation: async (nodeId: string, tag: string, value?: unknown, notes?: string) => {
    const { currentRhizome } = get()
    if (!currentRhizome) return

    try {
      const annotation = await api.addAnnotation(currentRhizome.rhizome_id, nodeId, {
        tag,
        value,
        notes,
      })
      set((state) => ({
        nodeAnnotations: {
          ...state.nodeAnnotations,
          [nodeId]: [...(state.nodeAnnotations[nodeId] ?? []), annotation],
        },
        currentRhizome: updateNode(state.currentRhizome, nodeId, (n) => ({
          annotation_count: n.annotation_count + 1,
        })),
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
    const { currentRhizome } = get()
    if (!currentRhizome) return

    try {
      await api.removeAnnotation(currentRhizome.rhizome_id, annotationId)
      set((state) => ({
        nodeAnnotations: {
          ...state.nodeAnnotations,
          [nodeId]: (state.nodeAnnotations[nodeId] ?? []).filter(
            (a) => a.annotation_id !== annotationId,
          ),
        },
        currentRhizome: updateNode(state.currentRhizome, nodeId, (n) => ({
          annotation_count: Math.max(0, n.annotation_count - 1),
        })),
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  fetchNodeAnnotations: (nodeId: string) => fetchRhizomeData(get, set,
    (id) => api.getNodeAnnotations(id, nodeId),
    (annotations, s) => ({ nodeAnnotations: { ...s.nodeAnnotations, [nodeId]: annotations } }),
  ),

  fetchTaxonomy: () => fetchRhizomeData(get, set,
    (id) => api.getRhizomeTaxonomy(id),
    (taxonomy) => ({ taxonomy }),
  ),

  addNote: async (nodeId: string, content: string) => {
    const { currentRhizome } = get()
    if (!currentRhizome) return

    try {
      const note = await api.addNote(currentRhizome.rhizome_id, nodeId, { content })
      set((state) => ({
        nodeNotes: {
          ...state.nodeNotes,
          [nodeId]: [...(state.nodeNotes[nodeId] ?? []), note],
        },
        rhizomeNotes: [...state.rhizomeNotes, note],
        currentRhizome: updateNode(state.currentRhizome, nodeId, (n) => ({
          note_count: n.note_count + 1,
        })),
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  removeNote: async (nodeId: string, noteId: string) => {
    const { currentRhizome } = get()
    if (!currentRhizome) return

    try {
      await api.removeNote(currentRhizome.rhizome_id, noteId)
      set((state) => ({
        nodeNotes: {
          ...state.nodeNotes,
          [nodeId]: (state.nodeNotes[nodeId] ?? []).filter(
            (n) => n.note_id !== noteId,
          ),
        },
        rhizomeNotes: state.rhizomeNotes.filter((n) => n.note_id !== noteId),
        currentRhizome: updateNode(state.currentRhizome, nodeId, (n) => ({
          note_count: Math.max(0, n.note_count - 1),
        })),
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  fetchNodeNotes: (nodeId: string) => fetchRhizomeData(get, set,
    (id) => api.getNodeNotes(id, nodeId),
    (notes, s) => ({ nodeNotes: { ...s.nodeNotes, [nodeId]: notes } }),
  ),

  fetchRhizomeNotes: () => fetchRhizomeData(get, set,
    (id) => api.getRhizomeNotes(id),
    (rhizomeNotes) => ({ rhizomeNotes }),
  ),

  fetchRhizomeAnnotations: () => fetchRhizomeData(get, set,
    (id) => api.getRhizomeAnnotations(id),
    (rhizomeAnnotations) => ({ rhizomeAnnotations }),
  ),

  setResearchPaneTab: (tab: 'bookmarks' | 'tags' | 'notes' | 'summaries' | 'experiments') => {
    set({ researchPaneTab: tab })
  },

  fetchBookmarks: async () => {
    const { currentRhizome } = get()
    if (!currentRhizome) return

    set({ bookmarksLoading: true })
    try {
      const bookmarks = await api.getRhizomeBookmarks(currentRhizome.rhizome_id)
      set({ bookmarks, bookmarksLoading: false })
    } catch (e) {
      set({ error: String(e), bookmarksLoading: false })
    }
  },

  addBookmark: async (nodeId: string, label: string, notes?: string) => {
    const { currentRhizome } = get()
    if (!currentRhizome) return

    try {
      const bookmark = await api.addBookmark(currentRhizome.rhizome_id, nodeId, { label, notes })
      set((state) => ({
        bookmarks: [...state.bookmarks, bookmark],
        currentRhizome: updateNode(state.currentRhizome, nodeId, { is_bookmarked: true }),
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  removeBookmark: async (bookmarkId: string) => {
    const { currentRhizome, bookmarks } = get()
    if (!currentRhizome) return

    const bookmark = bookmarks.find((b) => b.bookmark_id === bookmarkId)
    if (!bookmark) return

    try {
      await api.removeBookmark(currentRhizome.rhizome_id, bookmarkId)
      const remaining = bookmarks.filter((b) => b.bookmark_id !== bookmarkId)
      // Only set is_bookmarked=false if no other bookmarks reference the same node
      const nodeStillBookmarked = remaining.some((b) => b.node_id === bookmark.node_id)
      set((state) => ({
        bookmarks: remaining,
        currentRhizome: !nodeStillBookmarked
          ? updateNode(state.currentRhizome, bookmark.node_id, { is_bookmarked: false })
          : state.currentRhizome,
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  summarizeBookmark: async (bookmarkId: string) => {
    const { currentRhizome } = get()
    if (!currentRhizome) return

    try {
      const updated = await api.summarizeBookmark(currentRhizome.rhizome_id, bookmarkId)
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

  fetchExclusions: () => fetchRhizomeData(get, set,
    (id) => api.getExclusions(id),
    (exclusions) => ({ exclusions }),
  ),

  excludeNode: async (nodeId: string, scopeNodeId: string, reason?: string) => {
    const { currentRhizome } = get()
    if (!currentRhizome) return

    try {
      const exclusion = await api.excludeNode(currentRhizome.rhizome_id, nodeId, scopeNodeId, reason)
      set((state) => ({
        exclusions: [...state.exclusions, exclusion],
        currentRhizome: updateNode(state.currentRhizome, nodeId, { is_excluded: true }),
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  includeNode: async (nodeId: string, scopeNodeId: string) => {
    const { currentRhizome } = get()
    if (!currentRhizome) return

    try {
      await api.includeNode(currentRhizome.rhizome_id, nodeId, scopeNodeId)
      set((state) => {
        const remaining = state.exclusions.filter(
          (ex) => !(ex.node_id === nodeId && ex.scope_node_id === scopeNodeId),
        )
        const stillExcluded = remaining.some((ex) => ex.node_id === nodeId)
        return {
          exclusions: remaining,
          currentRhizome: updateNode(state.currentRhizome, nodeId, { is_excluded: stillExcluded }),
        }
      })
    } catch (e) {
      set({ error: String(e) })
    }
  },

  fetchDigressionGroups: () => fetchRhizomeData(get, set,
    (id) => api.getDigressionGroups(id),
    (digressionGroups) => ({ digressionGroups }),
  ),

  createDigressionGroup: async (req: CreateDigressionGroupRequest) => {
    const { currentRhizome } = get()
    if (!currentRhizome) return false

    try {
      const group = await api.createDigressionGroup(currentRhizome.rhizome_id, req)
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
    const { currentRhizome } = get()
    if (!currentRhizome) return

    try {
      const updated = await api.toggleDigressionGroup(currentRhizome.rhizome_id, groupId, included)
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
    const { currentRhizome } = get()
    if (!currentRhizome) return

    try {
      await api.deleteDigressionGroup(currentRhizome.rhizome_id, groupId)
      set((state) => ({
        digressionGroups: state.digressionGroups.filter((g) => g.group_id !== groupId),
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  setRightPaneMode: (mode: 'graph' | 'digressions' | 'research' | null) => set({ rightPaneMode: mode }),

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
    const { currentRhizome } = get()
    if (!currentRhizome) return

    try {
      const result = await api.toggleAnchor(currentRhizome.rhizome_id, nodeId)
      set((state) => ({
        currentRhizome: updateNode(state.currentRhizome, nodeId, { is_anchored: result.is_anchored }),
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  anchorGroup: async (groupId: string) => {
    const { currentRhizome, digressionGroups } = get()
    if (!currentRhizome) return

    const group = digressionGroups.find((g) => g.group_id === groupId)
    if (!group) return

    try {
      // If all nodes in the group are already anchored, unanchor all; otherwise anchor all
      const allAnchored = group.node_ids.every((nid) => {
        const node = currentRhizome.nodes.find((n) => n.node_id === nid)
        return node?.is_anchored ?? false
      })
      const anchor = !allAnchored
      await api.bulkAnchor(currentRhizome.rhizome_id, group.node_ids, anchor)
      // Update local state
      const anchoredSet = new Set(group.node_ids)
      set((state) => ({
        currentRhizome: state.currentRhizome
          ? {
              ...state.currentRhizome,
              nodes: state.currentRhizome.nodes.map((n) =>
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

  setSearchQuery: (query: string) => {
    set({ searchQuery: query })
    // Clear results immediately if query is empty
    if (!query.trim()) {
      set({ searchResults: [], searchLoading: false })
      return
    }
    // Debounced search is handled by the component
  },

  clearSearch: () => {
    set({ searchQuery: '', searchResults: [], searchLoading: false })
  },

  navigateToSearchResult: async (rhizomeId: string, nodeId: string) => {
    const { selectedRhizomeId } = get()
    if (selectedRhizomeId !== rhizomeId) {
      await get().selectRhizome(rhizomeId)
    }
    get().navigateToNode(nodeId)
    set({ scrollToNodeId: nodeId })
  },

  clearScrollToNode: () => {
    set({ scrollToNodeId: null })
  },

  archiveRhizome: async (rhizomeId: string) => {
    try {
      await api.archiveRhizome(rhizomeId)
      set((state) => ({
        rhizomes: state.rhizomes.filter((t) => t.rhizome_id !== rhizomeId),
        selectedRhizomeId: state.selectedRhizomeId === rhizomeId ? null : state.selectedRhizomeId,
        currentRhizome: state.selectedRhizomeId === rhizomeId ? null : state.currentRhizome,
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  unarchiveRhizome: async (rhizomeId: string) => {
    try {
      await api.unarchiveRhizome(rhizomeId)
      set((state) => ({
        rhizomes: state.rhizomes.filter((t) => t.rhizome_id !== rhizomeId),
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  fetchRhizomeSummaries: async () => {
    const { currentRhizome } = get()
    if (!currentRhizome) return
    try {
      const rhizomeSummaries = await api.getRhizomeSummaries(currentRhizome.rhizome_id)
      set({ rhizomeSummaries })
    } catch {
      /* ignore fetch errors */
    }
  },

  generateSummary: async (nodeId: string, req: CreateSummaryRequest) => {
    const { currentRhizome } = get()
    if (!currentRhizome) return null
    try {
      const summary = await api.generateSummary(currentRhizome.rhizome_id, nodeId, req)
      set((state) => ({
        rhizomeSummaries: [...state.rhizomeSummaries, summary],
      }))
      return summary
    } catch (e) {
      set({ error: String(e) })
      return null
    }
  },

  removeSummary: async (summaryId: string) => {
    const { currentRhizome } = get()
    if (!currentRhizome) return
    try {
      await api.removeSummary(currentRhizome.rhizome_id, summaryId)
      set((state) => ({
        rhizomeSummaries: state.rhizomeSummaries.filter((s) => s.summary_id !== summaryId),
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  startReplay: async (pathNodeIds, provider, model, mode, systemPrompt, samplingParams) => {
    const { currentRhizome } = get()
    if (!currentRhizome) return

    const rhizomeId = currentRhizome.rhizome_id
    const ac = new AbortController()
    set({
      error: null,
      _abortController: ac,
      replayState: {
        active: true,
        step: 0,
        total: pathNodeIds.length,
        streamingText: '',
        createdNodeIds: [],
      },
    })

    try {
      await api.replayStream(
        rhizomeId,
        {
          path_node_ids: pathNodeIds,
          provider,
          model,
          mode,
          system_prompt: systemPrompt,
          sampling_params: samplingParams,
        },
        (step, total, _type, _nodeId) => {
          set((state) => ({
            replayState: state.replayState
              ? { ...state.replayState, step, total, streamingText: '' }
              : null,
          }))
        },
        (text, _stepIndex) => {
          set((state) => ({
            replayState: state.replayState
              ? { ...state.replayState, streamingText: state.replayState.streamingText + text }
              : null,
          }))
        },
        (_event) => {
          // Step completed — clear streaming text for next step
          set((state) => ({
            replayState: state.replayState
              ? { ...state.replayState, streamingText: '' }
              : null,
          }))
        },
        (_createdNodeIds) => {
          set({
            replayState: null,
            _abortController: null,
          })
          refreshRhizome(rhizomeId, set)
        },
        (error) => {
          set({
            replayState: null,
            _abortController: null,
            error: error.message,
          })
          refreshRhizome(rhizomeId, set)
        },
        ac.signal,
      )
    } catch (e) {
      set({
        replayState: null,
        _abortController: null,
        error: String(e),
      })
    }
  },

  generateCrossModel: async (nodeId, targets, systemPrompt, samplingParams) => {
    const { currentRhizome } = get()
    if (!currentRhizome) return

    const rhizomeId = currentRhizome.rhizome_id
    const ac = new AbortController()
    set({
      ...MULTI_STREAMING_RESET,
      error: null,
      isGenerating: true,
      streamingTotal: targets.length,
      _abortController: ac,
      regeneratingParentId: nodeId,
      streamingParentId: nodeId,
    })

    try {
      await api.generateCrossStream(
        rhizomeId,
        nodeId,
        { targets, system_prompt: systemPrompt, sampling_params: samplingParams },
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
          set({ ...MULTI_STREAMING_RESET, regeneratingParentId: null })
          refreshRhizomeSelectNewest(rhizomeId, nodeId, set)
        },
        (error) => {
          set({
            ...MULTI_STREAMING_RESET,
            regeneratingParentId: null,
            error: error instanceof Error ? error.message : String(error),
          })
        },
        ac.signal,
      )
    } catch (e) {
      set({
        ...MULTI_STREAMING_RESET,
        regeneratingParentId: null,
        error: String(e),
      })
    }
  },

  runPerturbation: async (nodeId, perturbations, provider, model, samplingParams, includeControl = true) => {
    const { currentRhizome } = get()
    if (!currentRhizome) return

    const rhizomeId = currentRhizome.rhizome_id
    const ac = new AbortController()
    set({
      error: null,
      _abortController: ac,
      perturbationState: {
        active: true,
        step: 0,
        total: perturbations.length + (includeControl ? 1 : 0),
        currentLabel: '',
        stepContents: {},
      },
    })

    try {
      await api.perturbStream(
        rhizomeId,
        nodeId,
        {
          perturbations,
          provider,
          model,
          sampling_params: samplingParams,
          include_control: includeControl,
        },
        (step, total, _type, label) => {
          set((state) => ({
            perturbationState: state.perturbationState
              ? { ...state.perturbationState, step, total, currentLabel: label, stepContents: { ...state.perturbationState.stepContents, [step - 1]: '' } }
              : null,
          }))
        },
        (text, stepIndex) => {
          set((state) => ({
            perturbationState: state.perturbationState
              ? {
                  ...state.perturbationState,
                  stepContents: {
                    ...state.perturbationState.stepContents,
                    [stepIndex]: (state.perturbationState.stepContents[stepIndex] ?? '') + text,
                  },
                }
              : null,
          }))
        },
        (_event) => {
          // Step completed
        },
        (_report) => {
          set({
            perturbationState: null,
            _abortController: null,
          })
          refreshRhizome(rhizomeId, set)
          // Refresh reports
          api.getPerturbationReports(rhizomeId).then((reports) => {
            set({ perturbationReports: reports })
          }).catch(() => {})
        },
        (error) => {
          set({
            perturbationState: null,
            _abortController: null,
            error: error.message,
          })
          refreshRhizome(rhizomeId, set)
        },
        ac.signal,
      )
    } catch (e) {
      set({
        perturbationState: null,
        _abortController: null,
        error: String(e),
      })
    }
  },

  fetchPerturbationReports: async () => {
    const { currentRhizome } = get()
    if (!currentRhizome) return
    try {
      const reports = await api.getPerturbationReports(currentRhizome.rhizome_id)
      set({ perturbationReports: reports })
    } catch {
      // ignore
    }
  },

  deletePerturbationReport: async (reportId) => {
    const { currentRhizome } = get()
    if (!currentRhizome) return
    try {
      await api.deletePerturbationReport(currentRhizome.rhizome_id, reportId)
      set((state) => ({
        perturbationReports: state.perturbationReports.filter(r => r.report_id !== reportId),
      }))
    } catch {
      // ignore
    }
  },
}))

// ---------------------------------------------------------------------------
// Selector hooks — subscribe to focused state slices via useShallow
// Actions are stable references and safe to select individually.
// ---------------------------------------------------------------------------

export const useRhizomeData = () => useRhizomeStore(useShallow(s => ({
  rhizomes: s.rhizomes,
  selectedRhizomeId: s.selectedRhizomeId,
  currentRhizome: s.currentRhizome,
  providers: s.providers,
  isLoading: s.isLoading,
  error: s.error,
})))

export const useStreamingState = () => useRhizomeStore(useShallow(s => ({
  isGenerating: s.isGenerating,
  streamingContent: s.streamingContent,
  streamingThinkingContent: s.streamingThinkingContent,
  streamingContents: s.streamingContents,
  streamingThinkingContents: s.streamingThinkingContents,
  streamingNodeIds: s.streamingNodeIds,
  streamingTotal: s.streamingTotal,
  activeStreamIndex: s.activeStreamIndex,
  regeneratingParentId: s.regeneratingParentId,
  generationError: s.generationError,
  stopGeneration: s.stopGeneration,
})))

export const useNavigation = () => useRhizomeStore(useShallow(s => ({
  branchSelections: s.branchSelections,
})))

export const useComparison = () => useRhizomeStore(useShallow(s => ({
  splitViewNodeId: s.splitViewNodeId,
  comparisonNodeId: s.comparisonNodeId,
  comparisonHoveredNodeId: s.comparisonHoveredNodeId,
  comparisonPickingMode: s.comparisonPickingMode,
  comparisonPickingSourceId: s.comparisonPickingSourceId,
  inspectedNodeId: s.inspectedNodeId,
})))

export const useDigressionState = () => useRhizomeStore(useShallow(s => ({
  digressionGroups: s.digressionGroups,
  groupSelectionMode: s.groupSelectionMode,
  selectedGroupNodeIds: s.selectedGroupNodeIds,
})))

export const useResearchMetadata = () => useRhizomeStore(useShallow(s => ({
  bookmarks: s.bookmarks,
  bookmarksLoading: s.bookmarksLoading,
  exclusions: s.exclusions,
  editHistoryCache: s.editHistoryCache,
  selectedEditVersion: s.selectedEditVersion,
  nodeAnnotations: s.nodeAnnotations,
  nodeNotes: s.nodeNotes,
  rhizomeNotes: s.rhizomeNotes,
  rhizomeAnnotations: s.rhizomeAnnotations,
  rhizomeSummaries: s.rhizomeSummaries,
  perturbationReports: s.perturbationReports,
  researchPaneTab: s.researchPaneTab,
  taxonomy: s.taxonomy,
})))

export const useRightPane = () => useRhizomeStore(useShallow(s => ({
  rightPaneMode: s.rightPaneMode,
  canvasOpen: s.canvasOpen,
  libraryOpen: s.libraryOpen,
})))
