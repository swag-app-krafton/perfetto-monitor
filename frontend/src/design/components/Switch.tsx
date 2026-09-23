import s from './Switch.module.css'

/** An on/off switch with its label beside it (role="switch"). */
export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (on: boolean) => void; label: string }) {
  return (
    <button type="button" role="switch" aria-checked={checked} className={s.switch} onClick={() => onChange(!checked)}>
      <span className={s.track} aria-hidden="true">
        <span className={s.knob} />
      </span>
      {label}
    </button>
  )
}
