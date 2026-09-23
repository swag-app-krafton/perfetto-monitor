import type { Run, StepRow } from '@/api/types'

export interface StepDelta {
  step: string
  current: number
  baseline: number | null
  /** Where the baseline came from, for the label under a number. */
  baselineFrom: 'benchmark' | 'median' | null
  deltaMs: number | null
  deltaPct: number | null
  history: number[]
  row: StepRow
  /** Median of the same history, for drill-down stats. */
  p50: number | null
  p90: number | null
}

const median = (xs: number[]) => {
  if (!xs.length) return null
  const s = [...xs].sort((a, b) => a - b)
  const m = Math.floor(s.length / 2)
  return s.length % 2 ? s[m]! : (s[m - 1]! + s[m]!) / 2
}
const quantile = (xs: number[], q: number) => {
  if (!xs.length) return null
  const s = [...xs].sort((a, b) => a - b)
  return s[Math.min(s.length - 1, Math.round(q * (s.length - 1)))]!
}

/** Every step of `run` against its baseline: the pinned benchmark run when
 *  there is one, otherwise the median of the previous `window` runs. */
export function stepDeltas(run: Run, prior: Run[], benchmark: Run | null, window = 10): StepDelta[] {
  const earlier = prior.filter((r) => r.id < run.id).slice(-window)
  return run.steps.map((row) => {
    const history = earlier
      .map((r) => r.steps.find((s) => s.step === row.step)?.dur_ms)
      .filter((v): v is number => v != null)
    const benchVal = benchmark?.steps.find((s) => s.step === row.step)?.dur_ms ?? null
    const baseline = benchVal ?? median(history)
    const baselineFrom = benchVal != null ? 'benchmark' : baseline != null ? 'median' : null
    const deltaMs = baseline != null ? row.dur_ms - baseline : null
    return {
      step: row.step,
      current: row.dur_ms,
      baseline,
      baselineFrom,
      deltaMs,
      deltaPct: baseline ? (deltaMs! / baseline) * 100 : null,
      history: [...history, row.dur_ms],
      row,
      p50: median(history),
      p90: quantile(history, 0.9),
    }
  })
}

/** The step that moved most, and what share of the startup change it is.
 *  Only a move of at least 5ms counts -- the same floor regressions use. */
export function worstRegression(deltas: StepDelta[], ttidDelta: number | null) {
  const worst = [...deltas]
    .filter((d) => d.deltaMs != null && d.deltaMs >= 5)
    .sort((a, b) => b.deltaMs! - a.deltaMs!)[0]
  if (!worst) return null
  const share = ttidDelta && ttidDelta > 0 ? Math.min(100, (worst.deltaMs! / ttidDelta) * 100) : null
  return { ...worst, share }
}
