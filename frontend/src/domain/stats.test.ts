import { compareSamples, mannWhitney, quartiles } from './stats'

describe('stats', () => {
  it('quartiles interpolate', () => {
    expect(quartiles([1, 2, 3, 4, 5])).toMatchObject({ q1: 2, median: 3, q3: 4, min: 1, max: 5 })
  })

  it('Mann-Whitney separates clearly different samples and not identical ones', () => {
    const a = [300, 302, 305, 298, 301, 303, 299, 304, 300, 302]
    const b = a.map((x) => x + 40)
    expect(mannWhitney(a, b)!.p).toBeLessThan(0.001)
    expect(mannWhitney(a, [...a])!.p).toBeGreaterThan(0.9)
    expect(mannWhitney([1], [2, 3])).toBeNull()
  })

  it('calls a real shift a regression, and a tiny significant one noise', () => {
    const base = [300, 310, 305, 295, 302, 308, 298, 304, 301, 306]
    expect(compareSamples(base.map((x) => x + 60), base).verdict).toBe('regression')
    expect(compareSamples(base.map((x) => x - 60), base).verdict).toBe('improvement')
    // +2ms on everything: detectable, but well inside the baseline's IQR.
    expect(compareSamples(base.map((x) => x + 2), base).verdict).toBe('noise')
  })

  it('flags small samples as low confidence', () => {
    expect(compareSamples([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]).lowConfidence).toBe(true)
  })
})
