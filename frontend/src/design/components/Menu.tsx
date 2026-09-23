import { useEffect, useId, useRef } from 'react'
import { useListNav } from '../hooks/useListNav'
import { OptionList, Popover, type ListOption } from './Popover'
import type { Space } from '../primitives/space'
import s from './Popover.module.css'

/** A pick-one menu opened from a button: a Popover holding an OptionList,
 *  with keyboard focus on the list while it is open. Place it inside the
 *  same position: relative container as its trigger. */
export function Menu({ open, onClose, options, onPick, label, placement, inset, emptyText }: { open: boolean; onClose: () => void; options: ListOption[]; onPick: (o: ListOption) => void; label: string; placement?: 'below' | 'above'; inset?: Space; emptyText?: string }) {
  const id = useId()
  const box = useRef<HTMLDivElement>(null)
  const pick = (i: number) => {
    const o = options[i]
    if (o) onPick(o)
  }
  const nav = useListNav(options.length, { onPick: pick, onClose })
  useEffect(() => {
    if (open) box.current?.focus()
  }, [open])
  return (
    <Popover open={open} onClose={onClose} placement={placement} inset={inset}>
      <div ref={box} tabIndex={-1} className={s.focusBox} aria-activedescendant={options.length ? `${id}-${nav.active}` : undefined} onKeyDown={(e) => nav.onKeyDown(e)}>
        <OptionList id={id} label={label} options={options} active={nav.active} onPick={pick} onHover={nav.setActive} emptyText={emptyText} />
      </div>
    </Popover>
  )
}
