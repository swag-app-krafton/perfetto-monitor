import { useEffect, useRef } from 'react'
import { levelOf, type LogLine } from './logLevel'
import s from './LogConsole.module.css'

const fmtT = (t: number) => `${String(Math.floor(t / 60)).padStart(2, '0')}:${(t % 60).toFixed(2).padStart(5, '0')}`

/** Always dark, in both themes. Follows new lines only while the reader is
 *  already at the bottom, so scrolling up to read is not fought. */
export function LogConsole({ lines, running, label = 'Job log' }: { lines: LogLine[]; running?: boolean; label?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  useEffect(() => {
    const el = ref.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [lines.length])
  return (
    <div
      ref={ref}
      role="log"
      aria-live="polite"
      aria-label={label}
      onScroll={(e) => {
        const el = e.currentTarget
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24
      }}
      className={s.console}
    >
      {lines.map((l, i) => {
        const lv = levelOf(l.text)
        const tint = lv === 'WARN' ? s.warn : lv === 'ERROR' ? s.error : null
        return (
          <div key={i} className={tint ? `${s.line} ${tint}` : s.line}>
            <span className={s.time}>{fmtT(l.t)}</span>
            <span className={s.level}>{lv === 'INFO' ? '' : lv}</span>
            <span className={s.text}>{l.text.replace(/^(ERROR|FATAL|warning|note):\s*/i, '')}</span>
          </div>
        )
      })}
      {running && (
        <div className={s.pad}>
          <span className={s.cursor} />
        </div>
      )}
      {!lines.length && !running && <div className={s.empty}>No output yet.</div>}
    </div>
  )
}
