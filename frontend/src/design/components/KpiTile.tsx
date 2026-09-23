import type { ReactNode } from 'react'
import { HelpTip } from './HelpTip'
import { Sparkline } from '../charts/Sparkline'
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
        <span>{label}</span>
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
            <span className={`${s.deltaVal} ${same ? s.same : worse ? s.worse : s.better}`}>
              {same ? '= ' : worse ? '▲ ' : '▼ '}
              {delta.text}
            </span>{' '}
            {delta.against && <span className={s.aside}>{delta.against}</span>}
          </>
        )}
        {!delta && note && <span className={s.aside}>{note}</span>}
      </div>
      {trend && <Sparkline values={trend} label={`${label}, last ${trend.length} runs`} />}
    </div>
  )
}
