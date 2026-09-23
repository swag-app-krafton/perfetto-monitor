import { useId, useState, type ReactNode } from 'react'
import s from './Disclosure.module.css'

/** A quiet one-line toggle that reveals detail below it ("Queried traces ·
 *  4 steps"). Uncontrolled unless `open`/`onToggle` are given. */
export function Disclosure({ summary, children, defaultOpen = false, open, onToggle }: { summary: ReactNode; children: ReactNode; defaultOpen?: boolean; open?: boolean; onToggle?: (open: boolean) => void }) {
  const [own, setOwn] = useState(defaultOpen)
  const isOpen = open ?? own
  const id = useId()
  const toggle = () => {
    setOwn(!isOpen)
    onToggle?.(!isOpen)
  }
  return (
    <>
      <button type="button" className={s.summary} aria-expanded={isOpen} aria-controls={id} onClick={toggle}>
        {summary}
      </button>
      {isOpen && (
        <div id={id} className={s.panel}>
          {children}
        </div>
      )}
    </>
  )
}
