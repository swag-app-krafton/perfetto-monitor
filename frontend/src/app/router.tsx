import { createBrowserRouter, Navigate } from 'react-router'
import { AppShell } from './AppShell'
import { SCREENS } from './routes'
import { Placeholder } from './Placeholder'
import { OverviewPage } from '@/features/overview/OverviewPage'
import { StartupPage } from '@/features/startup/StartupPage'
import { FramesPage } from '@/features/frames/FramesPage'
import { MemoryPage } from '@/features/memory/MemoryPage'
import { StepsPage } from '@/features/steps/StepsPage'
import { ScreensPage } from '@/features/screens/ScreensPage'

const PAGES: Record<string, React.ReactNode> = {
  overview: <OverviewPage />,
  startup: <StartupPage />,
  frames: <FramesPage />,
  memory: <MemoryPage />,
  steps: <StepsPage />,
  screens: <ScreensPage />,
}

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/overview" replace /> },
      ...SCREENS.map((sc) => ({ path: sc.path.slice(1), element: PAGES[sc.id] ?? <Placeholder id={sc.id} /> })),
      { path: '*', element: <Navigate to="/overview" replace /> },
    ],
  },
])
