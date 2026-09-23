import type { SortDir } from '../hooks/useSort'
import s from './SortHeader.module.css'

/** A table header cell that sorts. The active column is full-strength text
 *  with an arrow; `aria-sort` belongs on the surrounding columnheader. */
export function SortHeader({ label, active, dir, onClick, align = 'left' }: { label: string; active: boolean; dir: SortDir; onClick: () => void; align?: 'left' | 'right' }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`Sort by ${label}${active ? (dir === 'asc' ? ', ascending' : ', descending') : ''}`}
      className={[s.btn, active && s.active, align === 'right' && s.right].filter(Boolean).join(' ')}
    >
      {label} {active ? (dir === 'asc' ? '↑' : '↓') : ''}
    </button>
  )
}
