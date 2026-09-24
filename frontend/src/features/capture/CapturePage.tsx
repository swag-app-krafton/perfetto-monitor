import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { keys, startCapture, useDevice, useJob, useRecentJobs } from '@/api/hooks'
import type { DevicePayload, Run } from '@/api/types'
import { Banner, Button, Card, ChoiceList, EmptyState, Grid, LogConsole, Progress, Row, SearchInput, Segmented, Stack, Stat, StatGrid, Stepper, Swatch, Text } from '@/design'
import { fmt } from '@/domain/format'
import { runVerdict } from '@/domain/metrics'
import { useLaneNavigate, useProfiler } from '@/app/profiler'
import { platformOf, useUi } from '@/app/store'
import { STAGES, stageStates } from './stages'
import s from './Capture.module.css'

type Connected = Extract<DevicePayload, { connected: true }>

/** A simulator's Mac: its CPU is the run's CPU, so its state is the one to show. */
type MacState = { host_power?: string; host_battery_pct?: number; host_load_1m?: number; host_thermal_warning?: boolean }

export function CapturePage() {
  // The lane decides the device: an adb device, or the booted iOS Simulator.
  const platform = platformOf(useProfiler())
  const ios = platform === 'ios'
  const dev = useDevice(platform)
  const qc = useQueryClient()
  const navigate = useLaneNavigate()
  const setFilters = useUi((s) => s.setFilters)
  const recent = useRecentJobs()
  const [q, setQ] = useState('')
  const [pkg, setPkg] = useState<string | null>(null)
  const [cold, setCold] = useState(true)
  const [duration, setDuration] = useState(10000)
  const [jobId, setJobId] = useState<string | null>(null)
  const [startErr, setStartErr] = useState<string | null>(null)

  // Resume a capture that is still running (a tab change or reload).
  const resumed = recent.data?.find((j) => j.kind === 'capture' && (j.platform ?? 'android') === platform && (j.state === 'running' || j.state === 'queued'))
  const activeId = jobId ?? resumed?.id ?? null
  const job = useJob(activeId).data
  const running = job?.state === 'queued' || job?.state === 'running'

  const d = dev.data?.connected ? (dev.data as Connected) : null
  const installed = useMemo(() => (d?.packages ?? []).filter((p) => p.installed), [d])
  const selected = pkg ?? installed.find((p) => p.role === 'own')?.pkg ?? installed[0]?.pkg ?? null
  const list = installed.filter((p) => !q || `${p.name} ${p.pkg}`.toLowerCase().includes(q.toLowerCase())).slice(0, 80)
  // A Debug iOS build loads its JS from Metro: a different app to measure.
  const debugBuild = ios && installed.find((p) => p.pkg === selected)?.build?.build_type === 'debug'
  const mac = (d?.health ?? {}) as MacState
  const host = (d?.host ?? {}) as { chip?: string }

  const profile = async () => {
    if (!selected) return
    setStartErr(null)
    try {
      const r = await startCapture({ pkg: selected, cold: ios || cold, duration_ms: duration, platform })
      setJobId(r.job_id)
      qc.invalidateQueries({ queryKey: keys.jobs })
    } catch (e) {
      setStartErr((e as Error).message)
    }
  }

  const stages = job ? stageStates(job) : null
  const pct = stages ? (stages.filter((x) => x === 'done').length / STAGES.length) * 100 : 0
  const result = job?.result as { run_id?: number; verdict?: 'pass' | 'warn' | 'fail'; headline?: string; path_kind?: string; simulator?: boolean } | undefined
  const verdict = runVerdict({ analysis: result?.verdict ? ({ verdict: result.verdict } as Run['analysis']) : null, simulator: !!result?.simulator })

  return (
    <Grid min={440}>
      <Stack gap={20}>
        {dev.isLoading ? (
          <EmptyState>{ios ? 'Looking for a booted simulator…' : 'Looking for a device…'}</EmptyState>
        ) : !d && ios ? (
          <EmptyState
            title="No iOS Simulator booted"
            actions={
              <Button variant="primary" onClick={() => dev.refetch()}>
                Retry detection
              </Button>
            }
          >
            Boot one with <code>xcrun simctl boot "iPhone 17"</code> or open Simulator.app, then install a Release build of the app.
          </EmptyState>
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
                    {ios ? 'SIMULATOR BOOTED' : 'DEVICE CONNECTED'}
                  </Text>
                </Row>
                <Stack gap={4}>
                  <Text variant="display">{d.model}</Text>
                  <Text variant="body">
                    {ios ? `iOS ${d.release} · Simulator` : `Android ${d.release} · serial ${d.serial}`} · {installed.length} apps installed
                    {d.devices && d.devices.length > 1 ? ` · ${d.devices.length} ${ios ? 'simulators booted' : 'devices attached'}, using the first` : ''}
                  </Text>
                </Stack>
              </Stack>
              {/* A small min keeps all three cells on one line down to phone width. */}
              {ios ? (
                <StatGrid variant="hairline" min={90}>
                  <Stat size="sm" label="Mac" value={<Text as="span" variant="heading-sm" breakAnywhere>{host.chip ?? '–'}</Text>} />
                  <Stat size="sm" label="Load (1 min)" value={mac.host_load_1m != null ? fmt(mac.host_load_1m, 2) : '–'} />
                  <Stat size="sm" label="Thermal" value={mac.host_thermal_warning == null ? '–' : mac.host_thermal_warning ? 'Warning' : 'Normal'} />
                </StatGrid>
              ) : (
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
              )}
            </Stack>
          </Card>
        )}

        {d && (
          <Card title="Installed packages">
            <Stack gap={12}>
              <SearchInput label="Search installed apps" placeholder="Search by name or package id" value={q} onChange={setQ} />
              <ChoiceList
                label="Package to profile"
                maxHeight={360}
                value={selected}
                onChange={setPkg}
                options={list.map((p) => ({
                  value: p.pkg,
                  title: `${p.name}${p.role === 'own' ? ' · ours' : ''}`,
                  description: p.build ? `${p.pkg} · ${p.build.build_type === 'debug' ? 'Debug build, cannot be profiled' : 'Release build'}` : p.pkg,
                }))}
                empty="No installed apps match that search."
              />
            </Stack>
          </Card>
        )}

        <Card>
          <Stack gap={12}>
            <Stack gap={10}>
              <Stack gap={14}>
                <Row gap={10} wrap>
                  {/* An iOS capture is always a cold launch under Instruments. */}
                  {!ios && (
                    <Segmented label="Start" value={cold ? 'cold' : 'warm'} onChange={(v) => setCold(v === 'cold')} options={[{ value: 'cold', label: 'Cold' }, { value: 'warm', label: 'Warm' }]} />
                  )}
                  <Segmented label="Duration" value={duration} onChange={setDuration} options={[5000, 10000, 20000].map((v) => ({ value: v, label: `${v / 1000} s` }))} />
                </Row>
                <Button variant="primary" large disabled={!d || !selected || running || debugBuild} onClick={profile}>
                  {running ? 'Profiling…' : job?.state === 'done' ? 'Profile again' : 'Profile'}
                </Button>
              </Stack>
              <Text variant="meta">
                {ios || cold ? 'Cold start' : 'Warm start'} · {duration / 1000} s {ios ? 'recording' : 'trace'} · {selected ?? 'no app selected'}
              </Text>
            </Stack>
            {debugBuild && (
              <Banner tone="warn" title="Debug build">
                This build has no JS bundle and loads its JavaScript from Metro, so it is a different app from the one users run. Install a Release build to profile
                it.
              </Banner>
            )}
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
              {stages && <Stepper steps={STAGES.map((st, i) => ({ label: ios && st.label === 'Pull trace' ? 'Convert trace' : st.label, state: stages[i]! }))} />}
              <LogConsole lines={job.log} running={running} label="Capture log" />
              {job.state === 'error' && (
                <Banner tone="fail" title="Capture failed">
                  {job.error}
                </Banner>
              )}
              {job.state === 'done' && result?.run_id != null && (
                <Banner
                  tone={verdict.tone === 'neutral' ? 'pass' : verdict.tone}
                  title={`Run #${result.run_id} saved · ${verdict.word}`}
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
