import { Button, EmptyState, ListButton, PanelBody, Row, Spinner, Text } from '@/design'
import { shortDate } from '@/domain/format'
import { useThreads } from './api'

/** Past conversations, newest first. Opening one restores it. */
export function Threads({ current, onOpen, onNew }: { current: number | null; onOpen: (id: number) => void; onNew: () => void }) {
  const q = useThreads(true)
  return (
    <PanelBody compact label="Past threads">
      <Row justify="between" gap={8}>
        <Text as="h3" variant="heading-sm">
          Past threads
        </Text>
        <Button variant="primary" size="sm" onClick={onNew}>
          New chat
        </Button>
      </Row>
      {q.isLoading && <Spinner />}
      {q.error && <EmptyState title="Could not load threads">{q.error.message}</EmptyState>}
      {q.data?.length === 0 && <EmptyState>No saved conversations yet. Questions you ask are kept here.</EmptyState>}
      {q.data?.map((t) => (
        <ListButton key={t.id} variant="plain" current={t.id === current} title={t.title} description={shortDate(t.updated, true)} onClick={() => onOpen(t.id)} />
      ))}
    </PanelBody>
  )
}
