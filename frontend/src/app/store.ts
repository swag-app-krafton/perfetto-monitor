import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type Theme = 'dark' | 'light'
export type RangeKey = '30' | '10' | '7d'

interface UiState {
  theme: Theme
  /** User's explicit rail choice; the effective rail also depends on the
   *  Copilot and the viewport (see useLayout). */
  railPinned: boolean
  drawerOpen: boolean
  /** Package name; '' until the data picks a default (the newest run's). */
  app: string
  /** A path_kind from the data ('cold', 'warm', 'returning_user', ...). */
  path: string
  range: RangeKey
  copilot: { open: boolean; maximised: boolean; width: number }
  /** A prompt a page asked the Copilot to send ("Ask Copilot why"). */
  copilotPrompt: { id: number; text: string } | null
  toast: { id: number; text: string } | null

  setTheme: (t: Theme) => void
  toggleTheme: () => void
  toggleRail: () => void
  setDrawer: (open: boolean) => void
  setFilters: (f: Partial<Pick<UiState, 'app' | 'path' | 'range'>>) => void
  setCopilot: (c: Partial<UiState['copilot']>) => void
  showToast: (text: string) => void
  askCopilot: (text: string) => void
}

export const COPILOT_MIN = 340
export const COPILOT_MAX = 720

export const useUi = create<UiState>()(
  persist(
    (set) => ({
      theme: 'dark',
      railPinned: false,
      drawerOpen: false,
      app: '',
      path: '',
      range: '30',
      copilot: { open: false, maximised: false, width: 400 },
      toast: null,
      copilotPrompt: null,

      setTheme: (theme) => set({ theme }),
      toggleTheme: () => set((s) => ({ theme: s.theme === 'dark' ? 'light' : 'dark' })),
      toggleRail: () => set((s) => ({ railPinned: !s.railPinned })),
      setDrawer: (drawerOpen) => set({ drawerOpen }),
      setFilters: (f) => set(f),
      setCopilot: (c) =>
        set((s) => {
          const next = { ...s.copilot, ...c }
          next.width = Math.min(COPILOT_MAX, Math.max(COPILOT_MIN, next.width))
          return { copilot: next }
        }),
      showToast: (text) => set({ toast: { id: Date.now(), text } }),
      askCopilot: (text) =>
        set((s) => ({ copilot: { ...s.copilot, open: true }, copilotPrompt: { id: Date.now(), text } })),
    }),
    {
      name: 'swagperf-ui',
      // Only durable preferences persist; transient UI (drawer, toast) does not.
      partialize: (s) => ({
        theme: s.theme,
        railPinned: s.railPinned,
        app: s.app,
        path: s.path,
        range: s.range,
        copilot: { ...s.copilot, open: false },
      }),
    },
  ),
)
