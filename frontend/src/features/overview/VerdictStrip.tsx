import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import type { Run } from '@/api/types'
import { Button, Card, GLYPH, Legend, Row, Spacer, Stack, StatusPill, Text, toneColor } from '@/design'
import { fmt, shortDate } from '@/domain/format'
import { verdictTone } from '@/domain/metrics'
import s from './Overview.module.css'

export function VerdictStrip({ runs, latest, benchmarkId }: { runs: Run[]; latest: Run; benchmarkId: number | null }) {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  // History's "Open" lands here with ?run=<id> selected in the strip.
  const [selId, setSelId] = useState(() => Number(params.get('run')) || latest.id)
  const sel = runs.find((r) => r.id === selId) ?? latest
  const counts = { pass: 0, warn: 0, fail: 0 }
  for (const r of runs) {
    const t = verdictTone(r.analysis?.verdict)
    if (t !== 'neutral') counts[t]++
  }
  const first = runs[0]!
  const last = runs[runs.length - 1]!
  const selTone = verdictTone(sel.analysis?.verdict)

  return (
    <Card
      data-hl="strip"
      title="Verdict by run"
      hint={`${runs.length === 1 ? 'One run' : `Last ${runs.length} runs`}, oldest to newest. Select a run to see its numbers.`}
      actions={<Legend label="Verdict counts" items={(['pass', 'warn', 'fail'] as const).map((k) => ({ label: `${counts[k]} ${k}`, color: `var(--${k})` }))} />}
    >
      <Row gap={4} align="stretch" className={s.strip}>
        {runs.map((r) => {
          const t = verdictTone(r.analysis?.verdict)
          const label = `Run #${r.id}, ${shortDate(r.ts)}, ${t === 'neutral' ? 'no verdict' : t.toUpperCase()}, TTID ${fmt(r.ttff_ms)} ms`
          return (
            <Stack key={r.id} gap={6} align="stretch" grow>
              <button
                type="button"
                className={s.cell}
                aria-label={label}
                title={label}
                aria-pressed={r.id === sel.id}
                style={{ background: t === 'neutral' ? 'var(--s3)' : toneColor(t) }}
                onClick={() => setSelId(r.id)}
              >
                {t === 'warn' || t === 'fail' ? GLYPH[t] : ''}
              </button>
              <span className={s.bMark}>{r.id === benchmarkId ? 'B' : ''}</span>
            </Stack>
          )
        })}
      </Row>
      <Row gap={8} justify="between" className={s.stripFoot}>
        <Text variant="caption">
          #{first.id} · {shortDate(first.ts)}
        </Text>
        {benchmarkId != null && <Text variant="caption">B = pinned benchmark</Text>}
        <Text variant="caption">
          #{last.id} · {shortDate(last.ts)}
        </Text>
      </Row>
      <Row gap={14} wrap className={s.detail}>
        <StatusPill tone={selTone}>{selTone === 'neutral' ? 'NO VERDICT' : undefined}</StatusPill>
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
        {sel.id !== latest.id && (
          <Button variant="mini" onClick={() => navigate(`/compare?a=${latest.id}&b=${sel.id}`)}>
            Compare with #{latest.id}
          </Button>
        )}
      </Row>
    </Card>
  )
}
