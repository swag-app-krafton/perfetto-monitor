import type { ElementType, HTMLAttributes, ReactNode } from 'react'
import s from './Text.module.css'

export type TextVariant =
  | 'caption'
  | 'meta'
  | 'small'
  | 'body'
  | 'lead'
  | 'ui'
  | 'label'
  | 'eyebrow'
  | 'th'
  | 'mono'
  | 'heading-xs'
  | 'heading-sm'
  | 'heading'
  | 'heading-lg'
  | 'display'
  | 'display-lg'
  | 'headline'
  | 'title'
  | 'stat'
  | 'stat-xl'
  | 'hero'

export type TextTone = 'primary' | 'secondary' | 'muted' | 'accent' | 'pass' | 'warn' | 'fail' | 'inherit'

/** Each role's usual colour, so most call sites name only the role. */
const DEFAULT_TONE: Record<TextVariant, TextTone> = {
  caption: 'muted',
  meta: 'muted',
  small: 'secondary',
  body: 'secondary',
  lead: 'secondary',
  ui: 'primary',
  label: 'muted',
  eyebrow: 'accent',
  th: 'muted',
  mono: 'secondary',
  'heading-xs': 'primary',
  'heading-sm': 'primary',
  heading: 'primary',
  'heading-lg': 'primary',
  display: 'primary',
  'display-lg': 'primary',
  headline: 'primary',
  title: 'primary',
  stat: 'primary',
  'stat-xl': 'primary',
  hero: 'primary',
}

export interface TextProps extends HTMLAttributes<HTMLElement> {
  as?: ElementType
  variant?: TextVariant
  tone?: TextTone
  weight?: 400 | 500 | 600 | 700 | 800
  align?: 'left' | 'center' | 'right'
  truncate?: boolean
  nowrap?: boolean
  /** Long unbroken strings (package names, routes) wrap anywhere. */
  breakAnywhere?: boolean
  preWrap?: boolean
  /** Take the remaining width in a Row. */
  grow?: boolean
  children?: ReactNode
}

/** Roles that are blocks of text by nature render a <div> by default. */
const BLOCK = new Set<TextVariant>(['body', 'lead', 'heading-xs', 'heading-sm', 'heading', 'heading-lg', 'display', 'display-lg', 'headline', 'title', 'hero'])

/** All text in the app: a role from the type scale, a tone, and a few
 *  wrapping options. Pass `as` for semantics (h2, p, label...). */
export function Text({ as, variant = 'body', tone, weight, align, truncate, nowrap, breakAnywhere, preWrap, grow, className, ...rest }: TextProps) {
  const cls = [
    s.text,
    s[variant],
    s[tone ?? DEFAULT_TONE[variant]],
    weight && s[`w${weight}`],
    align && s[align],
    truncate && s.truncate,
    nowrap && s.nowrap,
    breakAnywhere && s.breakAnywhere,
    preWrap && s.preWrap,
    grow && s.grow,
    className,
  ]
    .filter(Boolean)
    .join(' ')
  const As: ElementType = as ?? (BLOCK.has(variant) ? 'div' : 'span')
  return <As className={cls} {...rest} />
}
