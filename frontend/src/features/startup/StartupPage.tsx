import { useState } from 'react'
import type { Run } from '@/api/types'
import { Card, EmptyState, Grid, LineChart, Segmented, SectionTitle, StackedBars, StatusPill, StatusSquare, type StackRow } from '@/design/components'
import { fmt, signed, stepName } from '@/domain/format'
import { valueOf } from '@/domain/metrics'
import { useScope } from '@/domain/scope'
import { useUi } from '@/app/store'
import { FindingCard } from '@/features/shared/FindingCard'
import { findingArea, findingId } from '@/features/shared/findings'

const SERIES = ['var(--c1)', 'var(--c2)', 'var(--c3)', 'var(--c4)']

export function StartupPage() {
  const { scope, isLoading } = useScope()
  const askCopilot = useUi((s) => s.askCopilot)
  if (isLoading || !scope) return <EmptyState>Loading runs…</EmptyState>
  const { latest, runs, allRuns, benchmarkRun, history } = scope
  if (!latest) return <EmptyState title="No runs yet">Capture a cold start to see its startup here.</EmptyState>

  const prior = allRuns.filter((r) => r.id < latest.id)
  const base = benchmarkRun ?? prior[prior.length - 1] ?? null
  const ttid = valueOf(latest, 'ttff_ms')
  const baseTtid = valueOf(base, 'ttff_ms')
  const budget = latest.ttid_budget_ms
  const findings = (latest.analysis?.findings ?? []).map((f, i) => ({ f, i })).filter(({ f }) => findingArea(f) === 'Startup')
  const model = history.startup_model
  const critical = model.critical_path[latest.path_kind] ?? null

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <Card
        data-hl="ttidChart"
        title="TTID over runs"
        hint={`Time to initial display${latest.app_role === 'own' ? ' (the first usable camera frame)' : ''}.${budget ? ` Dashed line is the ${budget} ms budget.` : ' No budget is set for this app.'}`}
        actions={
          ttid != null && (
            <div style={{ textAlign: 'right' }}>
              <div style={{ font: '700 28px/1 var(--font-display)', color: budget && ttid > budget ? 'var(--fail)' : 'var(--tx)' }}>
                {fmt(ttid)} <span style={{ fontSize: 13, color: 'var(--tx3)' }}>ms</span>
              </div>
              {base && baseTtid != null && (
                <div style={{ fontSize: 12, marginTop: 4, color: ttid > baseTtid ? 'var(--fail)' : 'var(--pass)' }}>
                  {ttid > baseTtid ? '▲' : '▼'} {signed(ttid - baseTtid, 0, ' ms')} vs #{base.id}
                </div>
              )}
            </div>
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
        <Composition runs={runs.slice(-12)} latestId={latest.id} budget={budget} critical={critical} />
        <Ordering run={latest} benchmark={benchmarkRun} critical={critical} deferred={model.deferred_steps} />
      </Grid>

      <SectionTitle>Startup findings</SectionTitle>
      {findings.length === 0 && <EmptyState>No startup findings for run #{latest.id}.</EmptyState>}
      {findings.map(({ f, i }) => (
        <FindingCard key={i} compact finding={f} id={findingId(i)} area="Startup" onAsk={() => askCopilot(`Explain finding ${findingId(i)} on run #${latest.id}: ${f.title}`)} />
      ))}
    </section>
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
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', margin: '0 0 14px' }}>
        {top.map((k) => (
          <span key={k} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--tx2)' }}>
            <span style={{ width: 10, height: 10, background: colors[k] }} />
            {stepName(k)}
          </span>
        ))}
        {hasOther && (
          <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--tx2)' }}>
            <span style={{ width: 10, height: 10, background: 'var(--tx3)' }} />
            Other
          </span>
        )}
      </div>
      {rows.length ? <StackedBars rows={rows} colors={colors} budget={budget} unit="ms" /> : <EmptyState>No runs in range.</EmptyState>}
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
        <span style={{ alignSelf: 'flex-start' }}>
          <StatusPill tone={bad ? 'fail' : 'pass'}>{bad ? `${bad} violation${bad === 1 ? '' : 's'}` : 'No violations'}</StatusPill>
        </span>
        <div style={{ position: 'relative', height: 56, marginTop: 14, borderBottom: '1px solid var(--line2)' }}>
          <div style={{ position: 'absolute', left: 0, width: X(ff), top: 0, bottom: 0, background: 'var(--s2)' }} />
          <div style={{ position: 'absolute', left: X(ff), top: -16, bottom: 0, borderLeft: '2px solid var(--tx)' }}>
            <span style={{ position: 'absolute', left: 6, top: -2, fontSize: 11, fontWeight: 600, whiteSpace: 'nowrap' }}>First frame {fmt(ff)} ms</span>
          </div>
          {items.map((t) => (
            <div key={t.name} title={t.name} style={{ position: 'absolute', left: X(t.at), width: X(Math.max(t.dur, span / 200)), bottom: 8, height: 14, background: t.before ? 'var(--fail)' : 'var(--pass)' }} />
          ))}
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--tx3)', marginTop: -8 }}>
          <span>0 ms</span>
          <span>{fmt(span / 2)}</span>
          <span>{fmt(span)} ms</span>
        </div>
        <div>
          {items.length === 0 && <div style={{ fontSize: 13, color: 'var(--tx3)', paddingTop: 8 }}>No deferred work recorded in this run.</div>}
          {items.map((t) => (
            <div key={t.name} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 0', borderTop: '1px solid var(--line)', fontSize: 13 }}>
              <StatusSquare tone={t.before ? 'fail' : 'pass'} size={18} fontSize={10} />
              <span style={{ flex: 1, fontWeight: 500, minWidth: 0 }}>{t.name}</span>
              <span style={{ color: 'var(--tx2)', fontSize: 12 }}>
                starts {fmt(t.at)} ms · {fmt(t.dur)} ms
              </span>
              <span style={{ width: 124, textAlign: 'right', fontSize: 12, color: t.before ? 'var(--fail)' : 'var(--pass)' }}>
                {t.before ? 'Before first frame' : 'After first frame'}
              </span>
            </div>
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
      style={{ display: 'flex', flexDirection: 'column', gap: 16 }}
    >
      {body()}
    </Card>
  )
}
