import { useCallback, useEffect, useState } from 'react'
import type { ChildSlice, Run } from '@/api/types'
import { Button, EmptyState, Icon, Label, SortHeader, Sparkline } from '@/design/components'
import { fmt, signed, stepName } from '@/domain/format'
import { useScope } from '@/domain/scope'
import { stepDeltas, type StepDelta } from '@/domain/steps'
import { useFocusParam } from '@/lib/highlight'
import { useSort } from '@/lib/useSort'
import { useUi } from '@/app/store'
import s from './Steps.module.css'

type Key = 'name' | 'runtime' | 'current' | 'baseline' | 'deltaMs' | 'deltaPct'
const COLS: { key: Key; label: string; right?: boolean }[] = [
  { key: 'name', label: 'Step' },
  { key: 'runtime', label: 'Runtime' },
  { key: 'current', label: 'Current', right: true },
  { key: 'baseline', label: 'Baseline', right: true },
  { key: 'deltaMs', label: 'Δ ms', right: true },
  { key: 'deltaPct', label: 'Δ %', right: true },
]

// Same floor the backend's regression rule uses: a move under 5ms is not
// coloured as a regression however large it is in percent (a 0.3ms step going
// +27% is noise, not a finding).
const MIN_MS = 5
const deltaColor = (d: StepDelta) =>
  d.deltaPct == null || d.deltaMs == null || d.deltaMs < MIN_MS ? 'var(--tx2)' : d.deltaPct > 10 ? 'var(--fail)' : d.deltaPct > 4 ? 'var(--warn)' : 'var(--tx2)'

