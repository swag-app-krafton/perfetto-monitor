import type { ReactNode } from 'react'
import s from './DataTable.module.css'

/** A titled card holding a horizontally scrollable table. Rows and cells are
 *  plain <tr>/<td>; use `numCell` for right-aligned figures. */
export function TableCard({ title, hint, aside, minWidth, children, ...rest }: { title?: ReactNode; hint?: ReactNode; aside?: ReactNode; minWidth: number; children: ReactNode; 'data-hl'?: string }) {
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
      <div className={s.scroll}>
        <table className={s.table} style={{ minWidth }}>
          {children}
        </table>
      </div>
    </section>
  )
}

export const numCell = s.num!
