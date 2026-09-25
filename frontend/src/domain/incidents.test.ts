import { describe, expect, it } from 'vitest'
import type { Stability } from '@/api/types'
import { filterIncidents, incidentCounts, incidentsOf } from './incidents'

const st = (over: Partial<Stability> = {}): Stability => ({
  hangs: {
    count: 0,
    microhangs: 0,
    longest_ms: null,
    total_ms: 0,
    rate_s_per_hr: null,
    session_s: 10,
    startup: { count: 0, microhangs: 0, longest_ms: null },
    per_screen: {},
    events: [],
    source: "the app's main-thread slices",
  },
  errors: {
    js: 1,
    js_fatal: 1,
    by_name: {},
    by_source: {},
    per_screen: {},
    events: [{ id: 'k1', start_ms: 3000, name: 'TypeError', source: 'global', fatal: true, screen: 'Home', message: 'x', stack: null, component_stack: null, has_record: true }],
  },
  anrs: {
    measured: true,
    count: 1,
    by_type: {},
    per_screen: {},
    events: [{ id: 'e1', start_ms: 1000, type: 'INPUT_DISPATCHING_TIMEOUT', type_label: 'A touch or key went unanswered', subject: null, dur_ms: 5000, screen: 'Home', main_thread: null }],
  },
  crash: {
    measured: true,
    crashed: true,
    reason: 'boom',
    count: 1,
    events: [{ start_ms: 3001, kind: 'java', signature: 'java.lang.IllegalStateException', message: 'boom', log: 'FATAL EXCEPTION: main', screen: 'Home', pid: 4000 }],
  },
  ...over,
})

describe('incidents', () => {
  it('puts every kind in one list, in time order', () => {
    const list = incidentsOf(st())
    expect(list.map((i) => i.kind)).toEqual(['anr', 'js', 'crash'])
    expect(list.map((i) => i.name)).toEqual(['A touch or key went unanswered', 'TypeError', 'java.lang.IllegalStateException'])
    expect(list.map((i) => i.fatal)).toEqual([false, true, true])
  })

  it('filters by kind', () => {
    const list = incidentsOf(st())
    expect(filterIncidents(list, 'crash').map((i) => i.kind)).toEqual(['crash'])
    expect(filterIncidents(list, 'all')).toHaveLength(3)
  })

  it('keeps a crash with no time at the end', () => {
    const ios = st({
      anrs: { measured: false, count: null, by_type: {}, per_screen: {}, events: [] },
      crash: { measured: true, crashed: true, reason: 'SIGABRT', count: 1, events: [{ start_ms: null, kind: 'ios', signature: 'SIGABRT', message: 'SIGABRT', log: null, screen: null, pid: null }] },
    })
    expect(incidentsOf(ios).map((i) => i.kind)).toEqual(['js', 'crash'])
    expect(incidentCounts(ios)).toEqual({ js: 1, anr: null, crash: 1 })
  })

  it('reads a run recorded before ANRs and crash lists as not measured, not zero', () => {
    const old = st({ anrs: undefined, crash: { crashed: true, reason: 'FATAL EXCEPTION: main' } })
    expect(incidentCounts(old)).toEqual({ js: 1, anr: null, crash: 1 })
    const crashes = incidentsOf(old).filter((i) => i.kind === 'crash')
    expect(crashes).toHaveLength(1)
    expect(crashes[0]!.name).toBe('Crash')
  })

  it('says a trace without the crash log did not measure crashes', () => {
    const none = st({ crash: { measured: false, crashed: false, reason: null, count: null, events: [] } })
    expect(incidentCounts(none).crash).toBeNull()
  })
})
