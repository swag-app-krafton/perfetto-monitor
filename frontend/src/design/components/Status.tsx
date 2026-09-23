import type { ReactNode } from 'react'
import s from './Status.module.css'
import { GLYPH, type Tone } from './tone'


export function StatusPill({ tone, children }: { tone: Tone; children?: ReactNode }) {
  return (
    <span className={`${s.pill} ${s[tone]}`}>
      <span aria-hidden="true">{GLYPH[tone]}</span>
      {children ?? (tone === 'neutral' ? '' : tone.toUpperCase())}
    </span>
  )
}

export function StatusSquare({ tone, size = 18, fontSize }: { tone: Tone; size?: number; fontSize?: number }) {
  return (
    <span
      aria-hidden="true"
      className={`${s.square} ${s[`sq-${tone}`]}`}
      style={{ width: size, height: size, fontSize: fontSize ?? Math.round(size * 0.55) }}
    >
      {GLYPH[tone]}
    </span>
  )
}

export type Diff = 'worse' | 'better' | 'same'
const DIFF: Record<Diff, { cls: string; text: string }> = {
  worse: { cls: s.fail!, text: '▲ Worse' },
  better: { cls: s.pass!, text: '▼ Better' },
  same: { cls: s.neutral!, text: '= Same' },
}
export function DiffTag({ diff, children }: { diff: Diff; children?: ReactNode }) {
  return <span className={`${s.tag} ${DIFF[diff].cls}`}>{children ?? DIFF[diff].text}</span>
}

export type SeverityLevel = 'high' | 'medium' | 'low'
const SEV: Record<SeverityLevel, string> = { high: s.fail!, medium: s.warn!, low: s.info! }
export function SeverityPill({ level }: { level: SeverityLevel }) {
  return (
    <span className={`${s.sev} ${SEV[level]}`}>
      <span className={s.dot} aria-hidden="true" />
      {level}
    </span>
  )
}

