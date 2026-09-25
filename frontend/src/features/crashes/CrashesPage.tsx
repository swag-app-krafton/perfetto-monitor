import { useState } from 'react'
import { useStability } from '@/api/hooks'
import type { AnrEvent, CrashEvent, JsErrorEvent, ResolvedFrame, Run, Stability } from '@/api/types'
import { Card, CodeBlock, EmptyState, ExpandableTable, Grid, LineChart, Segmented, Stack, StatusPill, Text, type SegmentOption, type Tone } from '@/design'
import { fmt } from '@/domain/format'
import { filterIncidents, incidentCounts, incidentsOf, JS_SOURCE, nothingFound, runCrashCount, type Incident, type IncidentFilter } from '@/domain/incidents'
import { useScope } from '@/domain/scope'
import { DeltaTile } from '@/features/shared/DeltaTile'

/** JS exceptions, ANRs and crashes for the run in view (stability.py), in one
 *  list in time order. Hangs are on Frame pacing. */
export function CrashesPage() {
  const { scope, isLoading } = useScope()
  const run = scope?.run ?? null
  const q = useStability(run?.id ?? null)
  const [filter, setFilter] = useState<IncidentFilter>('all')
  if (isLoading || !scope) return <EmptyState>Loading runs…</EmptyState>
  if (!run) return <EmptyState title="No runs yet">Capture a trace to see JS exceptions, ANRs and crashes.</EmptyState>
  // The detail, with stacks resolved, once the server has answered; the history's copy until then.
  const st = q.data?.stability ?? run.stability
  if (!st)
    return (
      <EmptyState title="Not measured for this run">
        This run was recorded before JS exceptions, ANRs and crashes were measured. Run <code>swagperf reextract</code> to measure it from its trace.
      </EmptyState>
    )
  const base = scope.allRuns.filter((r) => r.id < run.id).pop() ?? null
  const counts = incidentCounts(st)
  const all = incidentsOf(st)
  const ios = run.platform === 'ios'
  const firstCrash = all.find((i) => i.kind === 'crash')?.name

  return (
    <Stack as="section" gap={20}>
      <Grid min={200} gap={12}>
        <DeltaTile label="JS exceptions" help="Uncaught JavaScript errors, unhandled promise rejections and errors a screen's error boundary caught." value={counts.js} base={base?.js_errors} note={`${st.errors.js_fatal} fatal`} />
        <DeltaTile
          label="ANRs"
          help="Times Android declared the app not responding: a touch or key went unanswered for about 5 s, or a receiver or service ran too long."
          value={counts.anr}
          base={base?.anr_count}
          note={ios ? 'Android only' : counts.anr == null ? 'not measured in this trace' : undefined}
        />
        <DeltaTile
          label="Crashes"
          help="Times the app's process died on its own: an exception nothing caught, or a native signal."
          value={counts.crash}
          base={base?.crash_count}
          note={counts.crash == null ? 'the crash log was not recorded' : firstCrash}
        />
      </Grid>

      {scope.runs.length > 1 && (
        <Card title="JS exceptions, ANRs and crashes per run" hint="Each kind counted for every run in range.">
          <LineChart
            label="JS exceptions, ANRs and crashes per run"
            labels={scope.runs.map((r) => `#${r.id}`)}
            series={[
              { name: 'JS exceptions', color: 'var(--c3)', values: scope.runs.map((r) => r.js_errors) },
              { name: 'ANRs', color: 'var(--c2)', values: scope.runs.map((r) => r.anr_count ?? null) },
              { name: 'Crashes', color: 'var(--c1)', values: scope.runs.map(runCrashCount) },
            ]}
            unit=""
            decimals={0}
          />
        </Card>
      )}

      <Card title="What went wrong" hint="Every JS exception, ANR and crash in the run, in time order. Open a row for its stack, reason or crash log. Hangs are on Frame pacing.">
        <Stack gap={12}>
          <Segmented label="Show" options={FILTERS} value={filter} onChange={setFilter} />
          <IncidentTable rows={filterIncidents(all, filter)} empty={all.length ? 'None of this kind in this run.' : nothingFound(st)} />
          {st.errors.js > 0 && <SourceMapNote st={st} run={run} />}
        </Stack>
      </Card>
    </Stack>
  )
}

const FILTERS: SegmentOption<IncidentFilter>[] = [
  { value: 'all', label: 'All' },
  { value: 'js', label: 'JS exceptions' },
  { value: 'anr', label: 'ANRs' },
  { value: 'crash', label: 'Crashes' },
]

const KIND: Record<Incident['kind'], { label: string; tone: Tone }> = {
  js: { label: 'JS EXCEPTION', tone: 'warn' },
  anr: { label: 'ANR', tone: 'warn' },
  crash: { label: 'CRASH', tone: 'fail' },
}

