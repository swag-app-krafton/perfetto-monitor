import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import type { Run } from '@/api/types'
import { Button, Card, GLYPH, StatusPill, toneColor } from '@/design/components'
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
      actions={
        <div className={s.legend}>
          {(['pass', 'warn', 'fail'] as const).map((k) => (
            <span key={k}>
              <span className={s.swatch} style={{ background: `var(--${k})` }} />
              {counts[k]} {k}
            </span>
          ))}
        </div>
      }
    >
      <div className={s.strip}>
        {runs.map((r) => {
          const t = verdictTone(r.analysis?.verdict)
          const label = `Run #${r.id}, ${shortDate(r.ts)}, ${t === 'neutral' ? 'no verdict' : t.toUpperCase()}, TTID ${fmt(r.ttff_ms)} ms`
          return (
            <div key={r.id} className={s.cellCol}>
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
            </div>
          )
        })}
      </div>
      <div className={s.stripFoot}>
        <span>
          #{first.id} · {shortDate(first.ts)}
        </span>
        {benchmarkId != null && <span>B = pinned benchmark</span>}
        <span>
          #{last.id} · {shortDate(last.ts)}
        </span>
      </div>
      <div className={s.detail}>
        <StatusPill tone={selTone}>{selTone === 'neutral' ? 'NO VERDICT' : undefined}</StatusPill>
        <span className={s.detailId}>Run #{sel.id}</span>
        <span style={{ fontSize: 13, color: 'var(--tx2)' }}>
          {shortDate(sel.ts)} · {sel.device ?? 'unknown device'} · {sel.app_version ?? sel.label ?? 'no build'}
        </span>
        <span style={{ fontSize: 13 }}>
          TTID <b>{fmt(sel.ttff_ms)} ms</b> · Slow <b>{fmt(sel.slow_pct, 2)} %</b> · Janky <b>{fmt(sel.janky_pct, 2)} %</b> · Peak{' '}
          <b>{fmt(sel.peak_rss_mb)} MB</b>
        </span>
        <div style={{ flex: 1 }} />
        {sel.id !== latest.id && (
          <Button variant="mini" onClick={() => navigate(`/compare?a=${latest.id}&b=${sel.id}`)}>
            Compare with #{latest.id}
          </Button>
        )}
      </div>
    </Card>
  )
}
