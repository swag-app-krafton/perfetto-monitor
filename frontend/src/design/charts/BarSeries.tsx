import { useState } from 'react'
import { niceTicks } from './scale'
import s from './BarSeries.module.css'

export interface Bar {
  label: string
  value: number | null
  /** Drawn in the fail colour, e.g. an outlier. */
  flagged?: boolean
  detail?: [string, string][]
}

/** Vertical bars in order, with an optional dashed mean. A null value is
 *  "no data", drawn as a dash, never as a zero-height bar. */
export function BarSeries({ bars, mean, unit, decimals = 1, height = 200, label, caption }: { bars: Bar[]; mean?: number | null; unit: string; decimals?: number; height?: number; label: string; caption?: string }) {
  const [hover, setHover] = useState<number | null>(null)
  const vals = bars.map((b) => b.value).filter((v): v is number => v != null)
  const hi = Math.max(...vals, mean ?? 0, 1) * 1.08
  const Y = (v: number) => 100 - (v / hi) * 100
  const w = 100 / Math.max(bars.length, 1)
  const f = (v: number) => v.toFixed(decimals)
  return (
    <div role="img" aria-label={label}>
      <div className={s.plot} style={{ height }}>
        {niceTicks(0, hi).map((t) => (
          <div key={t} className={s.tick} style={{ top: `${Y(t)}%` }}>
            <span className={s.tickLabel}>{f(t)}</span>
          </div>
        ))}
        {bars.map((b, i) => (
          <div key={i} className={s.slot} style={{ left: `${i * w}%`, width: `${w}%` }} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            {b.value == null ? (
              <div className={s.noData}>–</div>
            ) : (
              <div className={[s.bar, b.flagged && s.flagged, hover != null && hover !== i && s.dim].filter(Boolean).join(' ')} style={{ top: `${Y(b.value)}%` }} />
            )}
          </div>
        ))}
        {mean != null && vals.length > 1 && (
          <div className={s.mean} style={{ top: `${Y(mean)}%` }}>
            <span className={s.meanLabel}>
              mean {f(mean)}
              {unit}
            </span>
          </div>
        )}
        {hover != null && bars[hover] && (
          <div className={(hover + 0.5) * w > 65 ? `${s.tip} ${s.flip}` : s.tip} style={{ left: `${(hover + 0.5) * w}%` }}>
            <div className={s.tipTitle}>{bars[hover].label}</div>
            {(bars[hover].detail ?? []).map(([k, v]) => (
              <div key={k} className={s.tipRow}>
                <span className={s.tipKey}>{k}</span>
                <b>{v}</b>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className={s.xAxis}>
        {bars.map((b, i) => (
          <span key={i} className={s.xLabel} style={{ left: `${(i + 0.5) * w}%` }}>
            {b.label.replace(/^.*visit /, '')}
          </span>
        ))}
      </div>
      {caption && <div className={s.caption}>{caption}</div>}
    </div>
  )
}
