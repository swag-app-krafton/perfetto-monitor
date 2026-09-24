import { useCallback, useMemo, useState } from 'react'
import { useBenchmarkMutations } from '@/api/hooks'
import type { Run } from '@/api/types'
import { Badge, Button, Card, EmptyState, Grid, Row, SearchInput, Segmented, SectionTitle, SortTh, Stack, StatusPill, TableCard, TableEmptyRow, Text, numCell, selectedRow, useSort } from '@/design'
import { fmt, shortDate } from '@/domain/format'
import { runVerdict, valueOf } from '@/domain/metrics'
import { useScope, useSelectRun } from '@/domain/scope'
import { useLaneNavigate } from '@/app/profiler'
import { useUi } from '@/app/store'

type Key = 'id' | 'ts' | 'build' | 'device' | 'verdict' | 'ttid' | 'slow' | 'janky' | 'peak'
const COLS: { key: Key; label: string; num?: boolean }[] = [
  { key: 'id', label: 'Run' },
  { key: 'ts', label: 'Date' },
  { key: 'build', label: 'Build' },
  { key: 'device', label: 'Device' },
  { key: 'verdict', label: 'Verdict' },
  { key: 'ttid', label: 'TTID', num: true },
  { key: 'slow', label: 'Slow %', num: true },
  { key: 'janky', label: 'Janky %', num: true },
  { key: 'peak', label: 'Peak RAM', num: true },
]
const build = (r: Run) => r.app_version ?? r.git_sha?.slice(0, 7) ?? r.label ?? ''
const VERDICT_RANK = { fail: 3, warn: 2, pass: 1, neutral: 0 }

