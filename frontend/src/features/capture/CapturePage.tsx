import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { keys, startCapture, useDevice, useJob, useRecentJobs } from '@/api/hooks'
import type { DevicePayload, Job } from '@/api/types'
import { Banner, Button, Card, EmptyState, Grid, Label, LogConsole, Progress, SearchInput, Segmented, Stepper, type StepState } from '@/design/components'
import { fmt } from '@/domain/format'
import { useUi } from '@/app/store'

type Connected = Extract<DevicePayload, { connected: true }>

/** Stages of a capture job, recognised from the lines the job runner logs. */
const STAGES = [
  { label: 'Connect device', done: /^device:/ },
  { label: 'Launch', done: /force-stopping|capturing warm/ },
  { label: `Record`, done: /^trace saved/ },
  { label: 'Pull trace', done: /^extracting metrics/ },
  { label: 'Analyse', done: /^verdict:/ },
]

export function stageStates(job: Pick<Job, 'log' | 'state'>): StepState[] {
  const reached = STAGES.map((s) => job.log.some((l) => s.done.test(l.text)))
  const firstOpen = reached.findIndex((r) => !r)
  return STAGES.map((_, i) => (job.state === 'done' || reached[i] ? 'done' : i === firstOpen && job.state !== 'error' ? 'active' : 'pending'))
}

