import { afterEach, describe, expect, it, vi } from 'vitest'
import { postSSE, SSEParser, type SSEMessage } from './sse.ts'

const frame = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`

describe('SSEParser', () => {
  it('parses whole events', () => {
    const p = new SSEParser()
    expect(p.feed(frame('text_delta', { text: 'Hi' }) + frame('message_stop', { content: 'Hi' })))
      .toEqual([
        { event: 'text_delta', data: { text: 'Hi' } },
        { event: 'message_stop', data: { content: 'Hi' } },
      ])
  })

  it('keeps the event name when its data arrives in the next chunk', () => {
    // The old readers reset the event name per chunk and dropped this delta
    const p = new SSEParser()
    expect(p.feed('event: text_delta\n')).toEqual([])
    expect(p.feed('data: {"text":"lost?"}\n\n')).toEqual([{ event: 'text_delta', data: { text: 'lost?' } }])
  })

  it('survives any split point', () => {
    const stream = frame('text_delta', { text: 'a' }) + frame('text_delta', { text: 'b' })
      + frame('message_stop', { content: 'ab' })
    for (let cut = 0; cut <= stream.length; cut++) {
      const p = new SSEParser()
      const got = [...p.feed(stream.slice(0, cut)), ...p.feed(stream.slice(cut)), ...p.end()]
      expect(got.map(m => m.event)).toEqual(['text_delta', 'text_delta', 'message_stop'])
    }
  })

  it('handles CRLF, comments and an unterminated final event', () => {
    const p = new SSEParser()
    const got = [...p.feed(': keep-alive\r\nevent: error\r\ndata: {"error":"boom"}'), ...p.end()]
    expect(got).toEqual([{ event: 'error', data: { error: 'boom' } }])
  })

  it('skips malformed data without losing later events', () => {
    const p = new SSEParser()
    expect(p.feed('event: text_delta\ndata: {not json\n\n' + frame('text_delta', { text: 'ok' })))
      .toEqual([{ event: 'text_delta', data: { text: 'ok' } }])
  })
})

describe('postSSE', () => {
  afterEach(() => vi.unstubAllGlobals())

  const respond = (chunks: string[], init: ResponseInit = {}) => {
    const encoder = new TextEncoder()
    const body = new ReadableStream({
      start(controller) {
        for (const c of chunks) controller.enqueue(encoder.encode(c))
        controller.close()
      },
    })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(body, init)))
  }

  const run = async () => {
    const messages: SSEMessage[] = []
    const errors: Error[] = []
    await postSSE('/x', {}, m => messages.push(m), m => m.event === 'message_stop', e => errors.push(e))
    return { messages, errors }
  }

  it('delivers events across chunks and finishes cleanly', async () => {
    respond(['event: text_del', 'ta\ndata: {"text":"hi"}\n', '\n', frame('message_stop', {})])
    const { messages, errors } = await run()
    expect(messages.map(m => m.event)).toEqual(['text_delta', 'message_stop'])
    expect(errors).toEqual([])
  })

  it('reports a stream that ends without a terminal event', async () => {
    respond([frame('text_delta', { text: 'hi' })])
    const { errors } = await run()
    expect(errors.map(e => e.message)).toEqual(['Stream ended unexpectedly without completing'])
  })

  it('reports HTTP errors', async () => {
    respond(['nope'], { status: 502 })
    const { errors } = await run()
    expect(errors[0].message).toBe('API error 502: nope')
  })
})
