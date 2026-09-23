import type { Finding } from '@/api/types'

/** Which screen a finding is about, from what it names. */
export function findingArea(f: Finding): 'Startup' | 'Frames' | 'Memory' | 'Screens' | 'General' {
  const t = `${f.title} ${f.kind ?? ''} ${f.architectural_risk ?? ''}`.toLowerCase()
  if (/ram|memory|heap|rss|leak/.test(t)) return 'Memory'
  if (/frame|jank|drift|thermal|fps/.test(t)) return 'Frames'
  if (/screen|navigation/.test(t)) return 'Screens'
  if (/startup|ttid|ttff|step|launch|ordering|regress|camera/.test(t)) return 'Startup'
  return 'General'
}

export const findingId = (i: number) => `F-${i + 1}`

export function summariseSeverity(fs: Finding[]) {
  const n = (s: string) => fs.filter((f) => f.severity === s).length
  const parts = [`${fs.length} finding${fs.length === 1 ? '' : 's'}`]
  for (const s of ['high', 'medium', 'low']) if (n(s)) parts.push(`${n(s)} ${s}`)
  return parts.join(' · ')
}
