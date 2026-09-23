import type { GlobalBudgets, Run } from '@/api/types'
import type { Tone } from '@/design'

/** One definition per headline metric. Gates, KPI tiles, History columns and
 *  Compare rows all read from this table, so a metric is described once. */
export interface MetricDef {
  key: 'ttff_ms' | 'slow_pct' | 'janky_pct' | 'peak_rss_mb' | 'rss_growth_mb' | 'thermal_drift_pct'
  label: string
  short: string
  unit: string
  /** Unit shown after a delta; percentages move in percentage points. */
  deltaUnit: string
  dp: number
  help: string
  budget: (run: Run, g: GlobalBudgets) => number | null
}

const own = (r: Run) => r.app_role === 'own'

export const METRICS: MetricDef[] = [
  {
    key: 'ttff_ms',
    label: 'Time to initial display',
    short: 'TTID',
    unit: 'ms',
    deltaUnit: ' ms',
    dp: 0,
    help: 'From process start to the first frame the user can act on. For Swag Pay, the first usable camera frame.',
    budget: (r) => r.ttid_budget_ms,
  },
  {
    key: 'slow_pct',
    label: 'Slow frames',
    short: 'Slow',
    unit: '%',
    deltaUnit: ' pp',
    dp: 2,
    help: 'Share of frames that took longer than 16.67 ms (missed 60 fps).',
    budget: (_r, g) => g.slow_frame_pct,
  },
  {
    key: 'janky_pct',
    label: 'Janky frames',
    short: 'Janky',
    unit: '%',
    deltaUnit: ' pp',
    dp: 2,
    help: 'Share of frames longer than three frame budgets: a stutter a user sees.',
    budget: (_r, g) => g.janky_frame_pct,
  },
  {
    key: 'peak_rss_mb',
    label: 'Peak RAM',
    short: 'Peak',
    unit: 'MB',
    deltaUnit: ' MB',
    dp: 0,
    help: "Highest resident memory of the app's own process during the run.",
    // Memory and thermal budgets are this product's decisions, so they are
    // asserted against our own app only -- never a competitor's.
    budget: (r, g) => (own(r) ? g.peak_rss_mb : null),
  },
  {
    key: 'rss_growth_mb',
    label: 'RAM growth',
    short: 'Growth',
    unit: 'MB',
    deltaUnit: ' MB',
    dp: 0,
    help: 'How far resident memory rose from its lowest to its highest point during the run.',
    budget: (r, g) => (own(r) ? g.rss_growth_mb : null),
  },
  {
    key: 'thermal_drift_pct',
    label: 'Thermal drift',
    short: 'Drift',
    unit: '%',
    deltaUnit: ' pp',
    dp: 1,
    help: 'Mean frame time late in the run against early in it. Only measured when the work stays the same (one screen): otherwise a change of screen, not heat, moves it.',
    budget: (r, g) => (own(r) ? g.thermal_drift_pct : null),
  },
]

export const metricByKey = (k: MetricDef['key']) => METRICS.find((m) => m.key === k)!

/** A zero startup time means it could not be measured, not that it was instant. */
export function valueOf(run: Run | null | undefined, key: MetricDef['key']): number | null {
  if (!run) return null
  const v = run[key]
  if (v == null || !Number.isFinite(v)) return null
  if (key === 'ttff_ms' && v <= 0) return null
  return v
}

/** Gate status: over budget fails, within 10% of it warns. */
export function gateTone(value: number | null, budget: number | null): Tone {
  if (value == null || budget == null) return 'neutral'
  if (value > budget) return 'fail'
  if (value >= budget * 0.9) return 'warn'
  return 'pass'
}

export const verdictTone = (v: string | null | undefined): Tone =>
  v === 'pass' || v === 'warn' || v === 'fail' ? v : 'neutral'
