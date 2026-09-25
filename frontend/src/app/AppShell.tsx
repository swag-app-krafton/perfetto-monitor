import { Suspense, useCallback, useEffect, useRef, type ReactNode } from 'react'
import { Outlet, useLocation, useNavigate, useSearchParams } from 'react-router'
import { Banner, Spinner, Toast } from '@/design'
import { useHistory } from '@/api/hooks'
import { useAuditScope } from '@/domain/audits'
import { useScope, useSelectRun } from '@/domain/scope'
import { useHighlightTarget } from '@/lib/highlight'
import { useIsNarrow, useIsWide } from '@/lib/useMediaQuery'
import { AuditBox } from './AuditBox'
import { PageHeader } from './PageHeader'
import { toLane } from './profiler'
import { screenByPath } from './routes'
import { Sidebar } from './Sidebar'
import { TopBar } from './TopBar'
import { platformOf, useUi } from './store'
import { useApplyTheme } from './useApplyTheme'
import s from './Shell.module.css'

/** Layout: [sidebar] [main column] [copilot]. Only <main> scrolls, and the
 *  Copilot is a flex sibling, so opening it reflows the page instead of
 *  covering what the user is reading. */
export function AppShell({ copilot }: { copilot?: ReactNode }) {
  const { railPinned, drawerOpen, copilot: cp, toast, toggleRail, setDrawer } = useUi()
  const dismissToast = useCallback(() => useUi.setState({ toast: null }), [])
  const narrow = useIsNarrow()
  const wide = useIsWide()
  const { scope } = useScope()
  const loc = useLocation()
  const screen = screenByPath(loc.pathname)
  const audits = useAuditScope().scope
  const mainRef = useRef<HTMLElement>(null)
  useHighlightTarget(useCallback(() => mainRef.current, []))

  useApplyTheme()

  // Remember the profiler in view, so the bare URL opens where the user left off.
  const setProfiler = useUi((st) => st.setProfiler)
  useEffect(() => setProfiler(screen.profiler), [screen.profiler, setProfiler])

  // `?run=<id>` in any link puts that run in view everywhere, then leaves the
  // URL: the top bar is where the run in view lives.
  const selectRun = useSelectRun()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const runParam = Number(params.get('run')) || null
  const history = useHistory().data
  useEffect(() => {
    if (runParam == null || !history) return
    selectRun(runParam)
    const next = new URLSearchParams(params)
    next.delete('run')
    // A run is only ever shown in its own lane: a link to an iOS run from the
    // Android lane (or the reverse) opens the same page in the run's lane.
    const run = history.runs.find((r) => r.id === runParam)
    const lane = screen.profiler
    const pathname =
      run && lane !== 'flashlight' && platformOf(lane) !== (run.platform ?? 'android')
        ? toLane(loc.pathname, run.platform === 'ios' ? 'ios' : 'perfetto')
        : loc.pathname
    navigate({ pathname, search: next.toString() ? `?${next}` : '' }, { replace: true })
  }, [runParam, history, selectRun, navigate, params, loc.pathname, screen.profiler])

  // A tab change starts at the top of the page (a deep link then scrolls itself).
  useEffect(() => {
    mainRef.current?.scrollTo({ top: 0 })
    setDrawer(false)
  }, [loc.pathname, setDrawer])

  // The rail is the user's choice, or forced while the Copilot needs the room.
  const rail = railPinned || (cp.open && !wide)

  return (
    <div className={s.root}>
      {narrow ? (
        drawerOpen && (
          <>
            <div className={s.backdrop} onClick={() => setDrawer(false)} />
            <Sidebar rail={false} drawer onNavigate={() => setDrawer(false)} onToggleRail={toggleRail} />
          </>
        )
      ) : (
        <Sidebar rail={rail} drawer={false} onToggleRail={toggleRail} />
      )}
      <div className={s.column}>
        <TopBar scope={scope} narrow={narrow} />
        <main ref={mainRef} className={s.main} id="main">
          <div className={s.page}>
            {screen.profiler === 'flashlight' ? (
              <PageHeader
                group={screen.group}
                title={screen.label}
                hint={screen.hint}
                run={null}
                isLatest
                aside={audits?.audit && screen.id !== 'audit-run' ? <AuditBox audit={audits.audit} following={audits.following} /> : undefined}
              />
            ) : (
              <PageHeader
                group={screen.group}
                title={screen.label}
                hint={screen.hint}
                run={screen.ignores?.includes('run') ? null : (scope?.run ?? null)}
                isLatest={scope?.isLatest ?? true}
              />
            )}
            {screen.profiler === 'ios' && scope?.run?.simulator && (
              <Banner tone="warn" title="Simulator run: indicative only">
                Measured on the iOS Simulator, on this Mac's CPU with a warm cache. It compares only with other simulator runs, carries no North Star targets and
                can't be pinned as a benchmark. Frames are not measured on the simulator.
              </Banner>
            )}
            <Suspense fallback={<Spinner />}>
              <Outlet />
            </Suspense>
          </div>
        </main>
      </div>
      {copilot}
      <Toast message={toast?.text ?? null} id={toast?.id} onDismiss={dismissToast} />
    </div>
  )
}
