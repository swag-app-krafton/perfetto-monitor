import type { ReactNode } from 'react'
import s from './DescriptionList.module.css'

export interface Description {
  term: string
  value: ReactNode
  /** Identifiers (a fingerprint, a path) read better in the mono face. */
  mono?: boolean
}

/** Label/value pairs in columns that wrap as the space narrows. A value
 *  that was never recorded says so (`missing`), rather than leaving a gap
 *  that reads as zero or as a loading state. */
export function DescriptionList({ items, min = 280, missing = 'not recorded' }: { items: Description[]; min?: number; missing?: string }) {
  return (
    <dl className={s.list} style={{ gridTemplateColumns: `repeat(auto-fill, minmax(min(100%, ${min}px), 1fr))` }}>
      {items.map((it) => {
        const empty = it.value == null || it.value === ''
        return (
          <div key={it.term} className={s.item}>
            <dt className={s.term}>{it.term}</dt>
            <dd className={`${s.value} ${it.mono && !empty ? s.mono : ''} ${empty ? s.missing : ''}`}>{empty ? missing : it.value}</dd>
          </div>
        )
      })}
    </dl>
  )
}
