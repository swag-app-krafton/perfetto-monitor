import type { Audit } from '@/api/types'
import { Badge, Button, Row, Spacer, Stack, StatusPill, Text, type Tone } from '@/design'
import { auditLabel } from '@/domain/audits'
import { shortDate } from '@/domain/format'
import { useUi } from './store'
import s from './RunBox.module.css'

const STATE_TONE: Record<Audit['state'], Tone> = { done: 'pass', running: 'warn', error: 'fail', interrupted: 'neutral' }

/** The Flashlight audit in view, on every Flashlight screen: the counterpart
 *  of RunBox. */
export function AuditBox({ audit, following }: { audit: Audit; following: boolean }) {
  const setAuditId = useUi((st) => st.setAuditId)
  const ok = audit.summary?.successful
  return (
    <section className={s.box} aria-label={`Audit ${auditLabel(audit)}`}>
      <Stack gap={8}>
        <Row gap={8} wrap>
          <span className={s.id}>AUDIT {auditLabel(audit)}</span>
          <StatusPill tone={STATE_TONE[audit.state]}>{audit.state.toUpperCase()}</StatusPill>
          <Spacer />
          {following ? (
            <Badge tone="c1">Latest</Badge>
          ) : (
            <Button variant="quiet" onClick={() => setAuditId(null)} title="Show the newest audit">
              Older audit · go to latest
            </Button>
          )}
        </Row>
        <Stack gap={2}>
          <Text variant="small" tone="primary" weight={500} breakAnywhere>
            {audit.device ?? 'Device not recorded'}
          </Text>
          <Text variant="small" breakAnywhere>
            {audit.app_name}
          </Text>
          <Text variant="meta">
            {shortDate(audit.ts, true)} · {ok ?? '–'} of {audit.iterations} cold starts · {audit.duration_ms / 1000} s each
          </Text>
        </Stack>
      </Stack>
    </section>
  )
}
