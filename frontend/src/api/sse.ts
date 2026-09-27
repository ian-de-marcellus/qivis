/**
 * Server-sent events over a POST request.
 *
 * The parser follows the SSE framing (fields accumulate until a blank line),
 * so an event split across network chunks arrives whole: an `event:` line at
 * the end of one chunk still names the `data:` line at the start of the next.
 */

export interface SSEMessage {
  event: string
  data: Record<string, unknown>
}

export class SSEParser {
  private buffer = ''
  private event = ''
  private data: string[] = []

  /** Feed decoded text as it arrives; returns the events it completed. */
  feed(text: string): SSEMessage[] {
    this.buffer += text
    const out: SSEMessage[] = []
    let nl: number
    while ((nl = this.buffer.indexOf('\n')) >= 0) {
      let line = this.buffer.slice(0, nl)
      this.buffer = this.buffer.slice(nl + 1)
      if (line.endsWith('\r')) line = line.slice(0, -1)

      if (line === '') {
        const message = this.dispatch()
        if (message) out.push(message)
        continue
      }
      if (line.startsWith(':')) continue // comment / keep-alive

      const colon = line.indexOf(':')
      const field = colon < 0 ? line : line.slice(0, colon)
      let value = colon < 0 ? '' : line.slice(colon + 1)
      if (value.startsWith(' ')) value = value.slice(1)
      if (field === 'event') this.event = value
      else if (field === 'data') this.data.push(value)
    }
    return out
  }

  /** The stream ended: complete any event left without its closing blank line. */
  end(): SSEMessage[] {
    const rest = this.buffer ? this.feed('\n') : []
    const last = this.dispatch()
    return last ? [...rest, last] : rest
  }

  private dispatch(): SSEMessage | null {
    const event = this.event || 'message'
    const raw = this.data.join('\n')
    this.event = ''
    this.data = []
    if (!raw) return null
    try {
      const data = JSON.parse(raw) as unknown
      if (data && typeof data === 'object') return { event, data: data as Record<string, unknown> }
    } catch {
      // Not JSON: nothing our endpoints send, so skip it
    }
    return null
  }
}

/**
 * POST `body` and deliver each event to `onMessage`.
 *
 * Reports failures through `onError`: a non-OK response, a missing body, or a
 * stream that ends before any event `isTerminal` accepts (so callers never
 * wait forever on a dropped connection). A user abort returns silently.
 */
export async function postSSE(
  url: string,
  body: unknown,
  onMessage: (message: SSEMessage) => void,
  isTerminal: (message: SSEMessage) => boolean,
  onError?: (error: Error) => void,
  signal?: AbortSignal,
): Promise<void> {
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    })
    if (!res.ok) {
      onError?.(new Error(`API error ${res.status}: ${await res.text()}`))
      return
    }
    const reader = res.body?.getReader()
    if (!reader) {
      onError?.(new Error('No response body'))
      return
    }

    const parser = new SSEParser()
    const decoder = new TextDecoder()
    let finished = false
    const deliver = (messages: SSEMessage[]) => {
      for (const message of messages) {
        if (isTerminal(message)) finished = true
        onMessage(message)
      }
    }

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        deliver(parser.feed(decoder.decode(value, { stream: true })))
      }
      deliver(parser.feed(decoder.decode()))
      deliver(parser.end())
    } finally {
      reader.releaseLock()
    }

    if (!finished) onError?.(new Error('Stream ended unexpectedly without completing'))
  } catch (err) {
    // User stopped generation
    if (err instanceof DOMException && err.name === 'AbortError') return
    throw err
  }
}

/** The error text of an `error` event. */
export function sseError(message: SSEMessage): Error {
  return new Error(String(message.data.error ?? 'Unknown SSE error'))
}
