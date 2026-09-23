import { useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import s from './HelpTip.module.css'

/** A "?" button whose definition shows on hover *and* focus, positioned against
 *  the viewport so a horizontally scrolling table cannot clip it. */
export function HelpTip({ text, label, large }: { text: string; label: string; large?: boolean }) {
  const id = useId()
  const ref = useRef<HTMLButtonElement>(null)
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)

  const show = () => {
    const r = ref.current?.getBoundingClientRect()
    if (!r) return
    const left = Math.min(Math.max(8, r.left + r.width / 2 - 120), window.innerWidth - 248)
    const below = r.bottom + 8
    const top = below + 90 > window.innerHeight ? r.top - 98 : below
    setPos({ top, left })
  }
  const hide = () => setPos(null)

  return (
    <>
      <button
        ref={ref}
        type="button"
        className={`${s.btn} ${large ? s.lg : ''}`}
        aria-label={`What is ${label}?`}
        aria-describedby={pos ? id : undefined}
        aria-expanded={!!pos}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        onClick={(e) => {
          e.stopPropagation()
          if (pos) hide()
          else show()
        }}
      >
        ?
      </button>
      {pos &&
        createPortal(
          <div id={id} role="tooltip" className={s.tip} style={{ top: pos.top, left: pos.left }}>
            {text}
          </div>,
          document.body,
        )}
    </>
  )
}
