import type { Scope } from '@/domain/scope'
import { stepDeltas } from '@/domain/steps'
import { stepName } from '@/domain/format'

/** Suggested questions for a tab, phrased against the run in view and the
 *  runs in scope, and only ones the Copilot can answer from them. */
export function startersFor(tab: string, scope: Scope | null, compare?: { a: number | null; b: number | null }): string[] {
  const run = scope?.run
  if (!run) return ['What can you answer?']
  const worst = stepDeltas(run, scope.allRuns, scope.benchmarkRun)
    .filter((d) => d.deltaMs != null && d.deltaMs >= 5)
    .sort((x, y) => y.deltaMs! - x.deltaMs!)[0]
  const base = scope.benchmarkRun ? 'the benchmark' : 'recent runs'
  const why = `Why did TTID regress in run #${run.id}?`
  const pr = 'Summarise this run for a PR comment'
  const noise = 'Is this regression real or noise? Check the stress tests.'
  const grew = `Which step grew the most vs ${base}?`
  const peak = 'Compare peak RAM across the last 10 builds'
  const prior = scope.allRuns.filter((r) => r.id < run.id).at(-1)
  const a = compare?.a ?? run.id
  const b = compare?.b ?? scope.benchmarkRun?.id ?? prior?.id ?? null
  const byTab: Record<string, string[]> = {
    overview: [pr, why, noise],
    startup: [why, grew, 'Did deferred work run before the first frame?'],
    frames: [`What is causing slow frames in run #${run.id}?`, 'Is the thermal drift real or environmental?'],
    memory: [peak, 'Which screen is leaking memory?'],
    steps: [grew, ...(worst ? [`Why did ${stepName(worst.step)} grow?`] : [])],
    screens: ['Which screen burns the most CPU?', 'Which screen is leaking memory?'],
    capture: [noise, 'Summarise the last capture for a PR comment'],
    stress: [noise, 'How many sessions do I need for a stable result?'],
    manual: [`What is causing slow frames in run #${run.id}?`, 'Summarise this session for a PR comment'],
    compare: b != null && b !== a ? [`Explain the differences between #${a} and #${b}`, `Summarise run #${a} for a PR comment`] : [pr],
    history: [peak, 'When did TTID first go over budget?'],
  }
  return byTab[tab] ?? [pr, why]
}
