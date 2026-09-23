import { useState } from 'react'
import { Chip, ChipButton, Menu, PanelBar, Text } from '@/design'
import { chipKey } from './chat'
import type { Reference } from './context'
import type { ContextItem } from './types'

/** The context sent with every question, as removable chips, and a menu to
 *  add more from what is in scope. */
export function ContextBar({ items, references, onAdd, onRemove }: { items: ContextItem[]; references: Reference[]; onAdd: (c: ContextItem) => void; onRemove: (c: ContextItem) => void }) {
  const [open, setOpen] = useState(false)
  const present = new Set(items.map(chipKey))
  const avail = references.filter((r) => !present.has(chipKey(r.item)))
  // A short menu: a few recent runs, the steps that moved most, the findings.
  const pickFrom = (kind: Reference['kind'], n: number) => avail.filter((r) => r.kind === kind).slice(0, n)
  const options = [...pickFrom('Benchmark', 1), ...pickFrom('Run', 3), ...pickFrom('Step', 2), ...pickFrom('Finding', 2)]
  return (
    <PanelBar>
      <Text variant="label">Context</Text>
      {items.map((c) => (
        <Chip key={chipKey(c)} onRemove={() => onRemove(c)} removeLabel={`Remove ${c.label} from context`}>
          {c.label}
        </Chip>
      ))}
      <ChipButton aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen(!open)}>
        + Add
      </ChipButton>
      <Menu
        inset={14}
        open={open}
        onClose={() => setOpen(false)}
        label="Add context"
        emptyText="Everything in scope is already in context."
        options={options.map((r) => ({ key: chipKey(r.item), kind: r.kind, label: r.item.label }))}
        onPick={(o) => {
          const r = options.find((x) => chipKey(x.item) === o.key)
          if (r) onAdd(r.item)
          setOpen(false)
        }}
      />
    </PanelBar>
  )
}
