import { Spinner } from './Layout'
import { GLYPH } from './tone'
import s from './Steps.module.css'

export type StepState = 'done' | 'active' | 'pending'

/** A row of numbered stages. Done shows ✓ on pass, active is the accent,
 *  pending is muted. */
export function Stepper({ steps }: { steps: { label: string; state: StepState }[] }) {
  return (
    <ol className={s.stepper}>
      {steps.map((st, i) => (
        <li key={st.label} className={s.stage} data-state={st.state} aria-current={st.state === 'active' ? 'step' : undefined}>
          <span aria-hidden="true" className={s.num}>
            {st.state === 'done' ? GLYPH.pass : i + 1}
          </span>
          <span className={s.stageLabel}>{st.label}</span>
          {i < steps.length - 1 && <span aria-hidden="true" className={s.joint} />}
        </li>
      ))}
    </ol>
  )
}

/** A vertical checklist of work in progress: ✓ done, a spinner on the active
 *  step, a dashed circle for what is still to come. */
export function StepList({ steps, label }: { steps: { text: string; state: StepState }[]; label?: string }) {
  return (
    <ol className={s.list} aria-label={label}>
      {steps.map((st, i) => (
        <li key={i} className={s.item} data-state={st.state} aria-current={st.state === 'active' ? 'step' : undefined}>
          <span className={s.mark} aria-hidden="true">
            {st.state === 'done' ? <span className={s.tick}>{GLYPH.pass}</span> : st.state === 'active' ? <Spinner /> : <span className={s.pending} />}
          </span>
          <span>{st.text}</span>
        </li>
      ))}
    </ol>
  )
}
