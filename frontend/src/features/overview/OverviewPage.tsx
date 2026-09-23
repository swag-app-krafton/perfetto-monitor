import { Link } from 'react-router'
import { Button, EmptyState, Grid, KpiTile, SectionTitle, Stack } from '@/design'
import { fmt, signed } from '@/domain/format'
import { METRICS, valueOf } from '@/domain/metrics'
import { useScope } from '@/domain/scope'
import { stepDeltas, worstRegression } from '@/domain/steps'
import { useUi } from '@/app/store'
import { FindingCard } from '@/features/shared/FindingCard'
import { findingArea, findingId, summariseSeverity } from '@/features/shared/findings'
import { usePinMutations, usePins } from '@/features/copilot/api'
import { VerdictHero } from './VerdictHero'
import { VerdictStrip } from './VerdictStrip'

export function OverviewPage() {
  const { scope, isLoading, error } = useScope()
  const askCopilot = useUi((st) => st.askCopilot)
  const pins = usePins()
  const { unpin } = usePinMutations()
  if (isLoading) return <EmptyState>Loading runs…</EmptyState>
  if (error) return <EmptyState title="Could not load runs">{error.message}</EmptyState>
  if (!scope?.run) {
    return (
      <EmptyState title="No runs yet" actions={<Link to="/capture">Profile an app</Link>}>
        Capture a trace from a connected device, or record a manual session, and its verdict appears here.
      </EmptyState>
    )
  }

  const { run, latest, runs, allRuns, benchmarkRun, history } = scope
  const prior = allRuns.filter((r) => r.id < run.id)
  const previous = prior[prior.length - 1] ?? null
  const base = benchmarkRun ?? previous
  const deltas = stepDeltas(run, allRuns, benchmarkRun)
  const ttidBase = valueOf(base, 'ttff_ms')
  const ttid = valueOf(run, 'ttff_ms')
  const worst = worstRegression(deltas, ttid != null && ttidBase != null ? ttid - ttidBase : null)
  const trendRuns = runs.slice(-12)
  const findings = run.analysis?.findings ?? []
  const pinned = (pins.data ?? []).filter((p) => p.run_id === run.id)

  return (
    <Stack as="section" gap={28}>
      <VerdictHero
        run={run}
        benchmark={benchmarkRun}
        baselineLabel={previous ? `previous run #${previous.id}` : 'no earlier run'}
        worst={worst}
        budgets={history.global_budgets}
        isLatest={scope.isLatest}
      />

      <Grid min={160} gap={12}>
        {METRICS.map((m) => {
          const v = valueOf(run, m.key)
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
      </Grid>

      <VerdictStrip runs={runs} run={run} latest={latest} benchmarkId={benchmarkRun?.id ?? null} />

      <Stack gap={12}>
        <SectionTitle aside={summariseSeverity(findings) + (pinned.length ? ` · ${pinned.length} pinned from Copilot` : '')}>Findings</SectionTitle>
        {findings.length === 0 && pinned.length === 0 && <EmptyState>No findings. Every measured metric is within budget and baseline.</EmptyState>}
        {findings.map((f, i) => (
          <FindingCard
            key={i}
            finding={f}
            id={findingId(i)}
            area={findingArea(f)}
            onAsk={() => askCopilot(`Explain finding ${findingId(i)} on run #${run.id}: ${f.title}`)}
          />
        ))}
        {pinned.map((p) => (
          <FindingCard
            key={`pin-${p.id}`}
            finding={{ title: p.title, severity: p.severity, evidence: p.evidence, recommendation: 'Confirm this in the trace before acting on it; the answer was computed from the run data.' }}
            id={`C-${p.id}`}
            area="Pinned from Copilot"
            actions={
              <Button variant="mini" onClick={() => unpin.mutate(p.id)} disabled={unpin.isPending}>
                Unpin
              </Button>
            }
          />
        ))}
      </Stack>
    </Stack>
  )
}
