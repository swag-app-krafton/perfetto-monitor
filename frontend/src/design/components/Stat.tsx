import type { ReactNode } from 'react'
import { Text } from '../primitives/Text'
import type { Tone } from './tone'
import s from './Stat.module.css'

/** One labelled figure: a caps label over a value and its unit, with an
 *  optional line under it (a delta, a note). A status `tone` colours the
 *  value; pair it with a glyph or words in `note`, never colour alone. */
export function Stat({ label, value, unit, size = 'md', tone, note }: { label: ReactNode; value: ReactNode; unit?: ReactNode; size?: 'sm' | 'md' | 'lg'; tone?: Exclude<Tone, 'neutral'>; note?: ReactNode }) {
  return (
    <div className={s.stat}>
      <Text variant="label">{label}</Text>
      <div className={`${s.value} ${s[size]} ${tone ? s[tone] : ''}`}>
        <span>{value}</span>
        {unit && <span className={s.unit}>{unit}</span>}
      </div>
      {note}
    </div>
  )
}

/** Stats side by side, wrapping as the space narrows. `hairline` joins them
 *  with 1px rules; `boxes` gives each its own border. */
export const StatGrid = ({ children, min = 140, variant = 'hairline' }: { children: ReactNode; min?: number; variant?: 'hairline' | 'boxes' }) => (
  <div className={`${s.grid} ${s[variant]}`} style={{ gridTemplateColumns: `repeat(auto-fit, minmax(min(100%, ${min}px), 1fr))` }}>
    {children}
  </div>
)
