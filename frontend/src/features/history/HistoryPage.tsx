import { useCallback, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { useBenchmarkMutations } from '@/api/hooks'
import type { Run } from '@/api/types'
import { Button, EmptyState, Grid, SearchInput, Segmented, SectionTitle, SortHeader, StatusPill, TableCard, numCell } from '@/design/components'
import { fmt, shortDate } from '@/domain/format'
import { valueOf, verdictTone } from '@/domain/metrics'
import { useScope } from '@/domain/scope'
import { useSort } from '@/lib/useSort'
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
  const navigate = useNavigate()
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
      case 'verdict': return VERDICT_RANK[verdictTone(r.analysis?.verdict)]
      case 'ttid': return valueOf(r, 'ttff_ms')
      case 'slow': return valueOf(r, 'slow_pct')
      case 'janky': return valueOf(r, 'janky_pct')
      case 'peak': return valueOf(r, 'peak_rss_mb')
    }
  }, [])
  const { sorted, sort, toggle } = useSort(filtered, get, { key: 'id', dir: 'desc' })

  if (isLoading || !scope) return <EmptyState>Loading runs…</EmptyState>
  // Benchmarks never cross apps, so only this app's are listed.
  const appPkg = scope.latest?.app_pkg ?? null
  const benchmarks = scope.history.benchmarks.filter((b) => b.app_pkg === appPkg)
  const pinnedIds = new Set(benchmarks.map((b) => b.run_id))
  const activeId = scope.benchmarkRun?.id ?? null
  const latest = scope.latest

  const doPin = (r: Run) =>
    pin.mutate({ runId: r.id }, { onSuccess: () => showToast(`Pinned run #${r.id} as the benchmark`), onError: (e) => showToast(`Could not pin: ${e.message}`) })

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
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
        <span style={{ fontSize: 12.5, color: 'var(--tx3)' }}>
          {filtered.length} of {runs.length} runs
        </span>
      </div>

      <TableCard minWidth={1120}>
        <thead>
          <tr>
            {COLS.map((c) => (
              <th key={c.key} className={c.num ? numCell : undefined} aria-sort={sort.key === c.key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                <SortHeader label={c.label} active={sort.key === c.key} dir={sort.dir} onClick={() => toggle(c.key)} align={c.num ? 'right' : 'left'} />
              </th>
            ))}
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 && (
            <tr>
              <td colSpan={COLS.length + 1} style={{ textAlign: 'center', color: 'var(--tx3)', padding: 28 }}>
                No runs match these filters.
              </td>
            </tr>
          )}
          {sorted.map((r) => {
            const tone = verdictTone(r.analysis?.verdict)
            const ttid = valueOf(r, 'ttff_ms')
            const over = ttid != null && r.ttid_budget_ms != null && ttid > r.ttid_budget_ms
            return (
              <tr key={r.id} data-hl={`run:${r.id}`}>
                <td style={{ fontWeight: 700, whiteSpace: 'nowrap' }}>
                  #{r.id}
                  {pinnedIds.has(r.id) && <span style={{ marginLeft: 8, padding: '1px 6px', borderRadius: 999, background: 'var(--s2)', color: 'var(--c4)', font: '700 10px var(--font-display)' }}>B</span>}
                </td>
                <td style={{ whiteSpace: 'nowrap', color: 'var(--tx2)' }}>{shortDate(r.ts, true)}</td>
                <td style={{ color: 'var(--tx2)' }}>{build(r) || '–'}</td>
                <td style={{ color: 'var(--tx2)' }}>{r.device ?? '–'}</td>
                <td>
                  <StatusPill tone={tone}>{tone === 'neutral' ? 'NONE' : undefined}</StatusPill>
                </td>
                <td className={numCell} style={{ color: over ? 'var(--fail)' : undefined, fontWeight: 600 }}>
                  {ttid == null ? '–' : `${fmt(ttid)} ms`}
                </td>
                <td className={numCell}>{fmt(valueOf(r, 'slow_pct'), 2)}</td>
                <td className={numCell}>{fmt(valueOf(r, 'janky_pct'), 2)}</td>
                <td className={numCell}>{valueOf(r, 'peak_rss_mb') == null ? '–' : `${fmt(valueOf(r, 'peak_rss_mb'))} MB`}</td>
                <td>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <Button variant="mini" onClick={() => navigate(`/overview?run=${r.id}`)}>
                      Open
                    </Button>
                    {latest && latest.id !== r.id && (
                      <Button variant="mini" onClick={() => navigate(`/compare?mode=run&a=${latest.id}&b=${r.id}`)}>
                        Compare
                      </Button>
                    )}
                    <Button variant="mini" disabled={pinnedIds.has(r.id) || pin.isPending} onClick={() => doPin(r)}>
                      {pinnedIds.has(r.id) ? 'Pinned' : 'Pin as benchmark'}
                    </Button>
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </TableCard>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <SectionTitle aside="One per app, path and device. Regressions are measured against the active one.">Pinned benchmarks</SectionTitle>
        {benchmarks.length === 0 && <EmptyState>No benchmark is pinned. Pin a known-good run above to compare every new run against it.</EmptyState>}
        <Grid min={300}>
          {benchmarks.map((b) => {
            const r = scope.byId(b.run_id)
            const active = b.run_id === activeId
            return (
              <div key={b.scope} style={{ background: 'var(--s1)', border: '1px solid var(--line)', borderTop: '3px solid var(--c4)', padding: 20, display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
                  <span style={{ font: '800 22px var(--font-display)' }}>#{b.run_id}</span>
                  <span style={{ fontSize: 12, color: active ? 'var(--c4)' : 'var(--tx3)', fontWeight: 600 }}>{active ? 'Active benchmark' : 'Pinned'}</span>
                </div>
                {b.note && <div style={{ fontSize: 13, color: 'var(--tx2)' }}>{b.note}</div>}
                <div style={{ fontSize: 12, color: 'var(--tx3)' }}>
                  {shortDate(b.ts)} · {b.device ?? 'any device'} · {b.app_version ?? b.label ?? 'no build'} · pinned {shortDate(b.set_at)}
                </div>
                {r && (
                  <div style={{ display: 'flex', gap: 16, fontSize: 12.5 }}>
                    <span>
                      TTID <b>{fmt(valueOf(r, 'ttff_ms'))} ms</b>
                    </span>
                    <span>
                      Slow <b>{fmt(valueOf(r, 'slow_pct'), 2)}%</b>
                    </span>
                    <span>
                      Peak <b>{fmt(valueOf(r, 'peak_rss_mb'))} MB</b>
                    </span>
                  </div>
                )}
                <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                  {latest && latest.id !== b.run_id && (
                    <Button variant="mini" onClick={() => navigate(`/compare?mode=run&a=${latest.id}&b=${b.run_id}`)}>
                      Compare with #{latest.id}
                    </Button>
                  )}
                  <Button
                    variant="mini"
                    onClick={() => unpin.mutate(b.run_id, { onSuccess: () => showToast(`Unpinned run #${b.run_id}`) })}
                    title={active ? 'Unpinning leaves this app and path with no benchmark until another run is pinned.' : undefined}
                  >
                    Unpin
                  </Button>
                </div>
              </div>
            )
          })}
        </Grid>
      </div>
    </section>
  )
}
