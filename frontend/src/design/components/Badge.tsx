import type { ReactNode } from 'react'
import s from './Badge.module.css'

/** A small caps marker on a row or card ("PINNED", "B"). Not a status: for
 *  pass/warn/fail use StatusPill, which carries a glyph. */
export const Badge = ({ children, tone = 'neutral', title }: { children: ReactNode; tone?: 'neutral' | 'accent' | 'c1' | 'c4'; title?: string }) => (
  <span className={`${s.badge} ${s[tone]}`} title={title}>
    {children}
  </span>
)