export function CapturePage() {
  const dev = useDevice()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const setFilters = useUi((s) => s.setFilters)
  const recent = useRecentJobs()
  const [q, setQ] = useState('')
  const [pkg, setPkg] = useState<string | null>(null)
  const [cold, setCold] = useState(true)
  const [duration, setDuration] = useState(10000)
  const [jobId, setJobId] = useState<string | null>(null)
  const [startErr, setStartErr] = useState<string | null>(null)

  // Resume a capture that is still running (a tab change or reload).
  const resumed = recent.data?.find((j) => j.kind === 'capture' && (j.state === 'running' || j.state === 'queued'))
  const activeId = jobId ?? resumed?.id ?? null
  const job = useJob(activeId).data
  const running = job?.state === 'queued' || job?.state === 'running'

  const d = dev.data?.connected ? (dev.data as Connected) : null
  const installed = useMemo(() => (d?.packages ?? []).filter((p) => p.installed), [d])
  const selected = pkg ?? installed.find((p) => p.role === 'own')?.pkg ?? installed[0]?.pkg ?? null
  const list = installed.filter((p) => !q || `${p.name} ${p.pkg}`.toLowerCase().includes(q.toLowerCase())).slice(0, 80)

  const profile = async () => {
    if (!selected) return
    setStartErr(null)
    try {
      const r = await startCapture({ pkg: selected, cold, duration_ms: duration })
      setJobId(r.job_id)
      qc.invalidateQueries({ queryKey: keys.jobs })
    } catch (e) {
      setStartErr((e as Error).message)
    }
  }

  const stages = job ? stageStates(job) : null
  const pct = stages ? (stages.filter((x) => x === 'done').length / STAGES.length) * 100 : 0
  const result = job?.result as { run_id?: number; verdict?: string; headline?: string; path_kind?: string } | undefined

  return (
    <Grid min={440}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        {dev.isLoading ? (
          <EmptyState>Looking for a device…</EmptyState>
        ) : !d ? (
          <EmptyState
            title="No device connected"
            actions={
              <>
                <Button variant="primary" onClick={() => dev.refetch()}>
                  Retry detection
                </Button>
                <Button onClick={() => window.open('https://developer.android.com/tools/adb#Enabling', '_blank', 'noopener')}>Setup guide</Button>
              </>
            }
          >
            Connect an Android device with USB debugging on, or pair one over Wi-Fi with <code>adb connect &lt;host&gt;</code>.
          </EmptyState>
        ) : (
          <Card>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, font: '600 11px var(--font-ui)', letterSpacing: '.12em', color: 'var(--pass)' }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--pass)' }} />
              DEVICE CONNECTED
            </div>
            <div style={{ font: '800 24px var(--font-display)', marginTop: 10 }}>{d.model}</div>
            <div style={{ fontSize: 13, color: 'var(--tx2)', marginTop: 4 }}>
              Android {d.release} · serial {d.serial} · {installed.length} apps installed
              {d.devices && d.devices.length > 1 ? ` · ${d.devices.length} devices attached, using the first` : ''}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 1, background: 'var(--line)', border: '1px solid var(--line)', marginTop: 16 }}>
              {[
                ['Battery', d.health?.battery_pct != null ? `${d.health.battery_pct}%` : '–'],
                ['Battery temp', d.health?.battery_temp_c != null ? `${fmt(d.health.battery_temp_c, 1)} °C` : '–'],
                ['Perfetto', d.health?.perfetto_version ?? '–'],
              ].map(([k, v]) => (
                <div key={k} style={{ background: 'var(--s1)', padding: 12 }}>
                  <Label>{k}</Label>
                  <div style={{ font: '700 15px var(--font-display)', marginTop: 6, overflowWrap: 'anywhere' }}>{v}</div>
                </div>
              ))}
            </div>
          </Card>
        )}

        {d && (
          <Card title="Installed packages">
            <SearchInput label="Search installed apps" placeholder="Search by name or package id" value={q} onChange={setQ} />
            <div role="radiogroup" aria-label="Package to profile" style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 12, maxHeight: 360, overflowY: 'auto' }}>
              {list.map((p) => {
                const on = p.pkg === selected
                return (
                  <button
                    key={p.pkg}
                    type="button"
                    role="radio"
                    aria-checked={on}
                    onClick={() => setPkg(p.pkg)}
                    style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 12px', border: `1px solid ${on ? 'var(--accent)' : 'var(--line)'}`, background: on ? 'var(--accent-soft)' : 'transparent', color: 'var(--tx)', borderRadius: 4, cursor: 'pointer', textAlign: 'left' }}
                  >
                    <span aria-hidden="true" style={{ width: 14, height: 14, borderRadius: '50%', border: `1.5px solid ${on ? 'var(--accent)' : 'var(--line2)'}`, display: 'grid', placeItems: 'center', flex: 'none' }}>
                      {on && <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--accent)' }} />}
                    </span>
                    <span style={{ flex: 1, minWidth: 0 }}>
                      <span style={{ fontWeight: 600, display: 'block' }}>
                        {p.name}
                        {p.role === 'own' ? ' · ours' : ''}
                      </span>
                      <span style={{ fontSize: 12, color: 'var(--tx3)', overflowWrap: 'anywhere' }}>{p.pkg}</span>
                    </span>
                  </button>
                )
              })}
              {list.length === 0 && <div style={{ fontSize: 13, color: 'var(--tx3)', padding: 8 }}>No installed apps match that search.</div>}
            </div>
          </Card>
        )}

        <Card>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
            <Segmented label="Start" value={cold ? 'cold' : 'warm'} onChange={(v) => setCold(v === 'cold')} options={[{ value: 'cold', label: 'Cold' }, { value: 'warm', label: 'Warm' }]} />
            <Segmented label="Duration" value={duration} onChange={setDuration} options={[5000, 10000, 20000].map((v) => ({ value: v, label: `${v / 1000} s` }))} />
          </div>
          <Button variant="primary" large disabled={!d || !selected || running} onClick={profile}>
            {running ? 'Profiling…' : job?.state === 'done' ? 'Profile again' : 'Profile'}
          </Button>
          <div style={{ fontSize: 12, color: 'var(--tx3)', marginTop: 10 }}>
            {cold ? 'Cold start' : 'Warm start'} · {duration / 1000} s trace · {selected ?? 'no app selected'}
          </div>
          {startErr && (
            <div style={{ marginTop: 12 }}>
              <Banner tone="fail" title="Could not start">
                {startErr}
              </Banner>
            </div>
          )}
        </Card>
      </div>

      <Card title="Job" style={{ display: 'flex', flexDirection: 'column', gap: 16, alignSelf: 'start' }}>
        {!job ? (
          <EmptyState>No job running. Pick an app and press Profile.</EmptyState>
        ) : (
          <>
            {running && (
              <>
                <div style={{ font: '800 36px var(--font-display)' }}>{fmt(pct)}%</div>
                <Progress pct={pct} />
              </>
            )}
            {stages && <Stepper steps={STAGES.map((s, i) => ({ label: s.label, state: stages[i]! }))} />}
            <LogConsole lines={job.log} running={running} label="Capture log" />
            {job.state === 'error' && (
              <Banner tone="fail" title="Capture failed">
                {job.error}
              </Banner>
            )}
            {job.state === 'done' && result?.run_id != null && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', padding: '14px 16px', border: `1px solid var(--${result.verdict === 'pass' ? 'pass' : result.verdict === 'fail' ? 'fail' : 'warn'})`, background: `var(--${result.verdict === 'pass' ? 'pass' : result.verdict === 'fail' ? 'fail' : 'warn'}-bg)` }}>
                <div style={{ flex: 1, minWidth: 200 }}>
                  <div style={{ font: '700 14px var(--font-display)' }}>
                    Run #{result.run_id} saved · {(result.verdict ?? '').toUpperCase()}
                  </div>
                  <div style={{ fontSize: 13, color: 'var(--tx2)', marginTop: 3 }}>{result.headline}</div>
                </div>
                <Button
                  variant="primary"
                  onClick={() => {
                    if (result.path_kind) setFilters({ path: result.path_kind, app: (job as { pkg?: string }).pkg ?? '' })
                    qc.invalidateQueries({ queryKey: keys.history })
                    navigate(`/overview?run=${result.run_id}`)
                  }}
                >
                  View results
                </Button>
              </div>
            )}
          </>
        )}
      </Card>
    </Grid>
  )
}
