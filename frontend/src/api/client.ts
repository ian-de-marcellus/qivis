/** Typed API client for Qivis backend. */

import type {
  AddAnnotationRequest,
  AnnotationResponse,
  BookmarkResponse,
  CreateBookmarkRequest,
  CreateNodeRequest,
  CreateTreeRequest,
  EditHistoryResponse,
  GenerateRequest,
  InterventionTimelineResponse,
  MessageStopEvent,
  NodeResponse,
  PatchTreeRequest,
  ProviderInfo,
  TaxonomyResponse,
  TreeDetail,
  TreeSummary,
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

// -- Tree CRUD --

export function listTrees(): Promise<TreeSummary[]> {
  return request('/trees')
}

export function createTree(req: CreateTreeRequest): Promise<TreeDetail> {
  return request('/trees', {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

export function getTree(treeId: string): Promise<TreeDetail> {
  return request(`/trees/${treeId}`)
}

export function updateTree(treeId: string, req: PatchTreeRequest): Promise<TreeDetail> {
  return request(`/trees/${treeId}`, {
    method: 'PATCH',
    body: JSON.stringify(req),
  })
}

// -- Node CRUD --

export function createNode(
  treeId: string,
  req: CreateNodeRequest,
): Promise<NodeResponse> {
  return request(`/trees/${treeId}/nodes`, {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

export function editNodeContent(
  treeId: string,
  nodeId: string,
  editedContent: string | null,
): Promise<NodeResponse> {
  return request(`/trees/${treeId}/nodes/${nodeId}/content`, {
    method: 'PATCH',
    body: JSON.stringify({ edited_content: editedContent }),
  })
}

// -- Edit history --

export function getEditHistory(
  treeId: string,
  nodeId: string,
): Promise<EditHistoryResponse> {
  return request(`/trees/${treeId}/nodes/${nodeId}/edit-history`)
}

// -- Intervention timeline --

export function getInterventions(treeId: string): Promise<InterventionTimelineResponse> {
  return request(`/trees/${treeId}/interventions`)
}

// -- Annotations --

export function addAnnotation(
  treeId: string,
  nodeId: string,
  req: AddAnnotationRequest,
): Promise<AnnotationResponse> {
  return request(`/trees/${treeId}/nodes/${nodeId}/annotations`, {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

export function getNodeAnnotations(
  treeId: string,
  nodeId: string,
): Promise<AnnotationResponse[]> {
  return request(`/trees/${treeId}/nodes/${nodeId}/annotations`)
}

export function removeAnnotation(
  treeId: string,
  annotationId: string,
): Promise<void> {
  return request(`/trees/${treeId}/annotations/${annotationId}`, {
    method: 'DELETE',
  })
}

export function getTreeTaxonomy(treeId: string): Promise<TaxonomyResponse> {
  return request(`/trees/${treeId}/taxonomy`)
}

// -- Bookmarks --

export function addBookmark(
  treeId: string,
  nodeId: string,
  req: CreateBookmarkRequest,
): Promise<BookmarkResponse> {
  return request(`/trees/${treeId}/nodes/${nodeId}/bookmarks`, {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

export function getTreeBookmarks(
  treeId: string,
  query?: string,
): Promise<BookmarkResponse[]> {
  const params = query ? `?q=${encodeURIComponent(query)}` : ''
  return request(`/trees/${treeId}/bookmarks${params}`)
}

export function removeBookmark(
  treeId: string,
  bookmarkId: string,
): Promise<void> {
  return request(`/trees/${treeId}/bookmarks/${bookmarkId}`, {
    method: 'DELETE',
  })
}

export function summarizeBookmark(
  treeId: string,
  bookmarkId: string,
): Promise<BookmarkResponse> {
  return request(`/trees/${treeId}/bookmarks/${bookmarkId}/summarize`, {
    method: 'POST',
  })
}

// -- Generation (non-streaming) --

export function generate(
  treeId: string,
  nodeId: string,
  req: GenerateRequest = {},
): Promise<NodeResponse> {
  return request(`/trees/${treeId}/nodes/${nodeId}/generate`, {
    method: 'POST',
    body: JSON.stringify({ ...req, stream: false }),
  })
}

// -- Generation (streaming via SSE) --

export async function generateStream(
  treeId: string,
  nodeId: string,
  req: GenerateRequest,
  onDelta: (text: string) => void,
  onComplete: (event: MessageStopEvent) => void,
  onError?: (error: Error) => void,
  onThinkingDelta?: (thinking: string) => void,
): Promise<void> {
  const res = await fetch(`${BASE}/trees/${treeId}/nodes/${nodeId}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...req, stream: true }),
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
}

// -- Generation (multi-stream n>1 via SSE) --

export async function generateMultiStream(
  treeId: string,
  nodeId: string,
  req: GenerateRequest,
  onDelta: (text: string, completionIndex: number) => void,
  onStreamComplete: (event: MessageStopEvent) => void,
  onAllComplete: () => void,
  onError?: (error: Error, completionIndex?: number) => void,
  onThinkingDelta?: (thinking: string, completionIndex: number) => void,
): Promise<void> {
  const res = await fetch(`${BASE}/trees/${treeId}/nodes/${nodeId}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...req, stream: true }),
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
}
