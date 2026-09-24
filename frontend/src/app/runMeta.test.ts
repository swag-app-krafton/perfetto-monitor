import { describe, expect, it } from 'vitest'
import type { Run, RunDetails } from '@/api/types'
import { appSummary, asText, deviceSummary, runKind, sections } from './runMeta'

const empty: RunDetails = { device: {}, app: {}, state: {}, trace: {}, sources: [] }
const run = { id: 81, ts: '2026-09-23T07:24:00+00:00', label: 'manual-session', path_kind: 'cold', derived: 1, device: 'V2514', app_pkg: 'com.swag.pay', analysis: null } as unknown as Run

describe('run summaries', () => {
  it('names the kind of run from how it was recorded', () => {
    expect(runKind(run)).toBe('Manual session')
    expect(runKind({ ...run, label: 'stress3-s07' })).toBe('Stress test #3, session 7')
    expect(runKind({ ...run, label: 'cold-capture' })).toBe('Dashboard capture')
    expect(runKind({ ...run, label: 'PR-4821' })).toBe('Label: PR-4821')
  })

  it('summarises the device as recorded, without repeating the maker', () => {
    expect(deviceSummary({ ...empty, device: { manufacturer: 'vivo', model: 'V2514', android_release: '16' } }, null)).toBe('vivo V2514 · Android 16')
    expect(deviceSummary({ ...empty, device: { manufacturer: 'Google', model: 'Google Pixel 8' } }, null)).toBe('Google Pixel 8')
    expect(deviceSummary(empty, 'V2514')).toBe('V2514')
  })

  it('says when the app version was not recorded', () => {
    expect(appSummary({ ...empty, app: { name: 'Swag Pay', version_name: '2.3.1', version_code: 231 } }, null)).toBe('Swag Pay 2.3.1 (231)')
    expect(appSummary(empty, 'Swag Pay')).toBe('Swag Pay · version not recorded')
  })
})

describe('run detail sections', () => {
  it('lists every field, leaving unrecorded ones empty for the list to mark', () => {
    const secs = sections(run, empty)
    expect(secs.map((s) => s.title)).toEqual(['Run', 'App', 'Device', 'Device state', 'Trace'])
    const app = secs.find((s) => s.title === 'App')!
    expect(app.items.find((i) => i.term === 'Build number')!.value).toBeUndefined()
  })

  it('copies only what was recorded', () => {
    const text = asText(run, { ...empty, app: { version_name: '2.3.1', version_code: 231 } })
    expect(text).toContain('Version: 2.3.1')
    expect(text).toContain('Build number: 231')
    expect(text).not.toContain('Git SHA')
  })
})

describe('iOS runs', () => {
  const ios = { ...run, platform: 'ios', simulator: true } as unknown as Run
  const details: RunDetails = {
    ...empty,
    device: { platform: 'ios', model: 'iPhone 17', os_version: '27.0', simulator: true },
    host: { chip: 'Apple M5 Pro', macos: '27.0' },
    state: { host_power: 'ac', host_load_1m: 1.13 },
  }

  it('summarises a simulator run with the Mac it ran on', () => {
    expect(deviceSummary(details, null)).toBe('iPhone 17 · iOS 27.0 · Simulator on Apple M5 Pro')
    expect(deviceSummary({ ...details, device: { platform: 'ios', model: 'iPhone 17 Pro', os_version: '27.0' }, host: {} }, null)).toBe('iPhone 17 Pro · iOS 27.0')
  })

  it("lists the Mac's state for a simulator run", () => {
    const secs = sections(ios, details)
    expect(secs.map((s) => s.title)).toEqual(['Run', 'App', 'Device', 'Device state', 'Mac', 'Trace'])
    const mac = secs.find((s) => s.title === 'Mac')!
    expect(mac.items.find((i) => i.term === 'Chip')!.value).toBe('Apple M5 Pro')
    expect(mac.items.find((i) => i.term === 'Power')!.value).toBe('Mains')
    expect(secs.find((s) => s.title === 'Run')!.items.find((i) => i.term === 'Steps from')!.value).toContain('iOS')
  })
})