const COLS = [
  { key: 'at', label: 'At', width: '90px' },
  { key: 'what', label: 'What', width: '150px' },
  { key: 'name', label: 'Name', width: 'minmax(200px, 2fr)' },
  { key: 'screen', label: 'Screen', width: 'minmax(140px, 1fr)' },
  { key: 'fatal', label: 'Fatal', width: '96px' },
]

const at = (ms: number | null) => (ms == null ? '–' : `${fmt(ms / 1000, 2)} s`)

function IncidentTable({ rows, empty }: { rows: Incident[]; empty: string }) {
  const [open, setOpen] = useState<string | null>(null)
  if (rows.length === 0) return <Text variant="body">{empty}</Text>
  return (
    <ExpandableTable
      label="JS exceptions, ANRs and crashes"
      minWidth={720}
      columns={COLS}
      rows={rows}
      rowKey={(i) => i.key}
      toggleLabel={(i) => `${i.name} at ${at(i.start_ms)}`}
      openKey={open}
      onToggle={(k) => setOpen(open === k ? null : k)}
      cells={(i) => [
        at(i.start_ms),
        <StatusPill key="k" tone={KIND[i.kind].tone}>
          {KIND[i.kind].label}
        </StatusPill>,
        <Text key="n" as="span" variant="body" tone="primary" weight={600}>
          {i.name}
        </Text>,
        i.screen ?? '–',
        <StatusPill key="f" tone={i.fatal ? 'fail' : 'neutral'}>
          {i.fatal ? 'FATAL' : 'NO'}
        </StatusPill>,
      ]}
      detail={(i) => (i.kind === 'js' ? <JsErrorDetail e={i.js} /> : i.kind === 'anr' ? <AnrDetail a={i.anr} /> : <CrashDetail c={i.crash} />)}
    />
  )
}

/** How the run's JS stacks were resolved, or how to get its source map. */
function SourceMapNote({ st, run }: { st: Stability; run: Run }) {
  const map = st.errors.source_map
  if (map) return <Text variant="small">JS stacks are resolved against this build's source map ({map}).</Text>
  const app = run.meta?.app
  const tag = app?.version_name && app.version_code != null ? `v${app.version_name}-${app.version_code}` : 'v<name>-<code>'
  return (
    <Text variant="small">
      No source map is registered for this build, so its stacks are shown as Hermes reported them. For a tagged release, run <code>swagperf maps fetch --tag {tag}</code> (or{' '}
      <code>--all</code>). For a local build, run <code>swagperf maps add &lt;map&gt; --app {run.app_pkg ?? '<id>'} --bundle &lt;bundle&gt;</code>.
    </Text>
  )
}

const frameLine = (f: ResolvedFrame) => (f.resolved ? `${f.in_app ? '' : '  '}${f.fn ?? '<anonymous>'}  ${f.file ?? '?'}:${f.line ?? '?'}:${f.col ?? '?'}` : `  ${f.raw}`)

function JsErrorDetail({ e }: { e: JsErrorEvent }) {
  if (!e.has_record) return <Text variant="body">Only the marker arrived: the error's record (message and stack) is missing from the trace.</Text>
  return (
    <Stack gap={12}>
      <Text variant="small">{JS_SOURCE[e.source]}</Text>
      {e.message ? <Text variant="body">{e.message}</Text> : null}
      {e.frames ? <CodeBlock lang="Stack, resolved (library frames indented)" code={e.frames.map(frameLine).join('\n')} /> : e.stack && <CodeBlock lang="Stack, as Hermes reported it" code={e.stack} />}
      {e.component_stack && <CodeBlock lang="Component stack" code={e.component_stack.trim()} defaultOpen={false} />}
    </Stack>
  )
}

function AnrDetail({ a }: { a: AnrEvent }) {
  return (
    <Stack gap={12}>
      <Text variant="body">
        {a.type_label}.{a.dur_ms ? ` Android waits ${fmt(a.dur_ms)} ms for this before declaring an ANR.` : ''}
      </Text>
      {a.subject && <CodeBlock lang="The system's reason" code={a.subject} />}
      <Text variant="body">
        {a.main_thread
          ? `The main thread was in ${a.main_thread.name} for ${fmt(a.main_thread.dur_ms)} ms.`
          : "The trace doesn't show what the main thread was doing: nothing was traced on it in the window before the ANR."}
      </Text>
    </Stack>
  )
}

function CrashDetail({ c }: { c: CrashEvent }) {
  if (!c.log) return <Text variant="body">{c.message ?? 'The process ended on its own; this run recorded no crash log.'}</Text>
  return <CodeBlock lang={c.kind === 'native' ? 'Crash log: signal and backtrace' : 'Crash log: exception and stack'} code={c.log} />
}
