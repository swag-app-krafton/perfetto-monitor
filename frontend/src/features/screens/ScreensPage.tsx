import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'
import { useScreens } from '@/api/hooks'
import type { Run, ScreenSummary, ScreensPayload } from '@/api/types'
import {
  BandedTimeline,
  BarSeries,
  Card,
  EmptyState,
  FlushCard,
  Grid,
  HelpTip,
  KpiTile,
  Meter,
  Row,
  Segmented,
  SelectField,
  Spinner,
  Stack,
  Stat,
  StatGrid,
  Text,
} from '@/design'
import { fmt, shortDate, stepName } from '@/domain/format'
import { valueOf } from '@/domain/metrics'
import { useScope } from '@/domain/scope'
import s from './Screens.module.css'

type Instrumented = Extract<ScreensPayload, { instrumented: true }>

const HEAD: { label: string; right?: boolean; help?: string }[] = [
  { label: 'Screen' },
  { label: 'Runtime', help: 'What drew the screen: Compose, a React Native surface, or a native view such as the camera preview.' },
  { label: 'Depth', right: true, help: 'How far down the navigation stack the screen sat. 1 is the root; deeper means more screens still open underneath.' },
  { label: 'Visits', right: true },
  { label: 'CPU busy', right: true, help: "Share of wall time the app's threads were running on a CPU while this screen was in front. Over 100% means several cores at once." },
  { label: 'CPU time', right: true, help: 'Total CPU time across all app threads while on this screen, summed over its visits.' },
  { label: 'Peak RAM', right: true, help: "Highest resident memory reached while on this screen." },
  { label: 'RAM growth', right: true, help: 'The largest rise in resident memory within one visit. Growth that persists after leaving suggests a leak.' },
  { label: 'App jank', right: true, help: "Frames Android's FrameTimeline marked as the app missing its deadline -- the app's fault, not the compositor's." },
  { label: 'Time on screen', right: true, help: 'Wall time the screen was visible, summed over its visits.' },
]

const METRIC_OPTS = [
  { value: 'cpu_pct_of_wall', label: 'CPU busy %', unit: '%' },
  { value: 'cpu_ms', label: 'CPU time', unit: ' ms' },
  { value: 'peak_rss_mb', label: 'Peak RAM', unit: ' MB' },
  { value: 'rss_delta_mb', label: 'RAM growth', unit: ' MB' },
  { value: 'duration_ms', label: 'Time on screen', unit: ' ms' },
] as const
type VisitMetric = (typeof METRIC_OPTS)[number]['value']

export function ScreensPage() {
  const { scope, isLoading } = useScope()
  const traced = useMemo(() => (scope?.allRuns ?? []).filter((r) => r.trace_path), [scope])
  const [params] = useSearchParams()
  // Manual's "Open run" lands here with ?run=<id>.
  const [pick, setPick] = useState<number | null>(() => Number(params.get('run')) || null)
  const [view, setView] = useState<'usage' | 'launch'>('usage')
  const runId = pick ?? traced[traced.length - 1]?.id ?? null
  const q = useScreens(runId)
  const run = runId != null ? scope?.byId(runId) : undefined

  if (isLoading || !scope) return <EmptyState>Loading runs…</EmptyState>
  if (!traced.length) return <EmptyState title="No traced runs">Record a manual session or capture a trace to attribute cost to screens.</EmptyState>

  return (
    <Stack as="section" gap={20}>
      <Card>
        <Row gap={12} wrap>
          <SelectField
            label="Run"
            value={String(runId)}
            options={[...traced].reverse().map((r) => ({ value: String(r.id), label: `#${r.id} · ${shortDate(r.ts, true)} · ${r.label ?? r.device ?? ''}` }))}
            onChange={(v) => setPick(Number(v))}
          />
          <Segmented
            label="View"
            value={view}
            onChange={setView}
            options={[
              { value: 'usage', label: 'Screen usage' },
              { value: 'launch', label: 'Launch metrics' },
            ]}
          />
        </Row>
      </Card>
      {view === 'launch' && run ? (
        <LaunchView run={run} />
      ) : q.isLoading ? (
        <EmptyState>
          <Spinner /> &nbsp;Reading the trace…
        </EmptyState>
      ) : q.error ? (
        <EmptyState title="Could not read this trace">{q.error.message}</EmptyState>
      ) : !q.data?.instrumented ? (
        <EmptyState title="No screen markers in this trace">{q.data?.instrumented === false ? q.data.note : ''}</EmptyState>
      ) : (
        <Usage d={q.data} />
      )}
    </Stack>
  )
}

