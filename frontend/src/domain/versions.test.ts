import { describe, expect, it } from 'vitest'
import type { Run } from '@/api/types'
import { NO_VERSION, versionKey, versionLabel, versionsIn } from './versions'

const run = (id: number, name?: string, build?: number, column?: string) =>
  ({ id, app_version: column ?? null, meta: { app: { version_name: name, version_code: build }, device: {}, state: {}, trace: {}, sources: [] } }) as unknown as Run

describe('app versions', () => {
  it('groups runs by version name and build number, newest build first', () => {
    const v = versionsIn([run(1, '2.3.0', 230), run(2, '2.3.1', 231), run(3, '2.3.1', 231), run(4)])
    expect(v.map((x) => [versionLabel(x), x.runs])).toEqual([
      ['2.3.1 (build 231)', 2],
      ['2.3.0 (build 230)', 1],
      ['Version not recorded', 1],
    ])
  })

  it('keeps two builds of one version name apart', () => {
    expect(versionKey(run(1, '2.3.1', 231))).not.toBe(versionKey(run(2, '2.3.1', 232)))
  })

  it('falls back to the version passed on the command line', () => {
    expect(versionKey(run(1, undefined, undefined, '2.2.0'))).toBe('2.2.0|')
    expect(versionKey(run(2))).toBe(NO_VERSION)
  })
})
