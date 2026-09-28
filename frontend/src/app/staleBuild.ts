/** A tab opened before the dashboard was rebuilt still runs the old app, and
 *  the rebuild deleted the old app's page files. The first visit to a page
 *  then fails with "Failed to fetch dynamically imported module" (B-012).
 *  Reloading picks up the new build; index.html is served no-store. A reload
 *  within the last 30 s means the file is really missing, so the error shows
 *  instead of reloading in a loop. */
const KEY = 'swagperf-new-build-reload'
const WINDOW_MS = 30_000

interface Env {
  now: () => number
  storage: Pick<Storage, 'getItem' | 'setItem'>
  reload: () => void
}

const browser = (): Env => ({ now: Date.now, storage: sessionStorage, reload: () => window.location.reload() })

/** Chrome, Safari and Firefox word a missing module differently. */
export const isStaleChunkError = (e: unknown) =>
  /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module/i.test(
    String(e instanceof Error ? e.message : e),
  )

export function reloadForNewBuild(e: unknown, env: Env = browser()): boolean {
  if (!isStaleChunkError(e)) return false
  let last = 0
  try {
    last = Number(env.storage.getItem(KEY)) || 0
  } catch {
    // storage blocked: still reload once, the window guard is best effort
  }
  if (env.now() - last < WINDOW_MS) return false
  try {
    env.storage.setItem(KEY, String(env.now()))
  } catch {
    // as above
  }
  env.reload()
  return true
}

/** A page loader that reloads the tab for a newer build instead of failing. */
export const withNewBuild =
  <T,>(load: () => Promise<T>, env?: Env) =>
  () =>
    load().catch((e: unknown) => {
      if (reloadForNewBuild(e, env)) return new Promise<T>(() => {}) // the reload replaces the page
      throw e
    })
