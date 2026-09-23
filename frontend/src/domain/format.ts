/** Formatting helpers. Every number on screen goes through these so rounding
 *  and units stay consistent. */

export const fmt = (v: number | null | undefined, dp = 0) =>
  v == null || !Number.isFinite(v) ? '–' : v.toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp })

export const signed = (v: number, dp = 0, unit = '') => `${v > 0 ? '+' : v < 0 ? '−' : '±'}${fmt(Math.abs(v), dp)}${unit}`

export const pctChange = (cur: number, base: number) => (base ? ((cur - base) / base) * 100 : null)

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
export function shortDate(iso: string, withTime = false) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const base = `${MONTHS[d.getMonth()]} ${d.getDate()}`
  if (!withTime) return base
  return `${base}, ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

const PATH_LABEL: Record<string, string> = {
  cold: 'Cold',
  warm: 'Warm',
  returning_user: 'Returning user',
  first_run: 'First run',
}
export const pathLabel = (k: string | null | undefined) =>
  k ? (PATH_LABEL[k] ?? k.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())) : '–'

/** `step:bind_application` -> `bind_application`. */
export const stepName = (s: string) => s.replace(/^step:/, '')
