import type { CSSProperties, ReactNode } from 'react'
import { ariaSort, type SortDir } from '../hooks/useSort'
import { Text } from '../primitives/Text'
import { HelpTip } from './HelpTip'
import { SortHeader } from './SortHeader'
import s from './ExpandableTable.module.css'

export interface ExpandableColumn<K extends string = string> {
  key: string
  label: string
  /** The column's grid track: '90px', 'minmax(240px, 2fr)'. */
  width: string
  align?: 'left' | 'right'
  /** A plain-language definition, behind a "?" in the header. */
  help?: string
  /** The sort key this column sorts by; without it the column does not sort. */
  sortKey?: K
}

/** A table whose rows open to show detail underneath (a drill-down, a chart
 *  of the row's samples). Each row's toggle is a real button stretched over
 *  the whole row, so a click anywhere opens it and the row is one tab stop;
 *  controls inside a cell (a "?") sit above it and keep their own clicks.
 *  Columns are grid tracks, so figures line up across rows and the detail
 *  can span the full width. */
export function ExpandableTable<T, K extends string = string>({
  label,
  columns,
  rows,
  rowKey,
  cells,
  detail,
  openKey,
  onToggle,
  toggleLabel,
  sort,
  minWidth,
  rowAttrs,
}: {
  /** Accessible name for the table. */
  label: string
  columns: ExpandableColumn<K>[]
  rows: T[]
  rowKey: (row: T) => string
  /** One node per column, in column order. */
  cells: (row: T) => ReactNode[]
  detail: (row: T) => ReactNode
  openKey: string | null
  onToggle: (key: string) => void
  /** The row's name for its toggle, as a screen reader hears it. */
  toggleLabel: (row: T) => string
  sort?: { key: K; dir: SortDir; onSort: (key: K) => void }
  minWidth: number
  /** Extra attributes for a row's wrapper (a `data-hl` highlight target). */
  rowAttrs?: (row: T) => Record<`data-${string}`, string>
}) {
  const style = { minWidth, '--cols': `36px ${columns.map((c) => c.width).join(' ')}` } as CSSProperties
  return (
    <div role="table" aria-label={label} style={style}>
      <div role="row" className={`${s.cols} ${s.head}`}>
        <span role="columnheader">
          <span className="visually-hidden">Details</span>
        </span>
        {columns.map((c) => {
          const active = !!sort && c.sortKey != null && sort.key === c.sortKey
          return (
            <span key={c.key} role="columnheader" aria-sort={sort && c.sortKey != null ? ariaSort(active, sort.dir) : undefined} className={c.align === 'right' ? `${s.th} ${s.right}` : s.th}>
              {sort && c.sortKey != null ? (
                <SortHeader label={c.label} active={active} dir={sort.dir} align={c.align} onClick={() => sort.onSort(c.sortKey!)} />
              ) : (
                <Text as="span" variant="th">
                  {c.label}
                </Text>
              )}
              {c.help && <HelpTip text={c.help} label={c.label} />}
            </span>
          )
        })}
      </div>
      {rows.map((row) => {
        const key = rowKey(row)
        const open = openKey === key
        return (
          <div key={key} role="rowgroup" className={s.group} {...rowAttrs?.(row)}>
            <div role="row" className={open ? `${s.cols} ${s.row} ${s.open}` : `${s.cols} ${s.row}`}>
              <span role="cell" className={s.chevron}>
                <button type="button" className={s.toggle} aria-expanded={open} aria-label={toggleLabel(row)} onClick={() => onToggle(key)}>
                  <span aria-hidden="true">{open ? '▾' : '▸'}</span>
                </button>
              </span>
              {cells(row).map((cell, i) => (
                <span key={columns[i]?.key ?? i} role="cell" className={columns[i]?.align === 'right' ? `${s.cell} ${s.right}` : s.cell}>
                  {cell}
                </span>
              ))}
            </div>
            {open && (
              <div role="row">
                <div role="cell" className={s.detail}>
                  {detail(row)}
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
