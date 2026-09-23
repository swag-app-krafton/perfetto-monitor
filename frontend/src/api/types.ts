/** Wire types for the swagperf server (swagperf/server.py). Field names match
 *  the JSON exactly; derived, UI-friendly shapes live in src/domain. */

export type Verdict = 'pass' | 'warn' | 'fail'
export type Severity = 'high' | 'medium' | 'low'

export interface ChildSlice {
  name: string
  dur_ms: number
  count: number | null
  pct_of_step: number | null
}

export interface StepRow {
  id: number
  run_id: number
  step: string
  dur_ms: number
  start_ms: number | null
  budget_ms: number | null
  over_budget: number
  children: ChildSlice[]
}

export interface Finding {
  title: string
  runtime?: string
  severity: Severity
  kind?: string
  evidence: string
  architectural_risk?: string | null
  recommendation?: string
}

export interface Analysis {
  verdict: Verdict
  headline: string
  findings: Finding[]
  dismissed?: { title: string; reason?: string }[]
  _model?: string
  _heuristic?: boolean
}

export interface Breach {
  metric: string
  value: number
  budget: number
  over_by_pct: number
}

export interface FrameStats {
  total: number
  slow: number
  janky: number
  slow_pct: number | null
  janky_pct: number | null
  avg_ms: number | null
  max_ms: number | null
  thermal_drift_pct: number | null
}

export interface MemoryStats {
  rss?: { peak_mb: number; min_mb: number; growth_mb: number; source?: string }
  hermes_heap?: { peak_mb: number; min_mb: number; growth_mb: number }
}

/** Where a run was measured, merged server-side from what adb read at
 *  capture time, what the trace records, and the run's own columns. A field
 *  nothing recorded is absent, never guessed. */
export interface RunDetails {
  device: Partial<{
    manufacturer: string
    brand: string
    model: string
    market_name: string
    codename: string
    product: string
    android_release: string
    sdk: number
    security_patch: string
    build_id: string
    build_type: string
    fingerprint: string
    soc: string
    hardware: string
    abi: string
    kernel: string
    cpu_cores: number
    ram_gb: number
    screen: string
    density_dpi: number
    refresh_hz: number
    serial: string
  }>
  app: Partial<{
    package: string
    name: string
    version_name: string
    version_code: number
    min_sdk: number
    target_sdk: number
    debuggable: boolean
    installer: string
    first_install: string
    last_update: string
    git_sha: string
  }>
  state: Partial<{ battery_pct: number; battery_temp_c: number; charging: string; thermal_status: string }>
  /** When `state` was read: "before capture" or "end of session". */
  state_moment?: string | null
  trace: Partial<{ path: string; size_mb: number; duration_s: number; perfetto_version: string; utc_offset_min: number; uuid: string }>
  /** Which sources contributed: "capture" (adb at capture time), "from_trace". */
  sources: string[]
  trace_error?: string | null
}

export interface Run {
  id: number
  ts: string
  label: string | null
  git_sha: string | null
  app_version: string | null
  device: string | null
  path_kind: string
  trace_path: string | null
  app_pkg: string | null
  app_name: string | null
  app_role: 'own' | 'competitor' | 'reference' | null
  derived: number
  ttff_ms: number | null
  slow_pct: number | null
  janky_pct: number | null
  thermal_drift_pct: number | null
  peak_rss_mb: number | null
  rss_growth_mb: number | null
  ttid_budget_ms: number | null
  steps: StepRow[]
  breaches: Breach[]
  violations: { step: string; detail: string }[]
  frames: FrameStats | null
  memory: MemoryStats | null
  analysis: Analysis | null
  meta: RunDetails
}

export interface Benchmark {
  scope: string
  run_id: number
  note: string | null
  set_at: string
  label: string | null
  ts: string
  device: string | null
  path_kind: string | null
  app_version: string | null
  app_pkg: string | null
}

export type GlobalBudgets = Record<
  | 'time_to_first_camera_frame_ms'
  | 'slow_frame_pct'
  | 'janky_frame_pct'
  | 'peak_rss_mb'
  | 'rss_growth_mb'
  | 'thermal_drift_pct',
  number
>

export interface HistoryPayload {
  runs: Run[]
  step_budgets: Record<string, number>
  global_budgets: GlobalBudgets
  risk_map: Record<string, string>
  benchmarks: Benchmark[]
  metric_direction: Record<string, 'lower' | 'higher'>
  signed_metrics: string[]
  startup_model: {
    critical_path: Record<string, string[]>
    deferred_steps: string[]
    step_runtime: Record<string, string>
    /** What each step covers, in plain words (swagperf/budgets.py STEP_DESCRIPTIONS). */
    step_descriptions: Record<string, string>
  }
}

