import {
  Avatar,
  Banner,
  Bubble,
  Button,
  CodeBlock,
  CompactTable,
  Disclosure,
  Icon,
  IconButton,
  MiniBars,
  Row,
  Spacer,
  Stack,
  StatusPill,
  StepList,
  Text,
  Toolbar,
  type Diff,
  type TextTone,
} from '@/design'
import type { AnswerBlock, AnswerMessage, ChatMessage, Citation, Feedback } from './types'

const TAG_TONE: Record<Diff, TextTone> = { worse: 'fail', better: 'pass', same: 'inherit' }

const elapsed = (ms: number) => (ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`)

export interface AnswerActions {
  onCite: (c: Citation) => void
  onCopy: (m: AnswerMessage) => void
  onCompare: (m: AnswerMessage) => void
  onPin: (m: AnswerMessage) => void
  onExport: (m: AnswerMessage) => void
  onFeedback: (m: AnswerMessage, value: Feedback) => void
  onCopied: (what: string) => void
}

function Block({ b, onCite, onCopied }: { b: AnswerBlock } & Pick<AnswerActions, 'onCite' | 'onCopied'>) {
  switch (b.type) {
    case 'verdict':
      return (
        <Row gap={10} align="start">
          <StatusPill tone={b.tone}>{b.label}</StatusPill>
          <Text variant="lead" tone="primary" weight={600}>
            {b.text}
          </Text>
        </Row>
      )
    case 'heading':
      return (
        <Text as="h4" variant="heading-sm">
          {b.text}
        </Text>
      )
    case 'para':
      return (
        <Text as="p" variant="lead">
          {b.text}
        </Text>
      )
    case 'table':
      return (
        <CompactTable
          columns={b.cols}
          rows={b.rows.map((r) =>
            r.cells.map((c, i) =>
              i === r.cells.length - 1 ? (
                <Text key={i} variant="small" tone={TAG_TONE[r.tag]} weight={600}>
                  {c}
                </Text>
              ) : (
                c
              ),
            ),
          )}
        />
      )
    case 'bars':
      return <MiniBars title={b.title} labels={b.labels} values={b.values} unit={b.unit} budget={b.budget} />
    case 'code':
      return <CodeBlock lang={b.lang} code={b.code} defaultOpen={b.open} onCopy={() => onCopied(`${b.lang} copied`)} />
    case 'cites':
      return (
        <Row gap={6} wrap>
          <Text variant="label">Sources</Text>
          {b.items.map((c) => (
            <Button key={`${c.kind}:${c.id}`} variant="outline" onClick={() => onCite(c)}>
              {c.label}
              <Icon name="external" size={12} />
            </Button>
          ))}
        </Row>
      )
  }
}

/** The assistant's side of the conversation: the avatar, then content. */
const Assistant = ({ children, label }: { children: React.ReactNode; label?: string }) => (
  <Row as="article" gap={12} align="start" aria-label={label}>
    <Avatar />
    <Stack gap={12} grow>
      {children}
    </Stack>
  </Row>
)

function Answer({ m, actions }: { m: AnswerMessage; actions: AnswerActions }) {
  const saved = m.messageId != null
  return (
    <Assistant label="Copilot answer">
      {m.steps.length > 0 && (
        <Disclosure
          summary={
            <>
              <Text tone="pass" aria-hidden="true">
                ✓
              </Text>
              Queried run data · {m.steps.length} step{m.steps.length === 1 ? '' : 's'} · {elapsed(m.elapsedMs)}
            </>
          }
        >
          {m.steps.join(' → ')}
        </Disclosure>
      )}
      {m.blocks.map((b, i) => (
        <Block key={i} b={b} onCite={actions.onCite} onCopied={actions.onCopied} />
      ))}
      <Toolbar label="Answer actions">
        <Button variant="quiet" onClick={() => actions.onCopy(m)}>
          Copy
        </Button>
        <Button variant="quiet" onClick={() => actions.onCompare(m)}>
          Open in Compare
        </Button>
        <Button variant="quiet" disabled={!saved || m.runId == null} title={saved ? undefined : 'Available once the answer is saved'} onClick={() => actions.onPin(m)}>
          Pin as finding
        </Button>
        <Button variant="quiet" onClick={() => actions.onExport(m)}>
          Export .md
        </Button>
        <Spacer />
        <IconButton icon="thumbUp" size="sm" label="Helpful" pressed={m.feedback === 'up'} disabled={!saved} onClick={() => actions.onFeedback(m, m.feedback === 'up' ? null : 'up')} />
        <IconButton icon="thumbDown" size="sm" label="Not helpful" pressed={m.feedback === 'down'} disabled={!saved} onClick={() => actions.onFeedback(m, m.feedback === 'down' ? null : 'down')} />
      </Toolbar>
    </Assistant>
  )
}

export function Message({ m, actions, onRetry, onUseRun, onOpenHistory }: { m: ChatMessage; actions: AnswerActions; onRetry: (prompt: string) => void; onUseRun: (prompt: string, runId: number) => void; onOpenHistory: () => void }) {
  switch (m.role) {
    case 'user':
      return <Bubble>{m.text}</Bubble>
    case 'thinking':
      return (
        <Assistant label="Copilot is working">
          <Stack gap={8} aria-live="polite">
            <Text variant="body" tone="primary" weight={600}>
              Querying run data…
            </Text>
            <StepList steps={[...m.steps.map((text) => ({ text, state: 'done' as const })), { text: m.steps.length ? 'Working…' : 'Starting…', state: 'active' as const }]} />
          </Stack>
        </Assistant>
      )
    case 'stopped':
      return (
        <Text variant="small" tone="muted" role="status">
          {m.steps == null ? 'Stopped. No answer was saved for this question.' : `Stopped after ${m.steps} step${m.steps === 1 ? '' : 's'}. The answer was not saved.`}
        </Text>
      )
    case 'error':
      return (
        <Banner
          tone="fail"
          title={m.title}
          actions={
            <Button variant="inverse" onClick={() => onRetry(m.prompt)}>
              Retry
            </Button>
          }
        >
          {m.message}
        </Banner>
      )
    case 'nodata':
      return (
        <Banner
          tone="neutral"
          title={m.title}
          actions={
            <>
              {m.oldestRunId != null && (
                <Button variant="outline" onClick={() => onUseRun(m.prompt, m.oldestRunId!)}>
                  Use oldest kept run (#{m.oldestRunId})
                </Button>
              )}
              <Button variant="outline" onClick={onOpenHistory}>
                Open History
              </Button>
            </>
          }
        >
          {m.message}
        </Banner>
      )
    case 'answer':
      return <Answer m={m} actions={actions} />
  }
}
