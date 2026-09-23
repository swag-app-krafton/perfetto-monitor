import type { ElementType, HTMLAttributes, ReactNode } from 'react'
import type { Space } from './space'
import s from './Stack.module.css'

export interface StackProps extends HTMLAttributes<HTMLElement> {
  as?: ElementType
  direction?: 'column' | 'row'
  gap?: Space
  align?: 'start' | 'center' | 'end' | 'baseline' | 'stretch'
  justify?: 'start' | 'center' | 'end' | 'between'
  wrap?: boolean
  /** Take the remaining space in a parent stack (flex: 1, and may shrink). */
  grow?: boolean
  children?: ReactNode
}

/** One-dimensional layout: children in a column (default) or a row, with a
 *  gap from the spacing scale. Every layout in the app is built from this,
 *  Grid (two-dimensional) and Card, rather than ad-hoc flex styles. */
export function Stack({ as: As = 'div', direction = 'column', gap = 0, align, justify, wrap, grow, className, style, ...rest }: StackProps) {
  const cls = [
    s.stack,
    s[direction],
    align && s[`a-${align}`],
    justify && s[`j-${justify}`],
    wrap && s.wrap,
    grow && s.grow,
    className,
  ]
    .filter(Boolean)
    .join(' ')
  return <As className={cls} style={gap ? { gap, ...style } : style} {...rest} />
}

/** A row with vertically centred children: the common toolbar/label shape. */
export const Row = (p: Omit<StackProps, 'direction'>) => <Stack direction="row" align="center" {...p} />

/** Pushes the siblings after it to the far end of a row. */
export const Spacer = () => <div className={s.spacer} aria-hidden="true" />
