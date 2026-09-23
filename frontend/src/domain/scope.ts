import { useEffect, useMemo } from 'react'
import { useHistory } from '@/api/hooks'
import type { Benchmark, HistoryPayload, Run, Verdict } from '@/api/types'
import { useUi, type RangeKey } from '@/app/store'

export interface AppOption {
  pkg: string
  name: string
  own: boolean
  runs: number
}

/** Apps that have runs, own app first, then by run count. */
export function appsIn(h: HistoryPayload): AppOption[] {
  const m = new Map<string, AppOption>()
  for (const r of h.runs) {
    const pkg = r.app_pkg ?? 'unknown'
    const o = m.get(pkg) ?? { pkg, name: r.app_name ?? pkg, own: r.app_role === 'own', runs: 0 }
    o.runs++
    m.set(pkg, o)
  }
  return [...m.values()].sort((a, b) => Number(b.own) - Number(a.own) || b.runs - a.runs)
}

export function pathsIn(runs: Run[]): string[] {
  return [...new Set(runs.map((r) => r.path_kind).filter(Boolean))]
}

function inRange(runs: Run[], range: RangeKey): Run[] {
  if (range === '7d') {
    const since = Date.now() - 7 * 24 * 3600 * 1000
    return runs.filter((r) => new Date(r.ts).getTime() >= since)
  }
  return runs.slice(-Number(range))
}

/** The pinned benchmark that applies to a run: same app and path, and the
 *  same device when one was recorded. Benchmarks never cross apps or paths. */
export function benchmarkFor(run: Run | null, h: HistoryPayload): Benchmark | null {
  if (!run) return null
  const cands = h.benchmarks.filter((b) => (b.app_pkg ?? null) === (run.app_pkg ?? null) && b.path_kind === run.path_kind)
  return cands.find((b) => b.device === run.device) ?? cands.find((b) => !b.device) ?? null
}

export const verdictOf = (r: Run | null | undefined): Verdict | null => r?.analysis?.verdict ?? null

export interface Scope {
  history: HistoryPayload
  apps: AppOption[]
  paths: string[]
  /** Runs for the selected app and path, oldest first, within the range. */
  runs: Run[]
  /** Every run for the app and path, ignoring range (baselines, benchmark lookups). */
  allRuns: Run[]
  latest: Run | null
  benchmark: Benchmark | null
  benchmarkRun: Run | null
  byId: (id: number) => Run | undefined
}

/** The data every screen shares: selected app, path and range applied to the
 *  run history. Picks sensible defaults (the newest run's app and path) until
 *  the user chooses. */
export function useScope(): { scope: Scope | null; isLoading: boolean; error: Error | null } {
  const q = useHistory()
  const { app, path, range, setFilters } = useUi()

  // Default the filters from the newest run, and repair them if the stored
  // choice no longer exists in the data (a pruned app, a renamed path).
  useEffect(() => {
    const h = q.data
    if (!h || !h.runs.length) return
    const newest = h.runs[h.runs.length - 1]!
    const apps = appsIn(h)
    const nextApp = apps.some((a) => a.pkg === app) ? app : (newest.app_pkg ?? apps[0]?.pkg ?? '')
    const appRuns = h.runs.filter((r) => (r.app_pkg ?? 'unknown') === nextApp)
    const paths = pathsIn(appRuns)
    const newestForApp = appRuns[appRuns.length - 1]
    const nextPath = paths.includes(path) ? path : (newestForApp?.path_kind ?? paths[0] ?? '')
    if (nextApp !== app || nextPath !== path) setFilters({ app: nextApp, path: nextPath })
  }, [q.data, app, path, setFilters])

  const scope = useMemo<Scope | null>(() => {
    const h = q.data
    if (!h) return null
    const appRuns = h.runs.filter((r) => (r.app_pkg ?? 'unknown') === app)
    const allRuns = appRuns.filter((r) => r.path_kind === path)
    const runs = inRange(allRuns, range)
    const latest = runs[runs.length - 1] ?? null
    const benchmark = benchmarkFor(latest, h)
    const index = new Map(h.runs.map((r) => [r.id, r]))
    return {
      history: h,
      apps: appsIn(h),
      paths: pathsIn(appRuns),
      runs,
      allRuns,
      latest,
      benchmark,
      benchmarkRun: benchmark ? (index.get(benchmark.run_id) ?? null) : null,
      byId: (id) => index.get(id),
    }
  }, [q.data, app, path, range])

  return { scope, isLoading: q.isLoading, error: q.error }
}
