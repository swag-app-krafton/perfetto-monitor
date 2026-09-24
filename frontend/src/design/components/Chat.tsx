import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Icon, type IconName } from './Icon'
import s from './Chat.module.css'

/** A ringed circle holding an icon: the identity of an assistant or bot. */
export const Avatar = ({ icon = 'sparkle', size = 24 }: { icon?: IconName; size?: number }) => (
  <span className={s.avatar} style={{ width: size, height: size }} aria-hidden="true">
    <Icon name={icon} size={Math.round(size * 0.44)} />
  </span>
)

/** A message the user sent, right-aligned. Keeps the user's line breaks. */
export const Bubble = ({ children }: { children: ReactNode }) => <div className={s.bubble}>{children}</div>

/** The floating action pill in the bottom-right corner. */
export const Fab = ({ className, type = 'button', ...rest }: ButtonHTMLAttributes<HTMLButtonElement>) => (
  <button type={type} className={`${s.fab} ${className ?? ''}`} {...rest} />
)

/** A full-width row button: an outlined suggestion, or a plain list entry
 *  (`current` highlights the open one). */
export function ListButton({ title, description, trailing, variant = 'outlined', current, className, type = 'button', ...rest }: Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'title'> & { title: ReactNode; description?: ReactNode; trailing?: ReactNode; variant?: 'outlined' | 'plain'; current?: boolean }) {
  return (
    <button type={type} className={`${s.listButton} ${s[variant]} ${className ?? ''}`} aria-current={current || undefined} {...rest}>
      <span className={s.lbBody}>
        <span className={s.lbTitle}>{title}</span>
        {description && <span className={s.lbDesc}>{description}</span>}
      </span>
      {trailing && (
        <span className={s.trailing} aria-hidden="true">
          {trailing}
        </span>
      )}
    </button>
  )
}

