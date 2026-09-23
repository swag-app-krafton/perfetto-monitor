import { Meter } from '../components/Meter'
import { Term } from '../components/Term'
import { Text } from '../primitives/Text'
import s from './BarList.module.css'

export interface BarListItem {
  label: string
  value: number | null
  /** What the item is, in plain words, behind a "?" beside its name. */
  description?: string | null
}

/** Labelled horizontal bars, largest first: for magnitudes whose names are
 *  too long to sit under columns (threads, screens, files). One series, so no
 *  legend: the card's title names it. Every bar carries its value as text. */
export function BarList({
  items,
  unit = '',
  decimals = 0,
  max,
  limit = 10,
  color = 'var(--c1)',
  label,
  empty = 'Nothing to show.',
}: {
  items: BarListItem[]
  unit?: string
  decimals?: number
  /** The value a full bar stands for; the largest value when omitted. */
  max?: number
  limit?: number
  color?: string
  /** Accessible name for the list. */
  label: string
  empty?: string
}) {
  const shown = items
    .filter((it): it is BarListItem & { value: number } => it.value != null && it.value > 0)
    .sort((a, b) => b.value - a.value)
    .slice(0, limit)
  if (!shown.length)
    return (
      <Text variant="body" tone="muted">
        {empty}
      </Text>
    )
  const top = max ?? Math.max(...shown.map((it) => it.value))
  return (
    <ul className={s.list} aria-label={label}>
      {shown.map((it) => (
        <li key={it.label} className={s.row}>
          <span className={s.name}>
            <Term variant="small" description={it.description} truncate>
              {it.label}
            </Term>
          </span>
          <Meter value={it.value} max={top} color={color} height={8} label={`${it.label}: ${it.value.toFixed(decimals)}${unit}`} />
          <Text variant="small" weight={600} align="right">
            {it.value.toFixed(decimals)}
            {unit}
          </Text>
        </li>
      ))}
    </ul>
  )
}
