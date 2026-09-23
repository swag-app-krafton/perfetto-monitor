import type { ReactNode } from 'react'
import { Text, type TextTone, type TextVariant } from '../primitives/Text'
import { HelpTip } from './HelpTip'
import s from './Term.module.css'

/** A name that may come with a plain-language description, shown behind a
 *  "?" (HelpTip) after the name. For names in dense tables, legends and
 *  charts, where a second line would push the figures apart. Without a
 *  description it is just the name. TermList is the roomy form, with the
 *  description as a second line. */
export function Term({
  children,
  description,
  label,
  variant = 'body',
  tone = 'primary',
  weight,
  truncate,
}: {
  /** The name. It may be a control (a row's toggle): the "?" sits beside it, never inside. */
  children: ReactNode
  description?: string | null
  /** What the "?" is about, for a screen reader: "What is <label>?". Defaults to the name. */
  label?: string
  variant?: TextVariant
  tone?: TextTone
  weight?: 400 | 500 | 600 | 700 | 800
  /** Cut a long name with an ellipsis instead of wrapping it; the "?" stays visible. */
  truncate?: boolean
}) {
  const name = (
    // A cut name shows in full on hover.
    <Text as="span" variant={variant} tone={tone} weight={weight} truncate={truncate} title={truncate && typeof children === 'string' ? children : undefined}>
      {children}
    </Text>
  )
  if (!description) return name
  return (
    <span className={truncate ? s.truncate : s.term}>
      {name}
      <span className={s.tip}>
        <HelpTip label={label ?? (typeof children === 'string' ? children : 'this')} text={description} />
      </span>
    </span>
  )
}
