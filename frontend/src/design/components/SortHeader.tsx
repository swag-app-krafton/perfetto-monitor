import type { SortDir } from '@/lib/useSort'

/** A table header cell that sorts. The active column is full-strength text
 *  with an arrow; `aria-sort` belongs on the surrounding columnheader. */
export function SortHeader({ label, active, dir, onClick, align = 'left' }: { label: string; active: boolean; dir: SortDir; onClick: () => void; align?: 'left' | 'right' }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`Sort by ${label}${active ? (dir === 'asc' ? ', ascending' : ', descending') : ''}`}
      style={{
        display: 'flex',
        justifyContent: align === 'right' ? 'flex-end' : 'flex-start',
        gap: 4,
        width: '100%',
        padding: 0,
        border: 0,
        background: 'transparent',
        color: active ? 'var(--tx)' : 'var(--tx3)',
        font: '600 11px var(--font-ui)',
        letterSpacing: '.08em',
        textTransform: 'uppercase',
        cursor: 'pointer',
        whiteSpace: 'nowrap',
      }}
    >
      {label} {active ? (dir === 'asc' ? '↑' : '↓') : ''}
    </button>
  )
}
