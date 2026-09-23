import { useMemo } from 'react'
import { useAudits } from '@/api/hooks'
import type { Audit, RunnerStatus } from '@/api/types'
import { useUi } from '@/app/store'

/** Audits are numbered apart from Perfetto runs, so `A-3` can never be read as run #3. */
export const auditLabel = (a: Pick<Audit, 'id'>) => `A-${a.id}`

export interface AuditApp {
  pkg: string
  name: string
  own: boolean
  audits: number
}

/** Apps that have audits: the own app first, then by audit count. */
export function auditApps(audits: Audit[]): AuditApp[] {
  const m = new Map<string, AuditApp>()
  for (const a of audits) {
    const o = m.get(a.app_pkg) ?? { pkg: a.app_pkg, name: a.app_name || a.app_pkg, own: a.app_role === 'own', audits: 0 }
    o.audits++
    m.set(a.app_pkg, o)
  }
  return [...m.values()].sort((x, y) => Number(y.own) - Number(x.own) || y.audits - x.audits)
}

/** The audit to show: the one picked, else the app's newest finished audit,
 *  else its newest of any state (a running one, or one that failed). */
export function auditInView(appAudits: Audit[], auditId: number | null): Audit | null {
  if (auditId != null) {
    const picked = appAudits.find((a) => a.id === auditId)
    if (picked) return picked
  }
  const newestFirst = [...appAudits].sort((a, b) => b.id - a.id)
  return newestFirst.find((a) => a.state === 'done') ?? newestFirst[0] ?? null
}

export interface AuditScope {
  apps: AuditApp[]
  /** The app in view: the one chosen in the top bar when it has audits, else the first that does. */
  app: string
  /** That app's audits, newest first. */
  appAudits: Audit[]
  audit: Audit | null
  /** True when the audit in view is the app's newest, i.e. nothing is pinned. */
  following: boolean
  runner: RunnerStatus | null
}

export function scopeAudits(audits: Audit[], app: string, auditId: number | null, runner: RunnerStatus | null): AuditScope {
  const apps = auditApps(audits)
  const pkg = apps.some((a) => a.pkg === app) ? app : (apps[0]?.pkg ?? app)
  const appAudits = audits.filter((a) => a.app_pkg === pkg).sort((a, b) => b.id - a.id)
  const audit = auditInView(appAudits, auditId)
  return { apps, app: pkg, appAudits, audit, following: auditId == null || audit?.id !== auditId, runner }
}

/** The Flashlight counterpart of useScope: what every Flashlight screen shows. */
export function useAuditScope(): { scope: AuditScope | null; isLoading: boolean } {
  const q = useAudits()
  const app = useUi((s) => s.app)
  const auditId = useUi((s) => s.auditId)
  const scope = useMemo(
    () => (q.data ? scopeAudits(q.data.audits, app, auditId, q.data.runner) : null),
    [q.data, app, auditId],
  )
  return { scope, isLoading: q.isLoading }
}
