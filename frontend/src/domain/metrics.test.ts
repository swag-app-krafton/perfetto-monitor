import { gateTone, valueOf } from './metrics'
import type { Run } from '@/api/types'

describe('metrics', () => {
  it('grades a gate: over budget fails, within 10% warns', () => {
    expect(gateTone(968, 900)).toBe('fail')
    expect(gateTone(6.8, 7.5)).toBe('warn')
    expect(gateTone(9, 15)).toBe('pass')
    expect(gateTone(null, 900)).toBe('neutral')
    expect(gateTone(500, null)).toBe('neutral')
  })
  it('treats a zero startup time as unmeasured', () => {
    expect(valueOf({ ttff_ms: 0 } as Run, 'ttff_ms')).toBeNull()
    expect(valueOf({ slow_pct: 0 } as Run, 'slow_pct')).toBe(0)
  })
})
