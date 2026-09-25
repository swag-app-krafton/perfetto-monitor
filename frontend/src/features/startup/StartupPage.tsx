import { useState } from 'react'
import type { Run } from '@/api/types'
import { Card, EmptyState, Grid, Legend, LineChart, Row, Segmented, SectionTitle, SpanTimeline, Stack, StackedBars, StatusPill, StatusSquare, Term, Text, type StackRow } from '@/design'
import { fmt, signed, stepName } from '@/domain/format'
import { valueOf } from '@/domain/metrics'
import { useScope } from '@/domain/scope'
import { useUi } from '@/app/store'
import { FindingCard } from '@/features/shared/FindingCard'
import { findingArea, findingId } from '@/features/shared/findings'
import s from './Startup.module.css'

const SERIES = ['var(--c1)', 'var(--c2)', 'var(--c3)', 'var(--c4)']

/** What startup time measures for this run: the camera frame for our app's
 *  own step markers, the launch phases otherwise. */
const ttidMeaning = (r: Run) =>
  !r.derived && r.app_role === 'own' ? ' (the first usable camera frame)' : r.platform === 'ios' ? ' (process start to the first frame on screen)' : ''

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
        hint={`Time to initial display${ttidMeaning(run)}.${budget ? ` Dashed line is its ${budget} ms North Star target.` : ` ${run.ttid_target_reason ?? 'No startup North Star target is set for this app.'}`}`}
        actions={
          ttid != null && (
            <Stack gap={4} align="end">
              <Text as="div" variant="display-lg" weight={700} tone={budget && ttid > budget ? 'fail' : 'primary'}>
                {fmt(ttid)}{' '}
                <Text as="span" variant="heading-xs" tone="muted">
                  ms
                </Text>
              </Text>
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
        <Composition runs={runs.slice(-12)} latestId={run.id} budget={budget} critical={critical} descriptions={model.step_descriptions} />
        <Ordering run={run} benchmark={benchmarkRun} critical={critical} deferred={model.deferred_steps} descriptions={model.step_descriptions} />
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
function Composition({
  runs,
  latestId,
  budget,
  critical,
  descriptions,
}: {
  runs: Run[]
  latestId: number
  budget: number | null
  critical: string[] | null
  descriptions: Record<string, string>
}) {
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
        <Legend
          items={[
            ...top.map((k) => ({ label: stepName(k), color: colors[k]!, description: descriptions[k] })),
            ...(hasOther ? [{ label: 'Other', color: 'var(--tx3)', description: 'The remaining startup steps, each its own grey segment. Hover a segment for its name.' }] : []),
          ]}
        />
        {rows.length ? <StackedBars rows={rows} colors={colors} budget={budget} unit="ms" /> : <EmptyState>No runs in range.</EmptyState>}
      </Stack>
    </Card>
  )
}

/** Deferred work must start after the first frame -- when the app states which
 *  work is deferred. A run derived from Android's own launch slices has no such
 *  statement, and says so rather than showing an empty pass. */
function Ordering({
  run,
  benchmark,
  critical,
  deferred,
  descriptions,
}: {
  run: Run
  benchmark: Run | null
  critical: string[] | null
  deferred: string[]
  descriptions: Record<string, string>
}) {
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
      return { name: stepName(st.step), description: descriptions[st.step], at, dur: st.dur_ms, before: at < ff - 1 }
    })
    const bad = items.filter((t) => t.before).length
    return (
      <>
        <div>
          <StatusPill tone={bad ? 'fail' : 'pass'}>{bad ? `${bad} violation${bad === 1 ? '' : 's'}` : 'No violations'}</StatusPill>
        </div>
        <SpanTimeline
          label={`Deferred work against the first frame at ${fmt(ff)} ms`}
          marker={{ at: ff, label: `First frame ${fmt(ff)} ms` }}
          spans={items.map((t) => ({ key: t.name, label: t.name, start: t.at, dur: t.dur, tone: t.before ? 'fail' : 'pass' }))}
          unit="ms"
        />
        <div>
          {items.length === 0 && (
            <Text variant="body" tone="muted" className={s.noTasks}>
              No deferred work recorded in this run.
            </Text>
          )}
          {items.map((t) => (
            <Row key={t.name} gap={10} className={s.task}>
              <StatusSquare tone={t.before ? 'fail' : 'pass'} size={18} fontSize={10} />
              <span className={s.taskName}>
                <Term description={t.description} weight={500}>
                  {t.name}
                </Term>
              </span>
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
