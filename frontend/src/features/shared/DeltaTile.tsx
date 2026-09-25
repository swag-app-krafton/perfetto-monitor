import { KpiTile } from '@/design'
import { fmt, signed } from '@/domain/format'

/** A count or duration tile with its change against the previous run. */
export function DeltaTile({ label, help, value, base, unit, note }: { label: string; help: string; value: number | null; base: number | null | undefined; unit?: string; note?: string }) {
  return (
    <KpiTile
      label={label}
      help={help}
      value={value == null ? null : fmt(value)}
      unit={unit}
      delta={value != null && base != null ? { value: value - base, text: signed(value - base, 0, unit ? ` ${unit}` : ''), against: `vs ${fmt(base)} in the previous run` } : null}
      note={note}
    />
  )
}
