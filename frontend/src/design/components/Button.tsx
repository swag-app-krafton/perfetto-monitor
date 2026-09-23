import type { ButtonHTMLAttributes } from 'react'
import s from './Button.module.css'

export type ButtonVariant = 'primary' | 'secondary' | 'mini' | 'ghost'

export function Button({
  variant = 'secondary',
  large,
  className,
  type = 'button',
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; large?: boolean }) {
  const cls = [s.btn, s[variant], large ? s.large : '', className ?? ''].filter(Boolean).join(' ')
  return <button type={type} className={cls} {...rest} />
}
