import type { ReactNode } from 'react'
import s from './DataTable.module.css'

/** A card with a title bar and a flush body: for content that runs to the
 *  card's edges (a table, a grid of expandable rows). The body scrolls
 *  sideways when it is wider than the card. */
export function FlushCard({ title, hint, aside, children, ...rest }: { title?: ReactNode; hint?: ReactNode; aside?: ReactNode; children: ReactNode; 'data-hl'?: string }) {
  return (
    <section className={s.card} {...rest}>
      {(title || aside) && (
        <div className={s.head}>
          <div>
            {title && <div className={s.title}>{title}</div>}
            {hint && <div className={s.hint}>{hint}</div>}
          </div>
          {aside}
        </div>
      )}
      <div className={s.scroll}>{children}</div>
    </section>
  )
}

/** A titled card holding a horizontally scrollable table. Rows and cells are
 *  plain <tr>/<td>; use `numCell` for right-aligned figures, `selectedRow`
 *  for the row in focus, and TableEmptyRow when there are no rows. */
export function TableCard({ minWidth, children, ...rest }: { title?: ReactNode; hint?: ReactNode; aside?: ReactNode; minWidth: number; children: ReactNode; 'data-hl'?: string }) {
  return (
    <FlushCard {...rest}>
      <table className={s.table} style={{ minWidth }}>
        {children}
      </table>
    </FlushCard>
  )
}

/** The one row a table shows when it has none. */
export const TableEmptyRow = ({ colSpan, children }: { colSpan: number; children: ReactNode }) => (
  <tr>
    <td colSpan={colSpan} className={s.empty}>
      {children}
    </td>
  </tr>
)

/** A small bordered table for tight spaces (an answer in a side panel): the
 *  first column is the row's name, the rest are right-aligned figures. */
export function CompactTable({ columns, rows, minWidth = 320, label }: { columns: string[]; rows: ReactNode[][]; minWidth?: number; label?: string }) {
  return (
    <div className={s.compactScroll}>
      <table className={s.compact} style={{ minWidth }} aria-label={label}>
        <thead>
          <tr>
            {columns.map((c, i) => (
              <th key={i} scope="col">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((cell, j) => (j === 0 ? <th key={j} scope="row">{cell}</th> : <td key={j}>{cell}</td>))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
