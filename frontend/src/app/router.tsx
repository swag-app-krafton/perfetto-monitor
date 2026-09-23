import { createBrowserRouter, Navigate } from 'react-router'
import { AppShell } from './AppShell'
import { SCREENS } from './routes'
import { Placeholder } from './Placeholder'
import { OverviewPage } from '@/features/overview/OverviewPage'

const PAGES: Record<string, React.ReactNode> = {
  overview: <OverviewPage />,
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
