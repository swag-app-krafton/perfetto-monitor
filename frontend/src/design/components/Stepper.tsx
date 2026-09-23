import { GLYPH } from './Status'

export type StepState = 'done' | 'active' | 'pending'

/** A row of stages. Done shows ✓ on pass, active is the accent, pending is muted. */
export function Stepper({ steps }: { steps: { label: string; state: StepState }[] }) {
  return (
    <ol style={{ display: 'flex', gap: 8, flexWrap: 'wrap', listStyle: 'none', margin: 0, padding: 0 }}>
      {steps.map((st, i) => (
        <li key={st.label} aria-current={st.state === 'active' ? 'step' : undefined} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, color: st.state === 'pending' ? 'var(--tx3)' : 'var(--tx)' }}>
          <span
            aria-hidden="true"
            style={{
              width: 20,
              height: 20,
              borderRadius: '50%',
              display: 'grid',
              placeItems: 'center',
              font: '700 10px var(--font-ui)',
              background: st.state === 'done' ? 'var(--pass)' : st.state === 'active' ? 'var(--accent)' : 'transparent',
              border: st.state === 'pending' ? '1.5px solid var(--line2)' : 0,
              color: st.state === 'pending' ? 'var(--tx3)' : 'var(--on-accent)',
            }}
          >
            {st.state === 'done' ? GLYPH.pass : i + 1}
          </span>
          <span style={{ fontWeight: st.state === 'active' ? 600 : 400 }}>{st.label}</span>
          {i < steps.length - 1 && <span aria-hidden="true" style={{ width: 16, height: 1, background: 'var(--line2)' }} />}
        </li>
      ))}
    </ol>
  )
}
