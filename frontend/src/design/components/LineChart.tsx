import { useMemo, useState, type KeyboardEvent } from 'react'
import s from './LineChart.module.css'

export interface Series {
  name: string
  color: string
  /** One value per label; null is a gap (an unmeasured run), not zero. */
  values: (number | null)[]
}

/** "Nice" ticks at 1/2/5 x 10^n: the largest such step that still puts at
 *  least three ticks in the range (the handoff asks for 3-4). */
export function niceTicks(lo: number, hi: number): number[] {
  const span = hi - lo || 1
  const pw = Math.pow(10, Math.floor(Math.log10(span)))
  const count = (st: number) => Math.floor(hi / st + 1e-9) - Math.ceil(lo / st - 1e-9) + 1
  const steps = [10, 5, 2, 1, 0.5, 0.2, 0.1].map((m) => m * pw)
  const step = steps.find((st) => count(st) >= 3) ?? steps[steps.length - 1]!
  const out: number[] = []
  for (let v = Math.ceil(lo / step - 1e-9) * step; v <= hi + 1e-9; v += step) out.push(Number(v.toPrecision(12)))
  return out
}

export function LineChart({
  series,
  labels,
  budget,
  budgetLabel,
  unit = '',
  height = 200,
  decimals = 0,
  yMin,
  label,
}: {
  series: Series[]
  labels: string[]
  budget?: number | null
  budgetLabel?: string
  unit?: string
  height?: number
  decimals?: number
  yMin?: number
  /** Accessible name for the plot. */
  label: string
}) {
  const [off, setOff] = useState<Record<string, boolean>>({})
  const [hover, setHover] = useState<number | null>(null)
  const vis = series.filter((x) => !off[x.name])
  const n = labels.length || 1
  const fmt = (v: number | null | undefined) => (v == null ? '–' : v.toFixed(decimals))

  const geo = useMemo(() => {
    const vals = vis.flatMap((x) => x.values).filter((v): v is number => v != null)
    if (budget != null) vals.push(budget)
    let lo = vals.length ? Math.min(...vals) : 0
    let hi = vals.length ? Math.max(...vals) : 1
    const pad = (hi - lo) * 0.15 || Math.abs(hi) * 0.1 || 1
    lo = yMin ?? lo - pad
    hi = hi + pad
    const X = (i: number) => (n < 2 ? 50 : (i / (n - 1)) * 100)
    const Y = (v: number) => 100 - ((v - lo) / (hi - lo)) * 100
    return { lo, hi, X, Y }
  }, [vis, budget, yMin, n])
  const { X, Y } = geo

  // A null starts a new sub-path, so a gap shows as a gap.
  const pathFor = (values: (number | null)[]) => {
    let d = ''
    let pen = false
    values.forEach((v, i) => {
      if (v == null) return void (pen = false)
      d += `${pen ? 'L' : 'M'}${X(i).toFixed(2)} ${Y(v).toFixed(2)} `
      pen = true
    })
    return d.trim()
  }
  const lastOf = (values: (number | null)[]) => {
    for (let i = values.length - 1; i >= 0; i--) if (values[i] != null) return values[i]!
    return null
  }

  const step = Math.ceil(n / 7)
  const xl = labels
    .map((t, i) => ({ t, i }))
    .filter((o) => o.i === n - 1 || (o.i % step === 0 && n - 1 - o.i >= step * 0.6))

  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'ArrowRight') setHover((h) => Math.min(n - 1, (h ?? -1) + 1))
    else if (e.key === 'ArrowLeft') setHover((h) => Math.max(0, (h ?? n) - 1))
    else if (e.key === 'Escape') setHover(null)
    else return
    e.preventDefault()
  }

  return (
    <div className={s.wrap}>
      {series.length > 1 && (
        <div className={s.legend}>
          {series.map((x) => (
            <button key={x.name} type="button" className={s.chip} aria-pressed={!off[x.name]} onClick={() => setOff((o) => ({ ...o, [x.name]: !o[x.name] }))}>
              <span className={s.swatch} style={{ background: x.color }} />
              {x.name}
            </button>
          ))}
        </div>
      )}
      <div
        className={s.plot}
        style={{ height }}
        tabIndex={0}
        role="img"
        aria-label={`${label}. Use the arrow keys to read values.`}
        onKeyDown={onKey}
        onBlur={() => setHover(null)}
      >
        {niceTicks(geo.lo, geo.hi).map((v) => (
          <div key={v} className={s.tick} style={{ top: `${Y(v)}%` }}>
            <span className={s.tickLabel}>{Math.abs(geo.hi - geo.lo) < 5 ? v.toFixed(1) : Math.round(v)}</span>
          </div>
        ))}
        {budget != null && (
          <div className={s.budget} style={{ top: `${Y(budget)}%` }}>
            <span className={s.budgetLabel}>{budgetLabel ?? `Budget ${budget}${unit ? ' ' + unit : ''}`}</span>
          </div>
        )}
        <svg className={s.svg} viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          {vis.map((x) => (
            <path key={x.name} d={pathFor(x.values)} fill="none" stroke={x.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
          ))}
        </svg>
        {vis.map((x) => {
          const v = lastOf(x.values)
          return v == null ? null : (
            <div key={x.name} className={s.end} style={{ top: `${Y(v)}%`, color: x.color }}>
              {fmt(v)}
            </div>
          )
        })}
        {vis.length === 0 && <div className={s.none}>No series selected</div>}
        {hover != null && (
          <>
            <div className={s.guide} style={{ left: `${X(hover)}%` }} />
            {vis.map((x) => {
              const v = x.values[hover]
              return v == null ? null : <div key={x.name} className={s.dot} style={{ left: `${X(hover)}%`, top: `${Y(v)}%`, background: x.color }} />
            })}
            <div className={s.tip} style={{ left: `${X(hover)}%`, transform: X(hover) > 65 ? 'translateX(calc(-100% - 12px))' : 'translateX(12px)' }}>
              <div className={s.tipTitle}>{labels[hover]}</div>
              {vis.map((x) => (
                <div key={x.name} className={s.tipRow}>
                  <span className={s.tipDot} style={{ background: x.color }} />
                  <span style={{ color: 'var(--tx2)', flex: 1 }}>{x.name}</span>
                  <span style={{ fontWeight: 600 }}>{x.values[hover] == null ? 'not measured' : `${fmt(x.values[hover])}${unit ? ' ' + unit : ''}`}</span>
                </div>
              ))}
            </div>
          </>
        )}
        <div className={s.hits} onMouseLeave={() => setHover(null)}>
          {labels.map((_, i) => (
            <div key={i} style={{ flex: 1, height: '100%' }} onMouseEnter={() => setHover(i)} />
          ))}
        </div>
      </div>
      <div className={s.xAxis} aria-hidden="true">
        {xl.map((o) => (
          <span key={o.i} className={s.xLabel} style={{ left: `${X(o.i)}%` }}>
            {o.t}
          </span>
        ))}
      </div>
    </div>
  )
}
