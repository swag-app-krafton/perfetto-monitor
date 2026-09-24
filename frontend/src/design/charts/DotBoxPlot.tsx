import { niceTicks } from './scale'
import s from './DotBoxPlot.module.css'

export interface DotBoxRow {
  key: string
  label: string
  values: number[]
  color: string
  /** The box (the middle half) and the median bar. The caller computes them,
   *  so the chart holds no statistics of its own. */
  summary: { q1: number; median: number; q3: number }
  /** The figure printed at the right, usually the median. */
  valueText: string
}

/** Strip and box plot: one row per sample, one dot per value, the middle half
 *  as a box and the median as a bar. Rows share one axis, so two samples
 *  compare at a glance; an optional budget is a dashed rule across them. */
export function DotBoxPlot({ rows, budget, unit, label }: { rows: DotBoxRow[]; budget?: number | null; unit: string; label: string }) {
  const all = rows.flatMap((r) => r.values).concat(budget != null ? [budget] : [])
  if (!all.length) return null
  const pad = (Math.max(...all) - Math.min(...all)) * 0.08 || 10
  const lo = Math.min(...all) - pad
  const hi = Math.max(...all) + pad
  const X = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`
  const ticks = niceTicks(lo, hi)
  // A tick label within ~7% of the budget label would overprint it.
  const shownTicks = budget != null ? ticks.filter((t) => Math.abs(t - budget) / (hi - lo) > 0.07) : ticks

  return (
    <div role="img" aria-label={`${label}. ${rows.map((r) => `${r.label}: ${r.valueText}`).join('; ')}`}>
      <div className={s.rows}>
        {rows.map((r) => (
          <div key={r.key} className={s.grid}>
            <span className={s.label}>{r.label}</span>
            <div className={s.track}>
              <div className={s.box} style={{ left: X(r.summary.q1), width: `calc(${X(r.summary.q3)} - ${X(r.summary.q1)})`, borderColor: r.color }} />
              <div className={s.median} style={{ left: X(r.summary.median), background: r.color }} />
              {r.values.map((v, i) => (
                // Spread vertically by index, so repeated values stay visible.
                <span key={i} title={`${v.toFixed(1)} ${unit}`} className={s.dot} style={{ left: X(v), top: 10 + ((i * 7) % 28), background: r.color }} />
              ))}
              {budget != null && <div className={s.budget} style={{ left: X(budget) }} />}
            </div>
            <span className={s.value}>{r.valueText}</span>
          </div>
        ))}
      </div>
      <div className={`${s.grid} ${s.axis}`}>
        <span />
        <div className={s.ticks}>
          {shownTicks.map((t) => (
            <span key={t} className={s.tick} style={{ left: X(t) }}>
              {t}
            </span>
          ))}
          {budget != null && (
            <span className={`${s.tick} ${s.budgetTick}`} style={{ left: X(budget) }}>
              budget {budget}
            </span>
          )}
        </div>
        <span>{unit}</span>
      </div>
    </div>
  )
}
