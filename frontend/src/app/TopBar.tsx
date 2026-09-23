import { Link } from 'react-router'
import { GLYPH, Icon, Segmented, SelectField, type Tone } from '@/design'
import type { Run } from '@/api/types'
import { pathLabel, shortDate } from '@/domain/format'
import { useSelectRun, verdictOf, type Scope } from '@/domain/scope'
import { useUi, type RangeKey } from './store'
import s from './Shell.module.css'

const RANGES: { value: RangeKey; label: string }[] = [
  { value: '30', label: 'Last 30 runs' },
  { value: '10', label: 'Last 10 runs' },
  { value: '7d', label: 'Last 7 days' },
]

/** "#81 · Sep 23, 12:54 · ✕ FAIL" for the run picker. */
function runOption(r: Run) {
  const v = verdictOf(r)
  const tone: Tone = v === 'pass' || v === 'warn' || v === 'fail' ? v : 'neutral'
  return `#${r.id} · ${shortDate(r.ts, true)}${v ? ` · ${GLYPH[tone]} ${v.toUpperCase()}` : ''}`
}

export function TopBar({ scope, narrow }: { scope: Scope | null; narrow: boolean }) {
  const { app, path, range, runId, theme, setFilters, toggleTheme, setDrawer } = useUi()
  const selectRun = useSelectRun()
  const runs = scope ? [...scope.allRuns].reverse() : []
  return (
    <header className={s.top}>
      {narrow && (
        <button type="button" className={s.hamburger} aria-label="Open navigation" onClick={() => setDrawer(true)}>
          <Icon name="menu" size={16} />
        </button>
      )}
      <div className={s.titleBlock}>
        <div className={s.title}>Swag Pay Performance</div>
        <div className={s.subtitle}>Perfetto trace regression monitor · three runtimes, one process</div>
      </div>
      <div className={s.controls}>
        {scope && scope.apps.length > 0 && (
          <SelectField
            label="App"
            value={app}
            options={scope.apps.map((a) => ({ value: a.pkg, label: a.name + (a.own ? '' : ` · ${a.runs}`) }))}
            onChange={(v) => setFilters({ app: v, path: '' })}
          />
        )}
        {scope && scope.paths.length > 0 && (
          <Segmented
            label="Startup path"
            value={path}
            options={scope.paths.map((p) => ({ value: p, label: pathLabel(p) }))}
            onChange={(v) => setFilters({ path: v })}
          />
        )}
        {runs.length > 0 && (
          // The one place a run is chosen: every screen shows the run picked here.
          <SelectField
            label="Run"
            value={runId != null && scope?.run?.id === runId ? String(runId) : 'latest'}
            options={[
              { value: 'latest', label: `Latest · #${runs[0]!.id}` },
              ...runs.map((r) => ({ value: String(r.id), label: runOption(r) })),
            ]}
            onChange={(v) => selectRun(v === 'latest' ? null : Number(v))}
          />
        )}
        <SelectField label="Range" value={range} options={RANGES} onChange={(v) => setFilters({ range: v })} />
        <Link className={s.tokensLink} to="/design-system">
          Tokens
        </Link>
        <button type="button" className={s.themeBtn} onClick={toggleTheme} aria-label="Toggle colour theme">
          <span className={s.themeGlyph} aria-hidden="true" />
          {theme === 'dark' ? 'Dark' : 'Light'}
        </button>
      </div>
    </header>
  )
}
