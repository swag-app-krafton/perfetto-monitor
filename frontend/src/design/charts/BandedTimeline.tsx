import { useRef, useState } from 'react'
import { niceTicks } from './scale'
import s from './BandedTimeline.module.css'

export interface TimelinePanel {
  label: string
  color: string
  unit: string
  points: [number, number][]
}
export interface TimelineBand {
  start: number
  end: number
  label: string
  detail?: string
}

/** Stacked panels on one shared time axis, with bands (e.g. screen visits)
 *  drawn behind every panel and a single crosshair across all of them. Each
 *  panel has its own y-scale: different units never share an axis. */
export function BandedTimeline({ panels, bands, height = 150, label }: { panels: TimelinePanel[]; bands: TimelineBand[]; height?: number; label: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [hx, setHx] = useState<number | null>(null)
  const all = panels.flatMap((p) => p.points.map((q) => q[0])).concat(bands.flatMap((b) => [b.start, b.end]))
  if (!all.length) return null
  const t0 = Math.min(...all)
  const t1 = Math.max(...all)
  const X = (t: number) => ((t - t0) / Math.max(t1 - t0, 1)) * 100
  const span = (t1 - t0) / 1000
  const step = span > 240 ? 60 : span > 90 ? 20 : span > 30 ? 10 : 5
  const secs: number[] = []
  for (let sec = 0; sec <= span; sec += step) secs.push(sec)

  const tAt = hx == null ? null : t0 + (hx / 100) * (t1 - t0)
  const near = (pts: [number, number][], t: number) => pts.reduce<[number, number] | null>((best, p) => (!best || Math.abs(p[0] - t) < Math.abs(best[0] - t) ? p : best), null)
  const band = tAt == null ? null : bands.find((b) => tAt >= b.start && tAt <= b.end)

  return (
    <div className={s.root} aria-label={label} role="img">
      <div ref={ref} className={s.frame}>
        {/* band labels, above the first panel, where there is room */}
        <div className={s.bandLabels}>
          {bands.map((b, i) =>
            X(b.end) - X(b.start) > 6 ? (
              <span key={i} className={s.bandLabel} style={{ left: `${X(b.start)}%`, width: `${X(b.end) - X(b.start)}%` }}>
                {b.label}
              </span>
            ) : null,
          )}
        </div>
        {panels.map((p) => {
          const vals = p.points.map((q) => q[1])
          const hi = Math.max(...vals, 1) * 1.08
          const Y = (v: number) => 100 - (v / hi) * 100
          const ticks = niceTicks(0, hi)
          return (
            <div key={p.label} className={s.panel} style={{ height }}>
              {bands.map((b, i) => (
                <div key={i} className={i % 2 ? `${s.band} ${s.bandAlt}` : s.band} style={{ left: `${X(b.start)}%`, width: `${Math.max(X(b.end) - X(b.start), 0.2)}%` }} />
              ))}
              {ticks.map((t) => (
                <div key={t} className={s.tick} style={{ top: `${Y(t)}%` }}>
                  <span className={s.tickLabel}>{Math.round(t)}</span>
                </div>
              ))}
              <svg className={s.svg} viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
                <path d={p.points.map((q, i) => `${i ? 'L' : 'M'}${X(q[0]).toFixed(2)} ${Y(q[1]).toFixed(2)}`).join(' ')} fill="none" stroke={p.color} strokeWidth={2} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
              </svg>
              <span className={s.panelLabel}>{p.label}</span>
            </div>
          )
        })}
        <div className={s.xAxis}>
          {secs.map((sec) => (
            <span key={sec} className={s.xLabel} style={{ left: `${X(t0 + sec * 1000)}%` }}>
              {sec}s
            </span>
          ))}
        </div>
        {hx != null && <div className={s.crosshair} style={{ left: `${hx}%` }} />}
        <div
          className={s.hits}
          onMouseMove={(e) => {
            const r = e.currentTarget.getBoundingClientRect()
            setHx(Math.max(0, Math.min(100, ((e.clientX - r.left) / r.width) * 100)))
          }}
          onMouseLeave={() => setHx(null)}
        />
        {hx != null && tAt != null && (
          <div className={hx > 65 ? `${s.tip} ${s.flip}` : s.tip} style={{ left: `${hx}%` }}>
            <div className={s.tipTitle}>{band ? band.label : 'between screens'}</div>
            <div className={s.tipRow}>
              <span className={s.tipKey}>time</span>
              <b>{((tAt - t0) / 1000).toFixed(1)} s</b>
            </div>
            {panels.map((p) => {
              const q = near(p.points, tAt)
              return (
                <div key={p.label} className={s.tipRow}>
                  <span className={s.tipKey}>{p.label}</span>
                  <b>{q ? `${Math.round(q[1])}${p.unit}` : '–'}</b>
                </div>
              )
            })}
            {band?.detail && <div className={s.tipDetail}>{band.detail}</div>}
          </div>
        )}
      </div>
    </div>
  )
}
