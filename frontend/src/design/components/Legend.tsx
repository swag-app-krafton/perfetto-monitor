import { Row } from '../primitives/Stack'
import { Swatch } from '../primitives/Swatch'
import { Text } from '../primitives/Text'

export interface LegendItem {
  label: string
  color: string
  shape?: 'square' | 'circle'
}

/** A colour key: each item a swatch and its name. Charts with two or more
 *  series always carry one, so identity is never colour alone. */
export const Legend = ({ items, label }: { items: LegendItem[]; label?: string }) => (
  <Row as="ul" gap={12} wrap aria-label={label}>
    {items.map((it) => (
      <Row as="li" key={it.label} gap={6}>
        <Swatch color={it.color} shape={it.shape} />
        <Text variant="meta" tone="secondary">
          {it.label}
        </Text>
      </Row>
    ))}
  </Row>
)
