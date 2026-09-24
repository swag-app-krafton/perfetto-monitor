import { describe, expect, it } from 'vitest'
import { lanePath, toLane } from './profiler'
import { homeOf, screenByPath, screensFor } from './routes'

describe('lanes', () => {
  it('gives the iOS lane the trace screens under /ios, without manual sessions', () => {
    const ios = screensFor('ios')
    expect(ios.map((x) => x.page)).toEqual(screensFor('perfetto').filter((x) => x.id !== 'manual').map((x) => x.id))
    expect(ios.every((x) => x.path.startsWith('/ios/'))).toBe(true)
    expect(homeOf('ios')).toBe('/ios/overview')
    expect(screenByPath('/ios/memory').profiler).toBe('ios')
    expect(screenByPath('/memory').profiler).toBe('perfetto')
  })

  it('keeps links in the lane in view', () => {
    expect(lanePath('ios', '/steps?focus=step:pre_main')).toBe('/ios/steps?focus=step:pre_main')
    expect(lanePath('ios', '/ios/history')).toBe('/ios/history')
    expect(lanePath('ios', '/flashlight/audits')).toBe('/flashlight/audits')
    expect(lanePath('perfetto', '/history')).toBe('/history')
    expect(toLane('/ios/memory', 'perfetto')).toBe('/memory')
    expect(toLane('/memory', 'ios')).toBe('/ios/memory')
  })
})
