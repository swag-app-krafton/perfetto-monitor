import { useState } from 'react'
import type { Run } from '@/api/types'
import { Button, FieldButton, Popover, Row, RowAction, SortTh, Spacer, StatusPill, Table, Text, numCell, useSort, type Tone } from '@/design'
import { fmt, shortDate } from '@/domain/format'
import { valueOf } from '@/domain/metrics'
import { useSelectRun, verdictOf, type Scope } from '@/domain/scope'
import { NO_VERSION, versionKey, versionLabel, versionOf } from '@/domain/versions'
import { useIsNarrow } from '@/lib/useMediaQuery'
import s from './RunPicker.module.css'

type Key = 'id' | 'version' | 'verdict' | 'ttid' | 'slow' | 'janky' | 'peak' | 'growth'

const TONE: Record<string, Tone> = { pass: 'pass', warn: 'warn', fail: 'fail' }
const RANK: Record<string, number> = { fail: 3, warn: 2, pass: 1 }

const COLS: { key: Key; label: string; num?: boolean }[] = [
  { key: 'id', label: 'Run' },
  { key: 'version', label: 'Version' },
  { key: 'verdict', label: 'Verdict' },
  { key: 'ttid', label: 'TTID', num: true },
  { key: 'slow', label: 'Slow', num: true },
  { key: 'janky', label: 'Janky', num: true },
  { key: 'peak', label: 'Peak RAM', num: true },
  { key: 'growth', label: 'RAM growth', num: true },
]

function sortValue(r: Run, k: Key): number | string | null {
  switch (k) {
    case 'id':
      return r.id
    case 'version': {
      const v = versionOf(r)
      return v.build ?? v.name
    }
    case 'verdict':
      return RANK[verdictOf(r) ?? ''] ?? null
    case 'ttid':
      return valueOf(r, 'ttff_ms')
    case 'slow':
      return valueOf(r, 'slow_pct')
    case 'janky':
      return valueOf(r, 'janky_pct')
    case 'peak':
      return valueOf(r, 'peak_rss_mb')
    case 'growth':
      return valueOf(r, 'rss_growth_mb')
  }
}

/** The Run control in the top bar: the run in view, and a table of the runs in
 *  scope (the selected version's, when one is picked) sortable by any metric,
 *  so the slowest or heaviest run of a build is one click away. */
export function RunPicker({ scope, runId }: { scope: Scope; runId: number | null }) {
  const [open, setOpen] = useState(false)
  const selectRun = useSelectRun()
  const narrow = useIsNarrow()
  const { sorted, sort, toggle } = useSort(scope.versionRuns, sortValue, { key: 'id', dir: 'desc' })
  const run = scope.run
  const following = runId == null
  const pick = (id: number | null) => {
    selectRun(id)
    setOpen(false)
  }
  const value = run ? `#${run.id}${following ? ' · Latest' : ` · ${shortDate(run.ts, true)}`}` : 'No runs'

  return (
    <span className={s.wrap}>
      <FieldButton label="Run" value={value} open={open} onClick={() => setOpen(!open)} title="Choose the run every screen shows" />
      <Popover open={open} onClose={() => setOpen(false)} width={760} align={narrow ? 'start' : 'end'} maxHeight={480}>
        <Row gap={8} wrap className={s.head}>
          <Text variant="small">
            {sorted.length} run{sorted.length === 1 ? '' : 's'}
            {scope.versionRuns !== scope.allRuns && sorted[0] ? ` of ${versionLabel(versionOf(sorted[0]))}` : ''}. Sort by any column; pick a run to
            show it on every screen.
          </Text>
          <Spacer />
          <Button variant="outline" disabled={following} onClick={() => pick(null)}>
            {following ? 'Following the latest run' : 'Follow the latest run'}
          </Button>
        </Row>
        <div className={s.scroll}>
          <Table minWidth={640} density="dense" stickyHeader label="Runs">
            <thead>
              <tr>
                {COLS.map((c) => (
                  <SortTh key={c.key} label={c.label} sortKey={c.key} sort={sort} onSort={toggle} align={c.num ? 'right' : 'left'} />
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => {
                const v = verdictOf(r)
                const ttid = valueOf(r, 'ttff_ms')
                const over = ttid != null && r.ttid_budget_ms != null && ttid > r.ttid_budget_ms
                const inView = r.id === run?.id
                return (
                  <tr key={r.id} aria-current={inView || undefined}>
                    <td>
                      <RowAction onClick={() => pick(r.id)} aria-label={`Show run #${r.id}`}>
                        #{r.id}
                      </RowAction>{' '}
                      <Text variant="meta">{shortDate(r.ts, true)}</Text>
                    </td>
                    <td>
                      <Text variant="small" tone={versionKey(r) === NO_VERSION ? 'muted' : 'primary'}>
                        {versionKey(r) === NO_VERSION ? 'not recorded' : versionLabel(versionOf(r))}
                      </Text>
                    </td>
                    <td>{v ? <StatusPill tone={TONE[v] ?? 'neutral'} /> : <Text variant="meta">–</Text>}</td>
                    <td className={numCell}>
                      <Text variant="small" tone={over ? 'fail' : 'primary'} weight={600}>
                        {ttid == null ? '–' : `${fmt(ttid)} ms`}
                      </Text>
                    </td>
                    <td className={numCell}>{fmt(valueOf(r, 'slow_pct'), 2)}%</td>
                    <td className={numCell}>{fmt(valueOf(r, 'janky_pct'), 2)}%</td>
                    <td className={numCell}>{valueOf(r, 'peak_rss_mb') == null ? '–' : `${fmt(valueOf(r, 'peak_rss_mb'))} MB`}</td>
                    <td className={numCell}>{valueOf(r, 'rss_growth_mb') == null ? '–' : `${fmt(valueOf(r, 'rss_growth_mb'))} MB`}</td>
                  </tr>
                )
              })}
            </tbody>
          </Table>
        </div>
      </Popover>
    </span>
  )
}
