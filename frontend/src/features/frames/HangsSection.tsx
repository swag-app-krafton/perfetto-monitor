import type { Run, Stability } from '@/api/types'
import { Card, Grid, KpiTile, LineChart, Stack, StatusPill, TableCard, Text, numCell } from '@/design'
import { fmt } from '@/domain/format'
import { DeltaTile } from '@/features/shared/DeltaTile'

/** Hangs after the first frame (stability.py), by Apple's definitions on both
 *  platforms: a microhang is a 100-250 ms stall of the main thread, a hang
 *  250 ms or more. */
export function HangsSection({ run, runs, prev }: { run: Run; runs: Run[]; prev: Run | null }) {
  const st = run.stability
  if (!st)
    return (
      <Card title="Hangs" hint="Main-thread stalls of 100 ms or more after the first frame.">
        <Text variant="body">
          Not measured for this run. Run <code>swagperf reextract</code> to measure it from its trace.
        </Text>
      </Card>
    )
  const h = st.hangs
  return (
    <Stack gap={20}>
      <Grid min={180} gap={12}>
        <DeltaTile
          label="Hangs"
          help="Main-thread stalls of 250 ms or more after the first frame: the app did not respond to touch."
          value={h.count}
          base={prev?.hang_count}
          note={h.startup.count ? `${h.startup.count} more during startup` : 'none during startup'}
        />
        <KpiTile label="Microhangs" help="Main-thread stalls of 100 to 250 ms after the first frame: noticeable, short of a hang." value={fmt(h.microhangs)} />
        <DeltaTile label="Longest hang" help="The longest main-thread stall after the first frame." value={h.longest_ms} base={prev?.longest_hang_ms} unit="ms" />
        <KpiTile
          label="Hang rate"
          help="Seconds of hang per hour of use, Apple's measure. Only for sessions of a minute or more: one hang in a short capture would read as a huge rate."
          value={h.rate_s_per_hr == null ? null : fmt(h.rate_s_per_hr, 1)}
          unit="s/hr"
          note={h.rate_s_per_hr == null ? `session ${fmt(h.session_s)} s: under a minute` : undefined}
        />
      </Grid>
      {runs.length > 1 && (
        <Card title="Hangs per run" hint="Hangs after the first frame, for each run in range.">
          <LineChart label="Hangs per run" labels={runs.map((r) => `#${r.id}`)} series={[{ name: 'Hangs', color: 'var(--c2)', values: runs.map((r) => r.hang_count) }]} unit="" decimals={0} />
        </Card>
      )}
      <HangTable st={st} />
    </Stack>
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
