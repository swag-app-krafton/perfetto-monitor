import { Link } from 'react-router'
import { useAudit } from '@/api/hooks'
import type { AuditSummary, RangeStat, ThreadCpu } from '@/api/types'
import { Banner, BarList, Button, Card, DescriptionList, EmptyState, Grid, KpiTile, LineChart, Spinner, Stack, StatusPill, TableCard, Text, numCell } from '@/design'
import { auditLabel, useAuditScope } from '@/domain/audits'
import { fmt } from '@/domain/format'

const range = (r: RangeStat | undefined, dp: number, unit: string) =>
  r ? `${fmt(r.minMaxRange[0], dp)}–${fmt(r.minMaxRange[1], dp)}${unit} across cold starts` : undefined

/** The Flashlight audit in view. Flashlight's numbers, by Flashlight's own
 *  definitions: none of them is compared with a Perfetto run. */
export function AuditPage() {
  const { scope, isLoading } = useAuditScope()
  const q = useAudit(scope?.audit?.id ?? null)
  const a = q.data

  if (isLoading || (scope?.audit && q.isLoading)) return <Spinner />
  if (!scope?.audit || !a)
    return (
      <EmptyState
        title="No Flashlight audits yet"
        actions={
          <Link to="/flashlight/run">
            <Button variant="primary">Run an audit</Button>
          </Link>
        }
      >
        An audit measures an app's cold start with Flashlight several times over, and shows Flashlight's score, CPU by thread, RAM and FPS.
      </EmptyState>
    )

  const sm = a.summary as AuditSummary | null
  if (a.state === 'running')
    return (
      <EmptyState title={`Audit ${auditLabel(a)} is running`} actions={<Link to="/flashlight/run"><Button>Follow it on Run audit</Button></Link>}>
        Its numbers appear here when the last cold start has been measured.
      </EmptyState>
    )
  if (!sm?.metrics)
    return (
      <Banner tone="fail" title={`Audit ${auditLabel(a)} has no results`}>
        {a.error ?? 'No cold start was measured.'}
      </Banner>
    )

  const m = sm.metrics
  const labels = sm.series.map((p) => `${fmt(p.t_ms / 1000, 1)} s`)
  const hasJs = sm.series.some((p) => p.js_pct != null)
  const hasFps = sm.series.some((p) => p.fps != null)

  return (
    <Stack as="section" gap={20}>
      {(sm.failed > 0 || a.error) && (
        <Banner tone="warn" title={`${sm.failed} of ${sm.iterations_run} cold starts failed and were retried`}>
          {a.error ?? 'Only the successful cold starts are counted.'}
        </Banner>
      )}
      <Text variant="body" tone="secondary">
        Flashlight's own definitions: CPU is the sum across the app's threads, so it can pass 100% on a multi-core phone, and FPS is Flashlight's estimate from the UI
        thread. These numbers are never compared with Perfetto runs.
      </Text>

      <Grid min={200} gap={12}>
        <KpiTile
          label="Flashlight score"
          help="Flashlight's 0 to 100 score from average CPU, FPS and time any thread spent saturated."
          value={sm.score == null ? null : fmt(sm.score)}
          unit="/ 100"
          note={`${sm.successful} cold start${sm.successful === 1 ? '' : 's'} of ${a.duration_ms / 1000} s`}
        />
        <KpiTile label="Average CPU" value={fmt(m.cpu_pct, 1)} unit="%" lowerIsBetter note={range(sm.stats?.cpu, 1, '%')} />
        <KpiTile label="Average RAM" value={m.ram_mb == null ? null : fmt(m.ram_mb)} unit="MB" lowerIsBetter note={range(sm.stats?.ram, 0, ' MB')} />
        <KpiTile
          label="Average FPS"
          value={m.fps == null ? null : fmt(m.fps, 1)}
          note={[range(sm.stats?.fps, 1, ''), sm.refresh_rate ? `${sm.refresh_rate} Hz screen` : null].filter(Boolean).join(' · ') || undefined}
        />
      </Grid>

      <Card title="CPU over a cold start" hint="The average of the cold starts, one point per 500 ms sample after launch. Total is every thread of the app added up.">
        <LineChart
          label="CPU over a cold start"
          labels={labels}
          unit="%"
          decimals={1}
          yMin={0}
          series={[
            { name: 'Total', color: 'var(--c1)', values: sm.series.map((p) => p.cpu_pct) },
            { name: 'UI thread', color: 'var(--c2)', values: sm.series.map((p) => p.ui_pct) },
            ...(hasJs ? [{ name: 'JS thread', color: 'var(--c3)', values: sm.series.map((p) => p.js_pct) }] : []),
          ]}
        />
      </Card>

      <Grid min={440}>
        <Card title="RAM over a cold start" hint="The app's resident memory, averaged across the cold starts.">
          <LineChart label="RAM over a cold start" labels={labels} unit="MB" series={[{ name: 'RAM', color: 'var(--c1)', values: sm.series.map((p) => p.ram_mb) }]} />
        </Card>
        {hasFps && (
          <Card title="FPS over a cold start" hint="Flashlight's frame-rate estimate, averaged across the cold starts.">
            <LineChart label="FPS over a cold start" labels={labels} unit="fps" decimals={1} yMin={0} series={[{ name: 'FPS', color: 'var(--c1)', values: sm.series.map((p) => p.fps) }]} />
          </Card>
        )}
      </Grid>

      <Card
        title="CPU by thread"
        hint="Each thread's average share of one core, across the cold starts. For a hybrid app, the UI thread, RenderThread and the React Native JS thread (mqt_v_js) are the ones to watch. The ? beside a name says what the thread is. Android cuts thread names to 15 characters, and a number in brackets marks another thread with the same name."
      >
        <BarList
          label="CPU by thread"
          unit="%"
          decimals={1}
          items={sm.threads.map((t) => ({ label: t.name, value: t.cpu_pct, description: t.description }))}
          empty="No thread used measurable CPU."
        />
      </Card>

      <TableCard title="Cold starts" hint="Each cold start on its own. A failed one was retried and is not in the averages above." minWidth={720}>
        <thead>
          <tr>
            <th>Cold start</th>
            <th>State</th>
            <th className={numCell}>CPU</th>
            <th className={numCell}>UI thread</th>
            <th className={numCell}>JS thread</th>
            <th className={numCell}>RAM</th>
            <th className={numCell}>FPS</th>
            <th className={numCell}>Saturated</th>
          </tr>
        </thead>
        <tbody>
          {sm.iterations.map((it) => {
            const ok = it.status === 'SUCCESS' && !it.retried
            return (
              <tr key={it.index}>
                <Text as="td" variant="body" tone="primary" weight={700}>
                  #{it.index}
                </Text>
                <td>
                  <StatusPill tone={ok ? 'pass' : 'fail'}>{ok ? 'MEASURED' : 'FAILED'}</StatusPill>
                </td>
                <td className={numCell}>{it.cpu_pct == null ? '–' : `${fmt(it.cpu_pct, 1)}%`}</td>
                <td className={numCell}>{pct(it.key_threads?.ui)}</td>
                <td className={numCell}>{pct(it.key_threads?.js)}</td>
                <td className={numCell}>{it.ram_mb == null ? '–' : `${fmt(it.ram_mb)} MB`}</td>
                <td className={numCell}>{it.fps == null ? '–' : fmt(it.fps, 1)}</td>
                <td className={numCell}>{it.high_cpu_s == null ? '–' : `${fmt(it.high_cpu_s, 1)} s`}</td>
              </tr>
            )
          })}
        </tbody>
      </TableCard>

      <Card title="About this audit">
        <DescriptionList
          items={[
            { term: 'App', value: `${a.app_name} (${a.app_pkg})` },
            { term: 'Device', value: a.device },
            { term: 'Measured', value: `${a.iterations} cold starts, ${a.duration_ms / 1000} s each` },
            { term: 'Flashlight', value: sm.flashlight_version, mono: true },
            { term: 'Results file', value: a.results_path, mono: true },
            { term: 'Open in Flashlight', value: a.results_path ? `flashlight report ${a.results_path}` : null, mono: true },
          ]}
        />
      </Card>
    </Stack>
  )
}

const pct = (t: ThreadCpu | null | undefined) => (t?.cpu_pct == null ? '–' : `${fmt(t.cpu_pct, 1)}%`)
