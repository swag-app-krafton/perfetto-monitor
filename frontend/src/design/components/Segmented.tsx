import s from './Segmented.module.css'

export interface SegmentOption<T extends string | number> {
  value: T
  label: string
}

export function Segmented<T extends string | number>({
  options,
  value,
  onChange,
  label,
}: {
  options: SegmentOption<T>[]
  value: T
  onChange: (v: T) => void
  label: string
}) {
  return (
    <div role="group" aria-label={label} className={s.group}>
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          className={s.item}
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
