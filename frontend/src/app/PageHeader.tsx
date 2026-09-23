import type { ReactNode } from 'react'
import { Eyebrow, Row, Stack, Text } from '@/design'
import type { Run } from '@/api/types'
import { RunBox } from './RunBox'
import s from './Shell.module.css'

/** Every screen's header: where you are, and the run in view. */
export function PageHeader({ group, title, hint, run, isLatest, aside }: { group: string; title: string; hint: string; run: Run | null; isLatest: boolean; aside?: ReactNode }) {
  return (
    <Row align="end" justify="between" gap={16} wrap>
      <Stack>
        <Eyebrow>{group}</Eyebrow>
        <Text as="h1" variant="title" className={s.h1}>
          {title}
        </Text>
        <Text as="p" variant="ui" tone="secondary" className={s.hint}>
          {hint}
        </Text>
      </Stack>
      {aside ?? (run && <RunBox run={run} isLatest={isLatest} />)}
    </Row>
  )
}
