import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { ariaSort, type SortDir } from '../hooks/useSort'
import { SortHeader } from './SortHeader'
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

/** The app's table. Rows and cells are plain <thead>/<tr>/<td>; use
 *  `numCell` for right-aligned figures, `selectedRow` (or `aria-current`) for
 *  the row in focus, SortTh for a sortable column, RowAction for a row that
 *  picks something, and TableEmptyRow when there are no rows. `dense` is for
 *  tight spaces (a picker in a popover); `stickyHeader` keeps the header in
 *  view while the rows scroll. */
export function Table({
  minWidth,
  density = 'default',
  stickyHeader,
  label,
  children,
}: {
  minWidth: number
  density?: 'default' | 'dense'
  stickyHeader?: boolean
  label?: string
  children: ReactNode
}) {
  const cls = [s.table, density === 'dense' && s.dense, stickyHeader && s.sticky].filter(Boolean).join(' ')
  return (
    <table className={cls} style={{ minWidth }} aria-label={label}>
      {children}
    </table>
  )
}

/** A titled card holding a horizontally scrollable Table. */
export function TableCard({ minWidth, children, ...rest }: { title?: ReactNode; hint?: ReactNode; aside?: ReactNode; minWidth: number; children: ReactNode; 'data-hl'?: string }) {
  return (
    <FlushCard {...rest}>
      <Table minWidth={minWidth}>{children}</Table>
    </FlushCard>
  )
}

/** A header cell that sorts its table, driven by useSort's `sort` and `toggle`. */
export function SortTh<K extends string>({
  label,
  sortKey,
  sort,
  onSort,
  align = 'left',
}: {
  label: string
  sortKey: K
  sort: { key: K; dir: SortDir }
  onSort: (key: K) => void
  align?: 'left' | 'right'
}) {
  const active = sort.key === sortKey
  return (
    <th aria-sort={ariaSort(active, sort.dir)} className={align === 'right' ? s.num : undefined}>
      <SortHeader label={label} active={active} dir={sort.dir} align={align} onClick={() => onSort(sortKey)} />
    </th>
  )
}

/** What a whole row stands for (show this run): a text button whose click
 *  area covers its row, so a click anywhere on the row picks it and the row
 *  is one tab stop. Other controls in the row sit above it. */
export function RowAction({ className, type = 'button', ...rest }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button type={type} className={className ? `${s.rowAction} ${className}` : s.rowAction} {...rest} />
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
