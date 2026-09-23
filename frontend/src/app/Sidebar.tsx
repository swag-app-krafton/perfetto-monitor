import { NavLink } from 'react-router'
import { GROUPS, SCREENS } from './routes'
import s from './Shell.module.css'

export function Sidebar({
  rail,
  drawer,
  onNavigate,
  onToggleRail,
}: {
  rail: boolean
  drawer: boolean
  onNavigate?: () => void
  onToggleRail: () => void
}) {
  const width = drawer ? 264 : rail ? 72 : 232
  const full = !rail
  return (
    <nav aria-label="Primary" className={`${s.nav} ${drawer ? s.navDrawer : ''}`} style={{ width }}>
      <div className={s.brand}>
        <div className={s.brandMark}>SP</div>
        {full && (
          <div className={s.brandName}>
            SWAG PAY
            <br />
            PERFORMANCE
          </div>
        )}
      </div>
      {GROUPS.map((g) => (
        <div key={g} className={s.group}>
          <div className={s.groupLabel}>{full ? g : '—'}</div>
          <div className={s.items}>
            {SCREENS.filter((x) => x.group === g).map((x) => {
              const index = String(SCREENS.indexOf(x) + 1).padStart(2, '0')
              return (
                <NavLink key={x.id} to={x.path} className={s.item} title={x.label} onClick={onNavigate}>
                  <span className={s.mark}>{full ? index : x.code}</span>
                  {full && <span>{x.label}</span>}
                </NavLink>
              )
            })}
          </div>
        </div>
      ))}
      <div style={{ flex: 1 }} />
      <div className={s.navFoot}>
        {!drawer && (
          <button type="button" className={s.railBtn} onClick={onToggleRail} aria-label={rail ? 'Expand sidebar' : 'Collapse sidebar'}>
            {rail ? '»' : '«'}
          </button>
        )}
        {full && (
          <div className={s.footNote}>
            Perfetto trace processor
            <br />
            <a href="/tokens.html" style={{ color: 'var(--tx3)' }}>
              LLM token usage ↗
            </a>
          </div>
        )}
      </div>
    </nav>
  )
}
