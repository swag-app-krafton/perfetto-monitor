import type { Tone } from './tone'
import s from './Meter.module.css'

/** A share of a whole: a thin track filled to `value / max`, optionally with
 *  a marker (a baseline) drawn across it. The fill takes a status `tone`, or
 *  a `color` from the data (a series colour). Built from spans so it is valid
 *  inside a button (a clickable table row). */
export function Meter({ value, max = 1, tone, color, marker, height = 4, label }: { value: number; max?: number; tone?: Tone | 'accent'; color?: string; marker?: number | null; height?: 2 | 3 | 4 | 6 | 8; label: string }) {
  const pct = (v: number) => `${Math.max(0, Math.min(100, (v / (max || 1)) * 100))}%`
  return (
    <span className={s.meter} style={{ height }} role="meter" aria-label={label} aria-valuenow={value} aria-valuemin={0} aria-valuemax={max}>
      <span className={`${s.fill} ${tone ? s[tone] : ''}`} style={{ width: pct(value), background: color }} />
      {marker != null && <span className={s.marker} style={{ left: pct(marker) }} aria-hidden="true" />}
    </span>
  )
}
