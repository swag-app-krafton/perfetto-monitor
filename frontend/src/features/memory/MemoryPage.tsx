import { Link } from 'react-router'
import type { Run } from '@/api/types'
import { Card, EmptyState, Eyebrow, Grid, LineChart, Row, Stack, StackedBars, Stat, StatGrid, Swatch, Text, type StackRow } from '@/design'
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

type Breakdown = NonNullable<ReturnType<typeof breakdown>>

/** One bar row per run: the parts stacked, the peak at the right. */
const barRow = (id: string, label: string, b: Breakdown, budget: number | null, dim?: boolean): StackRow => ({
  id,
  label,
  dim,
  segments: b.parts.map((p) => ({ key: p.name, value: p.mb, title: `${p.name} · ${fmt(p.mb)} MB`, text: fmt(p.mb) })),
  total: b.total,
  totalText: `${fmt(b.total)} MB`,
  over: budget != null && b.total > budget,
})

export function MemoryPage() {
  const { scope, isLoading } = useScope()
  if (isLoading || !scope) return <EmptyState>Loading runs…</EmptyState>
  const { run, runs, allRuns, benchmarkRun, history } = scope
  if (!run) return <EmptyState title="No runs yet">Capture a trace to see memory.</EmptyState>
  const base = benchmarkRun ?? allRuns.filter((r) => r.id < run.id).pop() ?? null
  const cur = breakdown(run)
  const prev = breakdown(base)
  const peakBudget = metricByKey('peak_rss_mb').budget(run, history.global_budgets)
  const colors = Object.fromEntries([...(cur?.parts ?? []), ...(prev?.parts ?? [])].map((p) => [p.name, p.color]))
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
              <StackedBars
                size="lg"
                unit="MB"
                budget={peakBudget}
                colors={colors}
                rows={[
                  barRow(String(run.id), `Run #${run.id}`, cur, peakBudget),
                  ...(prev && base ? [barRow(String(base.id), benchmarkRun ? `Benchmark #${base.id}` : `Previous #${base.id}`, prev, peakBudget, true)] : []),
                ]}
              />
            ) : (
              <EmptyState>No memory samples were recorded for run #{run.id}.</EmptyState>
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
            budget={peakBudget}
            unit="MB"
          />
        </Card>
        <Card title="RAM growth" hint="Lowest to highest resident memory within each run.">
          <LineChart
            label="RAM growth per run"
            labels={labels}
            series={[{ name: 'RAM growth', color: 'var(--c2)', values: runs.map((r) => valueOf(r, 'rss_growth_mb')) }]}
            budget={metricByKey('rss_growth_mb').budget(run, history.global_budgets)}
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
