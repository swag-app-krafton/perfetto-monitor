/** The navigation model. The sidebar, page header and routes are all derived
 *  from this one table, so adding a screen is one entry here plus a component. */

export type NavGroup = 'ANALYSE' | 'RUN' | 'DATA'

export interface ScreenDef {
  id: string
  path: string
  label: string
  /** Two-letter code shown in the collapsed rail. */
  code: string
  group: NavGroup
  hint: string
}

export const SCREENS: ScreenDef[] = [
  { id: 'overview', path: '/overview', label: 'Overview', code: 'OV', group: 'ANALYSE', hint: 'Latest run against the pinned benchmark.' },
  { id: 'startup', path: '/startup', label: 'Startup', code: 'ST', group: 'ANALYSE', hint: 'Time to initial display, critical-path composition and the ordering constraint.' },
  { id: 'frames', path: '/frames', label: 'Frame pacing', code: 'FP', group: 'ANALYSE', hint: 'Slow and janky frames, and whether the device throttled.' },
  { id: 'memory', path: '/memory', label: 'Memory', code: 'ME', group: 'ANALYSE', hint: 'Peak RAM and growth across the session.' },
  { id: 'steps', path: '/steps', label: 'Steps', code: 'SP', group: 'ANALYSE', hint: 'Every startup step against its trailing baseline, with child slices.' },
  { id: 'screens', path: '/screens', label: 'Screens', code: 'SC', group: 'ANALYSE', hint: "Per-screen CPU and RAM from the app's own screen markers." },
  { id: 'capture', path: '/capture', label: 'Capture', code: 'CA', group: 'RUN', hint: 'Profile an app installed on the connected device.' },
  { id: 'stress', path: '/stress', label: 'Stress', code: 'SS', group: 'RUN', hint: 'Repeat cold starts to separate a real regression from noise.' },
  { id: 'manual', path: '/manual', label: 'Manual', code: 'MA', group: 'RUN', hint: 'Drive the app by hand while it is traced, then analyse.' },
  { id: 'compare', path: '/compare', label: 'Compare', code: 'CO', group: 'DATA', hint: 'Diff a run against the pinned benchmark or another run.' },
  { id: 'history', path: '/history', label: 'History', code: 'HI', group: 'DATA', hint: 'Every recorded run. Pin a benchmark here.' },
]

export const GROUPS: NavGroup[] = ['ANALYSE', 'RUN', 'DATA']

export const screenByPath = (pathname: string) =>
  SCREENS.find((s) => pathname === s.path || pathname.startsWith(s.path + '/')) ?? SCREENS[0]!
