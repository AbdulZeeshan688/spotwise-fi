// Typed client for the SpotWise API. No API keys here: the browser only talks to our
// backend, which holds the secrets.
import type {
  ChatEvent,
  CheapestWindowResponse,
  PricesResponse,
  QualitySummary,
} from './types'

export const API_URL = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000').replace(/\/$/, '')

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

type Params = Record<string, string | number | boolean>

function buildUrl(path: string, params: Params = {}): string {
  const url = new URL(API_URL + path)
  for (const [key, value] of Object.entries(params)) url.searchParams.set(key, String(value))
  return url.toString()
}

/** FastAPI puts error messages in `detail`; fall back to the status text. */
async function errorFrom(res: Response): Promise<ApiError> {
  let message = res.statusText || `HTTP ${res.status}`
  try {
    const body: unknown = await res.json()
    if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') {
      message = body.detail
    }
  } catch {
    // not JSON; keep the status text
  }
  return new ApiError(res.status, message)
}

async function getJson<T>(path: string, params: Params, signal?: AbortSignal): Promise<T> {
  const res = await fetch(buildUrl(path, params), { signal })
  if (!res.ok) throw await errorFrom(res)
  return (await res.json()) as T
}

export function getPrices(
  opts: { from: string; to: string; resolution: 15 | 60; vat: boolean },
  signal?: AbortSignal,
): Promise<PricesResponse> {
  return getJson('/prices', opts, signal)
}

/** The cheapest window of a day, or null when the day has no (published) prices. */
export async function getCheapestWindow(
  date: string,
  hours: number,
  vat: boolean,
  signal?: AbortSignal,
): Promise<CheapestWindowResponse | null> {
  try {
    return await getJson<CheapestWindowResponse>('/prices/cheapest-window', { date, hours, vat }, signal)
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null
    throw err
  }
}

export function getQuality(signal?: AbortSignal): Promise<QualitySummary> {
  return getJson('/quality/latest', {}, signal)
}

/** Parse one SSE block ("event: x\ndata: {...}") into a ChatEvent. */
export function parseSseBlock(block: string): ChatEvent | null {
  let event = 'message'
  const data: string[] = []
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
  }
  if (data.length === 0) return null // comments / keep-alives
  const payload = JSON.parse(data.join('\n')) as Record<string, unknown>
  return { type: event, ...payload } as ChatEvent
}

/**
 * Ask a question and yield the streamed events. EventSource only supports GET, so we
 * read the POST response body ourselves and split it on blank lines.
 */
export async function* streamChat(
  message: string,
  sessionId: string | null,
  signal?: AbortSignal,
): AsyncGenerator<ChatEvent> {
  const res = await fetch(buildUrl('/chat'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ message, session_id: sessionId }),
    signal,
  })
  if (!res.ok || !res.body) throw await errorFrom(res)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const blocks = buffer.split(/\r?\n\r?\n/)
    buffer = done ? '' : (blocks.pop() ?? '')
    for (const block of blocks) {
      const event = block.trim() ? parseSseBlock(block) : null
      if (event) yield event
    }
    if (done) return
  }
}
