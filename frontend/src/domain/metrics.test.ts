import { gateTone, METRICS, runVerdict, valueOf } from './metrics'
import type { GlobalBudgets, Run } from '@/api/types'

describe('metrics', () => {
  it('grades a gate: over budget fails, within 10% warns', () => {
    expect(gateTone(968, 900)).toBe('fail')
    expect(gateTone(6.8, 7.5)).toBe('warn')
    expect(gateTone(9, 15)).toBe('pass')
    expect(gateTone(null, 900)).toBe('neutral')
    expect(gateTone(500, null)).toBe('neutral')
  })
  it('never judges a simulator run against a budget', () => {
    const g = { slow_frame_pct: 5, janky_frame_pct: 0.5, peak_rss_mb: 320, rss_growth_mb: 60, thermal_drift_pct: 15 } as GlobalBudgets
    const phone = { app_role: 'own', ttid_budget_ms: 420, simulator: false } as Run
    const sim = { ...phone, simulator: true } as Run
    expect(METRICS.map((m) => m.budget(phone, g)).every((b) => b != null)).toBe(true)
    expect(METRICS.map((m) => m.budget(sim, g))).toEqual(METRICS.map(() => null))
  })
  it('shows a simulator pass as steady, and keeps its warnings', () => {
    const a = (verdict: 'pass' | 'warn') => ({ verdict }) as Run['analysis']
    expect(runVerdict({ analysis: a('pass'), simulator: true })).toEqual({ tone: 'neutral', word: 'STEADY' })
    expect(runVerdict({ analysis: a('warn'), simulator: true })).toEqual({ tone: 'warn', word: 'WARN' })
    expect(runVerdict({ analysis: a('pass'), simulator: false })).toEqual({ tone: 'pass', word: 'PASS' })
    expect(runVerdict({ analysis: null, simulator: false }).word).toBe('NO VERDICT')
  })
  it('treats a zero startup time as unmeasured', () => {
    expect(valueOf({ ttff_ms: 0 } as Run, 'ttff_ms')).toBeNull()
    expect(valueOf({ slow_pct: 0 } as Run, 'slow_pct')).toBe(0)
  })
})
