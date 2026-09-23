import type { ReactNode } from 'react'
import { Eyebrow } from '@/design/components'
import { pathLabel, shortDate } from '@/domain/format'
import type { Run } from '@/api/types'
import s from './Shell.module.css'

export function runMetaLines(run: Run | null): [string, string] | null {
  if (!run) return null
  const build = run.app_version ?? run.git_sha?.slice(0, 7) ?? run.label ?? 'no build recorded'
  return [
    `Run #${run.id} · ${run.device ?? 'unknown device'} · ${pathLabel(run.path_kind)}${/^(cold|warm)$/.test(run.path_kind) ? ' start' : ''}`,
    `${build} · ${shortDate(run.ts, true)}`,
  ]
}

export function PageHeader({ group, title, hint, run, aside }: { group: string; title: string; hint: string; run: Run | null; aside?: ReactNode }) {
  const meta = runMetaLines(run)
  return (
    <div className={s.header}>
      <div style={{ minWidth: 0 }}>
        <Eyebrow>{group}</Eyebrow>
        <h1 className={s.h1}>{title}</h1>
        <p className={s.hint}>{hint}</p>
      </div>
      {aside ??
        (meta && (
          <div className={s.runMeta}>
            {meta[0]}
            <br />
            {meta[1]}
          </div>
        ))}
    </div>
  )
}
