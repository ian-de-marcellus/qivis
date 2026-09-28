/** Zustand store for Qivis app state. */

import { create } from 'zustand'
import { useShallow } from 'zustand/react/shallow'
import * as api from '../api/client.ts'
import type {
  MessageStopEvent,
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
  PerturbationReportResponse,
  ModelEntry,
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
  models: ModelEntry[]
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
  showNodeIds: boolean
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
  /** Refresh the rhizome and follow the path to a node just created elsewhere */
  showNode: (nodeId: string) => Promise<void>
  /** Steering a reply token by token: the node it answers ('' for a first turn) */
  steerTarget: string | null
  openSteer: (parentId: string) => void
  closeSteer: () => void
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
    systemPrompt?: string,
    samplingParams?: SamplingParams,
    generationMode?: 'chat' | 'completion',
  ) => Promise<void>
  generateCrossModel: (
    nodeId: string,
    targets: CrossModelTarget[],
    systemPrompt?: string,
    samplingParams?: SamplingParams,
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

// Refreshes land only if the user is still looking at that rhizome: a slow
// response must not replace a rhizome they've since switched to.
function refreshRhizome(rhizomeId: string, set: SetFn) {
  api.getRhizome(rhizomeId).then((rhizome) =>
    set((state) => (state.selectedRhizomeId === rhizomeId ? { currentRhizome: rhizome } : {})),
  )
  api.listRhizomes().then((rhizomes) => set({ rhizomes }))
}

/** Refresh, and follow the newest child of parentNodeId ('' is the root key). */
function refreshRhizomeSelectNewest(
  rhizomeId: string,
  parentNodeId: string,
  set: SetFn,
) {
  api.getRhizome(rhizomeId).then((rhizome) => {
    const newChildren = rhizome.nodes.filter(
      (nd) => (nd.parent_id ?? '') === parentNodeId,
    )
    const newest = newChildren[newChildren.length - 1]
    set((state) => {
      if (state.selectedRhizomeId !== rhizomeId) return {}
      return newest
        ? {
            currentRhizome: rhizome,
            branchSelections: { ...state.branchSelections, [parentNodeId]: newest.node_id },
          }
        : { currentRhizome: rhizome }
    })
  })
  api.listRhizomes().then((rhizomes) => set({ rhizomes }))
}

/** Wait for the reply a stopped stream is stored as, then show it. */
async function followStoppedReply(
  rhizomeId: string, parentNodeId: string, known: Set<string>, set: SetFn,
) {
  for (let attempt = 0; attempt < 12; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 250))
    const rhizome = await api.getRhizome(rhizomeId).catch(() => null)
    if (rhizome?.nodes.some((n) => (n.parent_id ?? '') === parentNodeId && !known.has(n.node_id))) break
  }
  refreshRhizomeSelectNewest(rhizomeId, parentNodeId, set)
}

const errorMessage = (e: unknown) => (e instanceof Error ? e.message : String(e))

/** Streaming-state updates shared by every kind of generation. */
function streamCallbacks(set: SetFn) {
  return {
    delta: (text: string) =>
      set((s) => ({ streamingContent: s.streamingContent + text })),
    thinking: (text: string) =>
      set((s) => ({ streamingThinkingContent: s.streamingThinkingContent + text })),
    multiDelta: (text: string, idx: number) =>
      set((s) => ({
        streamingContents: { ...s.streamingContents, [idx]: (s.streamingContents[idx] ?? '') + text },
      })),
    multiThinking: (text: string, idx: number) =>
      set((s) => ({
        streamingThinkingContents: {
          ...s.streamingThinkingContents,
          [idx]: (s.streamingThinkingContents[idx] ?? '') + text,
        },
      })),
    multiStop: (event: MessageStopEvent) => {
      if (event.node_id != null && event.completion_index != null) {
        set((s) => ({
          streamingNodeIds: { ...s.streamingNodeIds, [event.completion_index!]: event.node_id! },
        }))
      }
    },
    // One completion of several failed: say so in its column, let the others finish
    multiError: (error: Error, idx: number) =>
      set((s) => ({
        streamingContents: {
          ...s.streamingContents,
          [idx]: `${s.streamingContents[idx] ?? ''}\n[failed: ${error.message}]`,
        },
      })),
  }
}

