import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type Theme = 'dark' | 'light'
export type RangeKey = '30' | '10' | '7d'
/** Which profiler's runs are in view. The two never run together on a device,
 *  and their numbers are never compared, so everything below it follows it. */
export type Profiler = 'perfetto' | 'flashlight'

interface UiState {
  theme: Theme
  /** User's explicit rail choice; the effective rail also depends on the
   *  Copilot and the viewport (see useLayout). */
  railPinned: boolean
  drawerOpen: boolean
  profiler: Profiler
  /** Package name; '' until the data picks a default (the newest run's). */
  app: string
  /** A path_kind from the data ('cold', 'warm', 'returning_user', ...). */
  path: string
  range: RangeKey
  /** An app build (see domain/versions); '' is every version. */
  version: string
  /** The run in view on every screen; null follows the newest run in scope. */
  runId: number | null
  /** The Flashlight audit in view; null follows the app's newest audit. */
  auditId: number | null
  copilot: { open: boolean; maximised: boolean; width: number }
  /** A prompt a page asked the Copilot to send ("Ask Copilot why"). */
  copilotPrompt: { id: number; text: string } | null
  toast: { id: number; text: string } | null

  setTheme: (t: Theme) => void
  toggleTheme: () => void
  toggleRail: () => void
  setDrawer: (open: boolean) => void
  setFilters: (f: Partial<Pick<UiState, 'app' | 'path' | 'range' | 'version'>>) => void
  setRunId: (id: number | null) => void
  setProfiler: (p: Profiler) => void
  setAuditId: (id: number | null) => void
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
      profiler: 'perfetto',
      app: '',
      path: '',
      range: '30',
      version: '',
      runId: null,
      auditId: null,
      copilot: { open: false, maximised: false, width: 400 },
      toast: null,
      copilotPrompt: null,

      setTheme: (theme) => set({ theme }),
      toggleTheme: () => set((s) => ({ theme: s.theme === 'dark' ? 'light' : 'dark' })),
      toggleRail: () => set((s) => ({ railPinned: !s.railPinned })),
      setDrawer: (drawerOpen) => set({ drawerOpen }),
      // A different app, path or version has different runs: go back to its
      // newest. A different app has different versions too.
      setFilters: (f) =>
        set((s) => {
          const appChanged = f.app !== undefined && f.app !== s.app
          const changed = appChanged || (f.path !== undefined && f.path !== s.path) || (f.version !== undefined && f.version !== s.version)
          return {
            ...f,
            version: appChanged ? (f.version ?? '') : (f.version ?? s.version),
            runId: changed ? null : s.runId,
            auditId: appChanged ? null : s.auditId,
          }
        }),
      setRunId: (runId) => set({ runId }),
      setProfiler: (profiler) => set({ profiler }),
      setAuditId: (auditId) => set({ auditId }),
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
        profiler: s.profiler,
        app: s.app,
        path: s.path,
        range: s.range,
        copilot: { ...s.copilot, open: false },
      }),
    },
  ),
)
