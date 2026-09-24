import { appsIn, benchmarkFor, laneHistory, pathsIn } from './scope'
import { fmt, pathLabel, signed, stepName } from './format'
import type { HistoryPayload, Run } from '@/api/types'

const run = (over: Partial<Run>): Run =>
  ({
    id: 1, ts: '2026-09-23T10:00:00Z', label: null, git_sha: null, app_version: null, device: 'V2514',
    path_kind: 'cold', trace_path: null, app_pkg: 'com.swag.pay', app_name: 'Swag Pay', app_role: 'own',
    derived: 0, ttff_ms: 380, slow_pct: 1, janky_pct: 0.4, thermal_drift_pct: null, peak_rss_mb: 490,
    rss_growth_mb: 300, ttid_budget_ms: 420, steps: [], breaches: [], violations: [], frames: null,
    memory: null, analysis: null, ...over,
  }) as Run

const history = (runs: Run[], benchmarks: HistoryPayload['benchmarks'] = []) =>
  ({ runs, benchmarks }) as unknown as HistoryPayload

describe('scope', () => {
  it('lists the own app first, then by run count', () => {
    const h = history([
      run({ id: 1, app_pkg: 'com.phonepe.app', app_name: 'PhonePe', app_role: 'competitor' }),
      run({ id: 2, app_pkg: 'com.phonepe.app', app_name: 'PhonePe', app_role: 'competitor' }),
      run({ id: 3 }),
    ])
    expect(appsIn(h).map((a) => a.pkg)).toEqual(['com.swag.pay', 'com.phonepe.app'])
  })

  it('offers only the paths the data has', () => {
    expect(pathsIn([run({ path_kind: 'cold' }), run({ path_kind: 'warm' }), run({ path_kind: 'cold' })])).toEqual(['cold', 'warm'])
  })

  it('never applies a benchmark across apps or paths', () => {
    const b = (over: object) => ({ scope: '', run_id: 9, note: null, set_at: '', label: null, ts: '', device: null, path_kind: 'cold', app_version: null, app_pkg: 'com.swag.pay', ...over })
    const h = history([], [b({ app_pkg: 'com.other' }), b({ path_kind: 'warm' })])
    expect(benchmarkFor(run({}), h)).toBeNull()
    const h2 = history([], [b({ device: 'pixel7', run_id: 5 }), b({ device: 'V2514', run_id: 7 })])
    expect(benchmarkFor(run({}), h2)?.run_id).toBe(7)
  })
})

describe('format', () => {
  it('formats and signs numbers', () => {
    expect(fmt(1234.567, 1)).toBe('1,234.6')
    expect(fmt(null)).toBe('–')
    expect(signed(12.4, 0, ' ms')).toBe('+12 ms')
    expect(signed(-3, 0)).toBe('−3')
  })
  it('names paths and steps for people', () => {
    expect(pathLabel('returning_user')).toBe('Returning user')
    expect(pathLabel('cold')).toBe('Cold')
    expect(stepName('step:bind_application')).toBe('bind_application')
  })
})

describe('lanes', () => {
  it("shows a lane only its own platform's runs and benchmarks", () => {
    const b = (run_id: number, platform?: 'android' | 'ios') => ({ run_id, app_pkg: 'com.swag.pay', path_kind: 'cold', device: null, platform }) as HistoryPayload['benchmarks'][number]
    const h = history([run({ id: 1 }), run({ id: 2, platform: 'ios', simulator: true }), run({ id: 3, platform: 'android' })], [b(1), b(2, 'ios')])
    expect(laneHistory(h, 'android').runs.map((r) => r.id)).toEqual([1, 3])
    expect(laneHistory(h, 'ios').runs.map((r) => r.id)).toEqual([2])
    expect(laneHistory(h, 'ios').benchmarks.map((x) => x.run_id)).toEqual([2])
  })

  it('never takes a benchmark from the other platform for the same app', () => {
    const h = history([], [{ run_id: 9, app_pkg: 'com.swag.pay', path_kind: 'cold', device: null, platform: 'android' } as HistoryPayload['benchmarks'][number]])
    expect(benchmarkFor(run({ id: 10, platform: 'ios' }), h)).toBeNull()
    expect(benchmarkFor(run({ id: 11, platform: 'android' }), h)?.run_id).toBe(9)
  })
})

