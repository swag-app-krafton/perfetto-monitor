import type { AnrEvent, CrashEvent, JsErrorEvent, Run, Stability } from '@/api/types'

/** JS exceptions, ANRs and crashes of one run, as one list (stability.py). */
export type IncidentKind = 'js' | 'anr' | 'crash'
export type IncidentFilter = IncidentKind | 'all'

interface Base {
  key: string
  start_ms: number | null
  name: string
  screen: string | null
  fatal: boolean
  /** How a JS exception reached the app's error reporting. */
  how?: string
}

/** How each JS exception surfaced (react-native/src/errorReporting.ts). */
export const JS_SOURCE: Record<JsErrorEvent['source'], string> = {
  global: 'Uncaught',
  promise: 'Unhandled rejection',
  boundary: 'Caught by a boundary',
  manual: 'Reported by the app',
}
export type Incident = (Base & { kind: 'js'; js: JsErrorEvent }) | (Base & { kind: 'anr'; anr: AnrEvent }) | (Base & { kind: 'crash'; crash: CrashEvent })

/** A run recorded before crash lists (F-028) says only whether it crashed. */
const crashesOf = (st: Stability): CrashEvent[] =>
  st.crash.events ?? (st.crash.crashed ? [{ start_ms: null, kind: 'unknown', signature: 'Crash', message: st.crash.reason, log: null, screen: null, pid: null }] : [])

/** Every JS exception, ANR and crash, in time order, so a fatal JS error just
 *  before a crash reads as its cause. A crash with no time (iOS) goes last:
 *  the app ended there. */
export function incidentsOf(st: Stability): Incident[] {
  const list: Incident[] = [
    ...st.errors.events.map((e): Incident => ({ kind: 'js', key: `js:${e.id}`, start_ms: e.start_ms, name: e.name, screen: e.screen, fatal: e.fatal, how: JS_SOURCE[e.source], js: e })),
    ...(st.anrs?.events ?? []).map((a): Incident => ({ kind: 'anr', key: `anr:${a.id}`, start_ms: a.start_ms, name: a.type_label, screen: a.screen, fatal: false, anr: a })),
    ...crashesOf(st).map((c, i): Incident => ({ kind: 'crash', key: `crash:${i}`, start_ms: c.start_ms, name: c.signature, screen: c.screen, fatal: true, crash: c })),
  ]
  const at = (x: Incident) => x.start_ms ?? Number.POSITIVE_INFINITY
  return list.sort((a, b) => (at(a) === at(b) ? 0 : at(a) < at(b) ? -1 : 1))
}

export const filterIncidents = (list: Incident[], f: IncidentFilter) => (f === 'all' ? list : list.filter((x) => x.kind === f))

/** The tiles' counts. Null where the run didn't measure it: an iOS run's
 *  ANRs, a trace recorded without the crash log, a run from before F-028. */
export function incidentCounts(st: Stability) {
  return {
    js: st.errors.js,
    anr: st.anrs?.measured ? st.anrs.count : null,
    crash: st.crash.measured === false ? null : (st.crash.count ?? (st.crash.crashed ? 1 : 0)),
  }
}

/** A run's crash count for a chart: a gap, never 0, where the run didn't
 *  measure crashes (no stability data, or a trace without the crash log). */
export const runCrashCount = (r: Run) => (r.stability ? incidentCounts(r.stability).crash : null)

const list = (xs: string[], last: string) => (xs.length < 2 ? xs.join('') : `${xs.slice(0, -1).join(', ')} ${last} ${xs[xs.length - 1]}`)

/** What an empty run's list says: the kinds it found none of, then the
 *  kinds it didn't measure, so "nothing found" never covers "not looked". */
export function nothingFound(st: Stability) {
  const c = incidentCounts(st)
  const kinds: [string, string, number | null][] = [
    ['JS exception', 'JS exceptions', c.js],
    ['ANR', 'ANRs', c.anr],
    ['crash', 'crashes', c.crash],
  ]
  const found = kinds.filter((k) => k[2] != null).map((k) => k[0])
  const missing = kinds.filter((k) => k[2] == null).map((k) => k[1])
  const unmeasured = list(missing, 'and')
  return [
    found.length ? `No ${list(found, 'or')} in this run.` : '',
    missing.length ? `${unmeasured.charAt(0).toUpperCase()}${unmeasured.slice(1)} were not measured.` : '',
  ]
    .filter(Boolean)
    .join(' ')
}
