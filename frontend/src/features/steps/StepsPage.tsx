import { useCallback, useState } from 'react'
import type { ChildSlice, Run } from '@/api/types'
import { Button, EmptyState, ExpandableTable, FlushCard, Icon, Label, Meter, Row, Sparkline, Stack, Stat, StatGrid, Term, Text, type ExpandableColumn, type TextTone } from '@/design'
import { fmt, signed, stepName } from '@/domain/format'
import { useScope } from '@/domain/scope'
import { stepDeltas, type StepDelta } from '@/domain/steps'
import { useFocusParam } from '@/lib/highlight'
import { useSort } from '@/design'
import { useUi } from '@/app/store'
import s from './Steps.module.css'

type Key = 'name' | 'runtime' | 'current' | 'baseline' | 'deltaMs' | 'deltaPct'
const COLS: ExpandableColumn<Key>[] = [
  { key: 'name', sortKey: 'name', label: 'Step', width: 'minmax(240px, 2.4fr)' },
  { key: 'runtime', sortKey: 'runtime', label: 'Runtime', width: '140px' },
  { key: 'current', sortKey: 'current', label: 'Current', width: '90px', align: 'right' },
  { key: 'baseline', sortKey: 'baseline', label: 'Baseline', width: '90px', align: 'right' },
  { key: 'deltaMs', sortKey: 'deltaMs', label: 'Δ ms', width: '90px', align: 'right' },
  { key: 'deltaPct', sortKey: 'deltaPct', label: 'Δ %', width: '80px', align: 'right' },
  { key: 'trend', label: 'Trend · 12', width: '120px', align: 'right' },
]

// Same floor the backend's regression rule uses: a move under 5ms is not
// coloured as a regression however large it is in percent (a 0.3ms step going
// +27% is noise, not a finding).
const MIN_MS = 5
const deltaTone = (d: StepDelta): TextTone =>
  d.deltaPct == null || d.deltaMs == null || d.deltaMs < MIN_MS ? 'secondary' : d.deltaPct > 10 ? 'fail' : d.deltaPct > 4 ? 'warn' : 'secondary'
const NO_RUNTIME: Record<string, string> = {}
const NO_DESCRIPTIONS: Record<string, string> = {}

export function StepsPage() {
  const { scope, isLoading } = useScope()
  const focus = useFocusParam()
  const askCopilot = useUi((st) => st.askCopilot)
  // A deep link (Overview's "Inspect step", a Copilot citation) opens its row.
  // Adjusted during render when the focus param changes; clicks toggle after.
  const [open, setOpen] = useState(focus)
  const [openedFor, setOpenedFor] = useState(focus)
  if (focus !== openedFor) {
    setOpenedFor(focus)
    if (focus) setOpen(focus)
  }

  const run = scope?.run ?? null
  const runtimeOf = scope?.history.startup_model.step_runtime ?? NO_RUNTIME
  const descriptionOf = scope?.history.startup_model.step_descriptions ?? NO_DESCRIPTIONS
  const deltas = run && scope ? stepDeltas(run, scope.allRuns, scope.benchmarkRun) : []
  const get = useCallback(
    (d: StepDelta, k: Key) =>
      k === 'name' ? stepName(d.step) : k === 'runtime' ? (runtimeOf[d.step] ?? '') : k === 'current' ? d.current : k === 'baseline' ? d.baseline : k === 'deltaMs' ? d.deltaMs : d.deltaPct,
    [runtimeOf],
  )
  const { sorted, sort, toggle } = useSort(deltas, get, { key: 'deltaMs', dir: 'desc' })

  if (isLoading || !scope) return <EmptyState>Loading runs…</EmptyState>
  if (!run) return <EmptyState title="No runs yet">Capture a trace to see its steps.</EmptyState>
  if (!deltas.length) return <EmptyState>Run #{run.id} recorded no startup steps.</EmptyState>
  const from = scope.benchmarkRun ? `pinned benchmark #${scope.benchmarkRun.id}` : 'the median of the previous 10 runs'
  const kids = run.steps.reduce((n, st) => n + st.children.length, 0)

  return (
    <FlushCard
      title="Step durations"
      hint={`Run #${run.id} against ${from}. Select a row to drill down; the ? beside a name says what the step covers.`}
      aside={
        <Text variant="meta">
          {deltas.length} top-level steps · {kids} child slices
        </Text>
      }
    >
      <ExpandableTable
        label="Step durations"
        minWidth={920}
        columns={COLS}
        rows={sorted}
        rowKey={(d) => d.step}
        rowAttrs={(d) => ({ 'data-hl': d.step })}
        toggleLabel={(d) => stepName(d.step)}
        openKey={open}
        onToggle={(k) => setOpen(open === k ? null : k)}
        sort={{ ...sort, onSort: toggle }}
        cells={(d) => {
          const tone = deltaTone(d)
          return [
            <Term key="name" description={descriptionOf[d.step]} label={stepName(d.step)} weight={600}>
              {stepName(d.step)}
            </Term>,
            <Text key="runtime" variant="meta" tone="secondary">
              {runtimeOf[d.step] ?? '–'}
            </Text>,
            <Text key="current" as="span" variant="body" tone="primary" weight={600}>
              {fmt(d.current, 1)} ms
            </Text>,
            <Text key="baseline" as="span" variant="body">
              {d.baseline == null ? '–' : `${fmt(d.baseline, 1)} ms`}
            </Text>,
            <Text key="deltaMs" as="span" variant="body" tone={tone} weight={600}>
              {d.deltaMs == null ? '–' : signed(d.deltaMs, 1)}
            </Text>,
            <Text key="deltaPct" as="span" variant="body" tone={tone}>
              {d.deltaPct == null ? '–' : signed(d.deltaPct, 1, '%')}
            </Text>,
            <Sparkline key="trend" values={d.history.slice(-12)} height={24} color={tone === 'fail' ? 'var(--fail)' : 'var(--c1)'} />,
          ]
        }}
        detail={(d) => (
          <Drill
            d={d}
            run={run}
            prior={scope.allRuns}
            bench={scope.benchmarkRun}
            runtime={runtimeOf[d.step]}
            description={descriptionOf[d.step]}
            onAsk={() => askCopilot(`Why did ${stepName(d.step)} change in run #${run.id}?`)}
          />
        )}
      />
    </FlushCard>
  )
}

