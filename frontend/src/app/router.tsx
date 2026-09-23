import { createBrowserRouter, Navigate } from 'react-router'
import { AppShell } from './AppShell'
import { SCREENS } from './routes'
import { Placeholder } from './Placeholder'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/overview" replace /> },
      ...SCREENS.map((sc) => ({ path: sc.path.slice(1), element: <Placeholder id={sc.id} /> })),
      { path: '*', element: <Navigate to="/overview" replace /> },
    ],
  },
])
