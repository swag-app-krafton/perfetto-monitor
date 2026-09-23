import { useEffect, useRef, type ReactNode } from 'react'
import type { Space } from '../primitives/space'
import s from './Popover.module.css'

/** A surface floating above or below its (position: relative) container,
 *  as wide as the container less `inset` on each side. Closes on a
 *  pointer-down outside that container, or on Escape. */
export function Popover({ open, onClose, placement = 'below', inset = 0, children }: { open: boolean; onClose: () => void; placement?: 'below' | 'above'; inset?: Space; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const container = ref.current?.parentElement
    const down = (e: PointerEvent) => {
      if (container && !container.contains(e.target as Node)) onClose()
    }
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
      }
    }
    document.addEventListener('pointerdown', down)
    document.addEventListener('keydown', key, true)
    return () => {
      document.removeEventListener('pointerdown', down)
      document.removeEventListener('keydown', key, true)
    }
  }, [open, onClose])
  if (!open) return null
  return (
    <div ref={ref} className={`${s.popover} ${s[placement]}`} style={inset ? { left: inset, right: inset } : undefined}>
      {children}
    </div>
  )
}

export interface ListOption {
  key: string
  label: ReactNode
  /** A short category shown in a fixed column before the label (RUN, STEP). */
  kind?: string
  /** A secondary line after the label (a date, a verdict). */
  meta?: ReactNode
}

/** A listbox of options. Selection follows `active`; the owner moves it
 *  (see useListNav) and focus can stay elsewhere, e.g. in a text field that
 *  points here with aria-activedescendant. */
export function OptionList({ id, label, options, active, onPick, onHover, emptyText }: { id: string; label: string; options: ListOption[]; active: number; onPick: (i: number) => void; onHover?: (i: number) => void; emptyText?: string }) {
  if (options.length === 0) return <div className={s.empty}>{emptyText ?? 'Nothing to choose.'}</div>
  return (
    <ul id={id} role="listbox" aria-label={label} className={s.list}>
      {options.map((o, i) => (
        <li
          key={o.key}
          id={`${id}-${i}`}
          role="option"
          aria-selected={i === active}
          className={`${s.option} ${i === active ? s.active : ''}`}
          // Keep focus where it is (a composer), so picking does not blur it.
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => onPick(i)}
          onMouseEnter={() => onHover?.(i)}
        >
          {o.kind && <span className={s.kind}>{o.kind}</span>}
          <span className={s.optLabel}>{o.label}</span>
          {o.meta && <span className={s.meta}>{o.meta}</span>}
        </li>
      ))}
    </ul>
  )
}
