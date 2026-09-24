import type { ButtonHTMLAttributes } from 'react'
import { Icon, type IconName } from './Icon'
import s from './Button.module.css'

/**
 * primary   accent fill, the one main action on a surface
 * secondary outlined, a second action
 * outline   small outlined link-like action (citations, "Open History")
 * quiet     small text action in a toolbar (Copy, Export .md)
 * inverse   small high-contrast action inside a status block (Retry)
 * mini      small filled action in a card header (Ask Copilot, Pin)
 * ghost     square icon-only; prefer IconButton, which requires a label
 */
export type ButtonVariant = 'primary' | 'secondary' | 'outline' | 'quiet' | 'inverse' | 'mini' | 'ghost'

export function Button({
  variant = 'secondary',
  size = 'md',
  large,
  className,
  type = 'button',
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: 'sm' | 'md'; large?: boolean }) {
  const cls = [s.btn, s[variant], size === 'sm' && s.sm, large && s.large, className].filter(Boolean).join(' ')
  return <button type={type} className={cls} {...rest} />
}

/** An icon-only button. The label is required: it is the accessible name
 *  and the hover title. `pressed` marks a toggle that is on; `outlined`
 *  gives it a border, for a control that stands alone in a bar. */
export function IconButton({
  icon,
  label,
  pressed,
  outlined,
  size = 'md',
  className,
  type = 'button',
  ...rest
}: Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> & { icon: IconName; label: string; pressed?: boolean; outlined?: boolean; size?: 'sm' | 'md' }) {
  return (
    <button
      type={type}
      aria-label={label}
      title={label}
      aria-pressed={pressed}
      className={[s.btn, s.ghost, size === 'sm' && s.ghostSm, outlined && s.outlined, className].filter(Boolean).join(' ')}
      {...rest}
    >
      <Icon name={icon} size={size === 'sm' ? 14 : 16} />
    </button>
  )
}
