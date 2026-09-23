import { Suspense, useCallback, useEffect, useRef, type ReactNode } from 'react'
import { Outlet, useLocation } from 'react-router'
import { Spinner, Toast } from '@/design'
import { useScope } from '@/domain/scope'
import { useHighlightTarget } from '@/lib/highlight'
import { useIsNarrow, useIsWide } from '@/lib/useMediaQuery'
import { PageHeader } from './PageHeader'
import { screenByPath } from './routes'
import { Sidebar } from './Sidebar'
import { TopBar } from './TopBar'
import { useUi } from './store'
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
  const mainRef = useRef<HTMLElement>(null)
  useHighlightTarget(useCallback(() => mainRef.current, []))

  useApplyTheme()

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
            <PageHeader group={screen.group} title={screen.label} hint={screen.hint} run={scope?.latest ?? null} />
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
