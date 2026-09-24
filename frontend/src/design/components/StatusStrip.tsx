import type { ReactNode } from 'react'
import { Text } from '../primitives/Text'
import { GLYPH, type Tone } from './tone'
import s from './StatusStrip.module.css'

export interface StatusCell {
  key: string
  tone: Tone
  /** Read out and shown on hover: what the cell is and its status. */
  label: string
  /** The item in view, outlined. */
  current?: boolean
  /** A one-letter note under the cell ("B" for the benchmark). */
  mark?: string
}

/** One cell per item, in order, filled with its status: a verdict per run,
 *  oldest to newest. Warn and fail carry their glyph, so status is never
 *  colour alone. Captions under the ends say what the ends are. */
export function StatusStrip({ cells, label, start, middle, end }: { cells: StatusCell[]; label: string; start?: ReactNode; middle?: ReactNode; end?: ReactNode }) {
  return (
    <div role="group" aria-label={label}>
      <div className={s.strip}>
        {cells.map((c) => (
          <div key={c.key} className={s.col}>
            <span role="img" aria-label={c.label} title={c.label} aria-current={c.current || undefined} className={`${s.cell} ${s[c.tone]}`}>
              {c.tone === 'warn' || c.tone === 'fail' ? GLYPH[c.tone] : ''}
            </span>
            <span className={s.mark}>{c.mark ?? ''}</span>
          </div>
        ))}
      </div>
      {(start || middle || end) && (
        <div className={s.foot}>
          <Text variant="caption">{start}</Text>
          {middle && <Text variant="caption">{middle}</Text>}
          <Text variant="caption">{end}</Text>
        </div>
      )}
    </div>
  )
}
