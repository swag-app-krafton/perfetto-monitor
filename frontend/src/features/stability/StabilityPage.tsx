import { useState } from 'react'
import { useStability } from '@/api/hooks'
import type { JsErrorEvent, ResolvedFrame, Run, Stability } from '@/api/types'
import { Card, CodeBlock, EmptyState, ExpandableTable, Grid, KpiTile, LineChart, Stack, StatusPill, TableCard, Text, numCell } from '@/design'
import { fmt, signed } from '@/domain/format'
import { useScope } from '@/domain/scope'

/** Hangs, JS errors and crashes for the run in view (stability.py). Hangs
 *  use Apple's definitions on both platforms: a microhang is a 100-250 ms
 *  stall of the main thread, a hang 250 ms or more. */
export function StabilityPage() {
  const { scope, isLoading } = useScope()
  const run = scope?.run ?? null
  const q = useStability(run?.id ?? null)
  if (isLoading || !scope) return <EmptyState>Loading runs…</EmptyState>
  if (!run) return <EmptyState title="No runs yet">Capture a trace to see hangs and JS errors.</EmptyState>
  // The detail, with stacks resolved, once the server has answered; the
  // history's copy until then.
  const st = q.data?.stability ?? run.stability
  if (!st)
    return (
      <EmptyState title="Not measured for this run">
        This run was recorded before hangs and JS errors were measured. Run <code>swagperf reextract</code> to measure it from its trace.
      </EmptyState>
    )
  const base = scope.allRuns.filter((r) => r.id < run.id).pop() ?? null
  const labels = scope.runs.map((r) => `#${r.id}`)

  return (
    <Stack as="section" gap={20}>
      <Grid min={180} gap={12}>
        <Tile label="Hangs" help="Main-thread stalls of 250 ms or more after the first frame: the app did not respond to touch." value={st.hangs.count} base={base?.hang_count} note={st.hangs.startup.count ? `${st.hangs.startup.count} more during startup` : 'none during startup'} />
        <KpiTile label="Microhangs" help="Main-thread stalls of 100 to 250 ms after the first frame: noticeable, short of a hang." value={fmt(st.hangs.microhangs)} />
        <Tile label="Longest hang" help="The longest main-thread stall after the first frame." value={st.hangs.longest_ms} base={base?.longest_hang_ms} unit="ms" />
        <KpiTile
          label="Hang rate"
          help="Seconds of hang per hour of use, Apple's measure. Only for sessions of a minute or more: one hang in a short capture would read as a huge rate."
          value={st.hangs.rate_s_per_hr == null ? null : fmt(st.hangs.rate_s_per_hr, 1)}
          unit="s/hr"
          note={st.hangs.rate_s_per_hr == null ? `session ${fmt(st.hangs.session_s)} s: under a minute` : undefined}
        />
        <Tile label="JS errors" help="Uncaught JavaScript errors, unhandled promise rejections and errors a screen's error boundary caught." value={st.errors.js} base={base?.js_errors} note={`${st.errors.js_fatal} fatal`} />
        <KpiTile label="Crashed" help="The app's process died on its own during the run." value={st.crash.crashed ? 'Yes' : 'No'} note={st.crash.reason ?? undefined} />
      </Grid>

      {scope.runs.length > 1 && (
        <Card title="Hangs and JS errors per run" hint="Hangs after the first frame, and JS errors of any kind, for each run in range.">
          <LineChart
            label="Hangs and JS errors per run"
            labels={labels}
            series={[
              { name: 'Hangs', color: 'var(--c2)', values: scope.runs.map((r) => r.hang_count) },
              { name: 'JS errors', color: 'var(--c3)', values: scope.runs.map((r) => r.js_errors) },
            ]}
            budget={null}
            unit=""
            decimals={0}
          />
        </Card>
      )}

      <HangTable st={st} />
      <ErrorTable st={st} run={run} />
    </Stack>
  )
}

function Tile({ label, help, value, base, unit, note }: { label: string; help: string; value: number | null; base: number | null | undefined; unit?: string; note?: string }) {
  return (
    <KpiTile
      label={label}
      help={help}
      value={value == null ? null : fmt(value)}
      unit={unit}
      delta={value != null && base != null ? { value: value - base, text: signed(value - base, 0, unit ? ` ${unit}` : ''), against: `vs ${fmt(base)} in the previous run` } : null}
      note={note}
    />
  )
}

const seconds = (ms: number) => `${fmt(ms / 1000, 2)} s`

