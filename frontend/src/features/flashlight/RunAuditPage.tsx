import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { keys, startAudit, useAudits, useDevice, useJob, useRecentJobs } from '@/api/hooks'
import type { DevicePayload, Job } from '@/api/types'
import { Banner, Button, Card, EmptyState, LogConsole, Progress, Row, Segmented, SelectField, Spinner, Stack, Text } from '@/design'
import { auditLabel } from '@/domain/audits'
import { fmt } from '@/domain/format'
import { useUi } from '@/app/store'

type Connected = Extract<DevicePayload, { connected: true }>
type AuditJob = Job<{ audit_id?: number; score?: number | null; successful?: number; failed?: number }> & {
  audit_id?: number
  progress?: { current: number; total: number }
}

const ITERATIONS = [3, 5, 10]
const DURATIONS = [5000, 10000, 20000]

/** Start a Flashlight audit: an app's cold start, measured by Flashlight, N times. */
export function RunAuditPage() {
  const dev = useDevice()
  const audits = useAudits()
  const recent = useRecentJobs()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { app, setFilters, setAuditId } = useUi()
  const [pkg, setPkg] = useState<string | null>(null)
  const [n, setN] = useState(5)
  const [duration, setDuration] = useState(10000)
  const [jobId, setJobId] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  // Resume an audit that is still running after a tab change or a reload.
  const resumed = recent.data?.find((j) => j.kind === 'audit' && (j.state === 'running' || j.state === 'queued'))
  const job = useJob(jobId ?? resumed?.id ?? null).data as AuditJob | undefined
  const running = job?.state === 'queued' || job?.state === 'running'

  const d = dev.data?.connected ? (dev.data as Connected) : null
  const installed = useMemo(() => (d?.packages ?? []).filter((p) => p.installed), [d])
  const selected = pkg ?? (installed.some((p) => p.pkg === app) ? app : (installed.find((p) => p.role === 'own')?.pkg ?? installed[0]?.pkg ?? null))
  const appName = installed.find((p) => p.pkg === selected)?.name ?? selected ?? ''

  // One profiler at a time on a device. Say why an audit can't start rather
  // than letting it fail on the phone.
  const runner = audits.data?.runner ?? d?.profilers?.flashlight_runner ?? null
  const blockers: string[] = []
  if (runner && !runner.ready) blockers.push(runner.reason)
  if (d?.profilers?.perfetto_recording)
    blockers.push('A Perfetto manual session is recording on this device. Stop it on the Manual page first: Flashlight would break its trace.')

  const run = async () => {
    if (!selected) return
    setErr(null)
    try {
      const r = await startAudit({ pkg: selected, iterations: n, duration_ms: duration })
      setJobId(r.job_id)
      qc.invalidateQueries({ queryKey: keys.jobs })
      setTimeout(() => qc.invalidateQueries({ queryKey: keys.audits }), 1500)
    } catch (e) {
      setErr((e as Error).message)
    }
  }

  const open = (id: number) => {
    if (selected) setFilters({ app: selected })
    setAuditId(id)
    navigate('/flashlight/audit')
  }

  if (dev.isLoading) return <EmptyState>Looking for a device…</EmptyState>
  if (!d)
    return (
      <EmptyState
        title="No device connected"
        actions={
          <Button variant="primary" onClick={() => dev.refetch()}>
            Retry detection
          </Button>
        }
      >
        Connect an Android device with USB debugging on to run a Flashlight audit.
      </EmptyState>
    )

  const result = job?.state === 'done' ? job.result : undefined
  return (
    <Stack as="section" gap={20}>
      <Card>
        <Stack gap={16}>
          <Row gap={16} wrap>
            <SelectField
              label="App"
              value={selected ?? ''}
              options={installed.map((p) => ({ value: p.pkg, label: p.name === p.pkg ? p.pkg : `${p.name} · ${p.pkg}` }))}
              onChange={setPkg}
            />
            <Segmented label="Cold starts" value={n} onChange={setN} options={ITERATIONS.map((v) => ({ value: v, label: String(v) }))} />
            <Segmented label="Measured" value={duration} onChange={setDuration} options={DURATIONS.map((v) => ({ value: v, label: `${v / 1000} s` }))} />
            <Button variant="primary" disabled={running || !selected || blockers.length > 0} onClick={run}>
              Run {n} cold starts with Flashlight
            </Button>
          </Row>
          <Text variant="body" tone="secondary">
            {appName} is force-stopped and launched {n} times on {d.model}. After each launch Flashlight samples CPU per thread, RAM and FPS every 500 ms for{' '}
            {duration / 1000} s. Nothing else may profile the phone meanwhile: Perfetto captures wait until the audit finishes.
          </Text>
          {blockers.map((b) => (
            <Banner key={b} tone="warn" title="Can't start an audit">
              {b}
            </Banner>
          ))}
          {err && (
            <Banner tone="fail" title="Could not start">
              {err}
            </Banner>
          )}
        </Stack>
      </Card>

      {job && (
        <Card title={job.audit_id ? `Audit ${auditLabel({ id: job.audit_id })}` : 'Audit'}>
          <Stack gap={12}>
            {running && (
              <Stack gap={8}>
                <Row gap={10}>
                  <Spinner />
                  <Text variant="body" tone="primary">
                    {job.progress ? `Cold start ${job.progress.current} of ${job.progress.total}` : 'Preparing Flashlight on the phone…'}
                  </Text>
                </Row>
                <Progress pct={job.progress ? (Math.max(0, job.progress.current - 1) / job.progress.total) * 100 : 0} />
              </Stack>
            )}
            {result?.audit_id != null && (
              <Banner
                tone={result.failed ? 'warn' : 'pass'}
                title={`Score ${fmt(result.score)} · ${result.successful} cold start${result.successful === 1 ? '' : 's'} measured${result.failed ? `, ${result.failed} failed` : ''}`}
                actions={
                  <Button variant="primary" onClick={() => open(result.audit_id!)}>
                    Open audit {auditLabel({ id: result.audit_id })}
                  </Button>
                }
              />
            )}
            {job.state === 'error' && (
              <Banner tone="fail" title="The audit failed">
                {job.error}
              </Banner>
            )}
            <LogConsole lines={job.log} running={running} label="Audit log" />
          </Stack>
        </Card>
      )}
    </Stack>
  )
}
