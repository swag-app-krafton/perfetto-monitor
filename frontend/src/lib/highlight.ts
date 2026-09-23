import { useEffect } from 'react'
import { useLocation } from 'react-router'

export const HIGHLIGHT_MS = 2800
const OFFSET = 96

/** Link target for "go to X on screen Y and ring it": `/steps?focus=step:foo`.
 *  Screens mark targets with `data-hl="<id>"`; screens that need to *open*
 *  something first (a step's drill-down) read `focus` themselves. */
export const focusHref = (path: string, id: string) => `${path}?focus=${encodeURIComponent(id)}`

export function useFocusParam(): string | null {
  const { search } = useLocation()
  return new URLSearchParams(search).get('focus')
}

/** Scrolls the focused element into view and rings it. Retries briefly, since
 *  the target may render only after its data arrives. */
export function useHighlightTarget(scroller: () => HTMLElement | null) {
  const focus = useFocusParam()
  const { key } = useLocation()
  useEffect(() => {
    if (!focus) return
    let tries = 0
    let clear: ReturnType<typeof setTimeout> | undefined
    const tick = setInterval(() => {
      const el = document.querySelector<HTMLElement>(`[data-hl="${CSS.escape(focus)}"]`)
      const main = scroller()
      if (!el || !main) {
        if (++tries > 40) clearInterval(tick)
        return
      }
      clearInterval(tick)
      const top = el.getBoundingClientRect().top - main.getBoundingClientRect().top + main.scrollTop - OFFSET
      main.scrollTo({ top, behavior: 'smooth' })
      el.classList.add('sp-highlight')
      clear = setTimeout(() => el.classList.remove('sp-highlight'), HIGHLIGHT_MS)
    }, 100)
    return () => {
      clearInterval(tick)
      if (clear) clearTimeout(clear)
    }
  }, [focus, key, scroller])
}
