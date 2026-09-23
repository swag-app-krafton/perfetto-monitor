import { useState } from 'react'
import type { Audit } from '@/api/types'
import { Button, FieldButton, Popover, Row, SortHeader, Spacer, StatusPill, Text, useSort, type Tone } from '@/design'
import { auditLabel, type AuditScope } from '@/domain/audits'
import { fmt, shortDate } from '@/domain/format'
import { useIsNarrow } from '@/lib/useMediaQuery'
import { useUi } from './store'
import s from './RunPicker.module.css'

type Key = 'id' | 'state' | 'score' | 'cpu' | 'ram' | 'fps'

const STATE_TONE: Record<Audit['state'], Tone> = { done: 'pass', running: 'warn', error: 'fail', interrupted: 'neutral' }

const COLS: { key: Key; label: string; num?: boolean }[] = [
  { key: 'id', label: 'Audit' },
  { key: 'state', label: 'State' },
  { key: 'score', label: 'Score', num: true },
  { key: 'cpu', label: 'CPU', num: true },
  { key: 'ram', label: 'RAM', num: true },
  { key: 'fps', label: 'FPS', num: true },
]

function sortValue(a: Audit, k: Key): number | string | null {
  switch (k) {
    case 'id':
      return a.id
    case 'state':
      return a.state
    case 'score':
      return a.score
    case 'cpu':
      return a.cpu_pct
    case 'ram':
      return a.ram_mb
    case 'fps':
      return a.fps
  }
}

/** The Audit control in the top bar when Flashlight is in view: the Run
 *  picker's counterpart, listing the app's audits only. */
export function AuditPicker({ scope }: { scope: AuditScope }) {
  const [open, setOpen] = useState(false)
  const setAuditId = useUi((st) => st.setAuditId)
  const narrow = useIsNarrow()
  const { sorted, sort, toggle } = useSort(scope.appAudits, sortValue, { key: 'id', dir: 'desc' })
  const audit = scope.audit
  const pick = (id: number | null) => {
    setAuditId(id)
    setOpen(false)
  }
  const value = audit ? `${auditLabel(audit)}${scope.following ? ' · Latest' : ` · ${shortDate(audit.ts, true)}`}` : 'No audits'

  return (
    <span className={s.wrap}>
      <FieldButton label="Audit" value={value} open={open} onClick={() => setOpen(!open)} title="Choose the audit every Flashlight screen shows" />
      <Popover open={open} onClose={() => setOpen(false)} width={600} align={narrow ? 'start' : 'end'} maxHeight={480}>
        <Row gap={8} wrap className={s.head}>
          <Text variant="small">
            {sorted.length} audit{sorted.length === 1 ? '' : 's'} of {scope.apps.find((a) => a.pkg === scope.app)?.name ?? scope.app}. Pick one to show it on every
            Flashlight screen.
          </Text>
          <Spacer />
          <Button variant="outline" disabled={scope.following} onClick={() => pick(null)}>
            {scope.following ? 'Following the latest audit' : 'Follow the latest audit'}
          </Button>
        </Row>
        <div className={s.scroll}>
          <table className={s.table}>
            <thead>
              <tr>
                {COLS.map((c) => (
                  <th key={c.key} className={c.num ? s.num : undefined} aria-sort={sort.key === c.key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                    <SortHeader label={c.label} active={sort.key === c.key} dir={sort.dir} align={c.num ? 'right' : 'left'} onClick={() => toggle(c.key)} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((a) => (
                <tr key={a.id} aria-current={a.id === audit?.id || undefined} onClick={() => pick(a.id)}>
                  <td>
                    <button
                      type="button"
                      className={s.pick}
                      onClick={(e) => {
                        e.stopPropagation()
                        pick(a.id)
                      }}
                      aria-label={`Show audit ${auditLabel(a)}`}
                    >
                      {auditLabel(a)}
                    </button>{' '}
                    <Text variant="meta">{shortDate(a.ts, true)}</Text>
                  </td>
                  <td>
                    <StatusPill tone={STATE_TONE[a.state]}>{a.state.toUpperCase()}</StatusPill>
                  </td>
                  <td className={s.num}>{a.score == null ? '–' : fmt(a.score)}</td>
                  <td className={s.num}>{a.cpu_pct == null ? '–' : `${fmt(a.cpu_pct, 1)}%`}</td>
                  <td className={s.num}>{a.ram_mb == null ? '–' : `${fmt(a.ram_mb)} MB`}</td>
                  <td className={s.num}>{a.fps == null ? '–' : fmt(a.fps, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Popover>
    </span>
  )
}
