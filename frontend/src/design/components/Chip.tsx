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
 *  and count. Off is dimmed, never hidden, so it can be turned back on.
 *  `description` is its tooltip; a disabled chip says why in it. */
export function ToggleChip({
  pressed,
  onClick,
  children,
  color,
  count,
  disabled,
  description,
}: {
  pressed: boolean
  onClick: () => void
  children: ReactNode
  color?: string
  count?: number
  disabled?: boolean
  description?: string
}) {
  return (
    <button type="button" className={s.toggle} aria-pressed={pressed} onClick={onClick} disabled={disabled} title={description}>
      {color && <Swatch color={color} size={8} />}
      {children}
      {count != null && <span className={s.count}>{count}</span>}
    </button>
  )
}

export interface ChipOption<T extends string> {
  value: T
  label: string
  description?: string
  count?: number
}

/** A labelled multi-select: one ToggleChip per option. `max` caps how many
 *  can be on; the rest are disabled and say why (`maxNote`) until one is
 *  turned off. `colorOf` keys an option that is on to its series colour. */
export function ChipGroup<T extends string>({
  label,
  options,
  value,
  onChange,
  max,
  maxNote,
  colorOf,
}: {
  label: string
  options: ChipOption<T>[]
  value: T[]
  onChange: (next: T[]) => void
  max?: number
  maxNote?: string
  colorOf?: (v: T) => string | undefined
}) {
  const full = max != null && value.length >= max
  return (
    <div role="group" aria-label={label} className={s.group}>
      <span className={s.groupLabel}>{label}</span>
      {options.map((o) => {
        const on = value.includes(o.value)
        return (
          <ToggleChip
            key={o.value}
            pressed={on}
            disabled={!on && full}
            description={!on && full ? (maxNote ?? `Up to ${max} at once.`) : o.description}
            color={on ? colorOf?.(o.value) : undefined}
            count={o.count}
            onClick={() => onChange(on ? value.filter((v) => v !== o.value) : [...value, o.value])}
          >
            {o.label}
          </ToggleChip>
        )
      })}
    </div>
  )
}