interface GenerationRun {
  rhizomeId: string
  /** The node being answered ('' for a root generation) */
  parentId: string
  req: GenerateRequest
  /** Show the answer as replacing the parent's current reply (regenerate) */
  regenerating?: boolean
  /** What the reply starts with before any tokens arrive (prefill) */
  initialContent?: string
}

/**
 * Run a generation -- one or n, streamed or not -- with the same streaming
 * state, error reporting, and branch selection for every caller. When it
 * ends, the view follows the newest reply.
 */
async function runGeneration(set: SetFn, run: GenerationRun): Promise<void> {
  const { rhizomeId, parentId, req } = run
  const n = req.n ?? 1
  const stream = req.stream !== false
  const ac = new AbortController()
  const running = {
    isGenerating: true,
    _abortController: ac,
    streamingParentId: parentId,
    regeneratingParentId: run.regenerating ? parentId : null,
  }
  set(stream && n > 1
    ? { ...MULTI_STREAMING_RESET, ...running, streamingTotal: n }
    : { ...MULTI_STREAMING_RESET, ...running, streamingContent: run.initialContent ?? '' })

  const done = () => {
    set({ ...MULTI_STREAMING_RESET, regeneratingParentId: null })
    refreshRhizomeSelectNewest(rhizomeId, parentId, set)
  }
  const fail = (error: unknown) => set({
    ...MULTI_STREAMING_RESET,
    regeneratingParentId: null,
    error: errorMessage(error),
    generationError: {
      parentNodeId: parentId,
      provider: req.provider ?? 'anthropic',
      model: req.model ?? null,
      systemPrompt: req.system_prompt ?? null,
      errorMessage: errorMessage(error),
    },
  })
  const cb = streamCallbacks(set)

  try {
    if (stream && n > 1) {
      await api.generateMultiStream(
        rhizomeId, parentId, req, cb.multiDelta, cb.multiStop, done,
        (error, idx) => (idx === undefined ? fail(error) : cb.multiError(error, idx)),
        cb.multiThinking, ac.signal,
      )
    } else if (stream) {
      await api.generateStream(
        rhizomeId, parentId, { ...req, stream: true }, cb.delta, done, fail, cb.thinking, ac.signal,
      )
    } else {
      await api.generate(rhizomeId, parentId, { ...req, n })
      done()
    }
  } catch (e) {
    fail(e)
  }
}

