import { useMemo } from 'react'
import { useTrend } from '@/api/hooks'
import { platformOf, useUi } from '@/app/store'
import { useProfiler } from '@/app/profiler'
import { Card, ChipGroup, EmptyState, Grid, LineChart, Spinner, Stack, Text } from '@/design'
import { pathLabel, stepName } from '@/domain/format'
import { METRICS } from '@/domain/metrics'
import { useScope } from '@/domain/scope'
import { buildChart, effectivePicks, MAX_DEVICES, nextSlots, SLOT_COLORS, TREND_METRICS } from '@/domain/trend'
import s from './Trend.module.css'

/** Each metric across app versions (F-026): a line per picked device, its
 *  pinned benchmark dotted, the North Star target dashed. The app and start
 *  path come from the top bar; everything else is picked here. */
export function TrendPage() {
  const { scope } = useScope()
  const app = useUi((st) => st.app)
  const path = useUi((st) => st.path)
  const stored = useUi((st) => st.trend[`${app}|${path}`])
  const setTrend = useUi((st) => st.setTrend)
  const platform = platformOf(useProfiler())
  const q = useTrend(app, path, platform)
  const p = q.data
  const picks = useMemo(() => (p ? effectivePicks(p, stored) : null), [p, stored])
  const descriptions = scope?.history.startup_model.step_descriptions ?? {}

  if (!app || !path) return <EmptyState>Loading runs…</EmptyState>
  if (q.isLoading || !p || !picks)
    return (
      <EmptyState>
        <Spinner /> &nbsp;Reading every run of this app…
      </EmptyState>
    )
  if (q.error) return <EmptyState title="Could not load the trend">{q.error.message}</EmptyState>

  const appName = scope?.apps.find((a) => a.pkg === app)?.name ?? app
  const save = (next: Partial<typeof picks>) => setTrend(`${app}|${path}`, { ...picks, ...next })
  const slotOf = (name: string) => picks.devices.indexOf(name)
  const picked = picks.devices.filter(Boolean)
  const charts = [...picks.metrics, ...picks.steps].map((m) => buildChart(p, m, picks.devices, descriptions))
  const unversioned = p.unversioned ? ` ${p.unversioned} run${p.unversioned === 1 ? ' has' : 's have'} no app version and ${p.unversioned === 1 ? 'is' : 'are'} not plotted.` : ''

  if (!p.versions.length) {
    return (
      <EmptyState title="No versions to trend">
        No {pathLabel(path).toLowerCase()} run of {appName} records an app version.{unversioned} Captures from the dashboard record it from the device; for the CLI,
        pass --app-version.
      </EmptyState>
    )
  }

  return (
    <Stack as="section" gap={20}>
      <Card>
        <Stack gap={12}>
          <div className={s.pickers}>
            <ChipGroup
              label="Devices"
              value={picked}
              onChange={(next) => save({ devices: nextSlots(picks.devices, next) })}
              max={MAX_DEVICES}
              maxNote={`Up to ${MAX_DEVICES} devices at once, so each keeps a colour that can be told apart. Turn one off first.`}
              colorOf={(d) => SLOT_COLORS[slotOf(d)]}
              options={p.devices.map((d) => ({ value: d.name, label: d.label, count: d.runs, description: d.simulator ? 'A simulator: no benchmark and no targets.' : undefined }))}
            />
            <ChipGroup
              label="Metrics"
              value={picks.metrics}
              onChange={(metrics) => save({ metrics })}
              options={TREND_METRICS.map((k) => {
                const def = METRICS.find((m) => m.key === k)
                return { value: k, label: k === 'ttff_ms' ? 'Startup time' : (def?.label ?? k), description: def?.help }
              })}
            />
            {p.steps.length > 0 && (
              <ChipGroup
                label="Launch steps"
                value={picks.steps}
                onChange={(steps) => save({ steps })}
                options={p.steps.map((st) => ({ value: st, label: stepName(st), description: descriptions[st] }))}
              />
            )}
          </div>
          <Text variant="caption">
            {appName} · {pathLabel(path)} start, from the top bar · {p.versions.length} version{p.versions.length === 1 ? '' : 's'}, oldest first.{unversioned}
            {p.versions.length === 1 ? ' A trend needs a second version to draw a line.' : ''}
          </Text>
        </Stack>
      </Card>

      {!picked.length ? (
        <EmptyState>Pick a device to draw its lines.</EmptyState>
      ) : !charts.length ? (
        <EmptyState>Pick a metric or a launch step.</EmptyState>
      ) : (
        <Grid min={440}>
          {charts.map((c) => (
            <Card key={c.key} title={c.title} hint={c.hint} data-hl={`trend-${c.key}`}>
              {c.hasData ? (
                <LineChart label={`${c.title} per app version`} labels={c.labels} series={c.series} references={c.references} budget={c.budget} unit={c.unit} decimals={c.dp} height={220} />
              ) : (
                <EmptyState>None of the picked devices measured this in any version.</EmptyState>
              )}
            </Card>
          ))}
        </Grid>
      )}
    </Stack>
  )
}
