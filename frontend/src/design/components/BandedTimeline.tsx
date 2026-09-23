import { useRef, useState } from 'react'
import { niceTicks } from './LineChart'

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
  const gap = 30
  const span = (t1 - t0) / 1000
  const step = span > 240 ? 60 : span > 90 ? 20 : span > 30 ? 10 : 5
  const secs: number[] = []
  for (let s = 0; s <= span; s += step) secs.push(s)

  const tAt = hx == null ? null : t0 + (hx / 100) * (t1 - t0)
  const near = (pts: [number, number][], t: number) => pts.reduce<[number, number] | null>((best, p) => (!best || Math.abs(p[0] - t) < Math.abs(best[0] - t) ? p : best), null)
  const band = tAt == null ? null : bands.find((b) => tAt >= b.start && tAt <= b.end)

  return (
    <div style={{ position: 'relative' }} aria-label={label} role="img">
      <div ref={ref} style={{ position: 'relative', marginLeft: 48, marginRight: 8 }}>
        {/* band labels, above the first panel, where there is room */}
        <div style={{ position: 'relative', height: 16 }}>
          {bands.map((b, i) =>
            X(b.end) - X(b.start) > 6 ? (
              <span key={i} style={{ position: 'absolute', left: `${X(b.start)}%`, width: `${X(b.end) - X(b.start)}%`, paddingLeft: 4, fontSize: 11, color: 'var(--tx2)', overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>
                {b.label}
              </span>
            ) : null,
          )}
        </div>
        {panels.map((p, pi) => {
          const vals = p.points.map((q) => q[1])
          const hi = Math.max(...vals, 1) * 1.08
          const Y = (v: number) => 100 - (v / hi) * 100
          const ticks = niceTicks(0, hi)
          return (
            <div key={p.label} style={{ position: 'relative', height, marginTop: pi ? gap : 0 }}>
              {bands.map((b, i) => (
                <div key={i} style={{ position: 'absolute', top: 0, bottom: 0, left: `${X(b.start)}%`, width: `${Math.max(X(b.end) - X(b.start), 0.2)}%`, background: i % 2 ? 'var(--s2)' : 'transparent' }} />
              ))}
              {ticks.map((t) => (
                <div key={t} style={{ position: 'absolute', left: 0, right: 0, top: `${Y(t)}%`, borderTop: '1px solid var(--grid)' }}>
                  <span style={{ position: 'absolute', right: 'calc(100% + 8px)', top: -8, fontSize: 11, color: 'var(--tx3)' }}>{Math.round(t)}</span>
                </div>
              ))}
              <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', overflow: 'visible' }} aria-hidden="true">
                <path d={p.points.map((q, i) => `${i ? 'L' : 'M'}${X(q[0]).toFixed(2)} ${Y(q[1]).toFixed(2)}`).join(' ')} fill="none" stroke={p.color} strokeWidth={2} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
              </svg>
              <span style={{ position: 'absolute', left: 0, bottom: -18, fontSize: 11, color: 'var(--tx2)' }}>{p.label}</span>
            </div>
          )
        })}
        <div style={{ position: 'relative', height: 30 }}>
          {secs.map((s) => (
            <span key={s} style={{ position: 'absolute', left: `${X(t0 + s * 1000)}%`, top: 14, transform: 'translateX(-50%)', fontSize: 11, color: 'var(--tx3)' }}>
              {s}s
            </span>
          ))}
        </div>
        {hx != null && <div style={{ position: 'absolute', top: 16, bottom: 30, left: `${hx}%`, borderLeft: '1px dashed var(--tx2)', pointerEvents: 'none' }} />}
        <div
          style={{ position: 'absolute', top: 16, bottom: 30, left: 0, right: 0, cursor: 'crosshair' }}
          onMouseMove={(e) => {
            const r = e.currentTarget.getBoundingClientRect()
            setHx(Math.max(0, Math.min(100, ((e.clientX - r.left) / r.width) * 100)))
          }}
          onMouseLeave={() => setHx(null)}
        />
        {hx != null && tAt != null && (
          <div style={{ position: 'absolute', top: 24, left: `${hx}%`, transform: hx > 65 ? 'translateX(calc(-100% - 12px))' : 'translateX(12px)', minWidth: 170, padding: '10px 12px', background: 'var(--s2)', border: '1px solid var(--line2)', boxShadow: '0 8px 24px rgba(0,0,0,.35)', pointerEvents: 'none', zIndex: 2, fontSize: 12, lineHeight: 1.7 }}>
            <div style={{ font: '700 12px var(--font-display)', marginBottom: 4 }}>{band ? band.label : 'between screens'}</div>
            <div style={{ display: 'flex', gap: 8 }}>
              <span style={{ color: 'var(--tx2)', flex: 1 }}>time</span>
              <b>{((tAt - t0) / 1000).toFixed(1)} s</b>
            </div>
            {panels.map((p) => {
              const q = near(p.points, tAt)
              return (
                <div key={p.label} style={{ display: 'flex', gap: 8 }}>
                  <span style={{ color: 'var(--tx2)', flex: 1 }}>{p.label}</span>
                  <b>{q ? `${Math.round(q[1])}${p.unit}` : '–'}</b>
                </div>
              )
            })}
            {band?.detail && <div style={{ color: 'var(--tx2)', marginTop: 2 }}>{band.detail}</div>}
          </div>
        )}
      </div>
    </div>
  )
}
