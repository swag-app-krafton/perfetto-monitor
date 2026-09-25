import { WRITE_HEADERS } from '@/api/client'

/** Server-sent events over a POST (EventSource only does GET). Yields each
 *  `{event, data}` as it arrives; `data` is the parsed JSON. Aborting the
 *  request's signal ends the stream. */
export interface SseEvent {
  event: string
  data: unknown
}

export function parseSseChunk(buffer: string): { events: SseEvent[]; rest: string } {
  const events: SseEvent[] = []
  const blocks = buffer.split(/\r?\n\r?\n/)
  const rest = blocks.pop() ?? ''
  for (const block of blocks) {
    let event = 'message'
    const data: string[] = []
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith(':')) continue
      const i = line.indexOf(':')
      const field = i < 0 ? line : line.slice(0, i)
      const value = i < 0 ? '' : line.slice(i + 1).replace(/^ /, '')
      if (field === 'event') event = value
      else if (field === 'data') data.push(value)
    }
    if (data.length === 0) continue
    const raw = data.join('\n')
    let parsed: unknown = raw
    try {
      parsed = JSON.parse(raw)
    } catch {
      // Not JSON: hand the text through as-is.
    }
    events.push({ event, data: parsed })
  }
  return { events, rest }
}

export async function* postSse(url: string, body: unknown, signal?: AbortSignal): AsyncGenerator<SseEvent> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { ...WRITE_HEADERS, Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok || !res.body) {
    const err: unknown = await res.json().catch(() => null)
    const msg = err && typeof err === 'object' && 'error' in err ? String((err as { error: unknown }).error) : res.statusText
    throw new Error(msg || `HTTP ${res.status}`)
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      const { events, rest } = parseSseChunk(buffer + value)
      buffer = rest
      yield* events
    }
    if (buffer.trim()) yield* parseSseChunk(buffer + '\n\n').events
  } finally {
    reader.releaseLock()
  }
}
