import { describe, expect, it } from 'vitest'
import { parseSseChunk } from './sse'

describe('parseSseChunk', () => {
  it('parses complete events and keeps the partial tail', () => {
    const { events, rest } = parseSseChunk('event: step\ndata: {"text":"a"}\n\nevent: block\ndata: {"ty')
    expect(events).toEqual([{ event: 'step', data: { text: 'a' } }])
    expect(rest).toBe('event: block\ndata: {"ty')
  })

  it('joins multi-line data, defaults the event name and skips comments', () => {
    const { events } = parseSseChunk(': ping\ndata: line one\ndata: line two\n\n')
    expect(events).toEqual([{ event: 'message', data: 'line one\nline two' }])
  })

  it('reassembles an event split across chunks', () => {
    const a = parseSseChunk('event: done\ndata: {"elapsed')
    const b = parseSseChunk(a.rest + '_ms":12}\n\n')
    expect(b.events).toEqual([{ event: 'done', data: { elapsed_ms: 12 } }])
  })
})
