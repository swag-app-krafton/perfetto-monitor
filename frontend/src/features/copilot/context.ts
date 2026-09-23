import type { Run } from '@/api/types'
import type { ScreenDef } from '@/app/routes'
import { shortDate, signed, stepName } from '@/domain/format'
import { verdictOf, type Scope } from '@/domain/scope'
import { stepDeltas } from '@/domain/steps'
import { findingId } from '@/features/shared/findings'
import { chipKey } from './chat'
import type { ContextItem } from './types'

/** What the panel is looking at: the tab, the run in view and its benchmark. */
export function defaultContext(scope: Scope | null, screen: ScreenDef): ContextItem[] {
  const out: ContextItem[] = [{ kind: 'tab', id: screen.id, label: `${screen.label} tab` }]
  const run = scope?.latest
  if (run) out.push({ kind: 'run', id: run.id, label: `Run #${run.id}` })
  const bench = scope?.benchmarkRun
  if (bench && bench.id !== run?.id) out.push({ kind: 'benchmark', id: bench.id, label: `vs Benchmark #${bench.id}` })
  return out
}

/** The context sent with a question: defaults the user kept, then additions. */
export function activeContext(defaults: ContextItem[], added: ContextItem[], removed: string[]): ContextItem[] {
  const keys = new Set<string>()
  return [...defaults.filter((c) => !removed.includes(chipKey(c))), ...added].filter((c) => {
    const k = chipKey(c)
    if (keys.has(k)) return false
    keys.add(k)
    return true
  })
}

/** Something a question can name: a run, the benchmark, a step, a finding. */
export interface Reference {
  /** What `@` inserts, e.g. `#81` or `bind_application`. */
  handle: string
  kind: 'Run' | 'Benchmark' | 'Step' | 'Finding'
  meta: string
  item: ContextItem
}

const runMeta = (r: Run) => ['Run', shortDate(r.ts), verdictOf(r)?.toUpperCase(), r.device].filter(Boolean).join(' · ')

/** Everything in scope that can be referenced, most relevant first. */
export function references(scope: Scope | null): Reference[] {
  if (!scope?.latest) return []
  const { latest, allRuns, benchmarkRun } = scope
  const out: Reference[] = []
  if (benchmarkRun) out.push({ handle: `#${benchmarkRun.id}`, kind: 'Benchmark', meta: 'Pinned benchmark', item: { kind: 'benchmark', id: benchmarkRun.id, label: `vs Benchmark #${benchmarkRun.id}` } })
  for (const r of [...allRuns].reverse().slice(0, 12)) {
    if (r.id === benchmarkRun?.id) continue
    out.push({ handle: `#${r.id}`, kind: 'Run', meta: runMeta(r), item: { kind: 'run', id: r.id, label: `Run #${r.id}` } })
  }
  const deltas = stepDeltas(latest, allRuns, benchmarkRun).sort((a, b) => Math.abs(b.deltaMs ?? 0) - Math.abs(a.deltaMs ?? 0))
  for (const d of deltas) {
    const name = stepName(d.step)
    out.push({ handle: name, kind: 'Step', meta: d.deltaMs == null ? 'Step · no baseline' : `Step · ${signed(d.deltaMs, 1, ' ms')}`, item: { kind: 'step', id: d.step, label: `Step: ${name}` } })
  }
  ;(latest.analysis?.findings ?? []).forEach((f, i) => {
    const id = findingId(i)
    out.push({ handle: id, kind: 'Finding', meta: `Finding · ${f.severity}`, item: { kind: 'finding', id, label: `Finding ${id}` } })
  })
  return out
}

/** The @-mention matches for `query` (what follows the @), up to `limit`. */
export function matchReferences(refs: Reference[], query: string, limit = 6): Reference[] {
  const q = query.toLowerCase().replace(/^#/, '')
  return refs.filter((r) => r.handle.toLowerCase().replace(/^#/, '').includes(q) || r.meta.toLowerCase().includes(q)).slice(0, limit)
}

/** The `@query` being typed at the end of the text, if any. */
export const mentionQuery = (text: string) => /(?:^|\s)@([\w#.:-]*)$/.exec(text)?.[1] ?? null
