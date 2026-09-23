import { stepDeltas, worstRegression } from './steps'
import type { Run } from '@/api/types'

const run = (id: number, durs: Record<string, number>) =>
  ({ id, steps: Object.entries(durs).map(([step, dur_ms]) => ({ step, dur_ms, children: [] })) }) as unknown as Run

describe('step deltas', () => {
  const prior = [run(1, { a: 100, b: 10 }), run(2, { a: 110, b: 12 }), run(3, { a: 90, b: 11 })]
  it('uses the trailing median without a benchmark', () => {
    const d = stepDeltas(run(4, { a: 150, b: 11 }), prior, null)
    expect(d[0]!.baseline).toBe(100)
    expect(d[0]!.baselineFrom).toBe('median')
    expect(d[0]!.deltaMs).toBe(50)
  })
  it('prefers the pinned benchmark', () => {
    const d = stepDeltas(run(4, { a: 150, b: 11 }), prior, run(2, { a: 110, b: 12 }))
    expect(d[0]!.baseline).toBe(110)
    expect(d[0]!.baselineFrom).toBe('benchmark')
  })
  it('names the worst move and its share of the startup change', () => {
    const d = stepDeltas(run(4, { a: 150, b: 14 }), prior, null)
    const w = worstRegression(d, 60)
    expect(w?.step).toBe('a')
    expect(Math.round(w!.share!)).toBe(83)
  })
  it('ignores moves under 5ms', () => {
    expect(worstRegression(stepDeltas(run(4, { a: 103, b: 12 }), prior, null), 4)).toBeNull()
  })
})
