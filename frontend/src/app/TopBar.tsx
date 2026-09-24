import { Link, useNavigate } from 'react-router'
import { Button, Icon, IconButton, Segmented, SelectField } from '@/design'
import { useAuditScope } from '@/domain/audits'
import { pathLabel } from '@/domain/format'
import type { Scope } from '@/domain/scope'
import { NO_VERSION, versionLabel } from '@/domain/versions'
import { AuditPicker } from './AuditPicker'
import { PROFILERS, useProfiler } from './profiler'
import { homeOf } from './routes'
import { RunPicker } from './RunPicker'
import { useUi, type Profiler, type RangeKey } from './store'
import s from './Shell.module.css'

const RANGES: { value: RangeKey; label: string }[] = [
  { value: '30', label: 'Last 30 runs' },
  { value: '10', label: 'Last 10 runs' },
  { value: '7d', label: 'Last 7 days' },
]

export function TopBar({ scope, narrow }: { scope: Scope | null; narrow: boolean }) {
  const { app, path, range, version, runId, theme, setFilters, toggleTheme, setDrawer } = useUi()
  const profiler = useProfiler()
  const navigate = useNavigate()
  const audits = useAuditScope().scope
  // Switching profiler opens its first screen; the page is what says which one is in view.
  const switchProfiler = (p: Profiler) => p !== profiler && navigate(homeOf(p))
  return (
    <header className={s.top}>
      {narrow && (
        <IconButton icon="menu" label="Open navigation" outlined onClick={() => setDrawer(true)} />
      )}
      <div className={s.titleBlock}>
        <div className={s.title}>Swag Pay Performance</div>
        <div className={s.subtitle}>
          {profiler === 'perfetto' ? 'Perfetto trace regression monitor · three runtimes, one process' : "Flashlight audits · repeated cold starts, Flashlight's own scoring"}
        </div>
      </div>
      <div className={s.controls}>
        {/* First: everything to its right shows this profiler's runs only. */}
        <Segmented label="Profiler" value={profiler} options={PROFILERS} onChange={switchProfiler} />
        {profiler === 'flashlight' && audits && audits.apps.length > 0 && (
          <SelectField
            label="App"
            value={audits.app}
            options={audits.apps.map((a) => ({ value: a.pkg, label: `${a.name} · ${a.audits}` }))}
            onChange={(v) => setFilters({ app: v })}
          />
        )}
        {profiler === 'flashlight' && audits && audits.appAudits.length > 0 && <AuditPicker scope={audits} />}
        {profiler === 'perfetto' && scope && scope.apps.length > 0 && (
          <SelectField
            label="App"
            value={app}
            options={scope.apps.map((a) => ({ value: a.pkg, label: a.name + (a.own ? '' : ` · ${a.runs}`) }))}
            onChange={(v) => setFilters({ app: v, path: '' })}
          />
        )}
        {profiler === 'perfetto' && scope && scope.paths.length > 0 && (
          <Segmented
            label="Startup path"
            value={path}
            options={scope.paths.map((p) => ({ value: p, label: pathLabel(p) }))}
            onChange={(v) => setFilters({ path: v })}
          />
        )}
        {profiler === 'perfetto' && scope && scope.versions.some((v) => v.key !== NO_VERSION) && (
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
        {profiler === 'perfetto' && scope && scope.allRuns.length > 0 && <RunPicker scope={scope} runId={runId} />}
        {profiler === 'perfetto' && <SelectField label="Range" value={range} options={RANGES} onChange={(v) => setFilters({ range: v })} />}
        <Link className={s.tokensLink} to="/design-system">
          Tokens
        </Link>
        <Button size="sm" onClick={toggleTheme} aria-label="Toggle colour theme">
          <Icon name="contrast" size={14} />
          {theme === 'dark' ? 'Dark' : 'Light'}
        </Button>
      </div>
    </header>
  )
}
