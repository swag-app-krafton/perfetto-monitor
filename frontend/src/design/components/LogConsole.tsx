import { useEffect, useRef } from 'react'

export interface LogLine {
  t: number
  text: string
}
export type LogLevel = 'INFO' | 'WARN' | 'ERROR'

/** Level from the line's own prefix, as the job runner writes them. */
export const levelOf = (text: string): LogLevel =>
  /^(ERROR|FATAL)\b/i.test(text) ? 'ERROR' : /^(warning|note|WARN)\b/i.test(text) ? 'WARN' : 'INFO'

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
      style={{ background: 'var(--con-bg)', padding: '10px 0', font: '12px/1.7 var(--font-mono)', color: 'var(--con-tx)', minHeight: 280, maxHeight: 420, overflowY: 'auto' }}
    >
      {lines.map((l, i) => {
        const lv = levelOf(l.text)
        const tint = lv === 'WARN' ? { background: 'rgba(245,184,61,.08)', color: 'var(--con-warn)' } : lv === 'ERROR' ? { background: 'rgba(255,87,115,.10)', color: 'var(--con-err)' } : {}
        return (
          <div key={i} style={{ display: 'flex', gap: 12, padding: '0 14px', ...tint }}>
            <span style={{ color: 'var(--con-dim)', flex: 'none' }}>{fmtT(l.t)}</span>
            <span style={{ width: 40, flex: 'none', fontWeight: 700 }}>{lv === 'INFO' ? '' : lv}</span>
            <span style={{ overflowWrap: 'anywhere' }}>{l.text.replace(/^(ERROR|FATAL|warning|note):\s*/i, '')}</span>
          </div>
        )
      })}
      {running && (
        <div style={{ padding: '0 14px' }}>
          <span className="sp-pulse" style={{ display: 'inline-block', width: 7, height: 14, background: 'var(--con-tx)', animation: 'sp-pulse 1.2s ease-in-out infinite', verticalAlign: 'middle' }} />
        </div>
      )}
      {!lines.length && !running && <div style={{ padding: '0 14px', color: 'var(--con-dim)' }}>No output yet.</div>}
    </div>
  )
}
