import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { keys, startStress, useDevice, useJob, useRecentJobs, useStress, useStressList } from '@/api/hooks'
import type { StressTest } from '@/api/types'
import { Banner, Button, Card, EmptyState, Progress, Row, Segmented, Spinner, Stack, StatusPill, TableCard, Text, numCell, selectedRow } from '@/design'
import { fmt, shortDate, signed } from '@/domain/format'
import { useScope } from '@/domain/scope'
import { compareSamples, quartiles } from '@/domain/stats'
import { useUi } from '@/app/store'
import s from './Stress.module.css'

const values = (t: StressTest | undefined) => (t?.sessions ?? []).map((x) => x.ttid_ms).filter((v): v is number => v != null && v > 0)

export function StressPage() {
  const { scope } = useScope()
  const app = useUi((st) => st.app)
  const qc = useQueryClient()
  const dev = useDevice()
  const list = useStressList()
  const recent = useRecentJobs()
  const [n, setN] = useState(10)
  const [pick, setPick] = useState<number | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)

  const resumed = recent.data?.find((j) => j.kind === 'stress' && (j.state === 'running' || j.state === 'queued'))
  const job = useJob(jobId ?? resumed?.id ?? null).data as (ReturnType<typeof useJob>['data'] & { stress_id?: number; progress?: { current: number; total: number } }) | undefined
  const running = job?.state === 'queued' || job?.state === 'running'

  const tests = useMemo(() => (list.data ?? []).filter((t) => t.app_pkg === app).sort((a, b) => b.id - a.id), [list.data, app])
  const curId = pick ?? (running ? job?.stress_id : undefined) ?? tests[0]?.id ?? null
  // Poll the test while its sessions are still landing, so dots appear live.
  const cur = useStress(curId, running).data
  const curIdx = tests.findIndex((t) => t.id === curId)
  const baseSummary = tests.slice(curIdx + 1).find((t) => t.state === 'done' && (t.completed ?? t.sessions_requested) >= 2)
  const base = useStress(baseSummary?.id ?? null).data

  const run = async () => {
    setErr(null)
    try {
      const r = await startStress({ pkg: app, sessions: n, cold: true, duration_ms: 8000 })
      setJobId(r.job_id)
      setPick(null)
      qc.invalidateQueries({ queryKey: keys.jobs })
      setTimeout(() => qc.invalidateQueries({ queryKey: keys.stressList }), 1500)
    } catch (e) {
      setErr((e as Error).message)
    }
  }

  const budget = scope?.latest?.ttid_budget_ms ?? null
  const appName = scope?.apps.find((a) => a.pkg === app)?.name ?? app

  return (
    <Stack as="section" gap={20}>
      <Card>
        <Stack gap={16}>
          <Stack gap={10}>
            <Row gap={16} wrap>
              <Text variant="label">COLD STARTS</Text>
              <Segmented label="Cold starts" value={n} onChange={setN} options={[5, 10, 20].map((v) => ({ value: v, label: String(v) }))} />
              <Text variant="body" className={s.intro}>
                {appName} is force-stopped and cold-launched {n} times back to back. The spread across sessions decides whether a change is real or noise.
              </Text>
              <Button variant="primary" disabled={running || !dev.data?.connected} onClick={run}>
                Run {n} cold starts
              </Button>
            </Row>
            {!dev.data?.connected && <Text variant="meta">Connect a device to run a stress test.</Text>}
          </Stack>
          {running && job?.progress && (
            <Stack gap={8}>
              <Row gap={10}>
                <Spinner />
                <Text variant="body" tone="primary">
                  Session {job.progress.current} of {job.progress.total}
                </Text>
              </Row>
              <Progress pct={(Math.max(0, job.progress.current - 1) / job.progress.total) * 100} />
            </Stack>
          )}
          {err && (
            <Banner tone="fail" title="Could not start">
              {err}
            </Banner>
          )}
        </Stack>
      </Card>

      {!cur ? (
        <EmptyState title="No stress tests yet">Run a stress test to see startup-time spread for {appName}.</EmptyState>
      ) : (
        <Distribution cur={cur} base={base ?? null} budget={budget} />
      )}

      {tests.length > 0 && (
        <TableCard title="Stress-test history" minWidth={760}>
          <thead>
            <tr>
              <th>Test</th>
              <th>Date</th>
              <th className={numCell}>Sessions</th>
              <th>Device</th>
              <th className={numCell}>Median</th>
              <th className={numCell}>Spread</th>
              <th>State</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {tests.map((t) => {
              const st = t.stats?.ttid_ms
              return (
                <tr key={t.id} data-hl={`stress:${t.id}`} className={t.id === curId ? selectedRow : undefined}>
                  <Text as="td" variant="body" tone="primary" weight={700}>
                    #{t.id}
                  </Text>
                  <Text as="td" variant="body">
                    {shortDate(t.ts, true)}
                  </Text>
                  <td className={numCell}>
                    {t.completed ?? '–'} / {t.sessions_requested}
                  </td>
                  <Text as="td" variant="body">
                    {t.device ?? '–'}
                  </Text>
                  <td className={numCell}>{st ? `${fmt(st.median)} ms` : '–'}</td>
                  <td className={numCell}>{st ? `± ${fmt(st.spread_pct, 1)}%` : '–'}</td>
                  <td>
                    <StatusPill tone={t.state === 'done' ? 'pass' : t.state === 'error' ? 'fail' : t.state === 'interrupted' ? 'neutral' : 'warn'}>{t.state.toUpperCase()}</StatusPill>
                  </td>
                  <td>
                    <Button variant="mini" onClick={() => setPick(t.id)} disabled={t.id === curId}>
                      {t.id === curId ? 'Shown' : 'Show'}
                    </Button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </TableCard>
      )}
    </Stack>
  )
}

/** Strip + box plot: one row per test, one dot per session, IQR box, median bar. */
function Distribution({ cur, base, budget }: { cur: StressTest; base: StressTest | null; budget: number | null }) {
  const a = values(cur)
  const b = values(base ?? undefined)
  const rows = [...(base && b.length ? [{ label: `Previous #${base.id}`, vals: b, color: 'var(--c4)' }] : []), { label: `Test #${cur.id}`, vals: a, color: 'var(--c1)' }]
  const all = rows.flatMap((r) => r.vals).concat(budget != null ? [budget] : [])
  if (!a.length) return <EmptyState>No completed sessions in test #{cur.id} yet.</EmptyState>
  const lo = Math.min(...all)
  const hi = Math.max(...all)
  const pad = (hi - lo) * 0.08 || 10
  const X = (v: number) => `${((v - (lo - pad)) / (hi - lo + 2 * pad)) * 100}%`
  const cmp = b.length >= 2 && a.length >= 2 ? compareSamples(a, b) : null

  return (
    <Card title="TTID distribution" hint={`${a.length} session${a.length === 1 ? '' : 's'} in test #${cur.id}${base ? ` against the previous completed test, #${base.id}` : ''}. One dot per cold start; the box is the middle half.`}>
      <Stack gap={14}>
        {rows.map((r) => {
          const q = quartiles(r.vals)
          return (
            <div key={r.label} className={s.row}>
              <Text variant="body" tone="primary" weight={600}>
                {r.label}
              </Text>
              <div className={s.track}>
                <div className={s.box} style={{ left: X(q.q1), width: `calc(${X(q.q3)} - ${X(q.q1)})`, borderColor: r.color }} />
                <div className={s.median} style={{ left: X(q.median), background: r.color }} />
                {r.vals.map((v, i) => (
                  <span key={i} title={`${fmt(v, 1)} ms`} className={s.dot} style={{ left: X(v), top: 10 + ((i * 7) % 28), background: r.color }} />
                ))}
                {budget != null && <div className={s.budget} style={{ left: X(budget) }} />}
              </div>
              <Text variant="ui" weight={700} align="right">
                {fmt(q.median)} ms
              </Text>
            </div>
          )
        })}
        <div className={s.row}>
          <span />
          <div className={s.axis}>
            <Text variant="caption" className={s.axisStart}>
              {fmt(lo - pad)} ms
            </Text>
            {budget != null && (
              <Text variant="caption" tone="accent" nowrap className={s.axisBudget} style={{ left: X(budget) }}>
                budget {budget}
              </Text>
            )}
            <Text variant="caption" className={s.axisEnd}>
              {fmt(hi + pad)} ms
            </Text>
          </div>
          <span />
        </div>
      </Stack>
      <Row gap={12} wrap className={s.verdict}>
        {cmp ? (
          <>
            <StatusPill tone={cmp.verdict === 'regression' ? 'fail' : 'pass'}>
              {cmp.verdict === 'regression' ? 'Real regression' : cmp.verdict === 'improvement' ? 'Real improvement' : 'Within noise'}
            </StatusPill>
            <Text variant="body">
              Median shift {signed(cmp.shift, 0, ' ms')} · {fmt(cmp.noiseMultiple, 1)}× the previous test's spread · p {cmp.p != null && cmp.p < 0.001 ? '< 0.001' : `= ${fmt(cmp.p, 3)}`}
            </Text>
            {cmp.lowConfidence && (
              <Text variant="meta" tone="warn">
                ! Fewer than 10 sessions: low confidence.
              </Text>
            )}
          </>
        ) : (
          <Text variant="body" tone="muted">
            No earlier completed test for this app to compare against.
          </Text>
        )}
      </Row>
    </Card>
  )
}
