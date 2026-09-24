import { useLocation, useNavigate } from 'react-router'
import { screenByPath } from './routes'
import type { Profiler } from './store'

/** The profiler in view. It comes from the page: every screen belongs to one
 *  profiler, so a link to a Flashlight page opens Flashlight's view. The store
 *  only remembers the last one, for where the bare URL opens. */
export const useProfiler = (): Profiler => screenByPath(useLocation().pathname).profiler

/** The first control in the top bar. The platform is in the label because a
 *  lane is a profiler on one platform. */
export const PROFILERS: { value: Profiler; label: string }[] = [
  { value: 'perfetto', label: 'Perfetto · Android' },
  { value: 'ios', label: 'Instruments · iOS' },
  { value: 'flashlight', label: 'Flashlight · Android' },
]

/** A trace-lane path in a given lane: the iOS lane has the same screens under
 *  `/ios`. Flashlight paths are its own and pass through unchanged. */
export const lanePath = (profiler: Profiler, path: string) =>
  profiler === 'ios' && !path.startsWith('/ios/') && !path.startsWith('/flashlight/') ? `/ios${path}` : path

/** The same trace-lane path in another trace lane: `/memory` <-> `/ios/memory`. */
export const toLane = (pathname: string, to: Profiler) =>
  lanePath(to, pathname.startsWith('/ios/') ? pathname.slice(4) : pathname)

/** lanePath for the lane in view, for links written as Android paths
 *  (`/history`, `/steps?focus=...`) so they stay in the lane the user is in. */
export function useLanePath() {
  const profiler = useProfiler()
  return (path: string) => lanePath(profiler, path)
}

/** navigate() for links written as Android paths: they open in the lane in view. */
export function useLaneNavigate() {
  const navigate = useNavigate()
  const lp = useLanePath()
  return (to: string) => navigate(lp(to))
}
