import { Link } from 'react-router'
import type { Run } from '@/api/types'
import { Card, EmptyState, Eyebrow, Grid, LineChart, Row, Stack, Stat, StatGrid, Swatch, Text } from '@/design'
import { fmt, signed } from '@/domain/format'
import { metricByKey, valueOf } from '@/domain/metrics'
import { useScope } from '@/domain/scope'
import s from './Memory.module.css'

/** What the trace can say about where the memory is. Real device traces carry
 *  the app's total resident memory; a per-runtime split exists only where the
 *  app reports a runtime's own heap (the Hermes heap counter). */
function breakdown(r: Run | null) {
  const rss = r?.memory?.rss?.peak_mb ?? null
  const hermes = r?.memory?.hermes_heap?.peak_mb ?? null
  if (rss == null) return null
  const parts = hermes != null ? [{ name: 'Hermes heap', color: 'var(--c2)', mb: hermes }, { name: 'Rest of process', color: 'var(--c1)', mb: Math.max(0, rss - hermes) }] : [{ name: 'App process', color: 'var(--c1)', mb: rss }]
  return { total: rss, parts }
}

function Bar({ label, b, max, dim }: { label: string; b: NonNullable<ReturnType<typeof breakdown>>; max: number; dim?: boolean }) {
  return (
    <div className={dim ? `${s.bar} ${s.dim}` : s.bar}>
      <Text variant="body" tone="primary" weight={600}>
        {label}
      </Text>
      <div className={s.track}>
        {b.parts.map((p) => (
          <div key={p.name} title={`${p.name} · ${fmt(p.mb)} MB`} className={s.segment} style={{ width: `${(p.mb / max) * 100}%`, background: p.color }}>
            {p.mb / max > 0.08 && (
              <Text variant="caption" tone="inherit" weight={600}>
                {fmt(p.mb)}
              </Text>
            )}
          </div>
        ))}
      </div>
      <Text variant="ui" weight={700} align="right">
        {fmt(b.total)} MB
      </Text>
    </div>
  )
}

export function MemoryPage() {
  const { scope, isLoading } = useScope()
  if (isLoading || !scope) return <EmptyState>Loading runs…</EmptyState>
  const { latest, runs, allRuns, benchmarkRun, history } = scope
  if (!latest) return <EmptyState title="No runs yet">Capture a trace to see memory.</EmptyState>
  const base = benchmarkRun ?? allRuns.filter((r) => r.id < latest.id).pop() ?? null
  const cur = breakdown(latest)
  const prev = breakdown(base)
  const max = Math.max(cur?.total ?? 0, prev?.total ?? 0, metricByKey('peak_rss_mb').budget(latest, history.global_budgets) ?? 0) * 1.05 || 1
  const labels = runs.map((r) => `#${r.id}`)
  const hasHermes = runs.some((r) => r.memory?.hermes_heap)
  const perRuntime = !!cur && cur.parts.length > 1

  return (
    <Stack as="section" gap={20}>
      <Card data-hl="memHero" className={s.hero}>
        <Stack gap={16}>
          <Stack gap={20}>
            <Stack gap={12}>
              <Eyebrow>PEAK MEMORY BREAKDOWN</Eyebrow>
              <Text as="h2" variant="display-lg">
                Three runtimes, one process
              </Text>
            </Stack>
            {cur ? (
              <Stack gap={12}>
                <Bar label={`Run #${latest.id}`} b={cur} max={max} />
                {prev && base && <Bar label={benchmarkRun ? `Benchmark #${base.id}` : `Previous #${base.id}`} b={prev} max={max} dim />}
              </Stack>
            ) : (
              <EmptyState>No memory samples were recorded for run #{latest.id}.</EmptyState>
            )}
            {cur && (
              <StatGrid variant="hairline" min={160}>
                {cur.parts.map((p) => {
                  const was = prev?.parts.find((q) => q.name === p.name)?.mb
                  const d = was != null ? p.mb - was : null
                  return (
                    <Stat
                      key={p.name}
                      size="lg"
                      label={
                        <Row as="span" gap={8}>
                          <Swatch color={p.color} />
                          {p.name}
                        </Row>
                      }
                      value={fmt(p.mb)}
                      unit="MB"
                      note={
                        d != null && (
                          <Text variant="meta" weight={600} tone={Math.abs(d) < 2 ? 'secondary' : d > 0 ? 'fail' : 'pass'}>
                            {Math.abs(d) < 2 ? '= ' : d > 0 ? '▲ ' : '▼ '}
                            {signed(d, 0, ' MB')}
                          </Text>
                        )
                      }
                    />
                  )
                })}
              </StatGrid>
            )}
          </Stack>
          {!perRuntime && (
            <Text as="p" variant="body" tone="muted" className={s.note}>
              This trace records the app's total resident memory only, so it cannot be split by runtime. A per-runtime breakdown needs the app to
              report each runtime's own heap as a trace counter, as the Hermes heap counter does.
            </Text>
          )}
        </Stack>
      </Card>
      <Grid min={440}>
        <Card data-hl="peakChart" title="Peak RAM" hint="Highest resident memory of the app's own process, per run.">
          <LineChart
            label="Peak RAM per run"
            labels={labels}
            series={[{ name: 'Peak RAM', color: 'var(--c1)', values: runs.map((r) => valueOf(r, 'peak_rss_mb')) }]}
            budget={metricByKey('peak_rss_mb').budget(latest, history.global_budgets)}
            unit="MB"
          />
        </Card>
        <Card title="RAM growth" hint="Lowest to highest resident memory within each run.">
          <LineChart
            label="RAM growth per run"
            labels={labels}
            series={[{ name: 'RAM growth', color: 'var(--c2)', values: runs.map((r) => valueOf(r, 'rss_growth_mb')) }]}
            budget={metricByKey('rss_growth_mb').budget(latest, history.global_budgets)}
            unit="MB"
          />
        </Card>
      </Grid>
      {hasHermes && (
        <Card title="Hermes heap" hint="The React Native runtime's own heap at its peak, per run.">
          <LineChart label="Hermes heap per run" labels={labels} series={[{ name: 'Hermes heap', color: 'var(--c3)', values: runs.map((r) => r.memory?.hermes_heap?.peak_mb ?? null) }]} unit="MB" />
        </Card>
      )}
      <Card title="Where the growth happens" hint="Growth within a session is attributed to screens on the Screens tab: RAM over time with each screen visit behind it, and the navigation stack held open beneath each screen.">
        <Link to="/screens">Open the session timeline →</Link>
      </Card>
    </Stack>
  )
}
