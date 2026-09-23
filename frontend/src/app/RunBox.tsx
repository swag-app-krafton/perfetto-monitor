import { useState } from 'react'
import { useRunMeta } from '@/api/hooks'
import type { Run } from '@/api/types'
import { Badge, Button, Icon, Row, Spacer, Stack, StatusPill, Text, type Tone } from '@/design'
import { shortDate } from '@/domain/format'
import { useSelectRun } from '@/domain/scope'
import { RunDetailsDialog } from './RunDetails'
import { appSummary, deviceSummary, runKind, startLabel } from './runMeta'
import s from './RunBox.module.css'

const VERDICT_TONE: Record<string, Tone> = { pass: 'pass', warn: 'warn', fail: 'fail' }

/** The run in view, on every screen: its ID and verdict, what it ran on, the
 *  app build, and a way to its full metadata. */
export function RunBox({ run, isLatest }: { run: Run; isLatest: boolean }) {
  const [open, setOpen] = useState(false)
  const selectRun = useSelectRun()
  // Reading an older run's trace metadata happens once; until then the
  // history's copy (device label only) is shown.
  const q = useRunMeta(run.id)
  const meta = q.data ?? run.meta
  const verdict = run.analysis?.verdict
  return (
    <section className={s.box} aria-label={`Run #${run.id}`}>
      <Stack gap={8}>
        <Row gap={8} wrap>
          <span className={s.id}>RUN #{run.id}</span>
          {verdict && <StatusPill tone={VERDICT_TONE[verdict] ?? 'neutral'} />}
          <Spacer />
          {isLatest ? (
            <Badge tone="c1">Latest</Badge>
          ) : (
            <Button variant="quiet" onClick={() => selectRun(null)} title="Show the newest run">
              Older run · go to latest
            </Button>
          )}
        </Row>
        <Stack gap={2}>
          <Text variant="small" tone="primary" weight={500} breakAnywhere>
            {deviceSummary(meta, run.device)}
          </Text>
          <Text variant="small" breakAnywhere>
            {appSummary(meta, run.app_name ?? null)}
          </Text>
          <Text variant="meta">
            {shortDate(run.ts, true)} · {startLabel(run.path_kind)} · {runKind(run)}
          </Text>
        </Stack>
        <Row>
          <Button variant="outline" onClick={() => setOpen(true)}>
            <Icon name="menu" size={12} />
            Run details
          </Button>
        </Row>
      </Stack>
      <RunDetailsDialog run={run} meta={meta} loading={q.isFetching && !q.data} open={open} onClose={() => setOpen(false)} />
    </section>
  )
}
