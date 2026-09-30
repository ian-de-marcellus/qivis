/** Typed API client for Qivis backend. */

import { postSSE, sseError, type SSEMessage } from './sse.ts'
import type {
  AddAnnotationRequest,
  NameDiscovery,
  NameStudy,
  NameStudySpec,
  NameStudySummary,
  Probe,
  ModelEntry,
  AnnotationResponse,
  BookmarkResponse,
  CreateBookmarkRequest,
  CreateDigressionGroupRequest,
  CreateNodeRequest,
  CreateNoteRequest,
  CreateSummaryRequest,
  CreateRhizomeRequest,
  CrossModelGenerateRequest,
  DigressionGroupResponse,
  EditHistoryResponse,
  GenerateRequest,
  ImportPreviewResponse,
  ImportResponse,
  InterventionTimelineResponse,
  InterventionTypeInfo,
  MergePreviewResponse,
  MergeResult,
  MessageStopEvent,
  NodeExclusionResponse,
  NodeResponse,
  NoteResponse,
  PatchRhizomeRequest,
  PerturbationReportResponse,
  ProviderInfo,
  ReplayRequest,
  SearchResponse,
  SummaryResponse,
  TaxonomyResponse,
  RhizomeDetail,
  RhizomeSummary,
  SteeringSession,
  TokenCandidate,
} from './types.ts'

/** Which completion an event in a fan-out stream (n>1, cross-model) belongs to */
function completionIndex({ data }: SSEMessage): number | undefined {
  return typeof data.completion_index === 'number' ? data.completion_index : undefined
}

/** A fan-out stream ends with generation_complete, or an error not tied to one completion */
function isFanOutEnd(message: SSEMessage): boolean {
  return message.event === 'generation_complete'
    || (message.event === 'error' && completionIndex(message) === undefined)
}

const BASE = '/api'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`API error ${res.status}: ${text}`)
  }
  if (res.status === 204) {
    return undefined as T
  }
  return res.json() as Promise<T>
}

// -- Providers --

export function getProviders(): Promise<ProviderInfo[]> {
  return request('/providers')
}

export function getModels(): Promise<ModelEntry[]> {
  return request('/models')
}

export function getInterventionTypes(): Promise<InterventionTypeInfo[]> {
  return request('/intervention-types')
}

// -- Rhizome CRUD --

export function listRhizomes(includeArchived?: boolean): Promise<RhizomeSummary[]> {
  const params = includeArchived ? '?include_archived=true' : ''
  return request(`/rhizomes${params}`)
}

export function archiveRhizome(rhizomeId: string): Promise<RhizomeDetail> {
  return request(`/rhizomes/${rhizomeId}/archive`, { method: 'POST' })
}

export function unarchiveRhizome(rhizomeId: string): Promise<RhizomeDetail> {
  return request(`/rhizomes/${rhizomeId}/unarchive`, { method: 'POST' })
}

