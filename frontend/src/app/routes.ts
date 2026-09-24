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
  /** The page component, when it differs from `id` (the iOS lane reuses the trace pages). */
  page?: string
}

const TRACE_SCREENS: ScreenDef[] = [
  { id: 'overview', path: '/overview', label: 'Overview', code: 'OV', group: 'ANALYSE', hint: 'The run in view against the pinned benchmark, or the run before it.', profiler: 'perfetto' },
  { id: 'startup', path: '/startup', label: 'Startup', code: 'ST', group: 'ANALYSE', hint: 'Time to initial display, critical-path composition and the ordering constraint.', profiler: 'perfetto' },
  { id: 'frames', path: '/frames', label: 'Frame pacing', code: 'FP', group: 'ANALYSE', hint: 'Slow and janky frames, and whether the device throttled.', profiler: 'perfetto' },
  { id: 'memory', path: '/memory', label: 'Memory', code: 'ME', group: 'ANALYSE', hint: 'Peak RAM and growth across the session.', profiler: 'perfetto' },
  { id: 'steps', path: '/steps', label: 'Steps', code: 'SP', group: 'ANALYSE', hint: 'Every startup step against its trailing baseline, with child slices.', profiler: 'perfetto' },
  { id: 'screens', path: '/screens', label: 'Screens', code: 'SC', group: 'ANALYSE', hint: "Per-screen CPU and RAM from the app's own screen markers.", profiler: 'perfetto' },
  { id: 'stability', path: '/stability', label: 'Stability', code: 'SB', group: 'ANALYSE', hint: 'Hangs, JS errors and crashes: when, on which screen, and the resolved stack.', profiler: 'perfetto' },
  { id: 'capture', path: '/capture', label: 'Capture', code: 'CA', group: 'RUN', hint: 'Profile an app installed on the connected device.', profiler: 'perfetto' },
  { id: 'stress', path: '/stress', label: 'Stress', code: 'SS', group: 'RUN', hint: 'Repeat cold starts to separate a real regression from noise.', profiler: 'perfetto' },
  { id: 'manual', path: '/manual', label: 'Manual', code: 'MA', group: 'RUN', hint: 'Drive the app by hand while it is traced, then analyse.', profiler: 'perfetto' },
  { id: 'compare', path: '/compare', label: 'Compare', code: 'CO', group: 'DATA', hint: 'Diff a run against the pinned benchmark or another run.', profiler: 'perfetto' },
  { id: 'history', path: '/history', label: 'History', code: 'HI', group: 'DATA', hint: 'Every recorded run. Pin a benchmark here.', profiler: 'perfetto' },
]

// Flashlight's own lane.
const FLASHLIGHT_SCREENS: ScreenDef[] = [
  { id: 'audit', path: '/flashlight/audit', label: 'Audit', code: 'AU', group: 'ANALYSE', profiler: 'flashlight', hint: "The audit in view: Flashlight's score, CPU by thread, RAM and FPS across its cold starts." },
  { id: 'audit-run', path: '/flashlight/run', label: 'Run audit', code: 'RA', group: 'RUN', profiler: 'flashlight', hint: "Measure an app's cold start with Flashlight, several times over." },
  { id: 'audits', path: '/flashlight/audits', label: 'Audits', code: 'AL', group: 'DATA', profiler: 'flashlight', hint: "Every Flashlight audit. Flashlight's numbers are its own and are never compared with Perfetto runs." },
]

// The iOS lane: the trace screens again, reading iOS runs (Instruments
// recordings converted to Perfetto traces). Manual sessions are not on iOS yet.
const IOS_HINTS: Record<string, string> = {
  frames: 'Slow and janky frames. Not measured on the iOS Simulator, which supports none of Instruments\' frame instruments.',
  capture: 'Profile an app installed on the booted iOS Simulator.',
  stress: 'Repeat cold starts on the simulator to separate a real change from noise.',
}
const IOS_SCREENS: ScreenDef[] = TRACE_SCREENS.filter((x) => x.id !== 'manual').map((x) => ({
  ...x,
  id: `ios-${x.id}`,
  path: `/ios${x.path}`,
  profiler: 'ios' as const,
  page: x.id,
  hint: IOS_HINTS[x.id] ?? x.hint,
}))

export const SCREENS: ScreenDef[] = [...TRACE_SCREENS, ...IOS_SCREENS, ...FLASHLIGHT_SCREENS]

export const GROUPS: NavGroup[] = ['ANALYSE', 'RUN', 'DATA']

export const screenByPath = (pathname: string) =>
  SCREENS.find((s) => pathname === s.path || pathname.startsWith(s.path + '/')) ?? SCREENS[0]!

export const screensFor = (profiler: Profiler) => SCREENS.filter((x) => x.profiler === profiler)

/** Where a profiler opens: its first screen. */
export const homeOf = (profiler: Profiler) => screensFor(profiler)[0]!.path
