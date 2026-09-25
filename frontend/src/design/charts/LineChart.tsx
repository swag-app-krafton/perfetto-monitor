import { niceTicks } from './scale'
import { useMemo, useState, type KeyboardEvent } from 'react'
import { Swatch } from '../primitives/Swatch'
import s from './LineChart.module.css'

export interface Series {
  name: string
  color: string
  /** One value per label; null is a gap (an unmeasured run), not zero. */
  values: (number | null)[]
  /** One note per label for the tooltip, e.g. "median of 3 runs". */
  notes?: (string | null)[]
}

/** A horizontal reference line: a target, a benchmark, a baseline. */
export interface Reference {
  value: number
  label: string
  /** The series it belongs to: it hides when that series is toggled off. */
  series?: string
  /** The line's colour (its label stays in text ink). Default: the accent. */
  color?: string
  style?: 'dashed' | 'dotted'
}

// Reference labels closer than this (in % of the plot's height) would
// overprint, so each one after the first is nudged down a line.
const LABEL_GAP_PCT = 9

export function LineChart({
  series,
  labels,
  budget,
  budgetLabel,
  references,
  unit = '',
  height = 200,
  decimals = 0,
  yMin,
  label,
}: {
  series: Series[]
  labels: string[]
  /** The North Star target: a dashed accent line. */
  budget?: number | null
  budgetLabel?: string
  /** More reference lines, such as a pinned benchmark per series. */
  references?: Reference[]
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
  const refs = useMemo<Reference[]>(
    () => [
      ...(budget != null ? [{ value: budget, label: budgetLabel ?? `North Star ${budget}${unit ? ' ' + unit : ''}`, style: 'dashed' as const }] : []),
      ...(references ?? []).filter((r) => !r.series || !off[r.series]),
    ],
    [budget, budgetLabel, unit, references, off],
  )

  const geo = useMemo(() => {
    const vals = vis.flatMap((x) => x.values).filter((v): v is number => v != null)
    for (const r of refs) vals.push(r.value)
    let lo = vals.length ? Math.min(...vals) : 0
    let hi = vals.length ? Math.max(...vals) : 1
    const pad = (hi - lo) * 0.15 || Math.abs(hi) * 0.1 || 1
    lo = yMin ?? lo - pad
    hi = hi + pad
    const X = (i: number) => (n < 2 ? 50 : (i / (n - 1)) * 100)
    const Y = (v: number) => 100 - ((v - lo) / (hi - lo)) * 100
    return { lo, hi, X, Y }
  }, [vis, refs, yMin, n])
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
        {placeLabels(refs, Y).map(({ r, shift }, i) => (
          <div
            key={`${r.label}-${i}`}
            className={`${s.ref} ${r.style === 'dotted' ? s.dotted : ''}`}
            style={{ top: `${Y(r.value)}%`, borderTopColor: r.color ?? 'var(--accent)' }}
          >
            {/* A series' own reference is named in the key below the plot:
                beside its line it would sit on the data it is close to. */}
            {!r.series && (
              <span className={s.budgetLabel} style={{ top: -19 + shift }}>
                {r.label}
              </span>
            )}
          </div>
        ))}
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
            <div className={X(hover) > 65 ? `${s.tip} ${s.flip}` : s.tip} style={{ left: `${X(hover)}%` }}>
              <div className={s.tipTitle}>{labels[hover]}</div>
              {vis.map((x) => (
                <div key={x.name} className={s.tipRow}>
                  <Swatch color={x.color} size={8} shape="circle" />
                  <span className={s.tipKey}>{x.name}</span>
                  <span className={s.tipValue}>
                    {x.values[hover] == null ? 'not measured' : `${fmt(x.values[hover])}${unit ? ' ' + unit : ''}`}
                    {x.values[hover] != null && x.notes?.[hover] ? <span className={s.tipNote}> · {x.notes[hover]}</span> : null}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}
        <div className={s.hits} onMouseLeave={() => setHover(null)}>
          {labels.map((_, i) => (
            <div key={i} className={s.hit} onMouseEnter={() => setHover(i)} />
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
      {refs.some((r) => r.series) && (
        <ul className={s.refKey} aria-label="Reference lines">
          {refs
            .filter((r) => r.series)
            .map((r, i) => (
              <li key={`${r.label}-${i}`} className={s.refKeyItem}>
                <span className={`${s.refSwatch} ${r.style === 'dotted' ? s.refSwatchDotted : ''}`} style={{ borderTopColor: r.color ?? 'var(--accent)' }} aria-hidden="true" />
                <span>{r.label}</span>
                <span className={s.refKeyValue}>
                  {fmt(r.value)}
                  {unit ? ' ' + unit : ''}
                </span>
              </li>
            ))}
        </ul>
      )}
    </div>
  )
}

/** Where each reference label goes: above its line, nudged down a line when
 *  it would overprint the label above it. */
function placeLabels(refs: Reference[], Y: (v: number) => number) {
  const order = refs.map((r, i) => ({ r, i, y: Y(r.value) })).sort((a, b) => a.y - b.y)
  const shift = new Map<number, number>()
  let prev = -Infinity
  let stack = 0
  for (const o of order) {
    stack = o.y - prev < LABEL_GAP_PCT ? stack + 1 : 0
    shift.set(o.i, stack * 16)
    prev = o.y
  }
  return refs.map((r, i) => ({ r, shift: shift.get(i) ?? 0 }))
}
