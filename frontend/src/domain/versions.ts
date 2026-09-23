import type { Run } from '@/api/types'

/** One build of the app, as the runs recorded it: a version name (2.3.1)
 *  and a build number (the Android versionCode, 231). */
export interface AppVersion {
  key: string
  name: string | null
  build: number | null
  runs: number
  /** The newest run of this build, which orders the list newest first. */
  newestId: number
}

export const NO_VERSION = 'unknown'

/** Capture-time metadata first, then the version passed on the command line. */
export function versionOf(r: Run): { name: string | null; build: number | null } {
  const a = r.meta?.app
  return { name: a?.version_name ?? r.app_version ?? null, build: a?.version_code ?? null }
}

export function versionKey(r: Run): string {
  const v = versionOf(r)
  return v.name == null && v.build == null ? NO_VERSION : `${v.name ?? ''}|${v.build ?? ''}`
}

export function versionLabel(v: { name: string | null; build: number | null }): string {
  if (v.name && v.build != null) return `${v.name} (build ${v.build})`
  if (v.name) return v.name
  if (v.build != null) return `build ${v.build}`
  return 'Version not recorded'
}

/** The builds among `runs`, newest first; runs with no version recorded are
 *  one group, listed last. */
export function versionsIn(runs: Run[]): AppVersion[] {
  const m = new Map<string, AppVersion>()
  for (const r of runs) {
    const key = versionKey(r)
    const v = m.get(key) ?? { key, ...versionOf(r), runs: 0, newestId: r.id }
    v.runs++
    v.newestId = Math.max(v.newestId, r.id)
    m.set(key, v)
  }
  return [...m.values()].sort((a, b) => Number(a.key === NO_VERSION) - Number(b.key === NO_VERSION) || b.newestId - a.newestId)
}
