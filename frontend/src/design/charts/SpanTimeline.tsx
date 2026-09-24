import { niceScale } from './scale'
import s from './SpanTimeline.module.css'

export interface TimelineSpan {
  key: string
  /** Shown on hover. */
  label: string
  start: number
  dur: number
  tone: 'pass' | 'fail' | 'neutral'
}

/** Spans of work on one time axis from 0, each placed by its start, with an
 *  optional marker (a deadline, the first frame) whose preceding time is
 *  shaded. For "did this start before that moment" questions. */
export function SpanTimeline({ spans, marker, unit, label }: { spans: TimelineSpan[]; marker?: { at: number; label: string } | null; unit: string; label: string }) {
  const end = Math.max(marker?.at ?? 0, ...spans.map((sp) => sp.start + sp.dur), 1)
  const { max, ticks } = niceScale(end, 1.05)
  const pct = (v: number) => `${(v / max) * 100}%`
  // A span too short to see still gets a sliver of width.
  const minDur = max / 200

  return (
    <div role="img" aria-label={label}>
      <div className={marker ? `${s.track} ${s.marked}` : s.track}>
        {marker && (
          <>
            <div className={s.before} style={{ width: pct(marker.at) }} />
            <div className={s.marker} style={{ left: pct(marker.at) }}>
              <span className={s.markerLabel}>{marker.label}</span>
            </div>
          </>
        )}
        {spans.map((sp) => (
          <div key={sp.key} title={sp.label} className={`${s.span} ${s[sp.tone]}`} style={{ left: pct(sp.start), width: pct(Math.max(sp.dur, minDur)) }} />
        ))}
      </div>
      <div className={s.ticks}>
        {ticks.map((t, i) => (
          <span key={t} className={i === 0 ? `${s.tick} ${s.first}` : i === ticks.length - 1 ? `${s.tick} ${s.last}` : s.tick} style={{ left: pct(t) }}>
            {t}
            {i === ticks.length - 1 ? ` ${unit}` : ''}
          </span>
        ))}
      </div>
    </div>
  )
}
