import type { ReactNode } from 'react'
import { Eyebrow, Row, Stack, Text } from '@/design'
import type { Run } from '@/api/types'
import { runMetaLines } from './runMeta'
import s from './Shell.module.css'

export function PageHeader({ group, title, hint, run, aside }: { group: string; title: string; hint: string; run: Run | null; aside?: ReactNode }) {
  const meta = runMetaLines(run)
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
      {aside ??
        (meta && (
          <Text as="div" variant="meta">
            {meta[0]}
            <br />
            {meta[1]}
          </Text>
        ))}
    </Row>
  )
}
