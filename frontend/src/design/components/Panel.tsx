import { useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode, type Ref } from 'react'
import s from './Panel.module.css'

/** A full-height side panel, docked as a flex sibling of the page so the
 *  page reflows beside it rather than being covered. `fullscreen` takes the
 *  whole viewport instead (phones). Resizable from its left edge when given
 *  `resize`. */
export function DockPanel({ label, width, fullscreen, resize, children }: { label: string; width: number; fullscreen?: boolean; resize?: { min: number; max: number; onResize: (w: number) => void }; children: ReactNode }) {
  return (
    <aside aria-label={label} className={`${s.dock} ${fullscreen ? s.fullscreen : ''}`} style={fullscreen ? undefined : { width }}>
      {resize && !fullscreen && <ResizeHandle value={width} min={resize.min} max={resize.max} onResize={resize.onResize} label={`Resize ${label} panel`} />}
      {children}
    </aside>
  )
}

/** The draggable edge of a panel docked on the right. Reports the width the
 *  panel should take (distance from the pointer to the viewport's right
 *  edge); ←/→ resize by 16px from the keyboard. */
function ResizeHandle({ value, min, max, onResize, label }: { value: number; min: number; max: number; onResize: (width: number) => void; label: string }) {
  const [dragging, setDragging] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const down = (e: PointerEvent) => {
    e.preventDefault()
    ref.current?.setPointerCapture(e.pointerId)
    setDragging(true)
  }
  const move = (e: PointerEvent) => {
    if (dragging) onResize(window.innerWidth - e.clientX)
  }
  const up = (e: PointerEvent) => {
    ref.current?.releasePointerCapture(e.pointerId)
    setDragging(false)
  }
  const key = (e: KeyboardEvent) => {
    const step = { ArrowLeft: 16, ArrowRight: -16 }[e.key as 'ArrowLeft' | 'ArrowRight']
    if (step) {
      e.preventDefault()
      onResize(value + step)
    }
  }
  return (
    <div
      ref={ref}
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={Math.round(value)}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      title="Drag to resize"
      className={s.handle}
      data-dragging={dragging}
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onPointerCancel={up}
      onKeyDown={key}
    >
      <span className={s.grip} />
    </div>
  )
}

/** The panel's 64px header: identity on the left, icon actions on the right. */
export const PanelHeader = ({ leading, title, subtitle, actions }: { leading?: ReactNode; title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) => (
  <div className={s.header}>
    {leading}
    <div className={s.headerText}>
      <div className={s.title}>{title}</div>
      {subtitle && <div className={s.subtitle}>{subtitle}</div>}
    </div>
    {actions}
  </div>
)

/** A strip under the header (filters, context chips). Positioned, so a
 *  Popover inside it anchors to the strip. */
export const PanelBar = ({ children }: { children: ReactNode }) => <div className={s.bar}>{children}</div>

/** The scrolling middle of the panel. */
export const PanelBody = ({ children, compact, label, ref }: { children: ReactNode; compact?: boolean; label?: string; ref?: Ref<HTMLDivElement> }) => (
  <div ref={ref} className={`${s.body} ${compact ? s.compact : ''}`} role={label ? 'region' : undefined} aria-label={label}>
    {children}
  </div>
)

/** The panel's bottom edge (a composer). Positioned, for popovers above it. */
export const PanelFooter = ({ children }: { children: ReactNode }) => <div className={s.footer}>{children}</div>
