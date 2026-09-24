import type { ReactNode } from 'react'
import type { Finding } from '@/api/types'
import { Button, Card, Icon, Row, SeverityPill, Spacer, Stack, Text } from '@/design'
import s from './FindingCard.module.css'

const EDGE = { high: 'var(--fail)', medium: 'var(--warn)', low: 'var(--c1)' } as const

export function FindingCard({
  finding,
  id,
  area,
  onAsk,
  actions,
  compact,
}: {
  finding: Finding
  id: string
  area: string
  onAsk?: () => void
  /** Extra actions beside "Ask Copilot" (Unpin). */
  actions?: ReactNode
  compact?: boolean
}) {
  const sev = finding.severity in EDGE ? finding.severity : 'low'
  return (
    <Card as="article" edge={{ side: 'left', color: EDGE[sev] }} data-hl={id} className={compact ? `${s.card} ${s.compact}` : s.card}>
      <Stack gap={compact ? 10 : 14}>
        <Row gap={10} wrap>
          <SeverityPill level={sev} />
          <Text variant="meta">
            {id} · {area}
          </Text>
          <Spacer />
          {actions}
          {onAsk && (
            <Button variant="mini" onClick={onAsk}>
              <Icon name="sparkle" size={11} tone="accent" />
              Ask Copilot
            </Button>
          )}
        </Row>
        <Text as="h3" variant={compact ? 'heading-sm' : 'heading'}>
          {finding.title}
        </Text>
        <div className={s.cols}>
          <Stack gap={6}>
            <Text variant="label">EVIDENCE</Text>
            <Text variant="body" breakAnywhere>
              {finding.evidence}
            </Text>
          </Stack>
          {finding.recommendation && (
            <Stack gap={6}>
              <Text variant="label">RECOMMENDATION</Text>
              <Text variant="body" tone="primary" breakAnywhere>
                {finding.recommendation}
              </Text>
            </Stack>
          )}
          {finding.architectural_risk && (
            <Stack gap={6}>
              <Text variant="label">RISK</Text>
              <Text variant="body" breakAnywhere>
                {finding.architectural_risk}
              </Text>
            </Stack>
          )}
        </div>
      </Stack>
    </Card>
  )
}
