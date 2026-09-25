import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { keys, manualAbort, manualStart, manualStop, useDevice, useJob, useLiveMarkers, useManualStatus, useRecentJobs } from '@/api/hooks'
import type { DevicePayload, LiveEvent } from '@/api/types'
import { Banner, Button, Card, EmptyState, Grid, LogConsole, Row, Segmented, SelectField, Spinner, Stack, StatusPill, Stepper, Swatch, Switch, Text, ToggleChip } from '@/design'
import { useUi } from '@/app/store'
import s from './Manual.module.css'

const KINDS: { kind: LiveEvent['kind']; label: string; color: string }[] = [
  { kind: 'screen', label: 'Screens', color: 'var(--c1)' },
  { kind: 'action', label: 'Actions', color: 'var(--c2)' },
  { kind: 'nav', label: 'Navigations', color: 'var(--c3)' },
  { kind: 'step', label: 'Steps', color: 'var(--c4)' },
]
const START_KEY = 'swagperf-manual-started'

function useElapsed(since: number | null) {
  const [now, setNow] = useState(() => Date.now())
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
  const { app, setFilters, aiSummary, setAiSummary } = useUi()
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
      const r = await manualStop({ pkg: target, ai_summary: aiSummary })
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
      <Card className={s.sessionCard}>
        <Stack gap={20}>
          <Stepper
            steps={['Start tracing', 'Use the app', 'Stop & analyse'].map((label, i) => ({ label, state: stepState(i) as 'done' | 'active' | 'pending' }))}
          />
          {!status.data?.device ? (
            <EmptyState title="No device connected" actions={<Button variant="primary" onClick={() => { status.refetch(); dev.refetch() }}>Check again</Button>}>
              Connect a device over USB with debugging enabled.
            </EmptyState>
          ) : phase === 'tracing' ? (
            <>
              <Row gap={10}>
                <Swatch color="var(--fail)" shape="circle" pulse />
                <Text variant="eyebrow" tone="fail">
                  RECORDING
                </Text>
              </Row>
              <Text as="div" variant="stat-xl" aria-live="off">
                {mmss}
              </Text>
              <Text variant="body">Drive the app on the device now. Stop when you are done and the trace is pulled, analysed and recorded.</Text>
              <Row gap={8}>
                <Button onClick={stop} disabled={busy} className={s.stop}>
                  <Swatch color="var(--accent)" /> Stop &amp; analyse
                </Button>
                <Button variant="mini" onClick={discard} disabled={busy}>
                  Discard
                </Button>
              </Row>
              <Switch checked={aiSummary} onChange={setAiSummary} label="Write an AI summary when it's recorded" />
            </>
          ) : phase === 'analysing' ? (
            <>
              <Row gap={10}>
                <Spinner size={18} />
                <Text variant="ui">Analysing trace…</Text>
              </Row>
              {job && <LogConsole lines={job.log} running label="Analysis log" />}
            </>
          ) : (
            <>
              {phase === 'done' && result?.run_id != null && (
                <Stack gap={10} className={s.result}>
                  <Row gap={10}>
                    <StatusPill tone={result.verdict === 'pass' ? 'pass' : result.verdict === 'fail' ? 'fail' : 'warn'} />
                    <Text variant="heading">Run #{result.run_id} analysed</Text>
                  </Row>
                  <Text variant="body">
                    {result.headline} {result.screens ? `· ${result.screens} screen visit${result.screens === 1 ? '' : 's'}` : '· no screen markers'}
                  </Text>
                  <Row gap={8}>
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
                  </Row>
                </Stack>
              )}
              <Text variant="display">Trace any session</Text>
              <Text variant="body">
                Tracing runs as a detached session with no fixed duration: use the app however you need to -- a real payment, a biometric unlock, a sequence no
                script reproduces -- then stop. Cold force-stops and relaunches the app so the launch is measured too.
              </Text>
              <Row gap={8} wrap>
                {installed.length > 0 && (
                  <SelectField label="App" value={target} options={installed.map((p) => ({ value: p.pkg, label: p.name + (p.role === 'own' ? ' · ours' : '') }))} onChange={setPkg} />
                )}
                <Segmented label="Start" value={cold ? 'cold' : 'warm'} onChange={(v) => setCold(v === 'cold')} options={[{ value: 'cold', label: 'Cold' }, { value: 'warm', label: 'Warm' }]} />
              </Row>
              <Stack gap={4}>
                <Switch checked={aiSummary} onChange={setAiSummary} label="Write an AI summary when it's recorded" />
                <Text variant="caption">After you stop, a model reads the run's numbers with your Claude session and writes a summary. The verdict stays the rules' verdict.</Text>
              </Stack>
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
        </Stack>
      </Card>

      <Card title="Live markers" hint="Screens, actions, navigations and steps as the app emits them, newest first. A screen marked open is the one on display now.">
        <Stack gap={14}>
          <Row gap={6} wrap>
            {KINDS.map((k) => {
              const on = kinds.has(k.kind)
              return (
                <ToggleChip
                  key={k.kind}
                  pressed={on}
                  color={k.color}
                  count={counts[k.kind] ?? 0}
                  onClick={() =>
                    setKinds((prev) => {
                      const n = new Set(prev)
                      // Never let the filter empty out: a blank list would read as "no markers".
                      if (on && n.size > 1) n.delete(k.kind)
                      else n.add(k.kind)
                      return n
                    })
                  }
                >
                  {k.label}
                </ToggleChip>
              )
            })}
            {live.data?.current_screen && (
              <StatusPill tone="pass">
                on {live.data.current_screen}
                {live.data.current_screen_kind ? ` · ${live.data.current_screen_kind}` : ''}
              </StatusPill>
            )}
          </Row>
          <Stack gap={8}>
            {live.data?.note && (
              <Text variant="meta" tone="warn">
                {live.data.note}
              </Text>
            )}
            {live.data?.mode && <Text variant="meta">This phone does not serve partial reads, so updates slow down as the session grows.</Text>}
            <div aria-live="polite" className={s.feed}>
              {!recording ? (
                <EmptyState>Markers appear here while a session records.</EmptyState>
              ) : events.length === 0 ? (
                <EmptyState>{live.isLoading ? 'Waiting for the first markers…' : 'No markers yet. Drive the app to produce some.'}</EmptyState>
              ) : (
                events.slice(0, 300).map((e, i) => {
                  const k = KINDS.find((x) => x.kind === e.kind)!
                  return (
                    <div key={`${e.kind}${e.at_ms}${i}`} className={s.event}>
                      <Text variant="meta">{(e.at_ms / 1000).toFixed(1)}s</Text>
                      <Row gap={6}>
                        <Swatch color={k.color} />
                        <Text variant="meta" tone="secondary">
                          {e.kind}
                          {e.screen_kind_label ? ` · ${e.screen_kind_label}` : ''}
                        </Text>
                      </Row>
                      <Text variant="body" tone="primary" weight={500} breakAnywhere>
                        {e.step ? '↳ ' : ''}
                        {e.name}
                      </Text>
                      <Text variant="meta" tone={e.open_ended ? 'pass' : 'muted'}>
                        {e.open_ended ? 'open' : e.duration_ms != null ? `${e.duration_ms.toFixed(0)} ms` : ''}
                      </Text>
                    </div>
                  )
                })
              )}
            </div>
          </Stack>
        </Stack>
      </Card>
    </Grid>
  )
}
