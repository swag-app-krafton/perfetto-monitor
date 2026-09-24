import { useNavigate } from 'react-router'
import { useAudits } from '@/api/hooks'
import type { Audit } from '@/api/types'
import { Button, EmptyState, SortTh, Spinner, StatusPill, TableCard, TableEmptyRow, Text, numCell, selectedRow, useSort, type Tone } from '@/design'
import { auditLabel, useAuditScope } from '@/domain/audits'
import { fmt, shortDate } from '@/domain/format'
import { useUi } from '@/app/store'

type Key = 'id' | 'app' | 'device' | 'runs' | 'score' | 'cpu' | 'ram' | 'fps' | 'state'

const STATE_TONE: Record<Audit['state'], Tone> = { done: 'pass', running: 'warn', error: 'fail', interrupted: 'neutral' }

const COLS: { key: Key; label: string; num?: boolean }[] = [
  { key: 'id', label: 'Audit' },
  { key: 'app', label: 'App' },
  { key: 'device', label: 'Device' },
  { key: 'runs', label: 'Cold starts', num: true },
  { key: 'score', label: 'Score', num: true },
  { key: 'cpu', label: 'CPU', num: true },
  { key: 'ram', label: 'RAM', num: true },
  { key: 'fps', label: 'FPS', num: true },
  { key: 'state', label: 'State' },
]

function sortValue(a: Audit, k: Key): number | string | null {
  switch (k) {
    case 'id':
      return a.id
    case 'app':
      return a.app_name
    case 'device':
      return a.device
    case 'runs':
      return a.summary?.successful ?? null
    case 'score':
      return a.score
    case 'cpu':
      return a.cpu_pct
    case 'ram':
      return a.ram_mb
    case 'fps':
      return a.fps
    case 'state':
      return a.state
  }
}

/** Every Flashlight audit, of every app. Picking one puts it in view on the
 *  Audit screen, as picking a run does for Perfetto. */
export function AuditsPage() {
  const q = useAudits()
  const { scope } = useAuditScope()
  const navigate = useNavigate()
  const { setFilters, setAuditId } = useUi()
  const { sorted, sort, toggle } = useSort(q.data?.audits ?? [], sortValue, { key: 'id', dir: 'desc' })

  if (q.isLoading) return <Spinner />
  if (!q.data?.audits.length)
    return (
      <EmptyState title="No Flashlight audits yet" actions={<Button variant="primary" onClick={() => navigate('/flashlight/run')}>Run an audit</Button>}>
        Audits are listed here once they have run, across every app.
      </EmptyState>
    )

  const show = (a: Audit) => {
    setFilters({ app: a.app_pkg })
    setAuditId(a.id)
    navigate('/flashlight/audit')
  }

  return (
    <TableCard title="Flashlight audits" hint="Newest first; sort by any column. Scores and averages are Flashlight's own." minWidth={900}>
      <thead>
        <tr>
          {COLS.map((c) => (
            <SortTh key={c.key} label={c.label} sortKey={c.key} sort={sort} onSort={toggle} align={c.num ? 'right' : 'left'} />
          ))}
          <th />
        </tr>
      </thead>
      <tbody>
        {sorted.length === 0 && <TableEmptyRow colSpan={COLS.length + 1}>No audits.</TableEmptyRow>}
        {sorted.map((a) => {
          const inView = a.id === scope?.audit?.id
          return (
            <tr key={a.id} className={inView ? selectedRow : undefined}>
              <td>
                <Text variant="body" tone="primary" weight={700}>
                  {auditLabel(a)}
                </Text>{' '}
                <Text variant="meta">{shortDate(a.ts, true)}</Text>
              </td>
              <Text as="td" variant="body">
                {a.app_name}
              </Text>
              <Text as="td" variant="body">
                {a.device ?? '–'}
              </Text>
              <td className={numCell}>
                {a.summary?.successful ?? '–'} / {a.iterations}
              </td>
              <td className={numCell}>{a.score == null ? '–' : fmt(a.score)}</td>
              <td className={numCell}>{a.cpu_pct == null ? '–' : `${fmt(a.cpu_pct, 1)}%`}</td>
              <td className={numCell}>{a.ram_mb == null ? '–' : `${fmt(a.ram_mb)} MB`}</td>
              <td className={numCell}>{a.fps == null ? '–' : fmt(a.fps, 1)}</td>
              <td>
                <StatusPill tone={STATE_TONE[a.state]}>{a.state.toUpperCase()}</StatusPill>
              </td>
              <td>
                <Button variant="mini" onClick={() => show(a)} disabled={inView}>
                  {inView ? 'Shown' : 'Show'}
                </Button>
              </td>
            </tr>
          )
        })}
      </tbody>
    </TableCard>
  )
}
