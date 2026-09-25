import { Fragment } from 'react'
import type { ComparePayload, DiffVerdict } from '@/api/types'
import { DiffTag, TableCard, Term, Text, numCell } from '@/design'
import { fmt, signed, stepName } from '@/domain/format'
import { METRICS } from '@/domain/metrics'
import s from './ComparisonTables.module.css'

const toDiff = (v: DiffVerdict | null) => (v === 'worse' ? 'worse' : v === 'better' ? 'better' : 'same')

/** Stability rows in a compare (store.METRIC_DIRECTION): not headline gates. */
const STABILITY_LABELS: Record<string, string> = { hang_count: 'Hangs', longest_hang_ms: 'Longest hang', js_errors: 'JS errors' }

const metricLabel = (m: string) => METRICS.find((x) => x.key === m)?.label ?? STABILITY_LABELS[m] ?? m

/** Two runs side by side, as store.compare returns them: the top-line metrics,
 *  then each step with its child slices. Used by Compare (Run A vs Run B) and
 *  by a run's AI summary (the run vs its pinned benchmark). */
export function ComparisonTables({
  data,
  runLabel,
  baseLabel,
  descriptions,
  hl,
}: {
  data: ComparePayload
  /** Column headings, e.g. "Run A #12" and "Benchmark #9". */
  runLabel: string
  baseLabel: string
  /** Plain-language description per step name, shown on hover. */
  descriptions: Record<string, string>
  /** A highlight id for the first table (deep links ring it). */
  hl?: string
}) {
  const d = data
  return (
    <>
      <TableCard
        data-hl={hl}
        title="Top-line metrics"
        minWidth={720}
        aside={
          <Text variant="meta">
            {d.summary.worse} worse · {d.summary.better} better · {d.summary.same} same
          </Text>
        }
      >
        <thead>
          <tr>
            <th>Metric</th>
            <th className={numCell}>{runLabel}</th>
            <th className={numCell}>{baseLabel}</th>
            <th className={numCell}>Δ</th>
            <th className={numCell}>Δ %</th>
            <th className={numCell}>Result</th>
          </tr>
        </thead>
        <tbody>
          {d.metrics.map((m) => {
            const def = METRICS.find((x) => x.key === m.metric)
            const dp = def?.dp ?? 1
            return (
              <tr key={m.metric}>
                <td>
                  <Text variant="body" tone="primary" weight={500}>
                    {metricLabel(m.metric)}
                  </Text>
                </td>
                <td className={numCell}>{m.value == null ? '–' : `${fmt(m.value, dp)} ${def?.unit ?? ''}`}</td>
                <td className={numCell}>
                  <Text variant="body">{m.base_value == null ? '–' : `${fmt(m.base_value, dp)} ${def?.unit ?? ''}`}</Text>
                </td>
                <td className={numCell}>{m.delta == null ? '–' : signed(m.delta, dp, def?.deltaUnit ?? '')}</td>
                <td className={numCell}>{m.delta_pct == null ? '–' : signed(m.delta_pct, 1, '%')}</td>
                <td className={numCell}>{m.verdict ? <DiffTag diff={toDiff(m.verdict)} /> : '–'}</td>
              </tr>
            )
          })}
        </tbody>
      </TableCard>
      <TableCard title="Steps diff" hint="Child slices are indented under the step they belong to." minWidth={720}>
        <thead>
          <tr>
            <th>Step</th>
            <th className={numCell}>{runLabel}</th>
            <th className={numCell}>{baseLabel}</th>
            <th className={numCell}>Δ ms</th>
            <th className={numCell}>Δ %</th>
            <th className={numCell}>Result</th>
          </tr>
        </thead>
        <tbody>
          {d.steps.map((st) => (
            <Fragment key={st.step}>
              <tr>
                <td>
                  <Term description={descriptions[st.step]} weight={700}>
                    {stepName(st.step)}
                  </Term>
                </td>
                <td className={numCell}>{st.dur_ms == null ? '–' : `${fmt(st.dur_ms, 1)} ms`}</td>
                <td className={numCell}>
                  <Text variant="body">{st.base_dur_ms == null ? '–' : `${fmt(st.base_dur_ms, 1)} ms`}</Text>
                </td>
                <td className={numCell}>{st.delta_ms == null ? '–' : signed(st.delta_ms, 1)}</td>
                <td className={numCell}>{st.delta_pct == null ? '–' : signed(st.delta_pct, 1, '%')}</td>
                <td className={numCell}>
                  {st.only_in ? <DiffTag diff="same">{st.only_in === 'run' ? 'New' : 'Removed'}</DiffTag> : st.verdict ? <DiffTag diff={toDiff(st.verdict)} /> : '–'}
                </td>
              </tr>
              {(st.children ?? []).map((c) => (
                <tr key={c.name} className={s.childRow}>
                  <td>{c.name}</td>
                  <td className={numCell}>{c.dur_ms == null ? '–' : `${fmt(c.dur_ms, 1)} ms`}</td>
                  <td className={numCell}>{c.base_dur_ms == null ? '–' : `${fmt(c.base_dur_ms, 1)} ms`}</td>
                  <td className={numCell}>{c.delta_ms == null ? '–' : signed(c.delta_ms, 1)}</td>
                  <td className={numCell}>{c.delta_pct == null ? '–' : signed(c.delta_pct, 1, '%')}</td>
                  <td />
                </tr>
              ))}
            </Fragment>
          ))}
        </tbody>
      </TableCard>
    </>
  )
}
