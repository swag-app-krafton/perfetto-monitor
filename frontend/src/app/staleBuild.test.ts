import { describe, expect, it } from 'vitest'
import { isStaleChunkError, reloadForNewBuild, withNewBuild } from './staleBuild'

const fakes = (start = 1_000_000) => {
  const store = new Map<string, string>()
  const env = {
    now: () => env.t,
    t: start,
    reloads: 0,
    storage: { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) },
    reload: () => void env.reloads++,
  }
  return env
}

const chrome = new TypeError('Failed to fetch dynamically imported module: http://127.0.0.1:8787/assets/ScreensPage-VaMXX1kI.js')

describe('a tab left open across a dashboard rebuild', () => {
  it('recognises a missing page file in each browser', () => {
    expect(isStaleChunkError(chrome)).toBe(true)
    expect(isStaleChunkError(new TypeError('Importing a module script failed.'))).toBe(true)
    expect(isStaleChunkError(new TypeError('error loading dynamically imported module'))).toBe(true)
    expect(isStaleChunkError(new TypeError("Cannot read properties of undefined (reading 'x')"))).toBe(false)
  })

  it('reloads once to pick up the new build, then shows the error if it happens again', () => {
    const env = fakes()
    expect(reloadForNewBuild(chrome, env)).toBe(true)
    expect(env.reloads).toBe(1)
    env.t += 5_000
    expect(reloadForNewBuild(chrome, env)).toBe(false)
    expect(env.reloads).toBe(1)
    env.t += 60_000
    expect(reloadForNewBuild(chrome, env)).toBe(true)
  })

  it('never reloads for any other error', () => {
    const env = fakes()
    expect(reloadForNewBuild(new Error('boom'), env)).toBe(false)
    expect(env.reloads).toBe(0)
  })

  it('passes a page through, and any other error on', async () => {
    const env = fakes()
    await expect(withNewBuild(() => Promise.resolve('page'), env)()).resolves.toBe('page')
    await expect(withNewBuild(() => Promise.reject(new Error('boom')), env)()).rejects.toThrow('boom')
    expect(env.reloads).toBe(0)
  })
})