function Usage({ d }: { d: Instrumented }) {
  const [open, setOpen] = useState<string | null>(null)
  const [metric, setMetric] = useState<VisitMetric>('cpu_pct_of_wall')
  const maxCpu = Math.max(...d.screen_summary.map((r) => (r.total_ms ? (r.total_cpu_ms / r.total_ms) * 100 : 0)), 1)
  const bands = d.screens.map((v) => ({ start: v.start_ms, end: v.start_ms + v.duration_ms, label: v.route, detail: v.stack.length > 1 ? v.stack.join(' › ') : undefined }))
  const t0 = d.screens[0]?.start_ms ?? 0
  const navCost = new Map(d.navigations.map((n) => [`${n.from}->${n.to}`, n]))

  return (
    <>
      <FlushCard title="Per-screen cost" hint="Select a screen to chart each of its visits separately.">
        <div className={s.table} role="table" aria-label="Per-screen cost">
          <div className={`${s.cols} ${s.hrow}`} role="row">
            {HEAD.map((h) => (
              <span key={h.label} role="columnheader" className={`${s.hcell} ${h.right ? s.right : ''}`}>
                {h.label}
                {h.help && <HelpTip text={h.help} label={h.label} />}
              </span>
            ))}
          </div>
          {d.screen_summary.map((r) => (
            <ScreenRow key={r.route} r={r} maxCpu={maxCpu} open={open === r.route} onToggle={() => setOpen(open === r.route ? null : r.route)} metric={metric} setMetric={setMetric} />
          ))}
        </div>
      </FlushCard>

      {d.timeline.rss.length > 0 && (
        <Card data-hl="timeline" title="Session timeline" hint="The app's own RAM and CPU across the whole session, each screen visit a band behind. RAM that steps up and never comes back down, on the same screen each time, is where to look first.">
          <BandedTimeline
            label="App RAM and CPU over the session"
            bands={bands}
            panels={[
              { label: 'RAM (MB)', color: 'var(--c1)', unit: ' MB', points: d.timeline.rss },
              { label: 'CPU busy (%)', color: 'var(--c2)', unit: '%', points: d.timeline.cpu },
            ]}
          />
        </Card>
      )}

      <Grid min={380}>
        <Card title="Navigation stack" hint="The screens in the order they were visited, with how long each transition took to draw.">
          <Stack gap={10}>
            <div>
              {d.screens.slice(0, 14).map((v, i) => {
                const next = d.screens[i + 1]
                const tr = next ? navCost.get(`${v.route}->${next.route}`) : undefined
                const slow = tr?.median_ms != null && tr.median_ms > 350
                return (
                  // Indented by how deep in the stack the screen sat.
                  <div key={i} style={{ marginLeft: (v.depth - 1) * 18 }}>
                    <div className={s.node}>
                      <span className={s.nodeName}>{v.route}</span>
                      <Text variant="meta">
                        {v.kind_label}
                        {v.depth > 1 ? ` · depth ${v.depth}` : ''}
                      </Text>
                    </div>
                    {next && (
                      <div className={s.link}>
                        <span className={s.linkBar} />
                        <Text variant="meta" tone={slow ? 'warn' : 'muted'}>
                          ↓ {slow ? 'Slow transition' : 'Transition'}
                          {tr?.median_ms != null ? ` · ${fmt(tr.median_ms)} ms` : ''}
                        </Text>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
            {d.screens.length > 14 && <Text variant="meta">+ {d.screens.length - 14} more visits</Text>}
          </Stack>
        </Card>
        <Card title="User actions" hint="Every action the app marked, in order, with the screen it happened on.">
          {d.action_events.length === 0 && (
            <Text variant="body" tone="muted">
              No actions were marked in this session.
            </Text>
          )}
          {d.action_events.slice(0, 40).map((a, i) => (
            <div key={i} className={s.action}>
              <Text variant="body" tone="muted">
                {((a.at_ms - t0) / 1000).toFixed(1)}s
              </Text>
              <Text variant="body" tone="primary" weight={500} breakAnywhere>
                {a.action}
              </Text>
              <Text variant="meta" tone="secondary">
                {a.screen ?? '–'}
              </Text>
            </div>
          ))}
        </Card>
      </Grid>

      {d.stack_summary.length > 1 && (
        <Card title="Cost by stack depth" hint="A screen that is cheap on its own can still hold a lot of memory when two others are still open beneath it.">
          <StatGrid variant="boxes" min={200}>
            {d.stack_summary.map((r) => (
              <Stat
                key={r.depth}
                size="lg"
                label={`Depth ${r.depth}`}
                value={
                  r.peak_rss_mb == null ? (
                    <Text variant="ui" tone="muted">
                      not measured
                    </Text>
                  ) : (
                    fmt(r.peak_rss_mb)
                  )
                }
                unit={r.peak_rss_mb == null ? undefined : 'MB peak'}
                note={
                  <Text variant="meta">
                    {fmt(r.mean_cpu_pct, 1)}% CPU busy · {r.routes.map(([k]) => k).join(', ')}
                    {r.beneath.length ? ` · beneath: ${r.beneath.map(([k]) => k).join(', ')}` : ''}
                  </Text>
                }
              />
            ))}
          </StatGrid>
        </Card>
      )}
    </>
  )
}

function ScreenRow({ r, maxCpu, open, onToggle, metric, setMetric }: { r: ScreenSummary; maxCpu: number; open: boolean; onToggle: () => void; metric: VisitMetric; setMetric: (m: VisitMetric) => void }) {
  const cpu = r.total_ms ? (r.total_cpu_ms / r.total_ms) * 100 : null
  const growth = r.max_rss_delta_mb
  const opt = METRIC_OPTS.find((o) => o.value === metric)!
  const st = r.stats[metric]
  return (
    <div data-hl={`screen:${r.route}`}>
      <button type="button" className={`${s.cols} ${s.row}`} aria-expanded={open} onClick={onToggle}>
        <Text as="span" variant="body" tone="primary" weight={600} className={r.step ? s.substep : undefined}>
          {r.step ? '↳ ' : ''}
          {r.route}
        </Text>
        <Text variant="meta" tone="secondary">
          {r.kind_label}
        </Text>
        <span className={s.right}>{r.depth_label ?? '–'}</span>
        <span className={s.right}>{r.visits}</span>
        <Row as="span" gap={10} justify="end">
          <span className={s.cpuBar}>
            <Meter value={cpu ?? 0} max={maxCpu} height={6} label={`CPU busy on ${r.route}`} />
          </span>
          <Text as="span" variant="body" tone="primary" weight={600} align="right" className={s.cpuValue}>
            {cpu == null ? '–' : `${fmt(cpu, 1)}%`}
          </Text>
        </Row>
        <span className={s.right}>{fmt(r.total_cpu_ms)} ms</span>
        <span className={s.right}>{r.peak_rss_mb == null ? '–' : `${fmt(r.peak_rss_mb)} MB`}</span>
        <Text as="span" variant="body" weight={600} align="right" tone={growth == null ? 'secondary' : growth > 10 ? 'fail' : growth < 0 ? 'pass' : 'secondary'}>
          {growth == null ? '–' : `${growth > 10 ? '▲ ' : growth < 0 ? '▼ ' : ''}${fmt(growth, 1)} MB`}
        </Text>
        <Text
          as="span"
          variant="body"
          align="right"
          tone={(r.jank?.app_jank_pct ?? 0) > 0.5 ? 'fail' : 'secondary'}
          title={r.jank ? `${r.jank.late} of ${r.jank.frames} frames late: ${r.jank.app} app deadline missed, ${r.jank.dropped} dropped, ${r.jank.buffer_stuffing} buffer stuffing, ${r.jank.system} system` : 'No FrameTimeline data'}
        >
          {r.jank?.app_jank_pct == null ? '–' : `${fmt(r.jank.app_jank_pct, 2)}%`}
        </Text>
        <Text as="span" variant="body" align="right">
          {fmt(r.total_ms / 1000, 1)} s
        </Text>
      </button>
      {open && (
        <Stack gap={14} className={s.detail}>
          <Row gap={12} wrap>
            <Segmented label="Chart" value={metric} onChange={setMetric} options={METRIC_OPTS.map((o) => ({ value: o.value, label: o.label }))} />
            <Text variant="meta">
              {r.visits} visit{r.visits === 1 ? '' : 's'} · red = more than two standard deviations from the mean
            </Text>
          </Row>
          <BarSeries
            label={`${opt.label} for each visit to ${r.route}`}
            unit={opt.unit}
            mean={st?.mean}
            caption="visit, in the order they happened"
            bars={r.visit_list.map((v) => {
              const val = metric === 'duration_ms' ? v.duration_ms : metric === 'cpu_ms' ? v.cpu_ms : metric === 'cpu_pct_of_wall' ? v.cpu_pct_of_wall : metric === 'peak_rss_mb' ? v.peak_rss_mb : v.rss_delta_mb
              const dev = st?.mean != null && st.stdev && val != null ? (val - st.mean) / st.stdev : null
              return {
                label: `${r.route} · visit ${v.index}`,
                value: val,
                flagged: !!v.outlier[metric],
                detail: [
                  [opt.label, val == null ? 'no data' : `${fmt(val, 1)}${opt.unit}`],
                  ...(st?.mean != null ? ([[`mean of ${r.visits}`, `${fmt(st.mean, 1)}${opt.unit}`]] as [string, string][]) : []),
                  ...(dev != null ? ([['deviation', `${dev >= 0 ? '+' : ''}${fmt(dev, 1)} sd`]] as [string, string][]) : []),
                  ['CPU busy', v.cpu_pct_of_wall == null ? '–' : `${fmt(v.cpu_pct_of_wall, 1)}%`],
                  ['peak RAM', v.peak_rss_mb == null ? '–' : `${fmt(v.peak_rss_mb)} MB`],
                  ['stack', v.stack.length > 1 ? v.stack.join(' › ') : 'root'],
                ],
              }
            })}
          />
        </Stack>
      )}
    </div>
  )
}

function LaunchView({ run }: { run: Run }) {
  const ttid = valueOf(run, 'ttff_ms')
  if (!run.steps.length && ttid == null) {
    return <EmptyState title="No launch in this trace">A session that begins with the app already open has no launch to measure. Trace a cold start to capture one.</EmptyState>
  }
  const t0 = Math.min(...run.steps.map((x) => x.start_ms ?? 0))
  return (
    <>
      <Grid min={200} gap={12}>
        <KpiTile label="TTID" value={ttid == null ? null : fmt(ttid)} unit="ms" note={run.ttid_budget_ms ? `budget ${run.ttid_budget_ms} ms` : undefined} />
        <KpiTile label="Startup steps" value={String(run.steps.length)} />
        <KpiTile label="Slowest step" value={run.steps.length ? fmt(Math.max(...run.steps.map((x) => x.dur_ms)), 1) : null} unit="ms" />
      </Grid>
      <Card title="Startup steps" hint={`Each stage of the launch run #${run.id} recorded, in order. Start is relative to the first step.`}>
        {run.steps.map((st) => (
          <div key={st.step} className={s.step}>
            <Text variant="body" tone="primary" weight={500}>
              {stepName(st.step)}
            </Text>
            <Text variant="body" align="right">
              +{fmt((st.start_ms ?? t0) - t0, 1)} ms
            </Text>
            <Text variant="body" tone="primary" weight={600} align="right">
              {fmt(st.dur_ms, 1)} ms
            </Text>
          </div>
        ))}
      </Card>
    </>
  )
}
