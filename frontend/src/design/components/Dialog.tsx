import { useEffect, useId, useRef, type ReactNode } from 'react'
import { Text } from '../primitives/Text'
import { IconButton } from './Button'
import s from './Dialog.module.css'

/** A modal over the page, on the native <dialog>: focus moves into it and
 *  returns on close, Esc and a click on the backdrop close it. */
export function Dialog({ open, onClose, title, subtitle, children, width = 760 }: { open: boolean; onClose: () => void; title: ReactNode; subtitle?: ReactNode; children: ReactNode; width?: number }) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  useEffect(() => {
    const d = ref.current
    if (!d || typeof d.showModal !== 'function') return
    if (open && !d.open) d.showModal()
    else if (!open && d.open) d.close()
  }, [open])
  return (
    <dialog
      ref={ref}
      className={s.dialog}
      style={{ width: `min(${width}px, calc(100vw - 32px))` }}
      aria-labelledby={titleId}
      onClose={onClose}
      // A click that lands on the <dialog> itself, not its content, is on the backdrop.
      onClick={(e) => e.target === ref.current && onClose()}
    >
      {open && (
        <>
          <div className={s.head}>
            <div className={s.headText}>
              <Text as="h2" id={titleId} variant="heading-lg">
                {title}
              </Text>
              {subtitle && (
                <Text as="p" variant="small" tone="muted">
                  {subtitle}
                </Text>
              )}
            </div>
            <IconButton icon="close" label="Close" onClick={onClose} />
          </div>
          <div className={s.body}>{children}</div>
        </>
      )}
    </dialog>
  )
}
