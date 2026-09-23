import { Navigate } from 'react-router'
import { homeOf } from './routes'
import { useUi } from './store'

/** The bare URL opens the profiler the user was last in. */
export function HomeRedirect() {
  return <Navigate to={homeOf(useUi.getState().profiler)} replace />
}
