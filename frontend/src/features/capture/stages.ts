import type { Job } from '@/api/types'
import type { StepState } from '@/design'

/** Stages of a capture job, recognised from the lines the job runner logs. */
export const STAGES = [
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