export function StepsPage() {
  const { scope, isLoading } = useScope()
  const focus = useFocusParam()
  const askCopilot = useUi((st) => st.askCopilot)
  const [open, setOpen] = useState<string | null>(null)

  const latest = scope?.latest ?? null
  const runtimeOf = scope?.history.startup_model.step_runtime ?? {}
  const deltas = latest && scope ? stepDeltas(latest, scope.allRuns, scope.benchmarkRun) : []
  const get = useCallback(
    (d: StepDelta, k: Key) =>
      k === 'name' ? stepName(d.step) : k === 'runtime' ? (runtimeOf[d.step] ?? '') : k === 'current' ? d.current : k === 'baseline' ? d.baseline : k === 'deltaMs' ? d.deltaMs : d.deltaPct,
    [runtimeOf],
  )
  const { sorted, sort, toggle } = useSort(deltas, get, { key: 'deltaMs', dir: 'desc' })

  // A deep link (Overview's "Inspect step", a Copilot citation) opens its row.
  useEffect(() => {
    if (focus) setOpen(focus)
  }, [focus])

  if (isLoading || !scope) return <EmptyState>Loading runs…</EmptyState>
  if (!latest) return <EmptyState title="No runs yet">Capture a trace to see its steps.</EmptyState>
  if (!deltas.length) return <EmptyState>Run #{latest.id} recorded no startup steps.</EmptyState>
  const from = scope.benchmarkRun ? `pinned benchmark #${scope.benchmarkRun.id}` : 'the median of the previous 10 runs'
  const kids = latest.steps.reduce((n, st) => n + st.children.length, 0)

  return (
    <section className={s.card}>
      <div className={s.head}>
        <div>
          <div style={{ font: '700 16px var(--font-display)' }}>Step durations</div>
          <div style={{ fontSize: 12.5, color: 'var(--tx3)', marginTop: 4 }}>
            Run #{latest.id} against {from}. Select a row to drill down.
          </div>
        </div>
        <div style={{ fontSize: 12, color: 'var(--tx3)', alignSelf: 'flex-end' }}>
          {deltas.length} top-level steps · {kids} child slices
        </div>
      </div>
      <div className={s.scroll}>
        <div className={s.table} role="table" aria-label="Step durations">
          <div className={`${s.cols} ${s.hrow}`} role="row">
            <span />
            {COLS.map((c) => (
              <span key={c.key} role="columnheader" aria-sort={sort.key === c.key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                <SortHeader label={c.label} active={sort.key === c.key} dir={sort.dir} onClick={() => toggle(c.key)} align={c.right ? 'right' : 'left'} />
              </span>
            ))}
            <span style={{ font: '600 11px var(--font-ui)', letterSpacing: '.08em', color: 'var(--tx3)', textAlign: 'right' }}>TREND · 12</span>
          </div>
          {sorted.map((d) => {
            const isOpen = open === d.step
            const c = deltaColor(d)
            return (
              <div key={d.step} className={s.row} data-hl={d.step} role="rowgroup">
                <button type="button" className={`${s.cols} ${s.rowBtn}`} aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : d.step)}>
                  <span style={{ color: 'var(--tx3)', textAlign: 'center' }}>{isOpen ? '▾' : '▸'}</span>
                  <span style={{ fontWeight: 600 }}>{stepName(d.step)}</span>
                  <span style={{ color: 'var(--tx2)', fontSize: 12 }}>{runtimeOf[d.step] ?? '–'}</span>
                  <span className={s.num} style={{ fontWeight: 600 }}>
                    {fmt(d.current, 1)} ms
                  </span>
                  <span className={s.num} style={{ color: 'var(--tx2)' }}>
                    {d.baseline == null ? '–' : `${fmt(d.baseline, 1)} ms`}
                  </span>
                  <span className={s.num} style={{ fontWeight: 600, color: c }}>
                    {d.deltaMs == null ? '–' : signed(d.deltaMs, 1)}
                  </span>
                  <span className={s.num} style={{ color: c }}>
                    {d.deltaPct == null ? '–' : signed(d.deltaPct, 1, '%')}
                  </span>
                  <Sparkline values={d.history.slice(-12)} height={24} color={c === 'var(--fail)' ? 'var(--fail)' : 'var(--c1)'} />
                </button>
                {isOpen && <Drill d={d} latest={latest} prior={scope.allRuns} bench={scope.benchmarkRun} runtime={runtimeOf[d.step]} onAsk={() => askCopilot(`Why did ${stepName(d.step)} change in run #${latest.id}?`)} />}
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}

function Drill({ d, latest, prior, bench, runtime, onAsk }: { d: StepDelta; latest: Run; prior: Run[]; bench: Run | null; runtime?: string; onAsk: () => void }) {
  // Each child's baseline comes from the same place as its step's.
  const baseKids = (name: string): number | null => {
    if (bench) return bench.steps.find((x) => x.step === d.step)?.children.find((c) => c.name === name)?.dur_ms ?? null
    const vals = prior
      .filter((r) => r.id < latest.id)
      .slice(-10)
      .map((r) => r.steps.find((x) => x.step === d.step)?.children.find((c) => c.name === name)?.dur_ms)
      .filter((v): v is number => v != null)
      .sort((a, b) => a - b)
    return vals.length ? vals[Math.floor(vals.length / 2)]! : null
  }
  const kids: ChildSlice[] = d.row.children
  const tiles = [
    { l: 'p50 · 10 runs', v: d.p50 == null ? '–' : `${fmt(d.p50, 1)} ms` },
    { l: 'p90 · 10 runs', v: d.p90 == null ? '–' : `${fmt(d.p90, 1)} ms` },
    { l: 'This run', v: `${fmt(d.current, 1)} ms` },
    { l: 'Runtime', v: runtime ?? '–' },
  ]
  return (
    <div className={s.drill}>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        {tiles.map((t) => (
          <div key={t.l} className={s.mini}>
            <div className={s.miniL}>{t.l}</div>
            <div className={s.miniV}>{t.v}</div>
          </div>
        ))}
        <div style={{ flex: 1 }} />
        <Button onClick={onAsk} style={{ alignSelf: 'center', height: 32, fontSize: 12.5 }}>
          <Icon name="sparkle" size={11} style={{ color: 'var(--accent)' }} />
          Ask Copilot
        </Button>
      </div>
      <div>
        <Label style={{ marginBottom: 10 }}>CHILD SLICES · BAR = THIS RUN, TICK = BASELINE</Label>
        {kids.length === 0 && <div style={{ fontSize: 13, color: 'var(--tx3)' }}>No child slices were recorded inside this step, so its time cannot be attributed further.</div>}
        {kids.map((k) => {
          const b = baseKids(k.name)
          const w = d.current ? Math.min(100, (k.dur_ms / d.current) * 100) : 0
          const bw = b != null && d.current ? Math.min(100, (b / d.current) * 100) : null
          const pct = b ? ((k.dur_ms - b) / b) * 100 : null
          return (
            <div key={k.name} className={s.kid}>
              <span style={{ overflowWrap: 'anywhere' }}>{k.name}</span>
              <div style={{ position: 'relative', height: 10, background: 'var(--s2)' }}>
                <div style={{ height: '100%', width: `${w}%`, background: 'var(--c1)' }} />
                {bw != null && <div style={{ position: 'absolute', left: `${bw}%`, top: -3, bottom: -3, borderLeft: '2px solid var(--tx)' }} />}
              </div>
              <span className={s.num} style={{ fontWeight: 600 }}>
                {fmt(k.dur_ms, 1)} ms
              </span>
              <span className={s.num} style={{ color: 'var(--tx2)' }}>
                {b == null ? '–' : `${fmt(b, 1)} ms`}
              </span>
              <span className={s.num} style={{ fontWeight: 600, color: pct != null && pct > 20 ? 'var(--fail)' : 'var(--tx2)' }}>
                {b == null ? '–' : signed(k.dur_ms - b, 1)}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
