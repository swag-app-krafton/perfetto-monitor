import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { keys, manualAbort, manualStart, manualStop, useDevice, useJob, useLiveMarkers, useManualStatus, useRecentJobs } from '@/api/hooks'
import type { DevicePayload, LiveEvent } from '@/api/types'
import { Banner, Button, Card, EmptyState, Grid, LogConsole, Segmented, SelectField, Spinner, StatusPill, Stepper } from '@/design/components'
import { useUi } from '@/app/store'

const KINDS: { kind: LiveEvent['kind']; label: string; color: string }[] = [
  { kind: 'screen', label: 'Screens', color: 'var(--c1)' },
  { kind: 'action', label: 'Actions', color: 'var(--c2)' },
  { kind: 'nav', label: 'Navigations', color: 'var(--c3)' },
  { kind: 'step', label: 'Steps', color: 'var(--c4)' },
]
const START_KEY = 'swagperf-manual-started'

function useElapsed(since: number | null) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (!since) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [since])
  return since ? Math.max(0, Math.floor((now - since) / 1000)) : null
}

export function ManualPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { app, setFilters } = useUi()
  const status = useManualStatus(true)
  const dev = useDevice()
  const recording = !!status.data?.recording
  const live = useLiveMarkers(recording)
  const recent = useRecentJobs()
  const [pkg, setPkg] = useState<string | null>(null)
  const [cold, setCold] = useState(true)
  const [jobId, setJobId] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [kinds, setKinds] = useState<Set<LiveEvent['kind']>>(new Set(KINDS.map((k) => k.kind)))
  const [since, setSince] = useState<number | null>(() => Number(sessionStorage.getItem(START_KEY)) || null)
  const elapsed = useElapsed(recording ? since : null)

  const resumed = recent.data?.find((j) => j.kind === 'manual_stop' && (j.state === 'running' || j.state === 'queued'))
  const job = useJob(jobId ?? resumed?.id ?? null).data
  const analysing = job?.state === 'queued' || job?.state === 'running'
  const result = job?.state === 'done' ? (job.result as { run_id?: number; verdict?: string; headline?: string; screens?: number; path_kind?: string; app_pkg?: string }) : null
  const phase = recording ? 'tracing' : analysing ? 'analysing' : result ? 'done' : 'idle'

  const d = dev.data?.connected ? (dev.data as Extract<DevicePayload, { connected: true }>) : null
  const installed = useMemo(() => (d?.packages ?? []).filter((p) => p.installed), [d])
  const target = pkg ?? (installed.some((p) => p.pkg === app) ? app : (installed.find((p) => p.role === 'own')?.pkg ?? installed[0]?.pkg ?? ''))

  const start = async () => {
    setErr(null)
    setBusy(true)
    try {
      await manualStart({ pkg: target, cold })
      const t = Date.now()
      sessionStorage.setItem(START_KEY, String(t))
      setSince(t)
      setJobId(null)
      await qc.invalidateQueries({ queryKey: keys.manualStatus })
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const stop = async () => {
    setErr(null)
    setBusy(true)
    try {
      const r = await manualStop({ pkg: target })
      setJobId(r.job_id)
      sessionStorage.removeItem(START_KEY)
      setSince(null)
      await qc.invalidateQueries({ queryKey: keys.manualStatus })
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const discard = async () => {
    await manualAbort()
    sessionStorage.removeItem(START_KEY)
    setSince(null)
    qc.invalidateQueries({ queryKey: keys.manualStatus })
  }

  const stepState = (i: number) => {
    const at = phase === 'idle' ? 0 : phase === 'tracing' ? 1 : phase === 'analysing' ? 2 : 3
    return i < at ? 'done' : i === at ? 'active' : 'pending'
  }
  const events = (live.data?.events ?? []).filter((e) => kinds.has(e.kind)).slice().reverse()
  const counts = live.data?.counts ?? {}
  const mmss = elapsed == null ? '--:--' : `${String(Math.floor(elapsed / 60)).padStart(2, '0')}:${String(elapsed % 60).padStart(2, '0')}`

  return (
    <Grid min={440}>
      <Card style={{ display: 'flex', flexDirection: 'column', gap: 20, alignSelf: 'start' }}>
        <Stepper
          steps={['Start tracing', 'Use the app', 'Stop & analyse'].map((label, i) => ({ label, state: stepState(i) as 'done' | 'active' | 'pending' }))}
        />
        {!status.data?.device ? (
          <EmptyState title="No device connected" actions={<Button variant="primary" onClick={() => { status.refetch(); dev.refetch() }}>Check again</Button>}>
            Connect a device over USB with debugging enabled.
          </EmptyState>
        ) : phase === 'tracing' ? (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, font: '600 12px var(--font-ui)', letterSpacing: '.14em', color: 'var(--fail)' }}>
              <span className="sp-pulse" style={{ width: 10, height: 10, borderRadius: '50%', background: 'var(--fail)', animation: 'sp-pulse 1.2s ease-in-out infinite' }} />
              RECORDING
            </div>
            <div style={{ font: '800 64px/1 var(--font-display)', letterSpacing: '-.02em' }} aria-live="off">
              {mmss}
            </div>
            <div style={{ fontSize: 13, color: 'var(--tx2)' }}>Drive the app on the device now. Stop when you are done and the trace is pulled, analysed and recorded.</div>
            <div style={{ display: 'flex', gap: 8 }}>
              <Button onClick={stop} disabled={busy} style={{ background: 'var(--tx)', color: 'var(--bg)', border: 0 }}>
                <span style={{ width: 10, height: 10, background: 'var(--accent)' }} /> Stop &amp; analyse
              </Button>
              <Button variant="mini" onClick={discard} disabled={busy} style={{ alignSelf: 'center' }}>
                Discard
              </Button>
            </div>
          </>
        ) : phase === 'analysing' ? (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 14 }}>
              <Spinner size={18} /> Analysing trace…
            </div>
            {job && <LogConsole lines={job.log} running label="Analysis log" />}
          </>
        ) : (
          <>
            {phase === 'done' && result?.run_id != null && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10, paddingBottom: 16, borderBottom: '1px solid var(--line)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <StatusPill tone={result.verdict === 'pass' ? 'pass' : result.verdict === 'fail' ? 'fail' : 'warn'} />
                  <span style={{ font: '700 16px var(--font-display)' }}>Run #{result.run_id} analysed</span>
                </div>
                <div style={{ fontSize: 13, color: 'var(--tx2)' }}>
                  {result.headline} {result.screens ? `· ${result.screens} screen visit${result.screens === 1 ? '' : 's'}` : '· no screen markers'}
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <Button
                    variant="primary"
                    onClick={() => {
                      if (result.app_pkg || result.path_kind) setFilters({ app: result.app_pkg ?? app, path: result.path_kind ?? '' })
                      qc.invalidateQueries({ queryKey: keys.history })
                      navigate(result.screens ? `/screens?run=${result.run_id}` : `/overview?run=${result.run_id}`)
                    }}
                  >
                    Open run #{result.run_id}
                  </Button>
                  <Button onClick={() => setJobId(null)}>New session</Button>
                </div>
              </div>
            )}
            <div style={{ font: '800 22px var(--font-display)' }}>Trace any session</div>
            <div style={{ fontSize: 13, color: 'var(--tx2)', lineHeight: 1.6 }}>
              Tracing runs as a detached session with no fixed duration: use the app however you need to -- a real payment, a biometric unlock, a sequence no
              script reproduces -- then stop. Cold force-stops and relaunches the app so the launch is measured too.
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {installed.length > 0 && (
                <SelectField label="App" value={target} options={installed.map((p) => ({ value: p.pkg, label: p.name + (p.role === 'own' ? ' · ours' : '') }))} onChange={setPkg} />
              )}
              <Segmented label="Start" value={cold ? 'cold' : 'warm'} onChange={(v) => setCold(v === 'cold')} options={[{ value: 'cold', label: 'Cold' }, { value: 'warm', label: 'Warm' }]} />
            </div>
            <Button variant="primary" large onClick={start} disabled={busy || !target}>
              Start tracing
            </Button>
          </>
        )}
        {err && (
          <Banner tone="fail" title="Something went wrong">
            {err}
          </Banner>
        )}
        {job?.state === 'error' && (
          <Banner tone="fail" title="Analysis failed">
            {job.error}
          </Banner>
        )}
      </Card>

      <Card title="Live markers" hint="Screens, actions, navigations and steps as the app emits them, newest first. A screen marked open is the one on display now.">
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 14 }}>
          {KINDS.map((k) => {
            const on = kinds.has(k.kind)
            return (
              <button
                key={k.kind}
                type="button"
                aria-pressed={on}
                onClick={() =>
                  setKinds((s) => {
                    const n = new Set(s)
                    // Never let the filter empty out: a blank list would read as "no markers".
                    if (on && n.size > 1) n.delete(k.kind)
                    else n.add(k.kind)
                    return n
                  })
                }
                style={{ display: 'flex', alignItems: 'center', gap: 8, height: 26, padding: '0 11px', borderRadius: 999, border: '1px solid var(--line2)', background: 'transparent', color: 'var(--tx2)', font: '500 12px var(--font-ui)', cursor: 'pointer', opacity: on ? 1 : 0.4 }}
              >
                <span style={{ width: 10, height: 10, background: k.color }} />
                {k.label} {counts[k.kind] ?? 0}
              </button>
            )
          })}
          {live.data?.current_screen && (
            <StatusPill tone="pass">
              on {live.data.current_screen}
              {live.data.current_screen_kind ? ` · ${live.data.current_screen_kind}` : ''}
            </StatusPill>
          )}
        </div>
        {live.data?.note && <div style={{ fontSize: 12, color: 'var(--warn)', marginBottom: 8 }}>{live.data.note}</div>}
        {live.data?.mode && <div style={{ fontSize: 12, color: 'var(--tx3)', marginBottom: 8 }}>This phone does not serve partial reads, so updates slow down as the session grows.</div>}
        <div aria-live="polite" style={{ maxHeight: 520, overflowY: 'auto' }}>
          {!recording ? (
            <EmptyState>Markers appear here while a session records.</EmptyState>
          ) : events.length === 0 ? (
            <EmptyState>{live.isLoading ? 'Waiting for the first markers…' : 'No markers yet. Drive the app to produce some.'}</EmptyState>
          ) : (
            events.slice(0, 300).map((e, i) => {
              const k = KINDS.find((x) => x.kind === e.kind)!
              return (
                <div key={`${e.kind}${e.at_ms}${i}`} style={{ display: 'grid', gridTemplateColumns: '64px 110px 1fr auto', gap: 10, alignItems: 'center', padding: '8px 0', borderTop: '1px solid var(--line)', fontSize: 13 }}>
                  <span style={{ color: 'var(--tx3)', fontSize: 12 }}>{(e.at_ms / 1000).toFixed(1)}s</span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--tx2)' }}>
                    <span style={{ width: 10, height: 10, background: k.color }} />
                    {e.kind}
                    {e.screen_kind_label ? ` · ${e.screen_kind_label}` : ''}
                  </span>
                  <span style={{ fontWeight: 500, overflowWrap: 'anywhere' }}>
                    {e.step ? '↳ ' : ''}
                    {e.name}
                  </span>
                  <span style={{ fontSize: 12, color: e.open_ended ? 'var(--pass)' : 'var(--tx3)' }}>{e.open_ended ? 'open' : e.duration_ms != null ? `${e.duration_ms.toFixed(0)} ms` : ''}</span>
                </div>
              )
            })
          )}
        </div>
      </Card>
    </Grid>
  )
}
