import { useState } from 'react'
import type { Run } from '@/api/types'
import { Card, EmptyState, Grid, Legend, LineChart, Row, Segmented, SectionTitle, Stack, StackedBars, StatusPill, StatusSquare, Text, type StackRow } from '@/design'
import { fmt, signed, stepName } from '@/domain/format'
import { valueOf } from '@/domain/metrics'
import { useScope } from '@/domain/scope'
import { useUi } from '@/app/store'
import { FindingCard } from '@/features/shared/FindingCard'
import { findingArea, findingId } from '@/features/shared/findings'
import s from './Startup.module.css'

const SERIES = ['var(--c1)', 'var(--c2)', 'var(--c3)', 'var(--c4)']

export function StartupPage() {
  const { scope, isLoading } = useScope()
  const askCopilot = useUi((s) => s.askCopilot)
  if (isLoading || !scope) return <EmptyState>Loading runs…</EmptyState>
  const { run, runs, allRuns, benchmarkRun, history } = scope
  if (!run) return <EmptyState title="No runs yet">Capture a cold start to see its startup here.</EmptyState>

  const prior = allRuns.filter((r) => r.id < run.id)
  const base = benchmarkRun ?? prior[prior.length - 1] ?? null
  const ttid = valueOf(run, 'ttff_ms')
  const baseTtid = valueOf(base, 'ttff_ms')
  const budget = run.ttid_budget_ms
  const findings = (run.analysis?.findings ?? []).map((f, i) => ({ f, i })).filter(({ f }) => findingArea(f) === 'Startup')
  const model = history.startup_model
  const critical = model.critical_path[run.path_kind] ?? null

  return (
    <Stack as="section" gap={20}>
      <Card
        data-hl="ttidChart"
        title="TTID over runs"
        hint={`Time to initial display${run.app_role === 'own' ? ' (the first usable camera frame)' : ''}.${budget ? ` Dashed line is the ${budget} ms budget.` : ' No budget is set for this app.'}`}
        actions={
          ttid != null && (
            <Stack gap={4} align="end">
              <div className={s.ttid} style={{ color: budget && ttid > budget ? 'var(--fail)' : 'var(--tx)' }}>
                {fmt(ttid)}{' '}
                <Text as="span" variant="heading-xs" tone="muted">
                  ms
                </Text>
              </div>
              {base && baseTtid != null && (
                <Text variant="meta" tone={ttid > baseTtid ? 'fail' : 'pass'}>
                  {ttid > baseTtid ? '▲' : '▼'} {signed(ttid - baseTtid, 0, ' ms')} vs #{base.id}
                </Text>
              )}
            </Stack>
          )
        }
      >
        <LineChart
          label="Time to initial display per run"
          labels={runs.map((r) => `#${r.id}`)}
          series={[{ name: 'TTID', color: 'var(--c1)', values: runs.map((r) => valueOf(r, 'ttff_ms')) }]}
          budget={budget}
          unit="ms"
          height={220}
        />
      </Card>

      <Grid min={440}>
        <Composition runs={runs.slice(-12)} latestId={run.id} budget={budget} critical={critical} />
        <Ordering run={run} benchmark={benchmarkRun} critical={critical} deferred={model.deferred_steps} />
      </Grid>

      <SectionTitle>Startup findings</SectionTitle>
      {findings.length === 0 && <EmptyState>No startup findings for run #{run.id}.</EmptyState>}
      {findings.map(({ f, i }) => (
        <FindingCard key={i} compact finding={f} id={findingId(i)} area="Startup" onAsk={() => askCopilot(`Explain finding ${findingId(i)} on run #${run.id}: ${f.title}`)} />
      ))}
    </Stack>
  )
}

/** Each run's startup split by its recorded steps. The four steps that take the
 *  most time get the series colours; everything else folds into "Other". */
function Composition({ runs, latestId, budget, critical }: { runs: Run[]; latestId: number; budget: number | null; critical: string[] | null }) {
  const onPath = (step: string) => !critical || critical.includes(step)
  const totals = new Map<string, number>()
  for (const r of runs) for (const st of r.steps) if (onPath(st.step)) totals.set(st.step, (totals.get(st.step) ?? 0) + st.dur_ms)
  const top = [...totals.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4).map(([k]) => k)
  const colors = Object.fromEntries(top.map((k, i) => [k, SERIES[i]!]))
  const hasOther = totals.size > top.length

  const rows: StackRow[] = runs.map((r) => {
    const total = valueOf(r, 'ttff_ms')
    return {
      id: String(r.id),
      label: `#${r.id}`,
      bold: r.id === latestId,
      segments: r.steps.filter((st) => onPath(st.step)).map((st) => ({ key: st.step, value: st.dur_ms, title: `${stepName(st.step)} · ${fmt(st.dur_ms, 1)} ms` })),
      total,
      totalText: total == null ? '–' : `${fmt(total)} ms`,
      over: budget != null && total != null && total > budget,
    }
  })

  return (
    <Card data-hl="compose" title="Critical-path composition" hint={`Last ${runs.length} runs, each split by its startup steps. Time no step accounts for is left as a gap.`}>
      <Stack gap={14}>
        <Legend items={[...top.map((k) => ({ label: stepName(k), color: colors[k]! })), ...(hasOther ? [{ label: 'Other', color: 'var(--tx3)' }] : [])]} />
        {rows.length ? <StackedBars rows={rows} colors={colors} budget={budget} unit="ms" /> : <EmptyState>No runs in range.</EmptyState>}
      </Stack>
    </Card>
  )
}

/** Deferred work must start after the first frame -- when the app states which
 *  work is deferred. A run derived from Android's own launch slices has no such
 *  statement, and says so rather than showing an empty pass. */
function Ordering({ run, benchmark, critical, deferred }: { run: Run; benchmark: Run | null; critical: string[] | null; deferred: string[] }) {
  const [which, setWhich] = useState<'run' | 'bench'>('run')
  const r = which === 'bench' && benchmark ? benchmark : run
  const tasks = r.steps.filter((st) => deferred.includes(st.step))
  const stated = !!critical && !r.derived

  const body = () => {
    if (!stated) {
      return (
        <EmptyState>
          No ordering constraint is stated for this app and path. Steps here are derived from Android's own launch slices, which do not say
          which work is deferred.
        </EmptyState>
      )
    }
    const t0 = Math.min(...r.steps.map((st) => st.start_ms ?? 0))
    const ff = valueOf(r, 'ttff_ms') ?? 0
    const items = tasks.map((st) => {
      const at = (st.start_ms ?? t0) - t0
      return { name: stepName(st.step), at, dur: st.dur_ms, before: at < ff - 1 }
    })
    const span = Math.max(ff, ...items.map((t) => t.at + t.dur), 1) * 1.1
    const X = (v: number) => `${(v / span) * 100}%`
    const bad = items.filter((t) => t.before).length
    return (
      <>
        <div>
          <StatusPill tone={bad ? 'fail' : 'pass'}>{bad ? `${bad} violation${bad === 1 ? '' : 's'}` : 'No violations'}</StatusPill>
        </div>
        <Stack gap={8}>
          <div className={s.track}>
            <div className={s.preFrame} style={{ width: X(ff) }} />
            <div className={s.frameMark} style={{ left: X(ff) }}>
              <Text variant="caption" tone="primary" weight={600} nowrap className={s.frameLabel}>
                First frame {fmt(ff)} ms
              </Text>
            </div>
            {items.map((t) => (
              <div
                key={t.name}
                title={t.name}
                className={s.taskBar}
                style={{ left: X(t.at), width: X(Math.max(t.dur, span / 200)), background: t.before ? 'var(--fail)' : 'var(--pass)' }}
              />
            ))}
          </div>
          <Row justify="between">
            <Text variant="caption">0 ms</Text>
            <Text variant="caption">{fmt(span / 2)}</Text>
            <Text variant="caption">{fmt(span)} ms</Text>
          </Row>
        </Stack>
        <div>
          {items.length === 0 && (
            <Text variant="body" tone="muted" className={s.noTasks}>
              No deferred work recorded in this run.
            </Text>
          )}
          {items.map((t) => (
            <Row key={t.name} gap={10} className={s.task}>
              <StatusSquare tone={t.before ? 'fail' : 'pass'} size={18} fontSize={10} />
              <Text variant="body" tone="primary" weight={500} className={s.taskName}>
                {t.name}
              </Text>
              <Text variant="meta" tone="secondary">
                starts {fmt(t.at)} ms · {fmt(t.dur)} ms
              </Text>
              <Text variant="meta" tone={t.before ? 'fail' : 'pass'} align="right" className={s.taskWhen}>
                {t.before ? 'Before first frame' : 'After first frame'}
              </Text>
            </Row>
          ))}
        </div>
      </>
    )
  }

  return (
    <Card
      data-hl="order"
      title="Ordering constraint"
      hint="Deferred work must start after the first frame."
      actions={
        benchmark ? (
          <Segmented
            label="Which run"
            value={which}
            onChange={setWhich}
            options={[
              { value: 'run', label: `Run #${run.id}` },
              { value: 'bench', label: `Benchmark #${benchmark.id}` },
            ]}
          />
        ) : undefined
      }
      className={s.ordering}
    >
      {body()}
    </Card>
  )
}
