import { useRef, type KeyboardEvent, type ReactNode } from 'react'
import { Swatch } from '../primitives/Swatch'
import { Text } from '../primitives/Text'
import s from './ChoiceList.module.css'

export interface Choice<T extends string> {
  value: T
  title: ReactNode
  /** A second line under the title (an id, a path). Wraps anywhere. */
  description?: ReactNode
}

const MOVES: Record<string, (i: number, n: number) => number> = {
  ArrowDown: (i, n) => (i + 1) % n,
  ArrowRight: (i, n) => (i + 1) % n,
  ArrowUp: (i, n) => (i - 1 + n) % n,
  ArrowLeft: (i, n) => (i - 1 + n) % n,
  Home: () => 0,
  End: (_, n) => n - 1,
}

/** Pick one of a list of options too long or too wordy for Segmented (the
 *  installed apps): a radio group of bordered rows, each a title and an
 *  optional second line. One tab stop; the arrow keys move the choice. */
export function ChoiceList<T extends string>({
  label,
  options,
  value,
  onChange,
  maxHeight,
  empty = 'Nothing to choose.',
}: {
  /** Accessible name for the group. */
  label: string
  options: Choice<T>[]
  value: T | null
  onChange: (value: T) => void
  /** Scroll the list past this height. */
  maxHeight?: number
  empty?: ReactNode
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const checked = options.findIndex((o) => o.value === value)
  const tabStop = checked >= 0 ? checked : 0
  const onKeyDown = (e: KeyboardEvent, i: number) => {
    const move = MOVES[e.key]
    if (!move || !options.length) return
    e.preventDefault()
    const next = move(i, options.length)
    onChange(options[next]!.value)
    refs.current[next]?.focus()
  }

  return (
    <div role="radiogroup" aria-label={label} className={s.list} style={maxHeight ? { maxHeight } : undefined}>
      {options.map((o, i) => {
        const on = i === checked
        return (
          <button
            key={o.value}
            ref={(el) => {
              refs.current[i] = el
            }}
            type="button"
            role="radio"
            aria-checked={on}
            tabIndex={i === tabStop ? 0 : -1}
            className={s.option}
            onClick={() => onChange(o.value)}
            onKeyDown={(e) => onKeyDown(e, i)}
          >
            <span aria-hidden="true" className={s.radio}>
              {on && <Swatch color="var(--accent)" shape="circle" size={6} />}
            </span>
            <span className={s.body}>
              <Text as="span" variant="body" tone="primary" weight={600}>
                {o.title}
              </Text>
              {o.description != null && (
                <Text variant="meta" breakAnywhere>
                  {o.description}
                </Text>
              )}
            </span>
          </button>
        )
      })}
      {options.length === 0 && (
        <Text variant="body" tone="muted" className={s.empty}>
          {empty}
        </Text>
      )}
    </div>
  )
}
