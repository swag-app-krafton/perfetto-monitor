import { useCallback, useState, type KeyboardEvent } from 'react'

/** Keyboard movement through a list of `count` options: ↑/↓ move (wrapping),
 *  Home/End jump, Enter picks, Escape closes. Returns `true` from `onKeyDown`
 *  when it handled the key, so a text field can let the rest through. */
export function useListNav(count: number, { onPick, onClose }: { onPick: (i: number) => void; onClose?: () => void }) {
  const [cursor, setActive] = useState(0)
  // A shorter list (a narrower @query) must not leave the cursor past its end.
  const active = count === 0 ? 0 : Math.min(cursor, count - 1)

  const onKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape' && onClose) {
        e.preventDefault()
        onClose()
        return true
      }
      if (count === 0) return false
      const moves: Record<string, (a: number) => number> = {
        ArrowDown: (a) => (a + 1) % count,
        ArrowUp: (a) => (a - 1 + count) % count,
        Home: () => 0,
        End: () => count - 1,
      }
      const move = moves[e.key]
      if (move) {
        e.preventDefault()
        setActive(move(active))
        return true
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault()
        onPick(active)
        return true
      }
      return false
    },
    [count, active, onPick, onClose],
  )
  return { active, setActive, onKeyDown }
}
