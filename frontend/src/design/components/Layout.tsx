import type { CSSProperties, HTMLAttributes, ReactNode } from 'react'
import { StatusSquare } from './Status'
import type { Tone } from './tone'
import s from './Layout.module.css'

export function Card({
  title,
  hint,
  actions,
  edge,
  children,
  className,
  style,
  ...rest
}: {
  title?: ReactNode
  hint?: ReactNode
  actions?: ReactNode
  /** A coloured rule on one side: a verdict, a severity, a series. */
  edge?: { side: 'top' | 'left'; color: string; width?: 3 | 4 }
} & HTMLAttributes<HTMLElement>) {
  const edgeStyle = edge ? { [edge.side === 'top' ? 'borderTop' : 'borderLeft']: `${edge.width ?? 4}px solid ${edge.color}` } : undefined
  return (
    <section className={`${s.card} ${className ?? ''}`} style={edgeStyle || style ? { ...edgeStyle, ...style } : undefined} {...rest}>
      {(title || actions) && (
        <div className={s.cardHead}>
          <div className={s.cardHeadText}>
            {title && <h2 className={s.cardTitle}>{title}</h2>}
            {hint && <p className={s.cardHint}>{hint}</p>}
          </div>
          {actions}
        </div>
      )}
      {children}
    </section>
  )
}

export const Eyebrow = ({ children, style }: { children: ReactNode; style?: CSSProperties }) => (
  <div className={s.eyebrow} style={style}>
    {children}
  </div>
)

export const Label = ({ children, style }: { children: ReactNode; style?: CSSProperties }) => (
  <div className={s.label} style={style}>
    {children}
  </div>
)

export const SectionTitle = ({ children, aside }: { children: ReactNode; aside?: ReactNode }) => (
  <div className={s.sectionRow}>
    <h2 className={s.section}>{children}</h2>
    {aside && <span className={s.sectionAside}>{aside}</span>}
  </div>
)

/** Auto-fit grid: columns wrap as the main column narrows (Copilot open, etc.). */
export const Grid = ({ min, gap = 20, children }: { min: number; gap?: number; children: ReactNode }) => (
  <div className={s.grid} style={{ gap, gridTemplateColumns: `repeat(auto-fit, minmax(min(100%, ${min}px), 1fr))` }}>
    {children}
  </div>
)

export function EmptyState({ title, children, actions, align = 'center' }: { title?: string; children?: ReactNode; actions?: ReactNode; align?: 'center' | 'start' }) {
  return (
    <div className={`${s.empty} ${align === 'start' ? s.emptyStart : ''}`}>
      {title && <div className={s.emptyTitle}>{title}</div>}
      {children}
      {actions && <div className={s.emptyActions}>{actions}</div>}
    </div>
  )
}

/** A status message across a surface. pass/warn/fail carry a glyph square
 *  on a tinted fill; neutral is a dashed outline for "nothing here" states. */
export function Banner({ tone, title, children, actions }: { tone: Tone; title: string; children?: ReactNode; actions?: ReactNode }) {
  return (
    <div role={tone === 'neutral' || tone === 'pass' ? 'status' : 'alert'} className={`${s.banner} ${s[`banner-${tone}`]}`}>
      {tone !== 'neutral' && <StatusSquare tone={tone} size={20} fontSize={11} />}
      <div className={s.bannerBody}>
        <div className={s.bannerTitle}>{title}</div>
        {children && <div className={s.bannerText}>{children}</div>}
        {actions && <div className={s.bannerActions}>{actions}</div>}
      </div>
    </div>
  )
}

export const Progress = ({ pct }: { pct: number }) => (
  <div className={s.progress} role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
    <div style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} />
  </div>
)

export const Spinner = ({ size = 14 }: { size?: number }) => (
  <span className={s.spinner} style={{ width: size, height: size }} aria-hidden="true" />
)

/** A row of small actions under a piece of content, divided from it by a
 *  rule. Wraps on narrow widths. */
export const Toolbar = ({ children, label }: { children: ReactNode; label?: string }) => (
  <div role="toolbar" aria-label={label} className={s.toolbar}>
    {children}
  </div>
)
