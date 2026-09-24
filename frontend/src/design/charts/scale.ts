/** Axis scales shared by the charts. */

/** "Nice" ticks at 1/2/5 x 10^n: the largest such step that still puts at
 *  least three ticks in the range (the handoff asks for 3-4). */
export function niceTicks(lo: number, hi: number): number[] {
  const span = hi - lo || 1
  const pw = Math.pow(10, Math.floor(Math.log10(span)))
  const count = (st: number) => Math.floor(hi / st + 1e-9) - Math.ceil(lo / st - 1e-9) + 1
  const steps = [10, 5, 2, 1, 0.5, 0.2, 0.1].map((m) => m * pw)
  const step = steps.find((st) => count(st) >= 3) ?? steps[steps.length - 1]!
  const out: number[] = []
  for (let v = Math.ceil(lo / step - 1e-9) * step; v <= hi + 1e-9; v += step) out.push(Number(v.toPrecision(12)))
  return out
}

/** A scale from 0 rounded up to a whole tick past `maxVal` (plus a little
 *  headroom), so neither the longest bar nor a marker lands on the axis edge.
 *  The last tick is the scale's end. */
export function niceScale(maxVal: number, headroom = 1.02): { max: number; ticks: number[] } {
  const raw = niceTicks(0, maxVal)
  const step = raw.length > 1 ? raw[1]! - raw[0]! : maxVal
  const max = Number((step * Math.ceil((maxVal * headroom) / step)).toPrecision(12))
  return { max, ticks: raw.concat(raw.length && raw[raw.length - 1]! < max ? [max] : []) }
}
