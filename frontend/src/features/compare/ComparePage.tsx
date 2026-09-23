import { Fragment, useMemo } from 'react'
import { useSearchParams } from 'react-router'
import { useCompare } from '@/api/hooks'
import type { DiffVerdict, Run } from '@/api/types'
import { Banner, Card, DiffTag, EmptyState, Grid, Label, Segmented, SelectField, Spinner, TableCard, numCell } from '@/design/components'
import { fmt, pathLabel, shortDate, signed, stepName } from '@/domain/format'
import { METRICS } from '@/domain/metrics'
import { useScope } from '@/domain/scope'

const toDiff = (v: DiffVerdict | null) => (v === 'worse' ? 'worse' : v === 'better' ? 'better' : 'same')

export function ComparePage() {
  const { scope, isLoading } = useScope()
  const [params, setParams] = useSearchParams()
  const runs = useMemo(() => scope?.allRuns ?? [], [scope])
  const bench = scope?.benchmarkRun ?? null
  const mode = params.get('mode') === 'run' || !bench ? 'run' : 'bench'
  const a = Number(params.get('a')) || scope?.latest?.id || null
  const bParam = Number(params.get('b')) || null
  const b = mode === 'bench' ? (bench?.id ?? null) : (bParam ?? runs.filter((r) => r.id !== a).pop()?.id ?? null)
  const q = useCompare(a, b)

  const set = (k: string, v: string | null) => {
    const next = new URLSearchParams(params)
    if (v == null) next.delete(k)
    else next.set(k, v)
    setParams(next, { replace: true })
  }

  if (isLoading || !scope) return <EmptyState>Loading runs…</EmptyState>
  if (runs.length < 2) return <EmptyState title="Not enough runs">Compare needs at least two runs for this app and path.</EmptyState>
  const runA = a != null ? scope.byId(a) : undefined
  const runB = b != null ? scope.byId(b) : undefined
  const sub = (r?: Run) => (r ? `${shortDate(r.ts, true)} · ${r.device ?? 'unknown device'} · ${r.app_version ?? r.label ?? 'no build'}` : '')
  // Pickers list every run of this app, across paths: comparing a cold run with
  // a warm one is allowed -- the "Not comparable" banner says why it misleads.
  const appRuns = scope.history.runs.filter((r) => r.app_pkg === scope.latest?.app_pkg)
  const opts = [...appRuns].reverse().map((r) => ({ value: String(r.id), label: `#${r.id} · ${shortDate(r.ts)} · ${pathLabel(r.path_kind)} · ${r.label ?? ''}` }))
  const d = q.data
  const label = (m: string) => METRICS.find((x) => x.key === m || (m === 'ttff_ms' && x.key === 'ttff_ms'))?.label ?? m

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div>
        <Segmented
          label="Compare against"
          value={mode}
          onChange={(v) => set('mode', v === 'run' ? 'run' : null)}
          options={[
            ...(bench ? [{ value: 'bench' as const, label: 'vs pinned benchmark' }] : []),
            { value: 'run' as const, label: 'Run A vs Run B' },
          ]}
        />
      </div>
      <Grid min={320}>
        <Card>
          <Label style={{ color: 'var(--c1)' }}>RUN A</Label>
          <div style={{ marginTop: 10 }}>
            <SelectField label="Run" value={String(a)} options={opts} onChange={(v) => set('a', v)} />
          </div>
          <div style={{ fontSize: 12, color: 'var(--tx3)', marginTop: 10 }}>{sub(runA)}</div>
        </Card>
        <Card>
          <Label style={{ color: 'var(--c4)' }}>RUN B</Label>
          <div style={{ marginTop: 10 }}>
            {mode === 'bench' && bench ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, height: 36 }}>
                <span style={{ font: '800 18px var(--font-display)' }}>#{bench.id}</span>
                <span style={{ padding: '2px 8px', borderRadius: 999, background: 'var(--s2)', color: 'var(--c4)', font: '700 11px var(--font-ui)', letterSpacing: '.08em' }}>PINNED</span>
              </div>
            ) : (
              <SelectField label="Run" value={String(b)} options={opts} onChange={(v) => set('b', v)} />
            )}
          </div>
          <div style={{ fontSize: 12, color: 'var(--tx3)', marginTop: 10 }}>{sub(runB)}</div>
        </Card>
      </Grid>

      {a === b && <Banner tone="warn" title="Same run">Run A and Run B are the same run; pick a different one to compare.</Banner>}
      {d && !d.same_device && (
        <Banner tone="warn" title="Different devices">
          #{d.run.id} ran on {d.run.device ?? 'an unknown device'}, #{d.base.id} on {d.base.device ?? 'an unknown device'}. Device classes differ in speed, so part
          of any difference is the hardware.
        </Banner>
      )}
      {d && !d.comparable && (
        <Banner tone="fail" title="Not comparable">
          #{d.run.id} is a {pathLabel(d.run.path_kind).toLowerCase()} run and #{d.base.id} a {pathLabel(d.base.path_kind).toLowerCase()} run. Different startup paths
          measure different work.
        </Banner>
      )}

      {q.isLoading && (
        <EmptyState>
          <Spinner /> &nbsp;Comparing…
        </EmptyState>
      )}
      {q.error && <EmptyState title="Could not compare">{q.error.message}</EmptyState>}
      {d && (
        <>
          <TableCard
            data-hl="compare"
            title="Top-line metrics"
            minWidth={720}
            aside={
              <span style={{ fontSize: 12, color: 'var(--tx3)' }}>
                {d.summary.worse} worse · {d.summary.better} better · {d.summary.same} same
              </span>
            }
          >
            <thead>
              <tr>
                <th>Metric</th>
                <th className={numCell}>Run A #{d.run.id}</th>
                <th className={numCell}>Run B #{d.base.id}</th>
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
                    <td style={{ fontWeight: 500 }}>{label(m.metric)}</td>
                    <td className={numCell}>{m.value == null ? '–' : `${fmt(m.value, dp)} ${def?.unit ?? ''}`}</td>
                    <td className={numCell} style={{ color: 'var(--tx2)' }}>
                      {m.base_value == null ? '–' : `${fmt(m.base_value, dp)} ${def?.unit ?? ''}`}
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
                <th className={numCell}>Run A</th>
                <th className={numCell}>Run B</th>
                <th className={numCell}>Δ ms</th>
                <th className={numCell}>Δ %</th>
                <th className={numCell}>Result</th>
              </tr>
            </thead>
            <tbody>
              {d.steps.map((st) => (
                <Fragment key={st.step}>
                  <tr>
                    <td style={{ fontWeight: 700 }}>{stepName(st.step)}</td>
                    <td className={numCell}>{st.dur_ms == null ? '–' : `${fmt(st.dur_ms, 1)} ms`}</td>
                    <td className={numCell} style={{ color: 'var(--tx2)' }}>
                      {st.base_dur_ms == null ? '–' : `${fmt(st.base_dur_ms, 1)} ms`}
                    </td>
                    <td className={numCell}>{st.delta_ms == null ? '–' : signed(st.delta_ms, 1)}</td>
                    <td className={numCell}>{st.delta_pct == null ? '–' : signed(st.delta_pct, 1, '%')}</td>
                    <td className={numCell}>
                      {st.only_in ? <DiffTag diff="same">{st.only_in === 'run' ? 'New' : 'Removed'}</DiffTag> : st.verdict ? <DiffTag diff={toDiff(st.verdict)} /> : '–'}
                    </td>
                  </tr>
                  {st.children.map((c) => (
                    <tr key={c.name}>
                      <td style={{ paddingLeft: 46, color: 'var(--tx2)' }}>{c.name}</td>
                      <td className={numCell} style={{ color: 'var(--tx2)' }}>
                        {c.dur_ms == null ? '–' : `${fmt(c.dur_ms, 1)} ms`}
                      </td>
                      <td className={numCell} style={{ color: 'var(--tx2)' }}>
                        {c.base_dur_ms == null ? '–' : `${fmt(c.base_dur_ms, 1)} ms`}
                      </td>
                      <td className={numCell} style={{ color: 'var(--tx2)' }}>
                        {c.delta_ms == null ? '–' : signed(c.delta_ms, 1)}
                      </td>
                      <td className={numCell} style={{ color: 'var(--tx2)' }}>
                        {c.delta_pct == null ? '–' : signed(c.delta_pct, 1, '%')}
                      </td>
                      <td />
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </TableCard>
        </>
      )}
    </section>
  )
}
