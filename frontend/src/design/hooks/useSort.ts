import { useMemo, useState } from 'react'

export type SortDir = 'asc' | 'desc'

/** Sortable rows. Clicking the active column flips it; a new column starts
 *  descending (the largest value is usually what a reader is looking for).
 *  Nulls always sort last, in either direction. */
export function useSort<T, K extends string>(
  rows: T[],
  get: (row: T, key: K) => number | string | null,
  // NoInfer: the key type comes from `get`, not from whichever key starts active.
  initial: { key: NoInfer<K>; dir: SortDir },
) {
  const [sort, setSort] = useState(initial)
  const sorted = useMemo(() => {
    const sign = sort.dir === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => {
      const x = get(a, sort.key)
      const y = get(b, sort.key)
      if (x == null && y == null) return 0
      if (x == null) return 1
      if (y == null) return -1
      return (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y))) * sign
    })
  }, [rows, get, sort])
  const toggle = (key: K) => setSort((s) => (s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'desc' }))
  return { sorted, sort, toggle }
}
