import type { ReactNode } from 'react'
import { HelpTip } from './HelpTip'
import { Sparkline } from './Sparkline'
import s from './KpiTile.module.css'

export interface Delta {
  /** Signed change; positive = worse for lower-is-better metrics. */
  value: number
  text: string
  /** What it is compared with, e.g. "vs 848 ms". */
  against?: string
}

export function KpiTile({
  label,
  help,
  value,
  unit,
  delta,
  trend,
  lowerIsBetter = true,
  note,
}: {
  label: string
  help?: string
  value: string | null
  unit?: string
  delta?: Delta | null
  trend?: (number | null)[]
  lowerIsBetter?: boolean
  note?: ReactNode
}) {
  const worse = delta ? (lowerIsBetter ? delta.value > 0 : delta.value < 0) : false
  const same = delta ? delta.value === 0 : true
  return (
    <div className={s.tile}>
      <span className={s.label}>
        {label}
        {help && <HelpTip text={help} label={label} large />}
      </span>
      {value == null ? (
        <div className={s.muted}>not measured</div>
      ) : (
        <div className={s.value}>
          <span className={s.num}>{value}</span>
          {unit && <span className={s.unit}>{unit}</span>}
        </div>
      )}
      <div className={s.delta}>
        {delta && (
          <>
            <span className={s.deltaVal} style={{ color: same ? 'var(--tx2)' : worse ? 'var(--fail)' : 'var(--pass)' }}>
              {same ? '= ' : worse ? '▲ ' : '▼ '}
              {delta.text}
            </span>{' '}
            {delta.against && <span style={{ color: 'var(--tx3)' }}>{delta.against}</span>}
          </>
        )}
        {!delta && note && <span style={{ color: 'var(--tx3)' }}>{note}</span>}
      </div>
      {trend && <Sparkline values={trend} label={`${label}, last ${trend.length} runs`} />}
    </div>
  )
}
