import type { CSSProperties, HTMLAttributes, ReactNode } from 'react'
import { StatusSquare, type Tone } from './Status'
import s from './Layout.module.css'

export function Card({
  title,
  hint,
  actions,
  children,
  className,
  style,
  ...rest
}: {
  title?: ReactNode
  hint?: ReactNode
  actions?: ReactNode
} & HTMLAttributes<HTMLElement>) {
  return (
    <section className={`${s.card} ${className ?? ''}`} style={style} {...rest}>
      {(title || actions) && (
        <div className={s.cardHead}>
          <div style={{ minWidth: 0 }}>
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
  <div style={{ display: 'flex', alignItems: 'baseline', gap: 14, flexWrap: 'wrap' }}>
    <h2 className={s.section}>{children}</h2>
    {aside && <span style={{ fontSize: 13, color: 'var(--tx3)' }}>{aside}</span>}
  </div>
)

/** Auto-fit grid: columns wrap as the main column narrows (Copilot open, etc.). */
export const Grid = ({ min, gap = 20, children }: { min: number; gap?: number; children: ReactNode }) => (
  <div className={s.grid} style={{ gap, gridTemplateColumns: `repeat(auto-fit, minmax(min(100%, ${min}px), 1fr))` }}>
    {children}
  </div>
)

export function EmptyState({ title, children, actions }: { title?: string; children?: ReactNode; actions?: ReactNode }) {
  return (
    <div className={s.empty}>
      {title && <div className={s.emptyTitle}>{title}</div>}
      {children}
      {actions && <div className={s.emptyActions}>{actions}</div>}
    </div>
  )
}

export function Banner({ tone, title, children }: { tone: Exclude<Tone, 'neutral' | 'pass'>; title: string; children?: ReactNode }) {
  return (
    <div role="alert" className={s.banner} style={{ borderColor: `var(--${tone})`, background: `var(--${tone}-bg)` }}>
      <StatusSquare tone={tone} size={20} fontSize={11} />
      <div>
        <div className={s.bannerTitle}>{title}</div>
        {children && <div className={s.bannerText}>{children}</div>}
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
