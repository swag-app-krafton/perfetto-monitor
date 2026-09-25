import { useEffect, useMemo } from 'react'
import { useSearchParams } from 'react-router'
import { useCompare } from '@/api/hooks'
import type { Run } from '@/api/types'
import { Badge, Banner, Card, EmptyState, Grid, Label, Row, Segmented, SelectField, Spinner, Stack, Text } from '@/design'
import { pathLabel, shortDate } from '@/domain/format'
import { useScope, useSelectRun } from '@/domain/scope'
import { ComparisonTables } from '@/features/shared/ComparisonTables'
import s from './Compare.module.css'

export function ComparePage() {
  const { scope, isLoading } = useScope()
  const [params, setParams] = useSearchParams()
  const runs = useMemo(() => scope?.allRuns ?? [], [scope])
  const bench = scope?.benchmarkRun ?? null
  const mode = params.get('mode') === 'run' || !bench ? 'run' : 'bench'
  // Run A is the run in view, chosen in the top bar. A link's `a` (Copilot,
  // History) selects that run there, then leaves the URL.
  const selectRun = useSelectRun()
  const aParam = Number(params.get('a')) || null
  const ready = !!scope
  useEffect(() => {
    if (aParam == null || !ready) return
    selectRun(aParam)
    const next = new URLSearchParams(params)
    next.delete('a')
    setParams(next, { replace: true })
  }, [aParam, ready, selectRun, params, setParams])
  const a = aParam ?? scope?.run?.id ?? null
  const bParam = Number(params.get('b')) || null
  const b = mode === 'bench' ? (bench?.id ?? null) : (bParam ?? runs.filter((r) => r.id !== a).pop()?.id ?? null)
  const q = useCompare(a, b)

  const set = (k: string, v: string | null) => {
    const next = new URLSearchParams(params)
    if (v == null) next.delete(k)
    else next.set(k, v)
    setParams(next, { replace: true })
  }

  if (isLoading || !scope) return <EmptyState>Loading runs…</EmptyState>
  if (runs.length < 2) return <EmptyState title="Not enough runs">Compare needs at least two runs for this app and path.</EmptyState>
  const runA = a != null ? scope.byId(a) : undefined
  const runB = b != null ? scope.byId(b) : undefined
  const sub = (r?: Run) => (r ? `${shortDate(r.ts, true)} · ${r.device ?? 'unknown device'} · ${r.app_version ?? r.label ?? 'no build'}` : '')
  // Pickers list every run of this app, across paths: comparing a cold run with
  // a warm one is allowed -- the "Not comparable" banner says why it misleads.
  const appRuns = scope.history.runs.filter((r) => r.app_pkg === scope.run?.app_pkg)
  const opts = [...appRuns].reverse().map((r) => ({ value: String(r.id), label: `#${r.id} · ${shortDate(r.ts)} · ${pathLabel(r.path_kind)} · ${r.label ?? ''}` }))
  const d = q.data
  const descriptionOf = scope.history.startup_model.step_descriptions

  return (
    <Stack as="section" gap={20}>
      <div>
        <Segmented
          label="Compare against"
          value={mode}
          onChange={(v) => set('mode', v === 'run' ? 'run' : null)}
          options={[
            ...(bench ? [{ value: 'bench' as const, label: 'vs pinned benchmark' }] : []),
            { value: 'run' as const, label: 'Run A vs Run B' },
          ]}
        />
      </div>
      <Grid min={320}>
        <Card>
          <Stack gap={10}>
            <Label color="var(--c1)">RUN A</Label>
            <Row gap={10} className={s.pinnedRun}>
              <Text variant="heading-lg">#{a}</Text>
              <Badge tone="c1">In view</Badge>
            </Row>
            <Text variant="meta">{sub(runA)}</Text>
            <Text variant="caption">Change it with Run in the top bar.</Text>
          </Stack>
        </Card>
        <Card>
          <Stack gap={10}>
            <Label color="var(--c4)">RUN B</Label>
            {mode === 'bench' && bench ? (
              <Row gap={10} className={s.pinnedRun}>
                <Text variant="heading-lg">#{bench.id}</Text>
                <Badge tone="c4">PINNED</Badge>
              </Row>
            ) : (
              <div>
                <SelectField label="Run" value={String(b)} options={opts} onChange={(v) => set('b', v)} />
              </div>
            )}
            <Text variant="meta">{sub(runB)}</Text>
          </Stack>
        </Card>
      </Grid>

      {a === b && <Banner tone="warn" title="Same run">Run A and Run B are the same run; pick a different one to compare.</Banner>}
      {d && !d.same_device && (
        <Banner tone="warn" title="Different devices">
          #{d.run.id} ran on {d.run.device ?? 'an unknown device'}, #{d.base.id} on {d.base.device ?? 'an unknown device'}. Device classes differ in speed, so part
          of any difference is the hardware.
        </Banner>
      )}
      {d && !d.comparable && (
        <Banner tone="fail" title="Not comparable">
          #{d.run.id} is a {pathLabel(d.run.path_kind).toLowerCase()} run and #{d.base.id} a {pathLabel(d.base.path_kind).toLowerCase()} run. Different startup paths
          measure different work.
        </Banner>
      )}

      {q.isLoading && (
        <EmptyState>
          <Spinner /> &nbsp;Comparing…
        </EmptyState>
      )}
      {q.error && <EmptyState title="Could not compare">{q.error.message}</EmptyState>}
      {d && <ComparisonTables data={d} runLabel={`Run A #${d.run.id}`} baseLabel={`Run B #${d.base.id}`} descriptions={descriptionOf} hl="compare" />}
    </Stack>
  )
}
