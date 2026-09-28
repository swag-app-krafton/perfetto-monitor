/** Search over the apps installed on the device, by the name the phone
 *  shows (F-031) or the package id: every word typed must match, in any
 *  order and any case. */
export function searchApps<T extends { pkg: string; name: string }>(apps: T[], q: string, limit = 80): T[] {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean)
  return apps.filter((a) => words.every((w) => `${a.name} ${a.pkg}`.toLowerCase().includes(w))).slice(0, limit)
}