export interface DevicePackage {
  pkg: string
  name: string
  role: string
  installed: boolean
  instrumented: boolean
  in_catalogue: boolean
  version?: string
}

export type DevicePayload =
  | { connected: false; error?: string }
  | {
      connected: true
      serial: string
      model: string
      release: string
      sdk?: string
      packages: DevicePackage[]
      health?: { battery_pct: number | null; battery_temp_c: number | null; perfetto_version: string | null }
      devices?: string[]
      /** What can run on the device now: one profiler at a time. */
      profilers?: {
        flashlight_runner: RunnerStatus
        /** Other tools using the kernel trace buffer, by name. */
        other_profilers: string[]
        perfetto_recording: boolean
      }
      [k: string]: unknown
    }

export interface JobLogLine {
  t: number
  text: string
}

export interface Job<R = Record<string, unknown>> {
  id: string
  kind?: string
  state: 'queued' | 'running' | 'done' | 'error'
  log: JobLogLine[]
  error?: string
  result?: R
}

export interface ManualStatus {
  device: boolean
  serial?: string
  recording: boolean
}

export interface LiveEvent {
  kind: 'screen' | 'action' | 'nav' | 'step'
  name: string
  at_ms: number
  duration_ms: number | null
  open_ended: boolean
  screen_kind?: string
  screen_kind_label?: string
  parent?: string | null
  step?: string | null
}

export interface LivePayload {
  recording: boolean
  events: LiveEvent[]
  counts: Partial<Record<LiveEvent['kind'], number>>
  current_screen?: string | null
  current_screen_kind?: string | null
  total?: number
  truncated?: boolean
  note?: string
  mode?: string
  read_mb?: number
  remote_mb?: number | null
  poll_s?: number
}

export interface JankSplit {
  frames: number
  late: number
  app: number
  system: number
  dropped: number
  buffer_stuffing: number
  other: number
  app_jank_pct: number | null
  late_pct: number | null
}

export interface ScreenVisit {
  route: string
  kind: string
  kind_label: string
  parent: string | null
  step: string | null
  start_ms: number
  duration_ms: number
  open_ended: boolean
  cpu_ms: number | null
  cpu_pct_of_wall: number | null
  rss: { min_mb: number; peak_mb: number; delta_mb: number } | null
  frames: number
  slow_frames: number
  slow_frame_pct: number | null
  depth: number
  stack: string[]
  beneath: string[]
}

export interface ScreenSummary {
  route: string
  kind: string
  kind_label: string
  parent: string | null
  step: string | null
  visits: number
  total_ms: number
  total_cpu_ms: number
  worst_ms: number
  frames: number
  slow_frames: number
  slow_frame_pct: number | null
  peak_rss_mb: number | null
  max_rss_delta_mb: number | null
  depths: number[]
  depth_label: string | null
  jank: JankSplit | null
  visit_list: (Pick<ScreenVisit, 'start_ms' | 'duration_ms' | 'cpu_ms' | 'cpu_pct_of_wall' | 'open_ended' | 'depth' | 'stack' | 'beneath' | 'slow_frame_pct'> & {
    index: number
    peak_rss_mb: number | null
    rss_delta_mb: number | null
    outlier: Record<string, boolean>
  })[]
  stats: Record<string, { mean: number | null; stdev: number | null; min: number | null; max: number | null }>
}

export interface StackDepthRow {
  depth: number
  visits: number
  total_ms: number
  total_cpu_ms: number
  mean_cpu_pct: number | null
  peak_rss_mb: number | null
  routes: [string, number][]
  beneath: [string, number][]
}

export interface Transition {
  transition: string
  from: string | null
  to: string | null
  count: number
  median_ms: number | null
  max_ms: number | null
  total_ms: number | null
}

export interface ActionRow {
  action: string
  count: number
  total_ms: number | null
  max_ms: number | null
  mean_ms: number | null
}

export type ScreensPayload =
  | { instrumented: false; note?: string; screens: []; screen_summary: []; actions: []; navigations: [] }
  | {
      instrumented: true
      screens: ScreenVisit[]
      screen_summary: ScreenSummary[]
      stack_summary: StackDepthRow[]
      max_depth: number
      timeline: { rss: [number, number][]; cpu: [number, number][]; bucket_ms: number }
      actions: ActionRow[]
      action_events: { at_ms: number; action: string; screen: string | null }[]
      navigations: Transition[]
    }

