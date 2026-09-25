import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { keys, useGenerateSummary, useJob, useSummary } from '@/api/hooks'
import type { Run, RunSummary as Summary } from '@/api/types'
import { Banner, Button, Card, Disclosure, EmptyState, Icon, Row, SectionTitle, Spinner, Stack, Text } from '@/design'
import { shortDate } from '@/domain/format'
import { ComparisonTables } from '@/features/shared/ComparisonTables'
import { FindingCard } from '@/features/shared/FindingCard'
import { findingArea } from '@/features/shared/findings'
import { verdictAuthor } from './verdictAuthor'
import s from './Overview.module.css'

/** A run's AI summary (F-023): the model's reading of the run's recorded
 *  numbers, and how the run compares with its pinned benchmark (F-024). It sits
 *  beside the verdict and never replaces it. */
export function RunSummary({ run, descriptions, pinnedBenchmarkId }: { run: Run; descriptions: Record<string, string>; pinnedBenchmarkId: number | null }) {
  const qc = useQueryClient()
  const q = useSummary(run.id)
  const generate = useGenerateSummary()
  // A job belongs to the run it was started for.
  const [started, setStarted] = useState<{ runId: number; jobId: string } | null>(null)
  const job = useJob(started?.runId === run.id ? started.jobId : null)
  const jobState = job.data?.state
  useEffect(() => {
    if (jobState === 'done' || jobState === 'error') {
      void qc.invalidateQueries({ queryKey: keys.summary(run.id) })
      void qc.invalidateQueries({ queryKey: keys.history })
    }
  }, [jobState, qc, run.id])

  const sm = q.data?.summary ?? null
  const writing = generate.isPending || q.data?.generating || jobState === 'queued' || jobState === 'running'
  const failed = jobState === 'error' ? (job.data?.error ?? 'The summary could not be written.') : generate.error?.message
  const start = () => generate.mutate(run.id, { onSuccess: (r) => setStarted({ runId: run.id, jobId: r.job_id }) })

  return (
    <Stack gap={12} data-hl="summary">
      <SectionTitle aside={sm ? `Written by ${sm._model ?? 'a model'} · ${shortDate(sm._created, true)}` : undefined}>AI summary</SectionTitle>
      {failed && !writing && (
        <Banner tone="warn" title="No summary written">
          {failed}
        </Banner>
      )}
      {q.isLoading ? (
        <EmptyState>
          <Spinner /> &nbsp;Loading the summary…
        </EmptyState>
      ) : !sm ? (
        <EmptyState
          align="start"
          title={writing ? 'Writing the summary…' : 'No AI summary for this run yet'}
          actions={
            <Button onClick={start} disabled={writing}>
              {writing ? <Spinner /> : <Icon name="sparkle" size={12} tone="accent" />}
              {writing ? 'Writing…' : 'Generate summary'}
            </Button>
          }
        >
          A model reads this run's recorded numbers (never its trace) and describes what stands out, what to check next and how the run compares with its pinned
          benchmark. It uses your Claude session, takes up to a few minutes, and never changes the verdict.
        </EmptyState>
      ) : (
        <SummaryBody run={run} sm={sm} descriptions={descriptions} pinnedBenchmarkId={pinnedBenchmarkId} writing={!!writing} onRegenerate={start} />
      )}
    </Stack>
  )
}

function SummaryBody({
  run,
  sm,
  descriptions,
  pinnedBenchmarkId,
  writing,
  onRegenerate,
}: {
  run: Run
  sm: Summary
  descriptions: Record<string, string>
  pinnedBenchmarkId: number | null
  writing: boolean
  onRegenerate: () => void
}) {
  const recorded = run.analysis?.verdict
  const bench = sm._benchmark ?? null
  const dismissed = (sm.dismissed ?? []).map((d) => (typeof d === 'string' ? d : d.reason ? `${d.title}: ${d.reason}` : d.title))
  return (
    <>
      {sm._stale && (
        <Banner tone="warn" title="Out of date">
          This run was re-extracted after the summary was written, so its numbers may have changed. Regenerate the summary.
        </Banner>
      )}
      {!!sm._unverified?.length && (
        <Banner tone="warn" title="Numbers not found in the run's data">
          {sm._unverified.join(', ')}. The model wrote them, but this run's recorded numbers don't contain them. Check them before acting on them.
        </Banner>
      )}
      <Card
        actions={
          <Button variant="mini" onClick={onRegenerate} disabled={writing}>
            {writing ? <Spinner size={11} /> : <Icon name="sparkle" size={11} tone="accent" />}
            {writing ? 'Writing…' : 'Regenerate'}
          </Button>
        }
        title={sm.headline}
      >
        <Stack gap={12}>
          {sm.summary && <Text variant="body">{sm.summary}</Text>}
          {recorded && sm.verdict && sm.verdict !== recorded && (
            <Text variant="meta">
              The model reads this run as {sm.verdict}. The recorded verdict ({verdictAuthor(run.analysis_meta?.model)}) is {recorded}, and it stands.
            </Text>
          )}
          {!!dismissed.length && (
            <Disclosure summary={`Looked at and set aside (${dismissed.length})`}>
              <Stack gap={6} className={s.dismissed}>
                {dismissed.map((d, i) => (
                  <Text key={i} variant="body">
                    {d}
                  </Text>
                ))}
              </Stack>
            </Disclosure>
          )}
        </Stack>
      </Card>

      {(sm.findings ?? []).map((f, i) => (
        <FindingCard key={i} finding={f} id={`S-${i + 1}`} area={`AI summary · ${findingArea(f)}`} compact />
      ))}

      <SectionTitle
        aside={
          bench
            ? `Benchmark #${bench.base.id}${bench.base.version ? ` · ${bench.base.version}` : ''}${bench.base.device ? ` · ${bench.base.device}` : ''}${bench.base.id !== pinnedBenchmarkId ? ' · the benchmark when this was written' : ''}`
            : undefined
        }
      >
        Against the pinned benchmark
      </SectionTitle>
      {bench ? (
        <>
          {sm.benchmark_comparison && (
            <Row gap={10}>
              <Text variant="body">{sm.benchmark_comparison}</Text>
            </Row>
          )}
          {/* Folded: Overview's tiles and findings come next, and Compare has these in full. */}
          <Disclosure summary={`Every metric and step against benchmark #${bench.base.id}: ${bench.summary.worse} worse · ${bench.summary.better} better · ${bench.summary.same} same`}>
            <Stack gap={12} className={s.dismissed}>
              <ComparisonTables data={bench} runLabel={`This run #${bench.run.id}`} baseLabel={`Benchmark #${bench.base.id}`} descriptions={descriptions} />
            </Stack>
          </Disclosure>
        </>
      ) : (
        <EmptyState align="start">
          {run.simulator
            ? 'A simulator run is never compared with a benchmark.'
            : 'No benchmark was pinned for this app, start path and device when this summary was written, or this run is the benchmark. Pin one on History, then regenerate.'}
        </EmptyState>
      )}
    </>
  )
}
