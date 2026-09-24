import type { Run } from '@/api/types'
import { Button, Card, Legend, Row, Spacer, StatusPill, StatusStrip, Text } from '@/design'
import { fmt, shortDate } from '@/domain/format'
import { runVerdict } from '@/domain/metrics'
import { useLaneNavigate } from '@/app/profiler'
import s from './Overview.module.css'

/** Every run in range as a verdict cell, oldest to newest. The run in view
 *  (picked in the top bar) is outlined and its numbers are shown below. */
export function VerdictStrip({ runs, run: sel, latest, benchmarkId }: { runs: Run[]; run: Run; latest: Run | null; benchmarkId: number | null }) {
  const navigate = useLaneNavigate()
  const counts = { pass: 0, warn: 0, fail: 0 }
  for (const r of runs) {
    const t = runVerdict(r).tone
    if (t !== 'neutral') counts[t]++
  }
  const first = runs[0]!
  const last = runs[runs.length - 1]!
  const selVerdict = runVerdict(sel)
  const selTone = selVerdict.tone

  return (
    <Card
      data-hl="strip"
      title="Verdict by run"
      hint={`${runs.length === 1 ? 'One run' : `Last ${runs.length} runs`}, oldest to newest. The outlined run is the one in view; pick another in the top bar.`}
      actions={<Legend label="Verdict counts" items={(['pass', 'warn', 'fail'] as const).map((k) => ({ label: `${counts[k]} ${k}`, color: `var(--${k})` }))} />}
    >
      <div className={s.strip}>
        <StatusStrip
          label="Verdict of each run, oldest to newest"
          cells={runs.map((r) => {
            const v = runVerdict(r)
            return {
              key: String(r.id),
              tone: v.tone,
              label: `Run #${r.id}, ${shortDate(r.ts)}, ${v.word.toLowerCase()}, TTID ${fmt(r.ttff_ms)} ms`,
              current: r.id === sel.id,
              mark: r.id === benchmarkId ? 'B' : undefined,
            }
          })}
          start={`#${first.id} · ${shortDate(first.ts)}`}
          middle={benchmarkId != null ? 'B = pinned benchmark' : undefined}
          end={`#${last.id} · ${shortDate(last.ts)}`}
        />
      </div>
      <Row gap={14} wrap className={s.detail}>
        <StatusPill tone={selTone}>{selTone === 'neutral' ? selVerdict.word : undefined}</StatusPill>
        <Text variant="heading-sm" as="span">
          Run #{sel.id}
        </Text>
        <Text variant="body" as="span">
          {shortDate(sel.ts)} · {sel.device ?? 'unknown device'} · {sel.app_version ?? sel.label ?? 'no build'}
        </Text>
        <Text variant="body" tone="primary" as="span">
          TTID <b>{fmt(sel.ttff_ms)} ms</b> · Slow <b>{fmt(sel.slow_pct, 2)} %</b> · Janky <b>{fmt(sel.janky_pct, 2)} %</b> · Peak{' '}
          <b>{fmt(sel.peak_rss_mb)} MB</b>
        </Text>
        <Spacer />
        {latest && sel.id !== latest.id && (
          <Button variant="mini" onClick={() => navigate(`/compare?mode=run&a=${sel.id}&b=${latest.id}`)}>
            Compare with latest #{latest.id}
          </Button>
        )}
      </Row>
    </Card>
  )
}