function HangTable({ st }: { st: Stability }) {
  const events = st.hangs.events
  return (
    <TableCard title="Hangs" hint={`Every stall of 100 ms or more, from ${st.hangs.source}. Startup stalls happen before the first frame.`} minWidth={560}>
      <thead>
        <tr>
          <th>At</th>
          <th className={numCell}>Duration</th>
          <th>Kind</th>
          <th>Screen</th>
        </tr>
      </thead>
      <tbody>
        {events.length === 0 && (
          <tr>
            <td colSpan={4}>
              <Text variant="body">No stall of 100 ms or more in this run.</Text>
            </td>
          </tr>
        )}
        {events.map((h) => (
          <tr key={`${h.start_ms}`}>
            <td>{seconds(h.start_ms)}</td>
            <td className={numCell}>{fmt(h.dur_ms)} ms</td>
            <td>
              <StatusPill tone={h.kind === 'hang' ? 'warn' : 'neutral'}>{h.kind === 'hang' ? 'HANG' : 'MICROHANG'}</StatusPill>
            </td>
            <td>
              <Text variant="body">{h.screen ?? 'startup'}</Text>
            </td>
          </tr>
        ))}
      </tbody>
    </TableCard>
  )
}

const SOURCE: Record<JsErrorEvent['source'], string> = {
  global: 'Uncaught',
  promise: 'Unhandled rejection',
  boundary: 'Caught by a boundary',
  manual: 'Reported by the app',
}

const COLS = [
  { key: 'at', label: 'At', width: '90px' },
  { key: 'error', label: 'Error', width: 'minmax(200px, 2fr)' },
  { key: 'source', label: 'How it surfaced', width: 'minmax(170px, 1.2fr)' },
  { key: 'fatal', label: 'Fatal', width: '96px' },
  { key: 'screen', label: 'Screen', width: 'minmax(140px, 1fr)' },
]

function ErrorTable({ st, run }: { st: Stability; run: Run }) {
  const [open, setOpen] = useState<string | null>(null)
  const events = st.errors.events
  const map = st.errors.source_map
  return (
    <Card
      title="JS errors"
      hint={
        map
          ? `Stacks resolved against this build's source map (${map}).`
          : `No source map is registered for this build, so stacks show Hermes bytecode offsets. Register it with: swagperf maps add <map> --app ${run.app_pkg ?? '<app>'} --platform ${run.platform ?? 'android'} --bundle <bundle>`
      }
    >
      {events.length === 0 ? (
        <Text variant="body">No JavaScript error in this run.</Text>
      ) : (
        <ExpandableTable
          label="JS errors"
          minWidth={720}
          columns={COLS}
          rows={events}
          rowKey={(e) => e.id}
          toggleLabel={(e) => `${e.name} at ${seconds(e.start_ms)}`}
          openKey={open}
          onToggle={(k) => setOpen(open === k ? null : k)}
          cells={(e) => [
            seconds(e.start_ms),
            <Text key="n" as="span" variant="body" tone="primary" weight={600}>
              {e.name}
            </Text>,
            SOURCE[e.source],
            <StatusPill key="f" tone={e.fatal ? 'fail' : 'neutral'}>
              {e.fatal ? 'FATAL' : 'NO'}
            </StatusPill>,
            e.screen ?? '–',
          ]}
          detail={(e) => <ErrorDetail e={e} />}
        />
      )}
    </Card>
  )
}

const frameLine = (f: ResolvedFrame) =>
  f.resolved ? `${f.in_app ? '' : '  '}${f.fn ?? '<anonymous>'}  ${f.file ?? '?'}:${f.line ?? '?'}:${f.col ?? '?'}` : `  ${f.raw}`

function ErrorDetail({ e }: { e: JsErrorEvent }) {
  if (!e.has_record)
    return <Text variant="body">Only the marker arrived: the error's record (message and stack) is missing from the trace.</Text>
  return (
    <Stack gap={12}>
      {e.message ? <Text variant="body">{e.message}</Text> : null}
      {e.frames ? (
        <CodeBlock lang="Stack, resolved (library frames indented)" code={e.frames.map(frameLine).join('\n')} />
      ) : (
        e.stack && <CodeBlock lang="Stack, as Hermes reported it" code={e.stack} />
      )}
      {e.component_stack && <CodeBlock lang="Component stack" code={e.component_stack.trim()} defaultOpen={false} />}
    </Stack>
  )
}
