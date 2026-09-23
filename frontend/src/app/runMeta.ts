import type { Run } from '@/api/types'
import { pathLabel, shortDate } from '@/domain/format'

/** The two lines that identify a run in a page header: what ran where, then
 *  the build and when. */
export function runMetaLines(run: Run | null): [string, string] | null {
  if (!run) return null
  const build = run.app_version ?? run.git_sha?.slice(0, 7) ?? run.label ?? 'no build recorded'
  return [
    `Run #${run.id} · ${run.device ?? 'unknown device'} · ${pathLabel(run.path_kind)}${/^(cold|warm)$/.test(run.path_kind) ? ' start' : ''}`,
    `${build} · ${shortDate(run.ts, true)}`,
  ]
}
