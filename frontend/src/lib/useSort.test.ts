import { act, renderHook } from '@testing-library/react'
import { useSort } from './useSort'

type R = { n: string; v: number | null }
const rows: R[] = [{ n: 'a', v: 2 }, { n: 'b', v: null }, { n: 'c', v: 9 }]
const get = (r: R, k: 'n' | 'v') => r[k]

describe('useSort', () => {
  it('sorts, flips the active column, starts a new one descending, keeps nulls last', () => {
    const { result } = renderHook(() => useSort<R, 'n' | 'v'>(rows, get, { key: 'v', dir: 'desc' }))
    expect(result.current.sorted.map((r) => r.n)).toEqual(['c', 'a', 'b'])
    act(() => result.current.toggle('v'))
    expect(result.current.sorted.map((r) => r.n)).toEqual(['a', 'c', 'b'])
    act(() => result.current.toggle('n'))
    expect(result.current.sort).toEqual({ key: 'n', dir: 'desc' })
  })
})
