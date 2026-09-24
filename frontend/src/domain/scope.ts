import { useCallback, useEffect, useMemo } from 'react'
import { useHistory } from '@/api/hooks'
import type { Benchmark, HistoryPayload, Platform, Run, Verdict } from '@/api/types'
import { useProfiler } from '@/app/profiler'
import { platformOf, useUi, type RangeKey } from '@/app/store'
import { versionKey, versionsIn, type AppVersion } from './versions'

export interface AppOption {
  pkg: string
  name: string
  own: boolean
  runs: number
}

/** The history as one lane sees it: its platform's runs and benchmarks only.
 *  An iOS run is never listed, charted or compared beside Android ones. */
export function laneHistory(h: HistoryPayload, platform: Platform): HistoryPayload {
  const mine = (p: Platform | undefined) => (p ?? 'android') === platform
  return { ...h, runs: h.runs.filter((r) => mine(r.platform)), benchmarks: h.benchmarks.filter((b) => mine(b.platform)) }
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
  const cands = h.benchmarks.filter(
    (b) => (b.app_pkg ?? null) === (run.app_pkg ?? null) && b.path_kind === run.path_kind && (b.platform ?? 'android') === (run.platform ?? 'android'),
  )
  return cands.find((b) => b.device === run.device) ?? cands.find((b) => !b.device) ?? null
}

export const verdictOf = (r: Run | null | undefined): Verdict | null => r?.analysis?.verdict ?? null

export interface Scope {
  history: HistoryPayload
  apps: AppOption[]
  paths: string[]
  /** Runs for the selected app, path and version, oldest first, within the range. */
  runs: Run[]
  /** Every run of the app and path in the selected version (the Run list). */
  versionRuns: Run[]
  /** The builds among the app and path's runs, newest first. */
  versions: AppVersion[]
  /** Every run for the app and path, ignoring range (baselines, benchmark lookups). */
  allRuns: Run[]
  /** The newest run in range. */
  latest: Run | null
  /** The run in view: the one picked in the top bar, else the newest. Every
   *  per-run screen reads this, never `latest`. */
  run: Run | null
  /** Whether `run` is the newest run (the top bar is following it). */
  isLatest: boolean
  benchmark: Benchmark | null
  benchmarkRun: Run | null
  byId: (id: number) => Run | undefined
}

/** The data every screen shares: selected app, path and range applied to the
 *  run history. Picks sensible defaults (the newest run's app and path) until
 *  the user chooses. */
export function useScope(): { scope: Scope | null; isLoading: boolean; error: Error | null } {
  const q = useHistory()
  const { app, path, range, version, runId, setFilters } = useUi()
  // Everything below reads the lane in view: the first control in the top bar.
  const platform = platformOf(useProfiler())
  const lane = useMemo(() => (q.data ? laneHistory(q.data, platform) : undefined), [q.data, platform])

  // Default the filters from the newest run, and repair them if the stored
  // choice no longer exists in the data (a pruned app, a renamed path).
  useEffect(() => {
    const h = lane
    if (!h || !h.runs.length) return
    const newest = h.runs[h.runs.length - 1]!
    const apps = appsIn(h)
    const nextApp = apps.some((a) => a.pkg === app) ? app : (newest.app_pkg ?? apps[0]?.pkg ?? '')
    const appRuns = h.runs.filter((r) => (r.app_pkg ?? 'unknown') === nextApp)
    const paths = pathsIn(appRuns)
    const newestForApp = appRuns[appRuns.length - 1]
    const nextPath = paths.includes(path) ? path : (newestForApp?.path_kind ?? paths[0] ?? '')
    if (nextApp !== app || nextPath !== path) setFilters({ app: nextApp, path: nextPath })
  }, [lane, app, path, setFilters])

  const scope = useMemo<Scope | null>(() => {
    const h = lane
    if (!h) return null
    const appRuns = h.runs.filter((r) => (r.app_pkg ?? 'unknown') === app)
    const allRuns = appRuns.filter((r) => r.path_kind === path)
    const versions = versionsIn(allRuns)
    // A version that is not among these runs (another app's) means every version.
    const v = versions.some((x) => x.key === version) ? version : ''
    const versionRuns = v ? allRuns.filter((r) => versionKey(r) === v) : allRuns
    const runs = inRange(versionRuns, range)
    const latest = runs[runs.length - 1] ?? null
    const run = (runId != null ? versionRuns.find((r) => r.id === runId) : null) ?? latest
    const benchmark = benchmarkFor(run, h)
    const index = new Map(h.runs.map((r) => [r.id, r]))
    return {
      history: h,
      apps: appsIn(h),
      paths: pathsIn(appRuns),
      runs,
      versionRuns,
      versions,
      allRuns,
      latest,
      run,
      isLatest: !!run && run.id === latest?.id,
      benchmark,
      benchmarkRun: benchmark ? (index.get(benchmark.run_id) ?? null) : null,
      byId: (id) => index.get(id),
    }
  }, [lane, app, path, range, version, runId])

  return { scope, isLoading: q.isLoading, error: q.error }
}

/** Put a run in view on every screen: switches the app and path to the run's
 *  own when they differ, so a link to any run lands on it. */
export function useSelectRun() {
  const q = useHistory()
  const { setFilters, setRunId } = useUi()
  return useCallback(
    (id: number | null) => {
      const run = id == null ? null : q.data?.runs.find((r) => r.id === id)
      if (run) {
        const { version } = useUi.getState()
        setFilters({ app: run.app_pkg ?? 'unknown', path: run.path_kind, ...(version && version !== versionKey(run) ? { version: '' } : {}) })
      }
      setRunId(run ? run.id : null)
    },
    [q.data, setFilters, setRunId],
  )
}
