import { useEffect } from 'react'
import { useUi } from '@/app/store'

/** Bottom-centre, inverted, auto-hides after 2.4s. Driven by useUi().showToast. */
export function Toast() {
  const toast = useUi((s) => s.toast)
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => useUi.setState({ toast: null }), 2400)
    return () => clearTimeout(t)
  }, [toast])
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: 'fixed',
        left: '50%',
        bottom: 28,
        transform: 'translateX(-50%)',
        zIndex: 300,
        pointerEvents: 'none',
      }}
    >
      {toast && (
        <div
          style={{
            padding: '10px 16px',
            background: 'var(--tx)',
            color: 'var(--bg)',
            font: '500 13px var(--font-ui)',
            borderRadius: 4,
            boxShadow: 'var(--shadow)',
          }}
        >
          {toast.text}
        </div>
      )}
    </div>
  )
}
