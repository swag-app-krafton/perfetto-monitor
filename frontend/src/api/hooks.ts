import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type {
  Audit,
  ComparePayload,
  DevicePayload,
  HistoryPayload,
  Job,
  LivePayload,
  ManualStatus,
  Platform,
  RunDetails,
  RunnerStatus,
  RunSummary,
  ScreensPayload,
  Stability,
  StressTest,
  TrendPayload,
} from './types'

export const keys = {
  history: ['history'] as const,
  screens: (runId: number) => ['screens', runId] as const,
  compare: (a: number, b: number) => ['compare', a, b] as const,
  device: (platform: Platform) => ['device', platform] as const,
  manualStatus: ['manual', 'status'] as const,
  live: ['manual', 'live'] as const,
  stressList: ['stress'] as const,
  stress: (id: number) => ['stress', id] as const,
  job: (id: string) => ['job', id] as const,
  jobs: ['jobs'] as const,
  runMeta: (id: number) => ['run-meta', id] as const,
  stability: (id: number) => ['stability', id] as const,
  audits: ['audits'] as const,
  audit: (id: number) => ['audits', id] as const,
  summary: (runId: number) => ['summary', runId] as const,
  trend: (app: string, path: string, platform: Platform) => ['trend', app, path, platform] as const,
}

/** One app and start path across every version (F-026), from every run, not
 *  the newest 100 that /api/history holds. */
export const useTrend = (app: string, path: string, platform: Platform) =>
  useQuery({
    queryKey: keys.trend(app, path, platform),
    queryFn: () =>
      api.get<TrendPayload>(`/api/trend?app=${encodeURIComponent(app)}&path=${encodeURIComponent(path)}&platform=${platform}`),
    enabled: !!app && !!path,
  })

export const useHistory = () =>
  useQuery({ queryKey: keys.history, queryFn: () => api.get<HistoryPayload>('/api/history') })

/** Screen extraction is cached server-side per trace, so this is cheap after
 *  the first read of a run. */
export const useScreens = (runId: number | null) =>
  useQuery({
    queryKey: keys.screens(runId ?? -1),
    queryFn: () => api.get<ScreensPayload>(`/api/screens?run=${runId}`),
    enabled: runId != null,
    staleTime: Infinity,
  })

/** A run's hangs, JS errors and crash state, its error stacks resolved
 *  against the build's source map when one is registered. */
export const useStability = (runId: number | null) =>
  useQuery({
    queryKey: keys.stability(runId ?? -1),
    queryFn: () => api.get<{ run_id: number; stability: Stability | null }>(`/api/stability?run=${runId}`),
    enabled: runId != null,
  })

export const useCompare = (a: number | null, b: number | null) =>
  useQuery({
    queryKey: keys.compare(a ?? -1, b ?? -1),
    queryFn: () => api.get<ComparePayload>(`/api/compare?run=${a}&base=${b}`),
    enabled: a != null && b != null && a !== b,
  })

/** The connected device (Android) or booted simulator (iOS), with its apps. */
export const useDevice = (platform: Platform = 'android') =>
  useQuery({
    queryKey: keys.device(platform),
    queryFn: () => api.get<DevicePayload>(`/api/device?platform=${platform}`),
    refetchInterval: 15_000,
  })

export const useManualStatus = (poll = false) =>
  useQuery({
    queryKey: keys.manualStatus,
    queryFn: () => api.get<ManualStatus>('/api/manual/status'),
    refetchInterval: poll ? 3_000 : false,
  })

/** Live markers while a manual session records. Each poll costs ~1s server
 *  side (it reads only what is new), so it is not polled faster than that. */
export const useLiveMarkers = (enabled: boolean) =>
  useQuery({
    queryKey: keys.live,
    queryFn: () => api.get<LivePayload>('/api/manual/live'),
    enabled,
    refetchInterval: enabled ? 3_000 : false,
  })

export const useStressList = () =>
  useQuery({
    queryKey: keys.stressList,
    queryFn: () => api.get<{ stress_tests: StressTest[] }>('/api/stress').then((r) => r.stress_tests),
  })

/** One stress test. `live` polls while its sessions are still landing. */
export const useStress = (id: number | null, live = false) =>
  useQuery({
    queryKey: keys.stress(id ?? -1),
    queryFn: () => api.get<StressTest>(`/api/stress?id=${id}`),
    enabled: id != null,
    refetchInterval: live ? 1_500 : false,
  })

