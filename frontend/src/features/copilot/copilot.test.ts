import { describe, expect, it } from 'vitest'
import { fromStored } from './chat'
import { activeContext, matchReferences, mentionQuery, type Reference } from './context'
import { toMarkdown } from './markdown'
import type { StoredMessage } from './types'

describe('mentionQuery', () => {
  it('finds the @query being typed at the end', () => {
    expect(mentionQuery('why did @#8')).toBe('#8')
    expect(mentionQuery('@')).toBe('')
    expect(mentionQuery('mail me@home')).toBeNull()
    expect(mentionQuery('@#81 grew')).toBeNull()
  })
})

describe('matchReferences', () => {
  const ref = (handle: string, meta: string): Reference => ({ handle, kind: 'Run', meta, item: { kind: 'run', id: handle, label: handle } })
  const refs = [ref('#81', 'Run · Sep 23 · FAIL'), ref('#79', 'Run · Sep 22 · PASS'), ref('bind_application', 'Step · +12.0 ms')]
  it('matches runs with or without the #, and steps by name', () => {
    expect(matchReferences(refs, '8').map((r) => r.handle)).toEqual(['#81'])
    expect(matchReferences(refs, '#79').map((r) => r.handle)).toEqual(['#79'])
    expect(matchReferences(refs, 'bind').map((r) => r.handle)).toEqual(['bind_application'])
    expect(matchReferences(refs, '', 2)).toHaveLength(2)
  })
})

describe('activeContext', () => {
  it('drops removed defaults and duplicate additions', () => {
    const tab = { kind: 'tab' as const, id: 'overview', label: 'Overview tab' }
    const run = { kind: 'run' as const, id: 81, label: 'Run #81' }
    expect(activeContext([tab, run], [run, { kind: 'run', id: 79, label: 'Run #79' }], ['tab:overview']).map((c) => c.label)).toEqual(['Run #81', 'Run #79'])
  })
})

describe('fromStored', () => {
  it('restores answers, errors and questions that were stopped', () => {
    const msgs: StoredMessage[] = [
      { id: 1, role: 'user', feedback: null, text: 'Why?' },
      { id: 2, role: 'assistant', feedback: 'up', blocks: [], result: { kind: 'done', elapsed_ms: 5, steps: ['a'], run_id: 81 } },
      { id: 3, role: 'user', feedback: null, text: 'Run #172?' },
      { id: 4, role: 'assistant', feedback: null, blocks: [], result: { kind: 'no_data', title: 'No data for run #172', message: 'm', oldest_run_id: 1 } },
      { id: 5, role: 'user', feedback: null, text: 'Stopped one' },
    ]
    const out = fromStored(msgs)
    expect(out.map((m) => m.role)).toEqual(['user', 'answer', 'user', 'nodata', 'user', 'stopped'])
    expect(out[1]).toMatchObject({ messageId: 2, feedback: 'up', runId: 81, prompt: 'Why?' })
    expect(out[3]).toMatchObject({ oldestRunId: 1, prompt: 'Run #172?' })
  })
})

describe('toMarkdown', () => {
  it('renders every block type', () => {
    const md = toMarkdown('Why?', [
      { type: 'verdict', tone: 'fail', label: 'FAIL', text: 'TTID is 480 ms.' },
      { type: 'heading', text: 'Where it stands' },
      { type: 'table', cols: ['Metric', 'Run #3', 'Base', 'Δ'], rows: [{ cells: ['TTID', '480 ms', '400 ms', '+80 ms'], tag: 'worse' }] },
      { type: 'code', lang: 'Markdown', open: true, code: '**x**' },
      { type: 'cites', items: [{ kind: 'run', id: 3, label: 'Run #3', path: '/history', focus: 'run:3' }] },
    ])
    expect(md).toContain('> Why?')
    expect(md).toContain('**FAIL** TTID is 480 ms.')
    expect(md).toContain('| TTID | 480 ms | 400 ms | ▲ +80 ms |')
    expect(md).toContain('```md\n**x**\n```')
    expect(md).toContain('[Run #3](/history)')
  })
})
