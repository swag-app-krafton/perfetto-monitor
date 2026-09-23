import { describe, expect, it } from 'vitest'
import type { Audit } from '@/api/types'
import { auditApps, auditInView, auditLabel, scopeAudits } from './audits'

const audit = (id: number, over: Partial<Audit> = {}): Audit => ({
  id,
  ts: `2026-09-23T10:0${id}:00+00:00`,
  app_pkg: 'com.swag.pay',
  app_name: 'Swag Pay',
  app_role: 'own',
  device: 'V2514',
  label: null,
  iterations: 5,
  duration_ms: 10000,
  state: 'done',
  error: null,
  finished: null,
  results_path: null,
  flashlight_version: null,
  score: 90,
  cpu_pct: 40,
  ram_mb: 400,
  fps: 55,
  meta: null,
  summary: null,
  ...over,
})

describe('audits', () => {
  it('labels audits apart from Perfetto runs', () => {
    expect(auditLabel({ id: 3 })).toBe('A-3')
  })

  it('lists the own app first, then by audit count', () => {
    const apps = auditApps([
      audit(1, { app_pkg: 'com.rival', app_name: 'Rival', app_role: 'competitor' }),
      audit(2, { app_pkg: 'com.rival', app_name: 'Rival', app_role: 'competitor' }),
      audit(3),
    ])
    expect(apps.map((a) => [a.pkg, a.audits])).toEqual([
      ['com.swag.pay', 1],
      ['com.rival', 2],
    ])
  })

  it('shows the picked audit, else the newest finished one', () => {
    const list = [audit(3, { state: 'running' }), audit(2), audit(1)]
    expect(auditInView(list, 1)?.id).toBe(1)
    expect(auditInView(list, null)?.id).toBe(2)
    expect(auditInView([audit(4, { state: 'error' })], null)?.id).toBe(4)
    expect(auditInView([], null)).toBeNull()
  })

  it('falls back to an app that has audits when the chosen one has none', () => {
    const s = scopeAudits([audit(1, { app_pkg: 'com.rival', app_name: 'Rival', app_role: 'competitor' })], 'com.swag.pay', null, null)
    expect(s.app).toBe('com.rival')
    expect(s.audit?.id).toBe(1)
    expect(s.following).toBe(true)
  })

  it('ignores a picked audit that belongs to another app', () => {
    const s = scopeAudits([audit(1), audit(2, { app_pkg: 'com.rival' })], 'com.swag.pay', 2, null)
    expect(s.audit?.id).toBe(1)
    expect(s.following).toBe(true)
  })
})
