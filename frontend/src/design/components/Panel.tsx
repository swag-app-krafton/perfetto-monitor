import type { ReactNode, Ref } from 'react'
import { ResizeHandle } from './Chat'
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
