import { useEffect } from 'react'
import s from './Toast.module.css'

/** A brief confirmation: bottom-centre, inverted, gone after `duration`.
 *  Pass a new `id` to show the same text again. */
export function Toast({ message, id, onDismiss, duration = 2400 }: { message: string | null; id?: number; onDismiss: () => void; duration?: number }) {
  useEffect(() => {
    if (!message) return
    const t = setTimeout(onDismiss, duration)
    return () => clearTimeout(t)
  }, [message, id, onDismiss, duration])
  return (
    <div role="status" aria-live="polite" className={s.region}>
      {message && <div className={s.toast}>{message}</div>}
    </div>
  )
}