export function HistoryPage() {
  const { scope, isLoading } = useScope()
  const navigate = useLaneNavigate()
  const selectRun = useSelectRun()
  const { pin, unpin } = useBenchmarkMutations()
  const showToast = useUi((s) => s.showToast)
  const [q, setQ] = useState('')
  const [verdict, setVerdict] = useState<'all' | 'pass' | 'warn' | 'fail'>('all')

  const runs = useMemo(() => scope?.runs ?? [], [scope])
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return runs.filter((r) => {
      if (verdict !== 'all' && r.analysis?.verdict !== verdict) return false
      if (!needle) return true
      return [`#${r.id}`, String(r.id), build(r), r.device ?? '', shortDate(r.ts, true), r.label ?? ''].some((x) => x.toLowerCase().includes(needle))
    })
  }, [runs, q, verdict])
  const get = useCallback((r: Run, k: Key): number | string | null => {
    switch (k) {
      case 'id': return r.id
      case 'ts': return r.ts
      case 'build': return build(r)
      case 'device': return r.device
      case 'verdict': return VERDICT_RANK[runVerdict(r).tone]
      case 'ttid': return valueOf(r, 'ttff_ms')
      case 'slow': return valueOf(r, 'slow_pct')
      case 'janky': return valueOf(r, 'janky_pct')
      case 'peak': return valueOf(r, 'peak_rss_mb')
    }
  }, [])
  const { sorted, sort, toggle } = useSort(filtered, get, { key: 'id', dir: 'desc' })

  if (isLoading || !scope) return <EmptyState>Loading runs…</EmptyState>
  // Benchmarks never cross apps, so only this app's are listed.
  const appPkg = scope.run?.app_pkg ?? null
  const benchmarks = scope.history.benchmarks.filter((b) => b.app_pkg === appPkg)
  const pinnedIds = new Set(benchmarks.map((b) => b.run_id))
  const activeId = scope.benchmarkRun?.id ?? null
  // Compare is always against the run in view (the top bar's Run).
  const inView = scope.run
  const open = (id: number) => {
    selectRun(id)
    navigate('/overview')
  }

  const doPin = (r: Run) =>
    pin.mutate({ runId: r.id }, { onSuccess: () => showToast(`Pinned run #${r.id} as the benchmark`), onError: (e) => showToast(`Could not pin: ${e.message}`) })

  return (
    <Stack as="section" gap={28}>
      <Row gap={10} wrap>
        <SearchInput label="Search runs" placeholder="Search run, build, device or date" value={q} onChange={setQ} />
        <Segmented
          label="Verdict"
          value={verdict}
          onChange={setVerdict}
          options={[
            { value: 'all', label: 'All' },
            { value: 'pass', label: 'Pass' },
            { value: 'warn', label: 'Warn' },
            { value: 'fail', label: 'Fail' },
          ]}
        />
        <Text variant="small" tone="muted">
          {filtered.length} of {runs.length} runs
        </Text>
      </Row>

      <TableCard minWidth={1120}>
        <thead>
          <tr>
            {COLS.map((c) => (
              <SortTh key={c.key} label={c.label} sortKey={c.key} sort={sort} onSort={toggle} align={c.num ? 'right' : 'left'} />
            ))}
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 && <TableEmptyRow colSpan={COLS.length + 1}>No runs match these filters.</TableEmptyRow>}
          {sorted.map((r) => {
            const { tone, word } = runVerdict(r)
            const ttid = valueOf(r, 'ttff_ms')
            const over = ttid != null && r.ttid_budget_ms != null && ttid > r.ttid_budget_ms
            return (
              <tr key={r.id} data-hl={`run:${r.id}`} className={r.id === inView?.id ? selectedRow : undefined} aria-current={r.id === inView?.id || undefined}>
                <td>
                  <Row gap={8}>
                    <Text variant="body" tone="primary" weight={700} nowrap>
                      #{r.id}
                    </Text>
                    {pinnedIds.has(r.id) && <Badge tone="c4">B</Badge>}
                  </Row>
                </td>
                <td>
                  <Text variant="body" nowrap>
                    {shortDate(r.ts, true)}
                  </Text>
                </td>
                <td>
                  <Text variant="body">{build(r) || '–'}</Text>
                </td>
                <td>
                  <Text variant="body">{r.device ?? '–'}</Text>
                </td>
                <td>
                  <StatusPill tone={tone}>{tone === 'neutral' ? (word === 'NO VERDICT' ? 'NONE' : word) : undefined}</StatusPill>
                </td>
                <td className={numCell}>
                  <Text variant="body" tone={over ? 'fail' : 'primary'} weight={600}>
                    {ttid == null ? '–' : `${fmt(ttid)} ms`}
                  </Text>
                </td>
                <td className={numCell}>{fmt(valueOf(r, 'slow_pct'), 2)}</td>
                <td className={numCell}>{fmt(valueOf(r, 'janky_pct'), 2)}</td>
                <td className={numCell}>{valueOf(r, 'peak_rss_mb') == null ? '–' : `${fmt(valueOf(r, 'peak_rss_mb'))} MB`}</td>
                <td>
                  <Row gap={6}>
                    <Button variant="mini" onClick={() => open(r.id)} disabled={inView?.id === r.id} title={inView?.id === r.id ? 'This run is in view' : `Put run #${r.id} in view on every screen`}>
                      {inView?.id === r.id ? 'In view' : 'Open'}
                    </Button>
                    {inView && inView.id !== r.id && (
                      <Button variant="mini" onClick={() => navigate(`/compare?mode=run&b=${r.id}`)} title={`Compare run #${inView.id} with #${r.id}`}>
                        Compare
                      </Button>
                    )}
                    <Button
                      variant="mini"
                      disabled={pinnedIds.has(r.id) || pin.isPending || r.simulator}
                      onClick={() => doPin(r)}
                      title={r.simulator ? "A simulator run can't be a benchmark: its numbers are the Mac's CPU, not a device's." : undefined}
                    >
                      {pinnedIds.has(r.id) ? 'Pinned' : 'Pin as benchmark'}
                    </Button>
                  </Row>
                </td>
              </tr>
            )
          })}
        </tbody>
      </TableCard>

      <Stack gap={14}>
        <SectionTitle aside="One per app, path and device. Regressions are measured against the active one.">Pinned benchmarks</SectionTitle>
        {benchmarks.length === 0 && <EmptyState>No benchmark is pinned. Pin a known-good run above to compare every new run against it.</EmptyState>}
        <Grid min={300}>
          {benchmarks.map((b) => {
            const r = scope.byId(b.run_id)
            const active = b.run_id === activeId
            return (
              <Card key={b.scope} edge={{ side: 'top', color: 'var(--c4)', width: 3 }}>
                <Stack gap={14}>
                  <Stack gap={10}>
                    <Row gap={10} align="baseline">
                      <Text variant="display">#{b.run_id}</Text>
                      <Badge tone={active ? 'c4' : 'neutral'}>{active ? 'Active benchmark' : 'Pinned'}</Badge>
                    </Row>
                    {b.note && <Text variant="body">{b.note}</Text>}
                    <Text variant="meta">
                      {shortDate(b.ts)} · {b.device ?? 'any device'} · {b.app_version ?? b.label ?? 'no build'} · pinned {shortDate(b.set_at)}
                    </Text>
                    {r && (
                      <Row gap={16}>
                        <Text variant="small" tone="primary">
                          TTID <b>{fmt(valueOf(r, 'ttff_ms'))} ms</b>
                        </Text>
                        <Text variant="small" tone="primary">
                          Slow <b>{fmt(valueOf(r, 'slow_pct'), 2)}%</b>
                        </Text>
                        <Text variant="small" tone="primary">
                          Peak <b>{fmt(valueOf(r, 'peak_rss_mb'))} MB</b>
                        </Text>
                      </Row>
                    )}
                  </Stack>
                  <Row gap={6}>
                    {inView && inView.id !== b.run_id && (
                      <Button variant="mini" onClick={() => navigate(`/compare?mode=run&b=${b.run_id}`)}>
                        Compare with #{inView.id}
                      </Button>
                    )}
                    <Button
                      variant="mini"
                      onClick={() => unpin.mutate(b.run_id, { onSuccess: () => showToast(`Unpinned run #${b.run_id}`) })}
                      title={active ? 'Unpinning leaves this app and path with no benchmark until another run is pinned.' : undefined}
                    >
                      Unpin
                    </Button>
                  </Row>
                </Stack>
              </Card>
            )
          })}
        </Grid>
      </Stack>
    </Stack>
  )
}
