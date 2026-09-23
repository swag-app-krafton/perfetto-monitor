import { lazy, Suspense, type ComponentType } from 'react'
import { createBrowserRouter, Navigate } from 'react-router'
import { Copilot } from '@/features/copilot/Copilot'
import { AppShell } from './AppShell'
import { Placeholder } from './Placeholder'
import { SCREENS } from './routes'

/** Each screen is its own chunk, loaded on first visit. */
const page = <K extends string>(load: () => Promise<Record<K, ComponentType>>, name: K) => lazy(() => load().then((m) => ({ default: m[name] })))

const PAGES: Record<string, ComponentType> = {
  overview: page(() => import('@/features/overview/OverviewPage'), 'OverviewPage'),
  startup: page(() => import('@/features/startup/StartupPage'), 'StartupPage'),
  frames: page(() => import('@/features/frames/FramesPage'), 'FramesPage'),
  memory: page(() => import('@/features/memory/MemoryPage'), 'MemoryPage'),
  steps: page(() => import('@/features/steps/StepsPage'), 'StepsPage'),
  screens: page(() => import('@/features/screens/ScreensPage'), 'ScreensPage'),
  compare: page(() => import('@/features/compare/ComparePage'), 'ComparePage'),
  history: page(() => import('@/features/history/HistoryPage'), 'HistoryPage'),
  capture: page(() => import('@/features/capture/CapturePage'), 'CapturePage'),
  stress: page(() => import('@/features/stress/StressPage'), 'StressPage'),
  manual: page(() => import('@/features/manual/ManualPage'), 'ManualPage'),
}
const DesignSystemPage = page(() => import('@/features/design-system/DesignSystemPage'), 'DesignSystemPage')

export const router = createBrowserRouter([
  // The design system's living reference stands outside the app shell.
  {
    path: '/design-system',
    element: (
      <Suspense>
        <DesignSystemPage />
      </Suspense>
    ),
  },
  {
    path: '/',
    element: <AppShell copilot={<Copilot />} />,
    children: [
      { index: true, element: <Navigate to="/overview" replace /> },
      ...SCREENS.map((sc) => {
        const Page = PAGES[sc.id]
        return { path: sc.path.slice(1), element: Page ? <Page /> : <Placeholder id={sc.id} /> }
      }),
      { path: '*', element: <Navigate to="/overview" replace /> },
    ],
  },
])
