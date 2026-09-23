import { niceTicks } from './scale'
import s from './StackedBars.module.css'

export interface StackRow {
  id: string
  label: string
  bold?: boolean
  segments: { key: string; value: number; title: string }[]
  /** The figure printed at the right. Can exceed the segments' sum: a gap is
   *  time no segment accounts for, and is shown as such rather than hidden. */
  total: number | null
  totalText: string
  over?: boolean
}

/** Horizontal stacked bars on one shared scale, with an optional budget marker.
 *  Colours come from `colors[key]`; a key without one is drawn as "Other". */
export function StackedBars({
  rows,
  colors,
  budget,
  unit,
}: {
  rows: StackRow[]
  colors: Record<string, string>
  budget?: number | null
  unit: string
}) {
  const maxVal = Math.max(budget ?? 0, ...rows.map((r) => Math.max(r.total ?? 0, r.segments.reduce((a, x) => a + x.value, 0))), 1)
  // Round the scale up to a whole tick past the largest value, so neither the
  // longest bar nor the budget marker lands on the axis edge.
  const raw = niceTicks(0, maxVal)
  const step = raw.length > 1 ? raw[1]! - raw[0]! : maxVal
  const max = step * Math.ceil((maxVal * 1.02) / step)
  const ticks = raw.concat(raw.length && raw[raw.length - 1]! < max ? [max] : [])
  const pct = (v: number) => `${(v / max) * 100}%`
  // A tick label within ~7% of the budget label would overprint it.
  const shownTicks = budget != null ? ticks.filter((t) => Math.abs(t - budget) / max > 0.07) : ticks
  return (
    <div>
      <div className={s.rows}>
        {rows.map((r) => (
          <div key={r.id} className={s.grid}>
            <span className={r.bold ? `${s.label} ${s.bold}` : s.label}>{r.label}</span>
            <div className={s.track}>
              {r.segments.map((sg, i) => (
                <div key={i} title={sg.title} className={s.segment} style={{ width: pct(sg.value), background: colors[sg.key] ?? 'var(--tx3)' }} />
              ))}
              {budget != null && <div className={s.budget} style={{ left: pct(budget) }} />}
            </div>
            <span className={r.over ? `${s.total} ${s.over}` : s.total}>{r.totalText}</span>
          </div>
        ))}
      </div>
      <div className={`${s.grid} ${s.axis}`}>
        <span />
        <div className={s.ticks}>
          {shownTicks.map((t) => (
            <span key={t} className={s.tick} style={{ left: pct(t) }}>
              {t}
            </span>
          ))}
          {budget != null && !ticks.includes(budget) && (
            <span className={`${s.tick} ${s.budgetTick}`} style={{ left: pct(budget) }}>
              {budget}
            </span>
          )}
        </div>
        <span>{unit}</span>
      </div>
    </div>
  )
}
