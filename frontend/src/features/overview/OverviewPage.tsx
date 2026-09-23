import { Link } from 'react-router'
import { EmptyState, KpiTile, SectionTitle } from '@/design/components'
import { fmt, signed } from '@/domain/format'
import { METRICS, valueOf } from '@/domain/metrics'
import { useScope } from '@/domain/scope'
import { stepDeltas, worstRegression } from '@/domain/steps'
import { useUi } from '@/app/store'
import { FindingCard } from '@/features/shared/FindingCard'
import { findingArea, findingId, summariseSeverity } from '@/features/shared/findings'
import { VerdictHero } from './VerdictHero'
import { VerdictStrip } from './VerdictStrip'
import s from './Overview.module.css'

export function OverviewPage() {
  const { scope, isLoading, error } = useScope()
  const askCopilot = useUi((st) => st.askCopilot)
  if (isLoading) return <EmptyState>Loading runs…</EmptyState>
  if (error) return <EmptyState title="Could not load runs">{error.message}</EmptyState>
  if (!scope?.latest) {
    return (
      <EmptyState title="No runs yet" actions={<Link to="/capture">Profile an app</Link>}>
        Capture a trace from a connected device, or record a manual session, and its verdict appears here.
      </EmptyState>
    )
  }

  const { latest, runs, allRuns, benchmarkRun, history } = scope
  const prior = allRuns.filter((r) => r.id < latest.id)
  const previous = prior[prior.length - 1] ?? null
  const base = benchmarkRun ?? previous
  const deltas = stepDeltas(latest, allRuns, benchmarkRun)
  const ttidBase = valueOf(base, 'ttff_ms')
  const ttid = valueOf(latest, 'ttff_ms')
  const worst = worstRegression(deltas, ttid != null && ttidBase != null ? ttid - ttidBase : null)
  const trendRuns = runs.slice(-12)
  const findings = latest.analysis?.findings ?? []

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
      <VerdictHero
        run={latest}
        benchmark={benchmarkRun}
        baselineLabel={previous ? `previous run #${previous.id}` : 'no earlier run'}
        worst={worst}
        budgets={history.global_budgets}
      />

      <div className={s.kpis}>
        {METRICS.map((m) => {
          const v = valueOf(latest, m.key)
          const b = valueOf(base, m.key)
          const delta =
            v != null && b != null
              ? { value: v - b, text: signed(v - b, m.dp, m.deltaUnit), against: `vs ${fmt(b, m.dp)} ${m.unit}` }
              : null
          return (
            <KpiTile
              key={m.key}
              label={m.key === 'ttff_ms' ? m.short : m.label}
              help={m.key === 'ttff_ms' ? `${m.label}. ${m.help}` : m.help}
              value={v == null ? null : fmt(v, m.dp)}
              unit={m.unit}
              delta={delta}
              note={base ? undefined : 'no earlier run to compare'}
              trend={trendRuns.map((r) => valueOf(r, m.key))}
            />
          )
        })}
      </div>

      <VerdictStrip runs={runs} latest={latest} benchmarkId={benchmarkRun?.id ?? null} />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <SectionTitle aside={summariseSeverity(findings)}>Findings</SectionTitle>
        {findings.length === 0 && <EmptyState>No findings. Every measured metric is within budget and baseline.</EmptyState>}
        {findings.map((f, i) => (
          <FindingCard
            key={i}
            finding={f}
            id={findingId(i)}
            area={findingArea(f)}
            onAsk={() => askCopilot(`Explain finding ${findingId(i)} on run #${latest.id}: ${f.title}`)}
          />
        ))}
      </div>
    </section>
  )
}
