import { useEffect } from 'react'
import { useUi } from './store'

/** Puts the chosen theme on <html>, where the colour tokens are scoped. */
export function useApplyTheme() {
  const theme = useUi((s) => s.theme)
  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])
}
