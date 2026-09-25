import type { TrendPayload, TrendSeries } from '@/api/types'
import type { Reference, Series } from '@/design'
import type { TrendPicks } from '@/app/store'
import { stepName } from './format'
import { METRICS } from './metrics'

/** The top-line metrics a trend can plot, in the order the page lists them. */
export const TREND_METRICS = ['ttff_ms', 'janky_pct', 'slow_pct', 'peak_rss_mb', 'rss_growth_mb'] as const

/** One colour per device slot. --c4 is left out: the dataviz validator puts it
 *  1.7 ΔE from --c2 for a protanope in the light theme (10.9 for full colour
 *  vision, under the 15 floor), so four devices at once would not be told
 *  apart. Three pass in both themes. */
export const SLOT_COLORS = ['var(--c1)', 'var(--c2)', 'var(--c3)'] as const
export const MAX_DEVICES = SLOT_COLORS.length

/** Devices keep their slot (and so their colour) while they stay picked:
 *  dropping one never repaints the others, and a new pick takes the first free
 *  slot. `slots` holds a device name or '' per slot. */
export function nextSlots(slots: string[], picked: string[]): string[] {
  const out = Array.from({ length: MAX_DEVICES }, (_, i) => (slots[i] && picked.includes(slots[i]!) ? slots[i]! : ''))
  for (const d of picked) {
    if (out.includes(d)) continue
    const free = out.indexOf('')
    if (free >= 0) out[free] = d
  }
  return out
}

/** What to plot: the stored picks, kept to what this app and path has. With
 *  no picks yet, the device with the most runs and the startup time. */
export function effectivePicks(p: TrendPayload, picks: TrendPicks | undefined): TrendPicks {
  const names = new Set(p.devices.map((d) => d.name))
  if (!picks) {
    const first = p.devices[0]?.name
    return { devices: first ? nextSlots([], [first]) : nextSlots([], []), metrics: ['ttff_ms'], steps: [] }
  }
  return {
    devices: nextSlots(picks.devices, picks.devices.filter((d) => d && names.has(d))),
    metrics: picks.metrics.filter((m) => (TREND_METRICS as readonly string[]).includes(m)),
    steps: picks.steps.filter((s) => p.steps.includes(s)),
  }
}

export interface TrendChart {
  key: string
  title: string
  hint: string
  unit: string
  dp: number
  labels: string[]
  series: Series[]
  references: Reference[]
  budget: number | null
  /** Whether any picked device measured this metric in any version. */
  hasData: boolean
}

const runs = (n: number) => `median of ${n} run${n === 1 ? '' : 's'}`

/** One chart: a line per picked device (two for a device whose startup was
 *  measured both ways), a dotted line per device for its pinned benchmark, and
 *  the dashed North Star target when one applies. */
export function buildChart(p: TrendPayload, metric: string, slots: string[], stepDescriptions: Record<string, string> = {}): TrendChart {
  const step = metric.startsWith('step:')
  const def = METRICS.find((m) => m.key === metric)
  const unit = step ? 'ms' : (def?.unit ?? '')
  const labelOf = (name: string) => p.devices.find((d) => d.name === name)?.label ?? name
  const series: Series[] = []
  const references: Reference[] = []
  const targets = new Set<number>()

  slots.forEach((device, slot) => {
    if (!device) return
    const color = SLOT_COLORS[slot]!
    const lines = p.series.filter((s) => s.device === device && s.metric === metric)
    for (const line of lines) {
      const name = labelOf(device) + (line.kind ? ` · ${line.startup_metric}` : '')
      series.push({
        name,
        color,
        values: line.points.map((pt) => pt.value),
        notes: line.points.map((pt) => (pt.n ? runs(pt.n) : null)),
      })
      if (line.target != null) targets.add(line.target)
      const bench = p.benchmarks[device]
      const value = bench?.values[metric]
      // A benchmark belongs to the line that measured what it measured.
      if (bench && value != null && benchFits(line, bench.derived)) {
        references.push({
          value,
          label: `${labelOf(device)} benchmark #${bench.run_id}${bench.version ? ` · ${bench.version}` : ''}`,
          series: name,
          color,
          style: 'dotted',
        })
      }
    }
  })

  // One target draws as the North Star line; several (devices judged
  // differently) each get their own dashed reference.
  const distinct = [...targets]
  const budget = distinct.length === 1 ? distinct[0]! : null
  if (distinct.length > 1) {
    for (const t of distinct) references.push({ value: t, label: `North Star ${t} ${unit}`.trim(), style: 'dashed' })
  }

  const title = step ? `${stepName(metric)} step` : metric === 'ttff_ms' ? 'Startup time' : (def?.label ?? metric)
  const parts = [
    step ? (stepDescriptions[metric] ?? 'One launch step, as the trace recorded it.') : (def?.help ?? ''),
    'Each point is the median of that version’s runs on that device; a gap is a version it has no measurement for.',
  ]
  if (references.some((r) => r.style === 'dotted')) parts.push('Dotted lines are each device’s pinned benchmark.')
  if (metric === 'ttff_ms' && budget == null && p.startup_target_reason) parts.push(p.startup_target_reason)
  return {
    key: metric,
    title,
    hint: parts.filter(Boolean).join(' '),
    unit,
    dp: step ? 1 : (def?.dp ?? 1),
    labels: p.versions.map((v) => v.label),
    series,
    references,
    budget,
    hasData: series.some((s) => s.values.some((v) => v != null)),
  }
}

function benchFits(line: TrendSeries, benchDerived: boolean) {
  if (line.metric !== 'ttff_ms' || line.kind == null) return true
  return (line.kind === 'derived') === benchDerived
}