/** Polls a background job until it finishes. */
export const useJob = (id: string | null) =>
  useQuery({
    queryKey: keys.job(id ?? ''),
    queryFn: () => api.get<Job>(`/api/jobs?id=${encodeURIComponent(id ?? '')}`),
    enabled: !!id,
    refetchInterval: (q) => (q.state.data && ['done', 'error'].includes(q.state.data.state) ? false : 1_200),
  })

export function useBenchmarkMutations() {
  const qc = useQueryClient()
  const refresh = () => qc.invalidateQueries({ queryKey: keys.history })
  return {
    pin: useMutation({
      mutationFn: (v: { runId: number; note?: string }) =>
        api.post('/api/benchmark/set', { run_id: v.runId, note: v.note }),
      onSuccess: refresh,
    }),
    unpin: useMutation({
      mutationFn: (runId: number) => api.post('/api/benchmark/clear', { run_id: runId }),
      onSuccess: refresh,
    }),
  }
}

export const startCapture = (v: { pkg: string; cold: boolean; duration_ms: number; platform?: Platform; ai_summary?: boolean }) =>
  api.post<{ job_id: string }>('/api/capture/start', v)
export const startStress = (v: { pkg: string; sessions: number; cold: boolean; duration_ms: number; platform?: Platform; ai_summary?: boolean }) =>
  api.post<{ job_id: string }>('/api/stress/start', v)
export const manualStart = (v: { pkg: string; cold: boolean }) => api.post('/api/manual/start', v)
export const manualStop = (v: { pkg: string; ai_summary?: boolean }) => api.post<{ job_id: string }>('/api/manual/stop', v)

/** A run's AI summary (F-023), and whether one is being written now. Polls
 *  while it is, so the card fills in when the job finishes. */
export const useSummary = (runId: number | null) =>
  useQuery({
    queryKey: keys.summary(runId ?? -1),
    queryFn: () => api.get<{ run_id: number; summary: RunSummary | null; generating: boolean }>(`/api/summary?run=${runId}`),
    enabled: runId != null,
    refetchInterval: (q) => (q.state.data?.generating ? 2_000 : false),
  })

/** Start writing a run's AI summary. The job is followed with useJob. */
export function useGenerateSummary() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (runId: number) => api.post<{ job_id: string }>('/api/summary/generate', { run_id: runId }),
    onSuccess: (_r, runId) => qc.invalidateQueries({ queryKey: keys.summary(runId) }),
  })
}
export const manualAbort = () => api.post('/api/manual/abort')

/** Recent background jobs, so a page can find its running job again after a
 *  tab change or a reload. Polls only while one is still running. */
export const useRecentJobs = () =>
  useQuery({
    queryKey: keys.jobs,
    queryFn: () =>
      api
        .get<{ jobs: (Job & { kind: string; pkg?: string; started: number; duration_ms?: number; cold?: boolean; platform?: Platform })[] }>('/api/jobs')
        .then((r) => r.jobs),
    refetchInterval: (q) => (q.state.data?.some((j) => j.state === 'queued' || j.state === 'running') ? 1_500 : false),
  })

/** A run's full metadata. The first request for an older run reads its trace
 *  once server-side (a few seconds); after that it is stored. */
export const useRunMeta = (id: number | null) =>
  useQuery({
    queryKey: keys.runMeta(id ?? -1),
    queryFn: () => api.get<{ run_id: number; meta: RunDetails }>(`/api/run/meta?id=${id}`).then((r) => r.meta),
    enabled: id != null,
    staleTime: Infinity,
  })

/** Every Flashlight audit, newest first, and whether Flashlight can run here.
 *  Polls while one is still running, so its row fills in without a reload. */
export const useAudits = () =>
  useQuery({
    queryKey: keys.audits,
    queryFn: () => api.get<{ audits: Audit[]; runner: RunnerStatus }>('/api/audits'),
    refetchInterval: (q) => (q.state.data?.audits.some((a) => a.state === 'running') ? 2_000 : false),
  })

/** One audit in full: per-iteration numbers and the average iteration's series. */
export const useAudit = (id: number | null) =>
  useQuery({
    queryKey: keys.audit(id ?? -1),
    queryFn: () => api.get<Audit>(`/api/audits?id=${id}`),
    enabled: id != null,
    refetchInterval: (q) => (q.state.data?.state === 'running' ? 2_000 : false),
  })

export const startAudit = (v: { pkg: string; iterations: number; duration_ms: number }) =>
  api.post<{ job_id: string }>('/api/audit/start', v)
