import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Swatch } from '../primitives/Swatch'
import s from './Chip.module.css'

/** A pill naming one item in a set (a context item, a filter). Removable
 *  when given `onRemove`; `removeLabel` names what the × removes. */
export function Chip({ children, onRemove, removeLabel, title }: { children: ReactNode; onRemove?: () => void; removeLabel?: string; title?: string }) {
  return (
    <span className={`${s.chip} ${onRemove ? s.removable : ''}`} title={title}>
      <span className={s.text}>{children}</span>
      {onRemove && (
        <button type="button" className={s.remove} onClick={onRemove} aria-label={removeLabel ?? 'Remove'}>
          ×
        </button>
      )}
    </span>
  )
}

/** The dashed pill that adds to a chip set ("+ Add"). */
export const ChipButton = ({ className, type = 'button', ...rest }: ButtonHTMLAttributes<HTMLButtonElement>) => (
  <button type={type} className={`${s.add} ${className ?? ''}`} {...rest} />
)

/** A filter that is on or off (aria-pressed), with an optional colour key
 *  and count. Off is dimmed, never hidden, so it can be turned back on. */
export function ToggleChip({ pressed, onClick, children, color, count }: { pressed: boolean; onClick: () => void; children: ReactNode; color?: string; count?: number }) {
  return (
    <button type="button" className={s.toggle} aria-pressed={pressed} onClick={onClick}>
      {color && <Swatch color={color} size={8} />}
      {children}
      {count != null && <span className={s.count}>{count}</span>}
    </button>
  )
}
