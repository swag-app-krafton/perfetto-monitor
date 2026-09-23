import s from './MiniBars.module.css'

/** A 72px bar chart for a side panel: one bar per label from a zero
 *  baseline, bars over the budget in the fail colour (and named so in their
 *  tooltip, never colour alone), and a dashed budget line. */
export function MiniBars({ title, labels, values, unit = '', budget, decimals = 0 }: { title: string; labels: string[]; values: (number | null)[]; unit?: string; budget?: number | null; decimals?: number }) {
  const nums = values.filter((v): v is number => v != null)
  const hi = Math.max(...nums, budget ?? 0, 1) * 1.08
  const pct = (v: number) => `${(v / hi) * 100}%`
  const f = (v: number) => `${v.toFixed(decimals)}${unit ? ` ${unit}` : ''}`
  const over = (v: number | null) => budget != null && v != null && v > budget
  const summary = labels.map((l, i) => `${l}: ${values[i] == null ? 'no data' : f(values[i]!)}`).join(', ')
  return (
    <figure className={s.box}>
      <figcaption className={s.title}>{title}</figcaption>
      <div className={s.plot} role="img" aria-label={`${title}. ${summary}${budget != null ? `. Budget ${f(budget)}` : ''}`}>
        {budget != null && (
          <div className={s.budget} style={{ bottom: pct(budget) }}>
            <span className={s.budgetLabel}>Budget {f(budget)}</span>
          </div>
        )}
        {values.map((v, i) => (
          <div
            key={i}
            className={`${s.bar} ${over(v) ? s.over : ''}`}
            style={{ height: v == null ? 0 : pct(v) }}
            title={`${labels[i]}: ${v == null ? 'no data' : f(v)}${over(v) ? ' (over budget)' : ''}`}
          />
        ))}
      </div>
      <div className={s.labels} aria-hidden="true">
        {labels.map((l, i) => (
          <span key={i} className={s.label}>
            {l}
          </span>
        ))}
      </div>
    </figure>
  )
}
