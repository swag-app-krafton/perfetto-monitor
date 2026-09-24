import { Link, useNavigate } from 'react-router'
import type { GlobalBudgets, Run } from '@/api/types'
import { Button, Card, Eyebrow, Icon, Label, Meter, Row, Stack, StatusSquare, Text, toneColor } from '@/design'
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
  isLatest,
}: {
  run: Run
  benchmark: Run | null
  baselineLabel: string
  worst: Worst
  budgets: GlobalBudgets
  isLatest: boolean
}) {
  const navigate = useNavigate()
  const askCopilot = useUi((st) => st.askCopilot)
  const tone = verdictTone(run.analysis?.verdict)
  const word = tone === 'neutral' ? 'NO VERDICT' : tone.toUpperCase()
  const gates = METRICS.map((m) => ({ m, value: valueOf(run, m.key), budget: m.budget(run, budgets) })).filter(
    (g) => g.budget != null,
  )

  return (
    <Card edge={{ side: 'top', color: toneColor(tone) }} className={s.hero} data-hl="verdict">
      <Stack direction="row" wrap>
        <Stack gap={24} className={s.heroMain}>
          <Row gap={12} wrap>
            <Eyebrow>{isLatest ? 'Latest run verdict' : `Run #${run.id} verdict`}</Eyebrow>
            <Text variant="meta">
              Run #{run.id} vs {benchmark ? `Benchmark #${benchmark.id}` : baselineLabel}
            </Text>
          </Row>
          <Row gap={24} wrap>
            <StatusSquare tone={tone} size={88} fontSize={46} />
            <Text variant="hero" tone={tone === 'neutral' ? 'muted' : tone}>
              {word}
            </Text>
          </Row>
          <Text variant="headline" breakAnywhere className={s.headline}>
            {run.analysis?.headline ?? 'This run has no recorded analysis yet.'}
          </Text>

          {!benchmark && (
            <Text variant="body">
              No benchmark is pinned for this app and path, so steps are compared with the median of recent runs.{' '}
              <Link to="/history">Pin a benchmark</Link> to compare against a known-good build.
            </Text>
          )}

          {worst && (
            <Row gap={16} align="start" wrap className={s.worst}>
              <Text variant="label" className={s.worstLabel}>
                WORST REGRESSION
              </Text>
              <Stack gap={2} className={s.worstBody}>
                <Text variant="ui" weight={600}>
                  {stepName(worst.step)} grew against the {worst.baselineFrom === 'benchmark' ? 'benchmark' : 'recent median'} ·{' '}
                  <Text variant="ui" tone="fail" weight={600} nowrap>
                    ▲ {signed(worst.deltaMs!, 0, ' ms')}
                  </Text>
                </Text>
                <Text variant="body">
                  {worst.share != null
                    ? `Accounts for ${fmt(worst.share)}% of the startup change.`
                    : `${fmt(worst.current, 1)} ms against ${fmt(worst.baseline, 1)} ms.`}
                </Text>
              </Stack>
            </Row>
          )}

          <Row gap={8} wrap>
            {worst && (
              <Button variant="primary" onClick={() => navigate(focusHref('/steps', worst.step))}>
                Inspect step
              </Button>
            )}
            <Button onClick={() => navigate(`/compare?a=${run.id}${benchmark ? `&b=${benchmark.id}` : ''}`)}>Open in Compare</Button>
            <Button onClick={() => askCopilot(`Why did run #${run.id} get a ${word} verdict?`)}>
              <Icon name="sparkle" size={14} tone="accent" />
              Ask Copilot why
            </Button>
          </Row>
        </Stack>

        <Stack gap={14} className={s.gates}>
          <Label>RELEASE GATES</Label>
          {gates.length === 0 && <Text variant="body">No budgets apply to this app.</Text>}
          {gates.map(({ m, value, budget }) => {
            const t = gateTone(value, budget)
            return (
              <Stack key={m.key} gap={8} className={s.gate}>
                <Row gap={10}>
                  <StatusSquare tone={t} size={18} fontSize={10} />
                  <Text variant="ui" weight={500} className={s.gateName}>
                    {m.label}
                  </Text>
                  <Text variant="ui" weight={600} nowrap>
                    {value == null ? 'not measured' : `${fmt(value, m.dp)} ${m.unit}`}
                  </Text>
                  <Text variant="meta" align="right" nowrap className={s.gateLim}>
                    ≤ {fmt(budget, m.dp)} {m.unit}
                  </Text>
                </Row>
                <Meter height={3} value={value ?? 0} max={budget ?? 0} color={toneColor(t)} label={`${m.label} against its budget`} />
              </Stack>
            )
          })}
        </Stack>
      </Stack>
    </Card>
  )
}