export function createRhizome(req: CreateRhizomeRequest): Promise<RhizomeDetail> {
  return request('/rhizomes', {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

export function getRhizome(rhizomeId: string): Promise<RhizomeDetail> {
  return request(`/rhizomes/${rhizomeId}`)
}

export function updateRhizome(rhizomeId: string, req: PatchRhizomeRequest): Promise<RhizomeDetail> {
  return request(`/rhizomes/${rhizomeId}`, {
    method: 'PATCH',
    body: JSON.stringify(req),
  })
}

// -- Node CRUD --

export function createNode(
  rhizomeId: string,
  req: CreateNodeRequest,
): Promise<NodeResponse> {
  return request(`/rhizomes/${rhizomeId}/nodes`, {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

export function editNodeContent(
  rhizomeId: string,
  nodeId: string,
  editedContent: string | null,
): Promise<NodeResponse> {
  return request(`/rhizomes/${rhizomeId}/nodes/${nodeId}/content`, {
    method: 'PATCH',
    body: JSON.stringify({ edited_content: editedContent }),
  })
}

/** A new version of a generated reply that ends before token `keep`: the branch point for a token. */
export function cutNode(rhizomeId: string, nodeId: string, keep: number): Promise<NodeResponse> {
  return request(`/rhizomes/${rhizomeId}/nodes/${nodeId}/cut`, {
    method: 'POST',
    body: JSON.stringify({ keep }),
  })
}

// -- Edit history --

export function getEditHistory(
  rhizomeId: string,
  nodeId: string,
): Promise<EditHistoryResponse> {
  return request(`/rhizomes/${rhizomeId}/nodes/${nodeId}/edit-history`)
}

// -- Intervention timeline --

export function getInterventions(rhizomeId: string): Promise<InterventionTimelineResponse> {
  return request(`/rhizomes/${rhizomeId}/interventions`)
}

// -- Annotations --

export function addAnnotation(
  rhizomeId: string,
  nodeId: string,
  req: AddAnnotationRequest,
): Promise<AnnotationResponse> {
  return request(`/rhizomes/${rhizomeId}/nodes/${nodeId}/annotations`, {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

export function getNodeAnnotations(
  rhizomeId: string,
  nodeId: string,
): Promise<AnnotationResponse[]> {
  return request(`/rhizomes/${rhizomeId}/nodes/${nodeId}/annotations`)
}

export function removeAnnotation(
  rhizomeId: string,
  annotationId: string,
): Promise<void> {
  return request(`/rhizomes/${rhizomeId}/annotations/${annotationId}`, {
    method: 'DELETE',
  })
}

export function getRhizomeTaxonomy(rhizomeId: string): Promise<TaxonomyResponse> {
  return request(`/rhizomes/${rhizomeId}/taxonomy`)
}

// -- Notes --

export function addNote(
  rhizomeId: string,
  nodeId: string,
  req: CreateNoteRequest,
): Promise<NoteResponse> {
  return request(`/rhizomes/${rhizomeId}/nodes/${nodeId}/notes`, {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

export function getNodeNotes(
  rhizomeId: string,
  nodeId: string,
): Promise<NoteResponse[]> {
  return request(`/rhizomes/${rhizomeId}/nodes/${nodeId}/notes`)
}

export function getRhizomeNotes(
  rhizomeId: string,
  query?: string,
): Promise<NoteResponse[]> {
  const params = query ? `?q=${encodeURIComponent(query)}` : ''
  return request(`/rhizomes/${rhizomeId}/notes${params}`)
}

export function removeNote(
  rhizomeId: string,
  noteId: string,
): Promise<void> {
  return request(`/rhizomes/${rhizomeId}/notes/${noteId}`, {
    method: 'DELETE',
  })
}

export function getRhizomeAnnotations(
  rhizomeId: string,
): Promise<AnnotationResponse[]> {
  return request(`/rhizomes/${rhizomeId}/annotations`)
}

// -- Bookmarks --

export function addBookmark(
  rhizomeId: string,
  nodeId: string,
  req: CreateBookmarkRequest,
): Promise<BookmarkResponse> {
  return request(`/rhizomes/${rhizomeId}/nodes/${nodeId}/bookmarks`, {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

export function getRhizomeBookmarks(
  rhizomeId: string,
  query?: string,
): Promise<BookmarkResponse[]> {
  const params = query ? `?q=${encodeURIComponent(query)}` : ''
  return request(`/rhizomes/${rhizomeId}/bookmarks${params}`)
}

export function removeBookmark(
  rhizomeId: string,
  bookmarkId: string,
): Promise<void> {
  return request(`/rhizomes/${rhizomeId}/bookmarks/${bookmarkId}`, {
    method: 'DELETE',
  })
}

export function summarizeBookmark(
  rhizomeId: string,
  bookmarkId: string,
): Promise<BookmarkResponse> {
  return request(`/rhizomes/${rhizomeId}/bookmarks/${bookmarkId}/summarize`, {
    method: 'POST',
  })
}

// -- Context exclusion --

export function excludeNode(
  rhizomeId: string,
  nodeId: string,
  scopeNodeId: string,
  reason?: string,
): Promise<NodeExclusionResponse> {
  return request(`/rhizomes/${rhizomeId}/nodes/${nodeId}/exclude`, {
    method: 'POST',
    body: JSON.stringify({ scope_node_id: scopeNodeId, reason }),
  })
}

export function includeNode(
  rhizomeId: string,
  nodeId: string,
  scopeNodeId: string,
): Promise<void> {
  return request(`/rhizomes/${rhizomeId}/nodes/${nodeId}/include`, {
    method: 'POST',
    body: JSON.stringify({ scope_node_id: scopeNodeId }),
  })
}

export function getExclusions(rhizomeId: string): Promise<NodeExclusionResponse[]> {
  return request(`/rhizomes/${rhizomeId}/exclusions`)
}

// -- Anchors --

export function toggleAnchor(
  rhizomeId: string,
  nodeId: string,
): Promise<{ is_anchored: boolean }> {
  return request(`/rhizomes/${rhizomeId}/nodes/${nodeId}/anchor`, {
    method: 'POST',
  })
}

export function bulkAnchor(
  rhizomeId: string,
  nodeIds: string[],
  anchor: boolean,
): Promise<{ changed: number; anchor: boolean }> {
  return request(`/rhizomes/${rhizomeId}/bulk-anchor`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ node_ids: nodeIds, anchor }),
  })
}

// -- Digression groups --

export function createDigressionGroup(
  rhizomeId: string,
  req: CreateDigressionGroupRequest,
): Promise<DigressionGroupResponse> {
  return request(`/rhizomes/${rhizomeId}/digression-groups`, {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

export function getDigressionGroups(rhizomeId: string): Promise<DigressionGroupResponse[]> {
  return request(`/rhizomes/${rhizomeId}/digression-groups`)
}

export function toggleDigressionGroup(
  rhizomeId: string,
  groupId: string,
  included: boolean,
): Promise<DigressionGroupResponse> {
  return request(`/rhizomes/${rhizomeId}/digression-groups/${groupId}/toggle`, {
    method: 'POST',
    body: JSON.stringify({ included }),
  })
}

export function deleteDigressionGroup(
  rhizomeId: string,
  groupId: string,
): Promise<void> {
  return request(`/rhizomes/${rhizomeId}/digression-groups/${groupId}`, {
    method: 'DELETE',
  })
}

// -- Export --

export async function exportRhizome(
  rhizomeId: string,
  format: 'json' | 'csv' = 'json',
  includeEvents = false,
): Promise<void> {
  const params = new URLSearchParams({ format })
  if (includeEvents) params.set('include_events', 'true')
  const res = await fetch(`${BASE}/rhizomes/${rhizomeId}/export?${params}`)
  if (!res.ok) throw new Error(`Export failed: ${res.status}`)

  const blob = await res.blob()
  const ext = format === 'csv' ? 'csv' : 'json'
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${rhizomeId}.${ext}`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

// -- Generation (non-streaming) --

/** Generate endpoint path. A null/empty nodeId is a root generation: the model speaks first. */
function generatePath(rhizomeId: string, nodeId: string | null): string {
  return nodeId
    ? `/rhizomes/${rhizomeId}/nodes/${nodeId}/generate`
    : `/rhizomes/${rhizomeId}/generate`
}

export function generate(
  rhizomeId: string,
  nodeId: string | null,
  req: GenerateRequest = {},
): Promise<NodeResponse> {
  return request(generatePath(rhizomeId, nodeId), {
    method: 'POST',
    body: JSON.stringify({ ...req, stream: false }),
  })
}

// -- Generation (streaming via SSE) --

export async function generateStream(
  rhizomeId: string,
  nodeId: string | null,
  req: GenerateRequest,
  onDelta: (text: string) => void,
  onComplete: (event: MessageStopEvent) => void,
  onError?: (error: Error) => void,
  onThinkingDelta?: (thinking: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  await postSSE(
    `${BASE}${generatePath(rhizomeId, nodeId)}`,
    { ...req, stream: true },
    ({ event, data }) => {
      if (event === 'thinking_delta' && typeof data.thinking === 'string') {
        onThinkingDelta?.(data.thinking)
      } else if (event === 'text_delta' && typeof data.text === 'string') {
        onDelta(data.text)
      } else if (event === 'message_stop') {
        onComplete(data as unknown as MessageStopEvent)
      } else if (event === 'error') {
        onError?.(sseError({ event, data }))
      }
    },
    ({ event }) => event === 'message_stop' || event === 'error',
    onError,
    signal,
  )
}

// -- Generation (multi-stream n>1 via SSE) --

export async function generateMultiStream(
  rhizomeId: string,
  nodeId: string | null,
  req: GenerateRequest,
  onDelta: (text: string, completionIndex: number) => void,
  onStreamComplete: (event: MessageStopEvent) => void,
  onAllComplete: () => void,
  onError?: (error: Error, completionIndex?: number) => void,
  onThinkingDelta?: (thinking: string, completionIndex: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  await postSSE(
    `${BASE}${generatePath(rhizomeId, nodeId)}`,
    { ...req, stream: true },
    (message) => {
      const { event, data } = message
      if (event === 'thinking_delta' && typeof data.thinking === 'string') {
        onThinkingDelta?.(data.thinking, data.completion_index as number)
      } else if (event === 'text_delta' && typeof data.text === 'string') {
        onDelta(data.text, data.completion_index as number)
      } else if (event === 'message_stop') {
        onStreamComplete(data as unknown as MessageStopEvent)
      } else if (event === 'generation_complete') {
        onAllComplete()
      } else if (event === 'error') {
        onError?.(sseError(message), completionIndex(message))
      }
    },
    isFanOutEnd,
    onError,
    signal,
  )
}

// -- Replay --

export async function replayStream(
  rhizomeId: string,
  req: ReplayRequest,
  onStep: (step: number, total: number, type: string, nodeId?: string) => void,
  onDelta: (text: string, stepIndex: number) => void,
  onStepComplete: (event: MessageStopEvent) => void,
  onComplete: (createdNodeIds: string[]) => void,
  onError?: (error: Error) => void,
  signal?: AbortSignal,
): Promise<void> {
  await postSSE(
    `${BASE}/rhizomes/${rhizomeId}/replay`,
    { ...req, stream: true },
    (message) => {
      const { event, data } = message
      if (event === 'replay_step') {
        onStep(
          data.step as number,
          data.total as number,
          data.type as string,
          data.node_id as string | undefined,
        )
      } else if (event === 'text_delta' && typeof data.text === 'string') {
        onDelta(data.text, data.completion_index as number)
      } else if (event === 'message_stop') {
        onStepComplete(data as unknown as MessageStopEvent)
      } else if (event === 'replay_complete') {
        onComplete(data.created_node_ids as string[])
      } else if (event === 'error') {
        onError?.(sseError(message))
      }
    },
    ({ event }) => event === 'replay_complete' || event === 'error',
    onError,
    signal,
  )
}

// -- Cross-model generation --

export async function generateCrossStream(
  rhizomeId: string,
  nodeId: string,
  req: CrossModelGenerateRequest,
  onDelta: (text: string, completionIndex: number) => void,
  onStreamComplete: (event: MessageStopEvent) => void,
  onAllComplete: () => void,
  onError?: (error: Error, completionIndex?: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  await postSSE(
    `${BASE}/rhizomes/${rhizomeId}/nodes/${nodeId}/generate-cross`,
    { ...req, stream: true },
    (message) => {
      const { event, data } = message
      if (event === 'text_delta' && typeof data.text === 'string') {
        onDelta(data.text, data.completion_index as number)
      } else if (event === 'message_stop') {
        onStreamComplete(data as unknown as MessageStopEvent)
      } else if (event === 'generation_complete') {
        onAllComplete()
      } else if (event === 'error') {
        onError?.(sseError(message), completionIndex(message))
      }
    },
    isFanOutEnd,
    onError,
    signal,
  )
}

// -- Perturbation experiments --

export function getPerturbationReports(rhizomeId: string): Promise<PerturbationReportResponse[]> {
  return request(`/rhizomes/${rhizomeId}/perturbation-reports`)
}

export function deletePerturbationReport(rhizomeId: string, reportId: string): Promise<void> {
  return request(`/rhizomes/${rhizomeId}/perturbation-reports/${reportId}`, {
    method: 'DELETE',
  })
}

// -- Search --

// -- Import --

export async function previewImport(file: File): Promise<ImportPreviewResponse> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`${BASE}/import/preview`, {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Import preview failed: ${res.status}: ${text}`)
  }
  return res.json()
}

export async function importConversations(
  file: File,
  options?: { format?: string; selected?: number[] },
): Promise<ImportResponse> {
  const params = new URLSearchParams()
  if (options?.format) params.set('format', options.format)
  if (options?.selected) params.set('selected', options.selected.join(','))
  const qs = params.toString() ? `?${params}` : ''
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`${BASE}/import${qs}`, {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Import failed: ${res.status}: ${text}`)
  }
  return res.json()
}

// -- Merge --

export async function previewMerge(rhizomeId: string, file: File): Promise<MergePreviewResponse> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`${BASE}/rhizomes/${rhizomeId}/merge/preview`, {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Merge preview failed: ${res.status}: ${text}`)
  }
  return res.json()
}

export async function executeMerge(
  rhizomeId: string,
  file: File,
  conversationIndex?: number,
): Promise<MergeResult> {
  const params = new URLSearchParams()
  if (conversationIndex != null) params.set('conversation_index', String(conversationIndex))
  const qs = params.toString() ? `?${params}` : ''
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`${BASE}/rhizomes/${rhizomeId}/merge${qs}`, {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Merge failed: ${res.status}: ${text}`)
  }
  return res.json()
}

// -- Summaries --

export function generateSummary(
  rhizomeId: string,
  nodeId: string,
  req: CreateSummaryRequest,
): Promise<SummaryResponse> {
  return request(`/rhizomes/${rhizomeId}/nodes/${nodeId}/summarize`, {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

export function getRhizomeSummaries(rhizomeId: string): Promise<SummaryResponse[]> {
  return request(`/rhizomes/${rhizomeId}/summaries`)
}

export function removeSummary(rhizomeId: string, summaryId: string): Promise<void> {
  return request(`/rhizomes/${rhizomeId}/summaries/${summaryId}`, {
    method: 'DELETE',
  })
}

// -- Search --

export function searchNodes(params: {
  q: string
  rhizome_ids?: string
  models?: string
  providers?: string
  roles?: string
  tags?: string
  date_from?: string
  date_to?: string
  limit?: number
}): Promise<SearchResponse> {
  const searchParams = new URLSearchParams()
  searchParams.set('q', params.q)
  if (params.rhizome_ids) searchParams.set('rhizome_ids', params.rhizome_ids)
  if (params.models) searchParams.set('models', params.models)
  if (params.providers) searchParams.set('providers', params.providers)
  if (params.roles) searchParams.set('roles', params.roles)
  if (params.tags) searchParams.set('tags', params.tags)
  if (params.date_from) searchParams.set('date_from', params.date_from)
  if (params.date_to) searchParams.set('date_to', params.date_to)
  if (params.limit != null) searchParams.set('limit', String(params.limit))
  return request(`/search?${searchParams.toString()}`)
}

// -- Steering --

export function startSteering(
  rhizomeId: string,
  nodeId: string | null,
  body: { provider: string; model?: string | null; system_prompt?: string | null },
): Promise<SteeringSession> {
  const path = nodeId ? `/rhizomes/${rhizomeId}/nodes/${nodeId}/steer` : `/rhizomes/${rhizomeId}/steer`
  return request(path, { method: 'POST', body: JSON.stringify(body) })
}

export function steerNext(sessionId: string, continuation: number[], k = 20): Promise<TokenCandidate[]> {
  return request(`/steer/${sessionId}/next`, {
    method: 'POST',
    body: JSON.stringify({ continuation, k }),
  })
}

export function steerTokenize(sessionId: string, text: string): Promise<{ id: number; token: string }[]> {
  return request(`/steer/${sessionId}/tokenize`, { method: 'POST', body: JSON.stringify({ text }) })
}

export function steerCommit(
  sessionId: string,
  tokenIds: number[],
  chosenBy: ('model' | 'researcher')[],
): Promise<NodeResponse> {
  return request(`/steer/${sessionId}/commit`, {
    method: 'POST',
    body: JSON.stringify({ token_ids: tokenIds, chosen_by: chosenBy }),
  })
}

export function steerDiscard(sessionId: string): Promise<void> {
  return request(`/steer/${sessionId}`, { method: 'DELETE' })
}

// -- Answer probes --

export function runProbe(
  rhizomeId: string,
  body: { node_id: string | null; provider: string; model?: string | null; n?: number; max_tokens?: number },
): Promise<Probe> {
  return request(`/rhizomes/${rhizomeId}/probes`, { method: 'POST', body: JSON.stringify(body) })
}

export function listProbes(rhizomeId: string): Promise<Probe[]> {
  return request(`/rhizomes/${rhizomeId}/probes`)
}

export function judgeProbe(rhizomeId: string, probeId: string): Promise<Probe> {
  return request(`/rhizomes/${rhizomeId}/probes/${probeId}/judge`, { method: 'POST' })
}

export function continueFromProbeSample(
  rhizomeId: string, probeId: string, index: number,
): Promise<NodeResponse> {
  return request(`/rhizomes/${rhizomeId}/probes/${probeId}/samples/${index}/continue`, { method: 'POST' })
}

// -- Name studies --

export function nameStudyDefaults(): Promise<{ frames: Record<string, string[]> }> {
  return request('/name-studies/defaults')
}

export function listNameStudies(): Promise<NameStudySummary[]> {
  return request('/name-studies')
}

export function getNameStudy(studyId: string): Promise<NameStudy> {
  return request(`/name-studies/${studyId}`)
}

export function createNameStudy(spec: NameStudySpec): Promise<NameStudy> {
  return request('/name-studies', { method: 'POST', body: JSON.stringify(spec) })
}

export function stopNameStudy(studyId: string): Promise<NameStudy> {
  return request(`/name-studies/${studyId}/stop`, { method: 'POST' })
}

export function resumeNameStudy(studyId: string): Promise<NameStudy> {
  return request(`/name-studies/${studyId}/resume`, { method: 'POST' })
}

export function extendNameStudy(studyId: string, names: string[]): Promise<NameStudy> {
  return request(`/name-studies/${studyId}/extend`, { method: 'POST', body: JSON.stringify({ names }) })
}

export function listNameDiscoveries(): Promise<NameDiscovery[]> {
  return request('/name-studies/discoveries')
}

export function getNameDiscovery(id: string): Promise<NameDiscovery> {
  return request(`/name-studies/discoveries/${id}`)
}

export function createNameDiscovery(spec: {
  title: string; model: string; pronoun: string; study_id: string; failure_study_ids: string[]
  weights: { ai: number; gender: number; character: number }; beam?: number; depth?: number
  alpha?: number; top?: number
}): Promise<NameDiscovery> {
  return request('/name-studies/discoveries', { method: 'POST', body: JSON.stringify(spec) })
}

/** Names never to shortlist: taken, as references, by AI products and the like. */
export function getExcludedNames(): Promise<{ names: string[] }> {
  return request('/name-studies/excluded')
}

export function setExcludedNames(names: string[]): Promise<{ names: string[] }> {
  return request('/name-studies/excluded', { method: 'PUT', body: JSON.stringify({ names }) })
}
