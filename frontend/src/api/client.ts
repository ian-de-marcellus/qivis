/** Typed API client for Qivis backend. */

import type {
  CreateNodeRequest,
  CreateTreeRequest,
  GenerateRequest,
  MessageStopEvent,
  NodeResponse,
  ProviderInfo,
  TreeDetail,
  TreeSummary,
} from './types.ts'

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
            if (currentEvent === 'text_delta' && typeof parsed.text === 'string') {
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