export interface StressSession {
  id: number
  seq: number
  run_id: number | null
  state: string
  error: string | null
  ttid_ms: number | null
  slow_pct?: number | null
  peak_rss_mb?: number | null
  run_label?: string | null
  run_ts?: string | null
}

export interface SpreadStats {
  n: number
  min: number
  max: number
  mean: number
  median: number
  p90: number
  stdev: number
  spread_pct: number
}

export interface StressTest {
  id: number
  ts: string
  app_pkg: string | null
  device: string | null
  label: string | null
  sessions_requested: number
  cold: number
  duration_ms: number | null
  state: string
  error: string | null
  finished: string | null
  completed?: number
  failed?: number
  sessions?: StressSession[]
  stats?: Record<string, SpreadStats | null>
}

export type DiffVerdict = 'better' | 'worse' | 'same'

export interface CompareMetric {
  metric: string
  value: number | null
  base_value: number | null
  delta: number | null
  delta_pct: number | null
  direction: 'lower' | 'higher'
  signed: boolean
  verdict: DiffVerdict | null
}

export interface CompareStep {
  step: string
  dur_ms: number | null
  base_dur_ms: number | null
  budget_ms: number | null
  /** Set when the step exists in only one of the two runs. */
  only_in: 'run' | 'base' | null
  delta_ms: number | null
  delta_pct: number | null
  verdict: DiffVerdict | null
  children: { name: string; dur_ms: number | null; base_dur_ms: number | null; delta_ms: number | null; delta_pct: number | null }[]
}

export interface RunMeta {
  id: number
  ts: string
  label: string | null
  git_sha: string | null
  app_version: string | null
  device: string | null
  path_kind: string
}

export interface ComparePayload {
  run: RunMeta
  base: RunMeta
  /** Same startup path: a cold start is not comparable with a warm one. */
  comparable: boolean
  same_device: boolean
  metrics: CompareMetric[]
  steps: CompareStep[]
  summary: Record<DiffVerdict, number>
}

// ---------------------------------------------------------------- Flashlight

/** Whether Flashlight can run on the machine serving the dashboard. */
export type RunnerStatus = { ready: true; version: string } | { ready: false; reason: string }

export interface AuditMetrics {
  cpu_pct: number | null
  fps: number | null
  ram_mb: number | null
  runtime_ms: number | null
  high_cpu_s: number | null
}

export interface ThreadCpu {
  name: string
  cpu_pct: number | null
  /** What the thread is, in plain words, when its name says (swagperf/threads.py). */
  description?: string
}

/** The threads a hybrid Compose + React Native app is read by. */
export interface KeyThreads {
  ui: ThreadCpu | null
  render: ThreadCpu | null
  js: ThreadCpu | null
  native_modules: ThreadCpu | null
}

export interface RangeStat {
  minMaxRange: [number, number]
  deviationRange: [number, number]
  variationCoefficient: number
}

export interface AuditIteration extends Partial<AuditMetrics> {
  index: number
  status: 'SUCCESS' | 'FAILURE'
  retried: boolean
  key_threads: KeyThreads | null
}

/** One point of the average iteration, 500 ms apart. */
export interface AuditPoint {
  t_ms: number
  cpu_pct: number | null
  ui_pct: number | null
  js_pct: number | null
  ram_mb: number | null
  fps: number | null
}

/** Everything Flashlight's reporter says about an audit (flashlight/summary.js). */
export interface AuditSummary {
  flashlight_version: string
  title: string
  status: string
  iterations_run: number
  successful: number
  failed: number
  failure: string | null
  refresh_rate: number | null
  score: number | null
  metrics: AuditMetrics | null
  key_threads: KeyThreads | null
  threads: ThreadCpu[]
  stats: { cpu: RangeStat; fps?: RangeStat; ram?: RangeStat; runtime: RangeStat } | null
  iterations: AuditIteration[]
  series: AuditPoint[]
}

export interface Audit {
  id: number
  ts: string
  app_pkg: string
  app_name: string
  app_role: string | null
  device: string | null
  label: string | null
  iterations: number
  duration_ms: number
  state: 'running' | 'done' | 'error' | 'interrupted'
  error: string | null
  finished: string | null
  results_path: string | null
  flashlight_version: string | null
  score: number | null
  cpu_pct: number | null
  ram_mb: number | null
  fps: number | null
  meta: Record<string, unknown> | null
  /** In a list, only the headline parts; the detail call has all of it. */
  summary: Partial<AuditSummary> | null
}
