import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { keys, startCapture, useDevice, useJob, useRecentJobs } from '@/api/hooks'
import type { DevicePayload } from '@/api/types'
import { Banner, Button, Card, EmptyState, Grid, LogConsole, Progress, Row, SearchInput, Segmented, Stack, Stat, StatGrid, Stepper, Swatch, Text } from '@/design'
import { fmt } from '@/domain/format'
import { useUi } from '@/app/store'
import { STAGES, stageStates } from './stages'
import s from './Capture.module.css'

type Connected = Extract<DevicePayload, { connected: true }>

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
  const verdictTone = result?.verdict === 'pass' ? 'pass' : result?.verdict === 'fail' ? 'fail' : 'warn'

  return (
    <Grid min={440}>
      <Stack gap={20}>
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
            <Stack gap={16}>
              <Stack gap={10}>
                <Row gap={8}>
                  <Swatch color="var(--pass)" shape="circle" size={8} />
                  <Text variant="eyebrow" tone="pass">
                    DEVICE CONNECTED
                  </Text>
                </Row>
                <Stack gap={4}>
                  <Text variant="display">{d.model}</Text>
                  <Text variant="body">
                    Android {d.release} · serial {d.serial} · {installed.length} apps installed
                    {d.devices && d.devices.length > 1 ? ` · ${d.devices.length} devices attached, using the first` : ''}
                  </Text>
                </Stack>
              </Stack>
              {/* A small min keeps all three cells on one line down to phone width. */}
              <StatGrid variant="hairline" min={90}>
                <Stat size="sm" label="Battery" value={d.health?.battery_pct ?? '–'} unit={d.health?.battery_pct != null ? '%' : undefined} />
                <Stat size="sm" label="Battery temp" value={d.health?.battery_temp_c != null ? fmt(d.health.battery_temp_c, 1) : '–'} unit={d.health?.battery_temp_c != null ? '°C' : undefined} />
                <Stat
                  size="sm"
                  label="Perfetto"
                  value={
                    // The version string ends in a long build hash; let it wrap inside the cell.
                    <Text as="span" variant="heading-sm" breakAnywhere>
                      {d.health?.perfetto_version ?? '–'}
                    </Text>
                  }
                />
              </StatGrid>
            </Stack>
          </Card>
        )}

        {d && (
          <Card title="Installed packages">
            <Stack gap={12}>
              <SearchInput label="Search installed apps" placeholder="Search by name or package id" value={q} onChange={setQ} />
              <Stack gap={6} role="radiogroup" aria-label="Package to profile" className={s.pkgList}>
                {list.map((p) => {
                  const on = p.pkg === selected
                  return (
                    <button key={p.pkg} type="button" role="radio" aria-checked={on} onClick={() => setPkg(p.pkg)} className={s.pkg}>
                      <span aria-hidden="true" className={s.radio}>
                        {on && <Swatch color="var(--accent)" shape="circle" size={6} />}
                      </span>
                      <Stack as="span" grow>
                        <Text as="span" variant="body" tone="primary" weight={600}>
                          {p.name}
                          {p.role === 'own' ? ' · ours' : ''}
                        </Text>
                        <Text variant="meta" breakAnywhere>
                          {p.pkg}
                        </Text>
                      </Stack>
                    </button>
                  )
                })}
                {list.length === 0 && (
                  <Text variant="body" tone="muted" className={s.noMatch}>
                    No installed apps match that search.
                  </Text>
                )}
              </Stack>
            </Stack>
          </Card>
        )}

        <Card>
          <Stack gap={12}>
            <Stack gap={10}>
              <Stack gap={14}>
                <Row gap={10} wrap>
                  <Segmented label="Start" value={cold ? 'cold' : 'warm'} onChange={(v) => setCold(v === 'cold')} options={[{ value: 'cold', label: 'Cold' }, { value: 'warm', label: 'Warm' }]} />
                  <Segmented label="Duration" value={duration} onChange={setDuration} options={[5000, 10000, 20000].map((v) => ({ value: v, label: `${v / 1000} s` }))} />
                </Row>
                <Button variant="primary" large disabled={!d || !selected || running} onClick={profile}>
                  {running ? 'Profiling…' : job?.state === 'done' ? 'Profile again' : 'Profile'}
                </Button>
              </Stack>
              <Text variant="meta">
                {cold ? 'Cold start' : 'Warm start'} · {duration / 1000} s trace · {selected ?? 'no app selected'}
              </Text>
            </Stack>
            {startErr && (
              <Banner tone="fail" title="Could not start">
                {startErr}
              </Banner>
            )}
          </Stack>
        </Card>
      </Stack>

      <Card title="Job" className={s.jobCard}>
        <Stack gap={16}>
          {!job ? (
            <EmptyState>No job running. Pick an app and press Profile.</EmptyState>
          ) : (
            <>
              {running && (
                <>
                  <Text as="div" variant="stat">
                    {fmt(pct)}%
                  </Text>
                  <Progress pct={pct} />
                </>
              )}
              {stages && <Stepper steps={STAGES.map((st, i) => ({ label: st.label, state: stages[i]! }))} />}
              <LogConsole lines={job.log} running={running} label="Capture log" />
              {job.state === 'error' && (
                <Banner tone="fail" title="Capture failed">
                  {job.error}
                </Banner>
              )}
              {job.state === 'done' && result?.run_id != null && (
                <Banner
                  tone={verdictTone}
                  title={`Run #${result.run_id} saved · ${(result.verdict ?? '').toUpperCase()}`}
                  actions={
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
                  }
                >
                  {result.headline}
                </Banner>
              )}
            </>
          )}
        </Stack>
      </Card>
    </Grid>
  )
}