function Drill({
  d,
  run,
  prior,
  bench,
  runtime,
  description,
  onAsk,
}: {
  d: StepDelta
  run: Run
  prior: Run[]
  bench: Run | null
  runtime?: string
  description?: string
  onAsk: () => void
}) {
  // Each child's baseline comes from the same place as its step's.
  const baseKids = (name: string): number | null => {
    if (bench) return bench.steps.find((x) => x.step === d.step)?.children.find((c) => c.name === name)?.dur_ms ?? null
    const vals = prior
      .filter((r) => r.id < run.id)
      .slice(-10)
      .map((r) => r.steps.find((x) => x.step === d.step)?.children.find((c) => c.name === name)?.dur_ms)
      .filter((v): v is number => v != null)
      .sort((a, b) => a - b)
    return vals.length ? vals[Math.floor(vals.length / 2)]! : null
  }
  const kids: ChildSlice[] = d.row.children
  const ms = (v: number | null) => (v == null ? { value: '–' } : { value: fmt(v, 1), unit: 'ms' })
  const tiles = [
    { label: 'p50 · 10 runs', ...ms(d.p50) },
    { label: 'p90 · 10 runs', ...ms(d.p90) },
    { label: 'This run', ...ms(d.current) },
    { label: 'Runtime', value: runtime ?? '–' },
  ]
  return (
    <Stack gap={18}>
      {description && (
        <Text as="p" variant="body" className={s.about}>
          {description}
        </Text>
      )}
      <Row gap={10} wrap>
        <Stack grow>
          <StatGrid variant="boxes" min={130}>
            {tiles.map((t) => (
              <Stat key={t.label} size="md" {...t} />
            ))}
          </StatGrid>
        </Stack>
        <Button size="sm" onClick={onAsk}>
          <Icon name="sparkle" size={11} tone="accent" />
          Ask Copilot
        </Button>
      </Row>
      <Stack gap={10}>
        <Label>CHILD SLICES · BAR = THIS RUN, TICK = BASELINE</Label>
        <div>
          {kids.length === 0 && (
            <Text variant="body" tone="muted">
              No child slices were recorded inside this step, so its time cannot be attributed further.
            </Text>
          )}
          {kids.map((k) => {
            const b = baseKids(k.name)
            const pct = b ? ((k.dur_ms - b) / b) * 100 : null
            return (
              <div key={k.name} className={s.kid}>
                <Text variant="small" tone="primary" breakAnywhere>
                  {k.name}
                </Text>
                <Meter value={d.current ? k.dur_ms : 0} max={d.current} marker={d.current ? b : null} height={8} label={`${k.name}, share of ${stepName(d.step)} this run`} />
                <Text variant="small" tone="primary" weight={600} align="right">
                  {fmt(k.dur_ms, 1)} ms
                </Text>
                <Text variant="small" align="right">
                  {b == null ? '–' : `${fmt(b, 1)} ms`}
                </Text>
                <Text variant="small" tone={pct != null && pct > 20 ? 'fail' : 'secondary'} weight={600} align="right">
                  {b == null ? '–' : signed(k.dur_ms - b, 1)}
                </Text>
              </div>
            )
          })}
        </div>
      </Stack>
    </Stack>
  )
}
