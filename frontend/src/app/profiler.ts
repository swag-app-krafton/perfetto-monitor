import { useLocation } from 'react-router'
import { screenByPath } from './routes'
import type { Profiler } from './store'

/** The profiler in view. It comes from the page: every screen belongs to one
 *  profiler, so a link to a Flashlight page opens Flashlight's view. The store
 *  only remembers the last one, for where the bare URL opens. */
export const useProfiler = (): Profiler => screenByPath(useLocation().pathname).profiler

export const PROFILERS: { value: Profiler; label: string }[] = [
  { value: 'perfetto', label: 'Perfetto' },
  { value: 'flashlight', label: 'Flashlight' },
]
