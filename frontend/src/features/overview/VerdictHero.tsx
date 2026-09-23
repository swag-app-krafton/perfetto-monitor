import { Link, useNavigate } from 'react-router'
import type { GlobalBudgets, Run } from '@/api/types'
import { Button, Eyebrow, Icon, Label, StatusSquare, toneColor } from '@/design/components'
import { fmt, signed, stepName } from '@/domain/format'
import { gateTone, METRICS, valueOf, verdictTone } from '@/domain/metrics'
import type { worstRegression } from '@/domain/steps'
import { focusHref } from '@/lib/highlight'
import { useUi } from '@/app/store'
import s from './Overview.module.css'

type Worst = ReturnType<typeof worstRegression>

export function VerdictHero({
  run,
  benchmark,
  baselineLabel,
  worst,
  budgets,
}: {
  run: Run
  benchmark: Run | null
  baselineLabel: string
  worst: Worst
  budgets: GlobalBudgets
}) {
  const navigate = useNavigate()
  const askCopilot = useUi((st) => st.askCopilot)
  const tone = verdictTone(run.analysis?.verdict)
  const word = tone === 'neutral' ? 'NO VERDICT' : tone.toUpperCase()
  const gates = METRICS.map((m) => ({ m, value: valueOf(run, m.key), budget: m.budget(run, budgets) })).filter(
    (g) => g.budget != null,
  )

  return (
    <div className={s.hero} style={{ borderTopColor: toneColor(tone) }} data-hl="verdict">
      <div className={s.heroMain}>
        <div className={s.heroMeta}>
          <Eyebrow>LATEST RUN VERDICT</Eyebrow>
          <span className={s.heroMetaText}>
            Run #{run.id} vs {benchmark ? `Benchmark #${benchmark.id}` : baselineLabel}
          </span>
        </div>
        <div className={s.verdictRow}>
          <StatusSquare tone={tone} size={88} fontSize={46} />
          <div className={s.verdictWord} style={{ color: toneColor(tone) }}>
            {word}
          </div>
        </div>
        <div className={s.headline}>{run.analysis?.headline ?? 'This run has no recorded analysis yet.'}</div>

        {!benchmark && (
          <div className={s.worstSub}>
            No benchmark is pinned for this app and path, so steps are compared with the median of recent runs.{' '}
            <Link to="/history">Pin a benchmark</Link> to compare against a known-good build.
          </div>
        )}

        {worst && (
          <div className={s.worst}>
            <span className={s.worstLabel}>WORST REGRESSION</span>
            <div style={{ flex: 1, minWidth: 240 }}>
              <div className={s.worstTitle}>
                {stepName(worst.step)} grew against the {worst.baselineFrom === 'benchmark' ? 'benchmark' : 'recent median'} ·{' '}
                <span style={{ color: 'var(--fail)', whiteSpace: 'nowrap' }}>▲ {signed(worst.deltaMs!, 0, ' ms')}</span>
              </div>
              <div className={s.worstSub}>
                {worst.share != null
                  ? `Accounts for ${fmt(worst.share)}% of the startup change.`
                  : `${fmt(worst.current, 1)} ms against ${fmt(worst.baseline, 1)} ms.`}
              </div>
            </div>
          </div>
        )}

        <div className={s.actions}>
          {worst && (
            <Button variant="primary" onClick={() => navigate(focusHref('/steps', worst.step))}>
              Inspect step
            </Button>
          )}
          <Button onClick={() => navigate(`/compare?a=${run.id}${benchmark ? `&b=${benchmark.id}` : ''}`)}>Open in Compare</Button>
          <Button onClick={() => askCopilot(`Why did run #${run.id} get a ${word} verdict?`)}>
            <Icon name="sparkle" size={14} style={{ color: 'var(--accent)' }} />
            Ask Copilot why
          </Button>
        </div>
      </div>

      <div className={s.gates}>
        <Label>RELEASE GATES</Label>
        {gates.length === 0 && <div className={s.worstSub}>No budgets apply to this app.</div>}
        {gates.map(({ m, value, budget }) => {
          const t = gateTone(value, budget)
          const pct = value != null && budget ? Math.min(100, (value / budget) * 100) : 0
          return (
            <div key={m.key} className={s.gate}>
              <div className={s.gateRow}>
                <StatusSquare tone={t} size={18} fontSize={10} />
                <span className={s.gateName}>{m.label}</span>
                <span className={s.gateVal}>{value == null ? 'not measured' : `${fmt(value, m.dp)} ${m.unit}`}</span>
                <span className={s.gateLim}>
                  ≤ {fmt(budget, m.dp)} {m.unit}
                </span>
              </div>
              <div className={s.bar}>
                <div style={{ width: `${pct}%`, background: toneColor(t) }} />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
