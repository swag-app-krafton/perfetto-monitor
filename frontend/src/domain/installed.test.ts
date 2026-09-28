import { describe, expect, it } from 'vitest'
import { searchApps } from './installed'

const apps = [
  { pkg: 'com.phonepe.app', name: 'PhonePe' },
  { pkg: 'money.super.payments', name: 'super.money' },
  { pkg: 'com.swag.pay', name: 'Swag Pay' },
  { pkg: 'com.zzz.nameless', name: 'com.zzz.nameless' },
]

describe('searching installed apps', () => {
  it('finds an app by the name the phone shows, in any case', () => {
    expect(searchApps(apps, 'PHONEPE').map((a) => a.pkg)).toEqual(['com.phonepe.app'])
  })

  it('finds an app by its package id', () => {
    expect(searchApps(apps, 'money.super').map((a) => a.pkg)).toEqual(['money.super.payments'])
  })

  it('matches every word typed, in any order', () => {
    expect(searchApps(apps, 'pay swag').map((a) => a.pkg)).toEqual(['com.swag.pay'])
  })

  it('lists everything for an empty search, up to the limit', () => {
    expect(searchApps(apps, '  ')).toHaveLength(4)
    expect(searchApps(apps, '', 2)).toHaveLength(2)
  })
})
