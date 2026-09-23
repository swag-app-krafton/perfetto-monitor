import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { keys, startStress, useDevice, useJob, useRecentJobs, useStress, useStressList } from '@/api/hooks'
import type { StressTest } from '@/api/types'
import { Banner, Button, Card, EmptyState, Progress, Segmented, Spinner, StatusPill, TableCard, numCell } from '@/design/components'
import { fmt, shortDate, signed } from '@/domain/format'
import { useScope } from '@/domain/scope'
import { compareSamples, quartiles } from '@/domain/stats'
import { useUi } from '@/app/store'

const values = (t: StressTest | undefined) => (t?.sessions ?? []).map((s) => s.ttid_ms).filter((v): v is number => v != null && v > 0)

export function StressPage() {
  const { scope } = useScope()
  const app = useUi((s) => s.app)
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
    <section style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <Card>
        <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ font: '600 10.5px var(--font-ui)', letterSpacing: '.16em', color: 'var(--tx3)' }}>COLD STARTS</span>
          <Segmented label="Cold starts" value={n} onChange={setN} options={[5, 10, 20].map((v) => ({ value: v, label: String(v) }))} />
          <span style={{ flex: '1 1 260px', fontSize: 13, color: 'var(--tx2)' }}>
            {appName} is force-stopped and cold-launched {n} times back to back. The spread across sessions decides whether a change is real or noise.
          </span>
          <Button variant="primary" disabled={running || !dev.data?.connected} onClick={run}>
            Run {n} cold starts
          </Button>
        </div>
        {!dev.data?.connected && <div style={{ fontSize: 12, color: 'var(--tx3)', marginTop: 10 }}>Connect a device to run a stress test.</div>}
        {running && job?.progress && (
          <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13 }}>
              <Spinner /> Session {job.progress.current} of {job.progress.total}
            </div>
            <Progress pct={(Math.max(0, job.progress.current - 1) / job.progress.total) * 100} />
          </div>
        )}
        {err && (
          <div style={{ marginTop: 12 }}>
            <Banner tone="fail" title="Could not start">
              {err}
            </Banner>
          </div>
        )}
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
                <tr key={t.id} data-hl={`stress:${t.id}`} style={t.id === curId ? { background: 'var(--s2)' } : undefined}>
                  <td style={{ fontWeight: 700 }}>#{t.id}</td>
                  <td style={{ color: 'var(--tx2)' }}>{shortDate(t.ts, true)}</td>
                  <td className={numCell}>
                    {t.completed ?? '–'} / {t.sessions_requested}
                  </td>
                  <td style={{ color: 'var(--tx2)' }}>{t.device ?? '–'}</td>
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
    </section>
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
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14, position: 'relative' }}>
        {rows.map((r) => {
          const q = quartiles(r.vals)
          return (
            <div key={r.label} style={{ display: 'grid', gridTemplateColumns: '120px 1fr 80px', gap: 12, alignItems: 'center' }}>
              <span style={{ fontSize: 13, fontWeight: 600 }}>{r.label}</span>
              <div style={{ position: 'relative', height: 48, background: 'var(--bg)' }}>
                <div style={{ position: 'absolute', top: 10, bottom: 10, left: X(q.q1), width: `calc(${X(q.q3)} - ${X(q.q1)})`, background: 'var(--s2)', border: `1.5px solid ${r.color}` }} />
                <div style={{ position: 'absolute', top: 6, bottom: 6, left: X(q.median), width: 3, marginLeft: -1.5, background: r.color }} />
                {r.vals.map((v, i) => (
                  <span key={i} title={`${fmt(v, 1)} ms`} style={{ position: 'absolute', left: X(v), top: 10 + ((i * 7) % 28), width: 7, height: 7, marginLeft: -3.5, borderRadius: '50%', background: r.color, opacity: 0.85 }} />
                ))}
                {budget != null && <div style={{ position: 'absolute', top: -4, bottom: -4, left: X(budget), borderLeft: '1.5px dashed var(--accent)' }} />}
              </div>
              <span style={{ textAlign: 'right', fontWeight: 700 }}>{fmt(q.median)} ms</span>
            </div>
          )
        })}
        <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr 80px', gap: 12, fontSize: 11, color: 'var(--tx3)' }}>
          <span />
          <div style={{ position: 'relative', height: 14 }}>
            <span style={{ position: 'absolute', left: 0 }}>{fmt(lo - pad)} ms</span>
            {budget != null && <span style={{ position: 'absolute', left: X(budget), transform: 'translateX(-50%)', color: 'var(--accent-tx)', whiteSpace: 'nowrap' }}>budget {budget}</span>}
            <span style={{ position: 'absolute', right: 0 }}>{fmt(hi + pad)} ms</span>
          </div>
          <span />
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginTop: 18, paddingTop: 16, borderTop: '1px solid var(--line)' }}>
        {cmp ? (
          <>
            <StatusPill tone={cmp.verdict === 'regression' ? 'fail' : 'pass'}>
              {cmp.verdict === 'regression' ? 'Real regression' : cmp.verdict === 'improvement' ? 'Real improvement' : 'Within noise'}
            </StatusPill>
            <span style={{ fontSize: 13, color: 'var(--tx2)' }}>
              Median shift {signed(cmp.shift, 0, ' ms')} · {fmt(cmp.noiseMultiple, 1)}× the previous test's spread · p {cmp.p != null && cmp.p < 0.001 ? '< 0.001' : `= ${fmt(cmp.p, 3)}`}
            </span>
            {cmp.lowConfidence && <span style={{ fontSize: 12, color: 'var(--warn)' }}>! Fewer than 10 sessions: low confidence.</span>}
          </>
        ) : (
          <span style={{ fontSize: 13, color: 'var(--tx3)' }}>No earlier completed test for this app to compare against.</span>
        )}
      </div>
    </Card>
  )
}
