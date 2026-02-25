/** Typed API client for Qivis backend. */

import type {
  AddAnnotationRequest,
  AnnotationResponse,
  BookmarkResponse,
  CreateBookmarkRequest,
  CreateDigressionGroupRequest,
  CreateNodeRequest,
  CreateNoteRequest,
  CreateSummaryRequest,
  CreateRhizomeRequest,
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
  ProviderInfo,
  SearchResponse,
  SummaryResponse,
  TaxonomyResponse,
  RhizomeDetail,
  RhizomeSummary,
} from './types.ts'

type SSEParsed = Record<string, unknown>

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

export function getRhizomePaths(
  rhizomeId: string,
): Promise<{ paths: string[][] }> {
  return request(`/rhizomes/${rhizomeId}/paths`)
}

// -- Generation (non-streaming) --

export function generate(
  rhizomeId: string,
  nodeId: string,
  req: GenerateRequest = {},
): Promise<NodeResponse> {
  return request(`/rhizomes/${rhizomeId}/nodes/${nodeId}/generate`, {
    method: 'POST',
    body: JSON.stringify({ ...req, stream: false }),
  })
}

// -- Generation (streaming via SSE) --

export async function generateStream(
  rhizomeId: string,
  nodeId: string,
  req: GenerateRequest,
  onDelta: (text: string) => void,
  onComplete: (event: MessageStopEvent) => void,
  onError?: (error: Error) => void,
  onThinkingDelta?: (thinking: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  try {
    const res = await fetch(`${BASE}/rhizomes/${rhizomeId}/nodes/${nodeId}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...req, stream: true }),
      signal,
    })

    if (!res.ok) {
      const text = await res.text()
      const err = new Error(`API error ${res.status}: ${text}`)
      onError?.(err)
      return
    }

    const reader = res.body?.getReader()
    if (!reader) {
      onError?.(new Error('No response body'))
      return
    }

    const decoder = new TextDecoder()
    let buffer = ''

    let receivedComplete = false
    let receivedError = false

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        // Keep the last potentially incomplete line in the buffer
        buffer = lines.pop() ?? ''

        let currentEvent = ''
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7)
          } else if (line.startsWith('data: ')) {
            const data = line.slice(6)
            try {
              const parsed = JSON.parse(data) as Record<string, unknown>
              if (currentEvent === 'thinking_delta' && typeof parsed.thinking === 'string') {
                onThinkingDelta?.(parsed.thinking)
              } else if (currentEvent === 'text_delta' && typeof parsed.text === 'string') {
                onDelta(parsed.text)
              } else if (currentEvent === 'message_stop') {
                receivedComplete = true
                onComplete(parsed as unknown as MessageStopEvent)
              } else if (currentEvent === 'error') {
                receivedError = true
                onError?.(new Error(String(parsed.error ?? 'Unknown SSE error')))
              }
            } catch {
              // Skip malformed JSON lines
            }
          }
        }
      }
    } finally {
      reader.releaseLock()
    }

    // If stream ended without a complete or error event, something went wrong
    if (!receivedComplete && !receivedError) {
      onError?.(new Error('Stream ended unexpectedly without completing'))
    }
  } catch (err) {
    // User stopped generation — return silently
    if (err instanceof DOMException && err.name === 'AbortError') return
    throw err
  }
}

// -- Generation (multi-stream n>1 via SSE) --

export async function generateMultiStream(
  rhizomeId: string,
  nodeId: string,
  req: GenerateRequest,
  onDelta: (text: string, completionIndex: number) => void,
  onStreamComplete: (event: MessageStopEvent) => void,
  onAllComplete: () => void,
  onError?: (error: Error, completionIndex?: number) => void,
  onThinkingDelta?: (thinking: string, completionIndex: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  try {
    const res = await fetch(`${BASE}/rhizomes/${rhizomeId}/nodes/${nodeId}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...req, stream: true }),
      signal,
    })

    if (!res.ok) {
      const text = await res.text()
      const err = new Error(`API error ${res.status}: ${text}`)
      onError?.(err)
      return
    }

    const reader = res.body?.getReader()
    if (!reader) {
      onError?.(new Error('No response body'))
      return
    }

    const decoder = new TextDecoder()
    let buffer = ''

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        let currentEvent = ''
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7)
          } else if (line.startsWith('data: ')) {
            const data = line.slice(6)
            try {
              const parsed = JSON.parse(data) as SSEParsed
              if (currentEvent === 'thinking_delta' && typeof parsed.thinking === 'string') {
                onThinkingDelta?.(parsed.thinking, parsed.completion_index as number)
              } else if (currentEvent === 'text_delta' && typeof parsed.text === 'string') {
                onDelta(parsed.text, parsed.completion_index as number)
              } else if (currentEvent === 'message_stop') {
                onStreamComplete(parsed as unknown as MessageStopEvent)
              } else if (currentEvent === 'generation_complete') {
                onAllComplete()
              } else if (currentEvent === 'error') {
                const idx = typeof parsed.completion_index === 'number'
                  ? parsed.completion_index
                  : undefined
                onError?.(new Error(String(parsed.error ?? 'Unknown SSE error')), idx)
              }
            } catch {
              // Skip malformed JSON lines
            }
          }
        }
      }
    } finally {
      reader.releaseLock()
    }
  } catch (err) {
    // User stopped generation — return silently
    if (err instanceof DOMException && err.name === 'AbortError') return
    throw err
  }
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