/** Add a user turn under parentId (the active path's leaf, or a fork point), shown at once. */
async function addUserTurn(
  set: SetFn,
  rhizomeId: string,
  parentId: string | undefined,
  content: string,
  { follow }: { follow: boolean },
): Promise<NodeResponse> {
  const userNode = await api.createNode(rhizomeId, { content, role: 'user', parent_id: parentId || undefined })
  set((state) => ({
    currentRhizome: state.currentRhizome
      ? { ...state.currentRhizome, nodes: [...state.currentRhizome.nodes, userNode] }
      : null,
    ...(follow && {
      branchSelections: { ...state.branchSelections, [parentId ?? '']: userNode.node_id },
    }),
  }))
  return userNode
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
  models: [],
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
  // App-level display preference, remembered across reloads
  showNodeIds: (() => { try { return localStorage.getItem('qivis-show-node-ids') === '1' } catch { return false } })(),
  searchQuery: '',
  searchResults: [],
  searchLoading: false,
  scrollToNodeId: null,
  replayState: null,
  steerTarget: null,
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

    // Clear all streaming state (an aborted stream reports nothing, so a
    // running replay ends here too)
    set({
      ...MULTI_STREAMING_RESET,
      regeneratingParentId: null,
      replayState: null,
    })

    const rhizomeId = currentRhizome?.rhizome_id
    // streamingParentId is '' for a root generation, so check null explicitly
    if (!rhizomeId || streamingParentId === null) {
      if (rhizomeId) refreshRhizome(rhizomeId, set)
      return
    }

    // Streams stopped part-way: the server stores what each said so far,
    // with its record, once it sees the disconnect
    const stoppedPartWay = streamingTotal > 0
      ? Object.entries(streamingContents).some(([i, text]) => !streamingNodeIds[Number(i)] && text.trim())
      : streamingContent.trim() !== ''
    if (!stoppedPartWay) {
      refreshRhizome(rhizomeId, set)
      return
    }
    const known = new Set(currentRhizome?.nodes.map((n) => n.node_id))
    followStoppedReply(rhizomeId, streamingParentId, known, set)
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
      const [providers, models] = await Promise.all([api.getProviders(), api.getModels()])
      set({ providers, models })
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
    // Re-selecting the open rhizome keeps your place (branches, panels)
    if (get().selectedRhizomeId === rhizomeId && get().currentRhizome?.rhizome_id === rhizomeId) return
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
          perturbationReports: [],
    })
    // Everything below lands only if this rhizome is still the selected one
    const stillSelected = () => get().selectedRhizomeId === rhizomeId
    const load = <T,>(fetch: Promise<T>, apply: (data: T) => Partial<RhizomeStore>) =>
      fetch.then((data) => { if (stillSelected()) set(apply(data)) }).catch(() => {/* non-critical */})
    try {
      const rhizome = await api.getRhizome(rhizomeId)
      if (!stillSelected()) return
      set({ currentRhizome: rhizome, isLoading: false })
      load(api.getRhizomeBookmarks(rhizomeId), (bookmarks) => ({ bookmarks }))
      load(api.getExclusions(rhizomeId), (exclusions) => ({ exclusions }))
      load(api.getDigressionGroups(rhizomeId), (digressionGroups) => ({ digressionGroups }))
      load(api.getRhizomeNotes(rhizomeId), (rhizomeNotes) => ({ rhizomeNotes }))
      load(api.getRhizomeAnnotations(rhizomeId), (rhizomeAnnotations) => ({ rhizomeAnnotations }))
      load(api.getRhizomeSummaries(rhizomeId), (rhizomeSummaries) => ({ rhizomeSummaries }))
      load(api.getPerturbationReports(rhizomeId), (perturbationReports) => ({ perturbationReports }))
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
      const rhizome = await api.createRhizome({
        title,
        default_system_prompt: opts?.systemPrompt,
        default_provider: opts?.defaultProvider,
        default_model: opts?.defaultModel,
        metadata: opts?.metadata,
      })
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
      const activePath = getActivePath(currentRhizome.nodes, branchSelections)
      const userNode = await addUserTurn(
        set, rhizomeId, activePath[activePath.length - 1]?.node_id, content, { follow: false },
      )
      // Branch-local defaults: the branch's last model, else the rhizome's
      const lastAssistant = [...activePath].reverse().find((n) => n.role === 'assistant')
      const provider = lastAssistant?.provider ?? currentRhizome.default_provider
      const model = lastAssistant?.model ?? currentRhizome.default_model
      await runGeneration(set, {
        rhizomeId,
        parentId: userNode.node_id,
        req: {
          ...(provider ? { provider } : {}),
          ...(model ? { model } : {}),
          ...(systemPromptOverride != null ? { system_prompt: systemPromptOverride } : {}),
          stream: currentRhizome.metadata?.stream_responses !== false,
        },
      })
    } catch (e) {
      set({ ...STREAMING_RESET, error: String(e) })
    }
  },

  sendMessageOnly: async (content: string) => {
    const { currentRhizome, branchSelections } = get()
    if (!currentRhizome) return
    set({ error: null })
    try {
      const activePath = getActivePath(currentRhizome.nodes, branchSelections)
      await addUserTurn(
        set, currentRhizome.rhizome_id, activePath[activePath.length - 1]?.node_id, content,
        { follow: false },
      )
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

  openSteer: (parentId: string) => set({ steerTarget: parentId }),
  closeSteer: () => set({ steerTarget: null }),

  showNode: async (nodeId: string) => {
    const { currentRhizome } = get()
    if (!currentRhizome) return
    const rhizome = await api.getRhizome(currentRhizome.rhizome_id)
    if (get().selectedRhizomeId !== rhizome.rhizome_id) return
    set({ currentRhizome: rhizome })
    get().navigateToNode(nodeId)
    api.listRhizomes().then((rhizomes) => set({ rhizomes })).catch(() => {})
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
      // A new user turn beside the existing ones, and the view follows it
      const userNode = await addUserTurn(set, rhizomeId, parentId, content, { follow: true })
      await runGeneration(set, { rhizomeId, parentId: userNode.node_id, req: overrides })
    } catch (e) {
      set({ ...STREAMING_RESET, error: String(e) })
    }
  },

  regenerate: async (parentNodeId: string, overrides: GenerateRequest) => {
    const { currentRhizome } = get()
    if (!currentRhizome) return
    set({ error: null, generationError: null })
    await runGeneration(set, {
      rhizomeId: currentRhizome.rhizome_id,
      parentId: parentNodeId,
      req: overrides,
      regenerating: true,
    })
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
    set({ error: null, generationError: null })
    await runGeneration(set, {
      rhizomeId: currentRhizome.rhizome_id,
      parentId,
      req: { ...overrides, prefill_content: prefillContent },
      initialContent: prefillContent,
    })
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

  startReplay: async (pathNodeIds, provider, model, systemPrompt, samplingParams, generationMode) => {
    const { currentRhizome } = get()
    if (!currentRhizome) return

    const rhizomeId = currentRhizome.rhizome_id
    const ac = new AbortController()
    set({
      error: null,
      isGenerating: true,
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
          system_prompt: systemPrompt,
          sampling_params: samplingParams,
          generation_mode: generationMode,
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
        (createdNodeIds) => {
          set({
            replayState: null,
            isGenerating: false,
            _abortController: null,
          })
          // Faithful replay adds a sibling at each assistant turn. Siblings
          // are leaves, so select only the deepest one: the path keeps the
          // original conversation and ends on the new model's last answer,
          // and earlier turns can be paged via their sibling arrows.
          api.getRhizome(rhizomeId).then((rhizome) => {
            const lastId = createdNodeIds[createdNodeIds.length - 1]
            const last = rhizome.nodes.find((n) => n.node_id === lastId)
            set((state) => (state.selectedRhizomeId !== rhizomeId ? {} : {
              currentRhizome: rhizome,
              branchSelections: last
                ? { ...state.branchSelections, [last.parent_id ?? '']: last.node_id }
                : state.branchSelections,
            }))
          })
        },
        (error) => {
          set({
            replayState: null,
            isGenerating: false,
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
        isGenerating: false,
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
    const cb = streamCallbacks(set)
    const fail = (error: unknown) =>
      set({ ...MULTI_STREAMING_RESET, regeneratingParentId: null, error: errorMessage(error) })
    try {
      await api.generateCrossStream(
        rhizomeId,
        nodeId,
        { targets, system_prompt: systemPrompt, sampling_params: samplingParams },
        cb.multiDelta,
        cb.multiStop,
        () => {
          set({ ...MULTI_STREAMING_RESET, regeneratingParentId: null })
          refreshRhizomeSelectNewest(rhizomeId, nodeId, set)
        },
        (error, idx) => (idx === undefined ? fail(error) : cb.multiError(error, idx)),
        ac.signal,
      )
    } catch (e) {
      fail(e)
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
  models: s.models,
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
