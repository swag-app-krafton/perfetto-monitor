/** The navigation model. The sidebar, page header and routes are all derived
 *  from this one table, so adding a screen is one entry here plus a component. */

import type { Profiler } from './store'

export type NavGroup = 'ANALYSE' | 'RUN' | 'DATA'

export interface ScreenDef {
  id: string
  path: string
  label: string
  /** Two-letter code shown in the collapsed rail. */
  code: string
  group: NavGroup
  hint: string
  /** The profiler whose runs the screen shows; the sidebar lists one profiler's screens. */
  profiler: Profiler
}

export const SCREENS: ScreenDef[] = [
  { id: 'overview', path: '/overview', label: 'Overview', code: 'OV', group: 'ANALYSE', hint: 'The run in view against the pinned benchmark, or the run before it.', profiler: 'perfetto' },
  { id: 'startup', path: '/startup', label: 'Startup', code: 'ST', group: 'ANALYSE', hint: 'Time to initial display, critical-path composition and the ordering constraint.', profiler: 'perfetto' },
  { id: 'frames', path: '/frames', label: 'Frame pacing', code: 'FP', group: 'ANALYSE', hint: 'Slow and janky frames, and whether the device throttled.', profiler: 'perfetto' },
  { id: 'memory', path: '/memory', label: 'Memory', code: 'ME', group: 'ANALYSE', hint: 'Peak RAM and growth across the session.', profiler: 'perfetto' },
  { id: 'steps', path: '/steps', label: 'Steps', code: 'SP', group: 'ANALYSE', hint: 'Every startup step against its trailing baseline, with child slices.', profiler: 'perfetto' },
  { id: 'screens', path: '/screens', label: 'Screens', code: 'SC', group: 'ANALYSE', hint: "Per-screen CPU and RAM from the app's own screen markers.", profiler: 'perfetto' },
  { id: 'capture', path: '/capture', label: 'Capture', code: 'CA', group: 'RUN', hint: 'Profile an app installed on the connected device.', profiler: 'perfetto' },
  { id: 'stress', path: '/stress', label: 'Stress', code: 'SS', group: 'RUN', hint: 'Repeat cold starts to separate a real regression from noise.', profiler: 'perfetto' },
  { id: 'manual', path: '/manual', label: 'Manual', code: 'MA', group: 'RUN', hint: 'Drive the app by hand while it is traced, then analyse.', profiler: 'perfetto' },
  { id: 'compare', path: '/compare', label: 'Compare', code: 'CO', group: 'DATA', hint: 'Diff a run against the pinned benchmark or another run.', profiler: 'perfetto' },
  { id: 'history', path: '/history', label: 'History', code: 'HI', group: 'DATA', hint: 'Every recorded run. Pin a benchmark here.', profiler: 'perfetto' },
  { id: 'audit', path: '/flashlight/audit', label: 'Audit', code: 'AU', group: 'ANALYSE', profiler: 'flashlight', hint: "The audit in view: Flashlight's score, CPU by thread, RAM and FPS across its cold starts." },
  { id: 'audit-run', path: '/flashlight/run', label: 'Run audit', code: 'RA', group: 'RUN', profiler: 'flashlight', hint: "Measure an app's cold start with Flashlight, several times over." },
  { id: 'audits', path: '/flashlight/audits', label: 'Audits', code: 'AL', group: 'DATA', profiler: 'flashlight', hint: "Every Flashlight audit. Flashlight's numbers are its own and are never compared with Perfetto runs." },
]

export const GROUPS: NavGroup[] = ['ANALYSE', 'RUN', 'DATA']

export const screenByPath = (pathname: string) =>
  SCREENS.find((s) => pathname === s.path || pathname.startsWith(s.path + '/')) ?? SCREENS[0]!

export const screensFor = (profiler: Profiler) => SCREENS.filter((x) => x.profiler === profiler)

/** Where a profiler opens: its first screen. */
export const homeOf = (profiler: Profiler) => screensFor(profiler)[0]!.path
