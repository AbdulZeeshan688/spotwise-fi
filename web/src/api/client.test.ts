import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, getCheapestWindow, getPrices, parseSseBlock, streamChat } from './client'
import type { ChatEvent } from './types'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

/** A streamed response whose body arrives in the given chunks (like a real network). */
function streamResponse(chunks: string[]): Response {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

afterEach(() => vi.unstubAllGlobals())

describe('getPrices', () => {
  it('sends the query parameters', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ prices: [] }))
    vi.stubGlobal('fetch', fetchMock)
    await getPrices({ from: '2025-11-15', to: '2025-11-17', resolution: 60, vat: false })
    const url = new URL(fetchMock.mock.calls[0][0] as string)
    expect(url.pathname).toBe('/prices')
    expect(Object.fromEntries(url.searchParams)).toEqual({
      from: '2025-11-15',
      to: '2025-11-17',
      resolution: '60',
      vat: 'false',
    })
  })

  it('throws ApiError with the FastAPI detail message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail: 'Range too long' }, 422)))
    await expect(getPrices({ from: 'a', to: 'b', resolution: 15, vat: true })).rejects.toEqual(
      new ApiError(422, 'Range too long'),
    )
  })
})

describe('getCheapestWindow', () => {
  it('returns null when the day is not published (404)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail: 'not published' }, 404)))
    expect(await getCheapestWindow('2025-11-16', 3, true)).toBeNull()
  })
})

describe('SSE parsing', () => {
  it('parses one event block', () => {
    expect(parseSseBlock('event: token\ndata: {"text":"Hi"}')).toEqual({ type: 'token', text: 'Hi' })
    expect(parseSseBlock(': keep-alive')).toBeNull()
  })

  it('streams events even when blocks are split across network chunks', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      streamResponse([
        'event: session\ndata: {"session_id":"abc"}\n\nevent: tok',
        'en\ndata: {"text":"Hel"}\n\nevent: token\ndata: {"text":"lo"}\n\n',
        'event: done\ndata: {"answer":"Hello","tools_used":[],"unsupported_numbers":[]}\n\n',
      ]),
    )
    vi.stubGlobal('fetch', fetchMock)
    const events: ChatEvent[] = []
    for await (const e of streamChat('hi', null)) events.push(e)
    expect(events.map((e) => e.type)).toEqual(['session', 'token', 'token', 'done'])
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({ message: 'hi', session_id: null })
  })

  it('throws ApiError for 429 before any event', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail: 'Too many' }, 429)))
    const run = async () => {
      for await (const _ of streamChat('hi', null)) {
        // no events expected
      }
    }
    await expect(run()).rejects.toMatchObject({ status: 429 })
  })
})
