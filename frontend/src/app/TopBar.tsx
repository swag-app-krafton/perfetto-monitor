import { Link } from 'react-router'
import { Icon, Segmented, SelectField } from '@/design'
import { pathLabel } from '@/domain/format'
import type { Scope } from '@/domain/scope'
import { NO_VERSION, versionLabel } from '@/domain/versions'
import { RunPicker } from './RunPicker'
import { useUi, type RangeKey } from './store'
import s from './Shell.module.css'

const RANGES: { value: RangeKey; label: string }[] = [
  { value: '30', label: 'Last 30 runs' },
  { value: '10', label: 'Last 10 runs' },
  { value: '7d', label: 'Last 7 days' },
]

export function TopBar({ scope, narrow }: { scope: Scope | null; narrow: boolean }) {
  const { app, path, range, version, runId, theme, setFilters, toggleTheme, setDrawer } = useUi()
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
        {scope && scope.versions.some((v) => v.key !== NO_VERSION) && (
          <SelectField
            label="Version"
            value={scope.versions.some((v) => v.key === version) ? version : ''}
            options={[
              { value: '', label: `All versions · ${scope.allRuns.length}` },
              ...scope.versions.map((v) => ({ value: v.key, label: `${versionLabel(v)} · ${v.runs} run${v.runs === 1 ? '' : 's'}` })),
            ]}
            onChange={(v) => setFilters({ version: v })}
          />
        )}
        {/* The one place a run is chosen: every screen shows the run picked here. */}
        {scope && scope.allRuns.length > 0 && <RunPicker scope={scope} runId={runId} />}
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
