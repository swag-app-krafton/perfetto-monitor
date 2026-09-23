import { Card, EmptyState, Grid, KpiTile, LineChart, Stack } from '@/design'
import { fmt, signed } from '@/domain/format'
import { metricByKey, valueOf, type MetricDef } from '@/domain/metrics'
import { useScope } from '@/domain/scope'

export function FramesPage() {
  const { scope, isLoading } = useScope()
  if (isLoading || !scope) return <EmptyState>Loading runs…</EmptyState>
  const { run, runs, allRuns, benchmarkRun, history } = scope
  if (!run) return <EmptyState title="No runs yet">Capture a trace to see frame pacing.</EmptyState>
  const base = benchmarkRun ?? allRuns.filter((r) => r.id < run.id).pop() ?? null
  const labels = runs.map((r) => `#${r.id}`)
  const f = run.frames

  const tile = (key: MetricDef['key'], label: string) => {
    const m = metricByKey(key)
    const v = valueOf(run, key)
    const b = valueOf(base, key)
    return (
      <KpiTile
        label={label}
        help={m.help}
        value={v == null ? null : fmt(v, m.dp)}
        unit={m.unit}
        delta={v != null && b != null ? { value: v - b, text: signed(v - b, m.dp, m.deltaUnit), against: `vs ${fmt(b, m.dp)} ${m.unit}` } : null}
      />
    )
  }
  const chart = (key: MetricDef['key'], color: string) => {
    const m = metricByKey(key)
    return (
      <LineChart
        label={`${m.label} per run`}
        labels={labels}
        series={[{ name: m.label, color, values: runs.map((r) => valueOf(r, key)) }]}
        budget={m.budget(run, history.global_budgets)}
        unit={m.unit}
        decimals={m.dp}
      />
    )
  }

  return (
    <Stack as="section" gap={20}>
      <Grid min={200} gap={12}>
        {tile('slow_pct', 'Slow frames · >16.67 ms')}
        {tile('janky_pct', 'Janky frames · >3× budget')}
        {tile('thermal_drift_pct', 'Thermal drift')}
        <KpiTile
          label="Frames analysed"
          help="Frames the app's own main thread rendered during the run. Other processes' frames are never counted."
          value={f && f.total ? fmt(f.total) : null}
          note={f && f.total ? `Mean ${fmt(f.avg_ms, 1)} ms · worst ${fmt(f.max_ms, 1)} ms` : undefined}
        />
      </Grid>
      <Grid min={440}>
        <Card data-hl="framesChart" title="Slow frames" hint="Share of frames over the 16.67 ms budget, per run.">
          {chart('slow_pct', 'var(--c2)')}
        </Card>
        <Card title="Janky frames" hint="Share of frames over three budgets: a stutter a user sees.">
          {chart('janky_pct', 'var(--c3)')}
        </Card>
      </Grid>
      <Card
        title="Thermal drift"
        hint="Mean frame time late in each run against early in it. A rising value means the device is throttling. Runs that moved between screens are gaps: a change of screen, not heat, moves them."
      >
        {chart('thermal_drift_pct', 'var(--c1)')}
      </Card>
    </Stack>
  )
}
