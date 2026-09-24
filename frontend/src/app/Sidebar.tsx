import { NavLink } from 'react-router'
import { IconButton, Row, Spacer, Stack, Text } from '@/design'
import { useProfiler } from './profiler'
import { GROUPS, screensFor } from './routes'
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
  // Only the screens of the profiler in view: its runs are the only ones they show.
  const screens = screensFor(useProfiler())
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
            {screens.filter((x) => x.group === g).map((x) => {
              const index = String(screens.indexOf(x) + 1).padStart(2, '0')
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
          <IconButton icon={rail ? 'chevronsRight' : 'chevronsLeft'} label={rail ? 'Expand sidebar' : 'Collapse sidebar'} outlined onClick={onToggleRail} />
        )}
        {full && (
          <Text as="div" variant="caption">
            {screens[0]?.profiler === 'flashlight' ? 'Flashlight, pinned npm build' : 'Perfetto trace processor'}
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
