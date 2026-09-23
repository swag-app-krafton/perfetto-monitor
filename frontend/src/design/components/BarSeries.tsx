import { useState } from 'react'
import { niceTicks } from './LineChart'

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
      <div style={{ position: 'relative', height, marginLeft: 52, marginRight: 8 }}>
        {niceTicks(0, hi).map((t) => (
          <div key={t} style={{ position: 'absolute', left: 0, right: 0, top: `${Y(t)}%`, borderTop: '1px solid var(--grid)' }}>
            <span style={{ position: 'absolute', right: 'calc(100% + 8px)', top: -8, fontSize: 11, color: 'var(--tx3)' }}>{f(t)}</span>
          </div>
        ))}
        {bars.map((b, i) => (
          <div key={i} style={{ position: 'absolute', left: `${i * w}%`, width: `${w}%`, top: 0, bottom: 0, padding: '0 3px' }} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            {b.value == null ? (
              <div style={{ position: 'absolute', bottom: 2, left: 0, right: 0, textAlign: 'center', color: 'var(--tx3)', fontSize: 11 }}>–</div>
            ) : (
              <div style={{ position: 'absolute', left: 3, right: 3, bottom: 0, top: `${Y(b.value)}%`, background: b.flagged ? 'var(--fail)' : 'var(--c2)', borderRadius: '3px 3px 0 0', opacity: hover == null || hover === i ? 1 : 0.55 }} />
            )}
          </div>
        ))}
        {mean != null && vals.length > 1 && (
          <div style={{ position: 'absolute', left: 0, right: 0, top: `${Y(mean)}%`, borderTop: '1.5px dashed var(--tx2)', pointerEvents: 'none' }}>
            <span style={{ position: 'absolute', right: 0, top: -17, fontSize: 11, color: 'var(--tx2)' }}>
              mean {f(mean)}
              {unit}
            </span>
          </div>
        )}
        {hover != null && bars[hover] && (
          <div style={{ position: 'absolute', top: 8, left: `${(hover + 0.5) * w}%`, transform: (hover + 0.5) * w > 65 ? 'translateX(calc(-100% - 12px))' : 'translateX(12px)', minWidth: 190, padding: '10px 12px', background: 'var(--s2)', border: '1px solid var(--line2)', boxShadow: '0 8px 24px rgba(0,0,0,.35)', pointerEvents: 'none', zIndex: 2, fontSize: 12, lineHeight: 1.7 }}>
            <div style={{ font: '700 12px var(--font-display)', marginBottom: 4 }}>{bars[hover].label}</div>
            {(bars[hover].detail ?? []).map(([k, v]) => (
              <div key={k} style={{ display: 'flex', gap: 10 }}>
                <span style={{ color: 'var(--tx2)', flex: 1 }}>{k}</span>
                <b>{v}</b>
              </div>
            ))}
          </div>
        )}
      </div>
      <div style={{ position: 'relative', height: 16, marginLeft: 52, marginRight: 8 }}>
        {bars.map((b, i) => (
          <span key={i} style={{ position: 'absolute', left: `${(i + 0.5) * w}%`, transform: 'translateX(-50%)', fontSize: 11, color: 'var(--tx3)' }}>
            {b.label.replace(/^.*visit /, '')}
          </span>
        ))}
      </div>
      {caption && <div style={{ textAlign: 'center', fontSize: 11, color: 'var(--tx3)', marginTop: 4 }}>{caption}</div>}
    </div>
  )
}
