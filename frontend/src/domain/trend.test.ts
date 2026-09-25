import { describe, expect, it } from 'vitest'
import type { TrendPayload, TrendSeries } from '@/api/types'
import { buildChart, effectivePicks, MAX_DEVICES, nextSlots, SLOT_COLORS } from './trend'

const line = (device: string, metric: string, values: (number | null)[], extra: Partial<TrendSeries> = {}): TrendSeries => ({
  device,
  metric,
  kind: null,
  startup_metric: metric === 'ttff_ms' ? 'time to initial display' : null,
  target: null,
  points: values.map((value, i) => ({ version: `v${i}`, value, n: value == null ? 0 : 3, run_ids: [] })),
  ...extra,
})

const payload = (over: Partial<TrendPayload> = {}): TrendPayload => ({
  app: 'com.swag.pay',
  path: 'cold',
  platform: 'android',
  versions: [
    { key: 'v0', name: '2.3.0', build: 230, label: '2.3.0 (build 230)', runs: 3 },
    { key: 'v1', name: '2.4.0', build: 240, label: '2.4.0 (build 240)', runs: 3 },
  ],
  unversioned: 0,
  devices: [
    { name: 'V2514', label: 'vivo V2514', simulator: false, runs: 6 },
    { name: 'Pixel 7', label: 'Google Pixel 7', simulator: false, runs: 3 },
  ],
  steps: ['step:process_start', 'step:bind_application'],
  series: [
    line('V2514', 'ttff_ms', [500, 520]),
    line('Pixel 7', 'ttff_ms', [400, null]),
    line('V2514', 'janky_pct', [0.4, 0.6], { target: 0.5 }),
    line('Pixel 7', 'janky_pct', [0.3, 0.2], { target: 0.5 }),
  ],
  benchmarks: { V2514: { run_id: 12, device: 'V2514', derived: true, version: '2.3.0 (build 230)', values: { ttff_ms: 480, janky_pct: 0.3 } } },
  startup_target_reason: 'No startup target (B-010).',
  ...over,
})

describe('device slots', () => {
  it('keeps each device in its slot, so dropping one never repaints the others', () => {
    const a = nextSlots([], ['V2514', 'Pixel 7', 'SM-S918'])
    expect(a).toEqual(['V2514', 'Pixel 7', 'SM-S918'])
    const b = nextSlots(a, ['V2514', 'SM-S918'])
    expect(b).toEqual(['V2514', '', 'SM-S918'])
    expect(nextSlots(b, ['V2514', 'SM-S918', 'Pixel 8'])).toEqual(['V2514', 'Pixel 8', 'SM-S918'])
  })

  it('holds as many devices as there are colours that pass the validator', () => {
    expect(MAX_DEVICES).toBe(SLOT_COLORS.length)
    expect(SLOT_COLORS).not.toContain('var(--c4)')
    expect(nextSlots([], ['a', 'b', 'c', 'd']).filter(Boolean)).toHaveLength(MAX_DEVICES)
  })
})

describe('picks', () => {
  it('defaults to the device with the most runs and the startup time', () => {
    expect(effectivePicks(payload(), undefined)).toEqual({ devices: ['V2514', '', ''], metrics: ['ttff_ms'], steps: [] })
  })

  it('drops what this app and path no longer has', () => {
    const picks = effectivePicks(payload(), { devices: ['Gone', 'Pixel 7', ''], metrics: ['ttff_ms', 'nope'], steps: ['step:gone', 'step:process_start'] })
    expect(picks).toEqual({ devices: ['', 'Pixel 7', ''], metrics: ['ttff_ms'], steps: ['step:process_start'] })
  })
})

describe('a chart', () => {
  it('draws a line per device in its slot colour, with its notes and gaps', () => {
    const c = buildChart(payload(), 'ttff_ms', ['V2514', 'Pixel 7', ''])
    expect(c.labels).toEqual(['2.3.0 (build 230)', '2.4.0 (build 240)'])
    expect(c.series.map((s) => [s.name, s.color, s.values])).toEqual([
      ['vivo V2514', 'var(--c1)', [500, 520]],
      ['Google Pixel 7', 'var(--c2)', [400, null]],
    ])
    expect(c.series[1]!.notes).toEqual(['median of 3 runs', null])
    expect(c.title).toBe('Startup time')
    expect(c.hasData).toBe(true)
  })

  it('dots each device’s own benchmark, tied to its line', () => {
    const c = buildChart(payload(), 'ttff_ms', ['V2514', 'Pixel 7', ''])
    expect(c.references).toEqual([
      { value: 480, label: 'vivo V2514 benchmark #12 · 2.3.0 (build 230)', series: 'vivo V2514', color: 'var(--c1)', style: 'dotted' },
    ])
    expect(c.hint).toContain('pinned benchmark')
  })

  it('draws a shared North Star target once, and says why startup has none', () => {
    expect(buildChart(payload(), 'janky_pct', ['V2514', 'Pixel 7', '']).budget).toBe(0.5)
    const ttff = buildChart(payload(), 'ttff_ms', ['V2514', '', ''])
    expect(ttff.budget).toBeNull()
    expect(ttff.hint).toContain('B-010')
  })

  it('splits a device whose startup was measured both ways, and ties the benchmark to its kind', () => {
    const p = payload({
      series: [
        line('V2514', 'ttff_ms', [500, 520], { kind: 'derived', startup_metric: 'time to initial display' }),
        line('V2514', 'ttff_ms', [300, 310], { kind: 'instrumented', startup_metric: 'time to first camera frame', target: 420 }),
      ],
    })
    const c = buildChart(p, 'ttff_ms', ['V2514', '', ''])
    expect(c.series.map((s) => s.name)).toEqual(['vivo V2514 · time to initial display', 'vivo V2514 · time to first camera frame'])
    expect(c.references.map((r) => r.series)).toEqual(['vivo V2514 · time to initial display'])
    expect(c.budget).toBe(420)
  })

  it('names a launch step and knows when nothing was measured', () => {
    const c = buildChart(payload(), 'step:bind_application', ['V2514', '', ''], { 'step:bind_application': 'Binds the app.' })
    expect(c.title).toBe('bind_application step')
    expect(c.unit).toBe('ms')
    expect(c.hint).toContain('Binds the app.')
    expect(c.hasData).toBe(false)
  })
})
