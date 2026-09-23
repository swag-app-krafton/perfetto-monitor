/** Small, dependency-free statistics for comparing two sets of timings. */

export function quartiles(xs: number[]) {
  const s = [...xs].sort((a, b) => a - b)
  const q = (p: number) => {
    if (!s.length) return NaN
    const k = (s.length - 1) * p
    const lo = Math.floor(k)
    const hi = Math.ceil(k)
    return s[lo]! + (s[hi]! - s[lo]!) * (k - lo)
  }
  return { min: s[0] ?? NaN, q1: q(0.25), median: q(0.5), q3: q(0.75), max: s[s.length - 1] ?? NaN, n: s.length }
}

/** Standard normal CDF (Abramowitz & Stegun 7.1.26), enough for p-values. */
function phi(z: number) {
  const t = 1 / (1 + 0.3275911 * Math.abs(z) / Math.SQRT2)
  const erf = 1 - ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-(z * z) / 2)
  return z >= 0 ? (1 + erf) / 2 : (1 - erf) / 2
}

/** Two-sided Mann-Whitney U test with the normal approximation and a tie
 *  correction. Rank-based, so it assumes nothing about the timings'
 *  distribution -- startup times are skewed, with a long slow tail. */
export function mannWhitney(a: number[], b: number[]): { u: number; p: number } | null {
  const n1 = a.length
  const n2 = b.length
  if (n1 < 2 || n2 < 2) return null
  const all = [...a.map((v) => ({ v, g: 0 })), ...b.map((v) => ({ v, g: 1 }))].sort((x, y) => x.v - y.v)
  const ranks = new Array<number>(all.length)
  let tieTerm = 0
  for (let i = 0; i < all.length; ) {
    let j = i
    while (j + 1 < all.length && all[j + 1]!.v === all[i]!.v) j++
    const r = (i + j + 2) / 2
    for (let k = i; k <= j; k++) ranks[k] = r
    const t = j - i + 1
    tieTerm += t * t * t - t
    i = j + 1
  }
  const r1 = all.reduce((acc, x, i) => (x.g === 0 ? acc + ranks[i]! : acc), 0)
  const u1 = r1 - (n1 * (n1 + 1)) / 2
  const u = Math.min(u1, n1 * n2 - u1)
  const n = n1 + n2
  const sd = Math.sqrt(((n1 * n2) / 12) * (n + 1 - tieTerm / (n * (n - 1))))
  if (sd === 0) return { u, p: 1 }
  const z = (Math.abs(u1 - (n1 * n2) / 2) - 0.5) / sd
  return { u, p: Math.min(1, 2 * (1 - phi(z))) }
}

export type ShiftVerdict = 'regression' | 'improvement' | 'noise'

/** Is `cur` really different from `base`? Needs both significance and a shift
 *  larger than the baseline's own spread (its IQR), so a statistically
 *  detectable 2ms move on a 300ms startup does not read as a regression. */
export function compareSamples(cur: number[], base: number[]) {
  const qc = quartiles(cur)
  const qb = quartiles(base)
  const shift = qc.median - qb.median
  const noise = Math.max(qb.q3 - qb.q1, 1e-9)
  const test = mannWhitney(cur, base)
  const real = test != null && test.p < 0.05 && Math.abs(shift) > noise
  const verdict: ShiftVerdict = !real ? 'noise' : shift > 0 ? 'regression' : 'improvement'
  return { verdict, shift, noiseMultiple: Math.abs(shift) / noise, p: test?.p ?? null, lowConfidence: Math.min(cur.length, base.length) < 10 }
}
