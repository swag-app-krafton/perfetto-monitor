import { niceTicks } from './LineChart'

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
  const grid = { display: 'grid', gridTemplateColumns: '44px 1fr 64px', gap: 10, alignItems: 'center' } as const
  return (
    <div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {rows.map((r) => (
          <div key={r.id} style={grid}>
            <span style={{ fontSize: 12, fontWeight: r.bold ? 700 : 400 }}>{r.label}</span>
            <div style={{ position: 'relative', height: 16, display: 'flex', background: 'var(--s2)' }}>
              {r.segments.map((sg, i) => (
                <div
                  key={i}
                  title={sg.title}
                  style={{ width: pct(sg.value), height: '100%', background: colors[sg.key] ?? 'var(--tx3)', borderRight: '1px solid var(--s1)' }}
                />
              ))}
              {budget != null && (
                <div style={{ position: 'absolute', left: pct(budget), top: -3, bottom: -3, borderLeft: '1.5px dashed var(--accent)' }} />
              )}
            </div>
            <span style={{ fontSize: 12, textAlign: 'right', fontWeight: 600, color: r.over ? 'var(--fail)' : 'var(--tx)' }}>{r.totalText}</span>
          </div>
        ))}
      </div>
      <div style={{ ...grid, marginTop: 8, fontSize: 11, color: 'var(--tx3)' }}>
        <span />
        <div style={{ position: 'relative', height: 14 }}>
          {shownTicks.map((t) => (
            <span key={t} style={{ position: 'absolute', left: pct(t), transform: 'translateX(-50%)', whiteSpace: 'nowrap' }}>
              {t}
            </span>
          ))}
          {budget != null && !ticks.includes(budget) && (
            <span style={{ position: 'absolute', left: pct(budget), transform: 'translateX(-50%)', color: 'var(--accent-tx)', whiteSpace: 'nowrap' }}>{budget}</span>
          )}
        </div>
        <span>{unit}</span>
      </div>
    </div>
  )
}
