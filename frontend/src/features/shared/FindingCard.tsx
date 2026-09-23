import type { Finding } from '@/api/types'
import { Button, Icon, SeverityPill } from '@/design/components'
import s from './FindingCard.module.css'

const EDGE = { high: 'var(--fail)', medium: 'var(--warn)', low: 'var(--c1)' } as const

export function FindingCard({
  finding,
  id,
  area,
  onAsk,
  compact,
}: {
  finding: Finding
  id: string
  area: string
  onAsk?: () => void
  compact?: boolean
}) {
  const sev = finding.severity in EDGE ? finding.severity : 'low'
  return (
    <article data-hl={id} className={`${s.card} ${compact ? s.compact : ''}`}>
      <div className={s.edge} style={{ background: EDGE[sev] }} />
      <div className={s.body}>
        <div className={s.meta}>
          <SeverityPill level={sev} />
          <span className={s.id}>
            {id} · {area}
          </span>
          <div style={{ flex: 1 }} />
          {onAsk && (
            <Button variant="mini" onClick={onAsk}>
              <Icon name="sparkle" size={11} style={{ color: 'var(--accent)' }} />
              Ask Copilot
            </Button>
          )}
        </div>
        <h3 className={s.title}>{finding.title}</h3>
        <div className={s.cols}>
          <div>
            <div className={s.colLabel}>EVIDENCE</div>
            <div className={s.colText}>{finding.evidence}</div>
          </div>
          {finding.recommendation && (
            <div>
              <div className={s.colLabel}>RECOMMENDATION</div>
              <div className={s.colText} style={{ color: 'var(--tx)' }}>
                {finding.recommendation}
              </div>
            </div>
          )}
          {finding.architectural_risk && (
            <div>
              <div className={s.colLabel}>RISK</div>
              <div className={s.colText}>{finding.architectural_risk}</div>
            </div>
          )}
        </div>
      </div>
    </article>
  )
}
