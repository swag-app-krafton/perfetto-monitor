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
}

export interface SpreadStats {
  n: number
  median: number
  p10?: number
  p90?: number
  min: number
  max: number
  [k: string]: number | undefined
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
  sessions?: StressSession[]
  stats?: Record<string, SpreadStats | null>
}

export interface CompareMetric {
  key: string
  label?: string
  a: number | null
  b: number | null
  delta: number | null
  pct: number | null
  worse: boolean
  same: boolean
  signed?: boolean
  [k: string]: unknown
}

export interface ComparePayload {
  run: Run | Record<string, unknown>
  base: Run | Record<string, unknown>
  metrics: CompareMetric[]
  steps: Record<string, unknown>[]
  [k: string]: unknown
}
