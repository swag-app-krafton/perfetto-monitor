import { NavLink } from 'react-router'
import { Row, Spacer, Stack, Text } from '@/design'
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
  const full = !rail
  return (
    <nav aria-label="Primary" className={`${s.nav} ${drawer ? s.navDrawer : rail ? s.navRail : ''}`}>
      <Row gap={12} className={s.brand}>
        <div className={s.brandMark}>SP</div>
        {full && (
          <div className={s.brandName}>
            SWAG PAY
            <br />
            PERFORMANCE
          </div>
        )}
      </Row>
      {GROUPS.map((g) => (
        <div key={g} className={s.group}>
          <Text as="div" variant="label" nowrap className={s.groupLabel}>
            {full ? g : '—'}
          </Text>
          <Stack gap={2}>
            {SCREENS.filter((x) => x.group === g).map((x) => {
              const index = String(SCREENS.indexOf(x) + 1).padStart(2, '0')
              return (
                <NavLink key={x.id} to={x.path} className={s.item} title={x.label} onClick={onNavigate}>
                  <span className={s.mark}>{full ? index : x.code}</span>
                  {full && <span>{x.label}</span>}
                </NavLink>
              )
            })}
          </Stack>
        </div>
      ))}
      <Spacer />
      <Row gap={10} className={s.navFoot}>
        {!drawer && (
          <button type="button" className={s.railBtn} onClick={onToggleRail} aria-label={rail ? 'Expand sidebar' : 'Collapse sidebar'}>
            {rail ? '»' : '«'}
          </button>
        )}
        {full && (
          <Text as="div" variant="caption">
            Perfetto trace processor
            <br />
            <a href="/tokens.html" className={s.footLink}>
              LLM token usage ↗
            </a>
          </Text>
        )}
      </Row>
    </nav>
  )
}
