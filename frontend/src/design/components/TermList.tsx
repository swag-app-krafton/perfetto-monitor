import type { ReactNode } from 'react'
import { Text } from '../primitives/Text'
import s from './TermList.module.css'

export interface TermListItem {
  key: string
  /** The name. A string is set as the list's usual term; pass a node to style it yourself. */
  term: ReactNode
  /** A plain-language line under the name. Omit it and the row is the name alone. */
  description?: string | null
  /** Figures after the name, right-aligned, one per column; columns line up across rows. */
  values?: ReactNode[]
}

/** Named rows whose names need explaining: each name with its description as
 *  a quieter second line, and its figures at the right. For short lists that
 *  are read rather than scanned (the stages of a launch). On a narrow screen
 *  the description takes the row's full width. Term is the compact form, for
 *  tables and charts. */
export function TermList({ items, label }: { items: TermListItem[]; label?: string }) {
  const cols = Math.max(0, ...items.map((it) => it.values?.length ?? 0))
  return (
    <ul className={s.list} aria-label={label} style={{ gridTemplateColumns: `minmax(0, 1fr)${' auto'.repeat(cols)}` }}>
      {items.map((it) => (
        <li key={it.key} className={s.row}>
          <div className={s.term}>
            {typeof it.term === 'string' ? (
              <Text variant="body" tone="primary" weight={500}>
                {it.term}
              </Text>
            ) : (
              it.term
            )}
          </div>
          {Array.from({ length: cols }, (_, i) => (
            <div key={i} className={s.value}>
              {it.values?.[i]}
            </div>
          ))}
          {it.description && (
            <Text variant="meta" className={s.description}>
              {it.description}
            </Text>
          )}
        </li>
      ))}
    </ul>
  )
}
