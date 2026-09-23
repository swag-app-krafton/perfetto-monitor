import s from './Sparkline.module.css'

/** A 28px trend line. Needs at least two points; fewer renders nothing. */
export function Sparkline({
  values,
  height = 28,
  color = 'var(--c1)',
  label,
}: {
  values: (number | null)[]
  height?: number
  color?: string
  label?: string
}) {
  const v = values.filter((x): x is number => x != null && Number.isFinite(x))
  if (v.length < 2) return <div style={{ height }} aria-hidden="true" />
  const lo = Math.min(...v)
  const hi = Math.max(...v)
  const d = hi - lo || 1
  const path = v
    .map((y, i) => `${i ? 'L' : 'M'}${((i / (v.length - 1)) * 100).toFixed(1)} ${(height - 2 - ((y - lo) / d) * (height - 4)).toFixed(1)}`)
    .join(' ')
  return (
    <svg className={s.svg} viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" style={{ height }} role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      <path d={path} fill="none" stroke={color} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
    </svg>
  )
}
