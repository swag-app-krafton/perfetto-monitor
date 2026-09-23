import type { Run, RunDetails } from '@/api/types'
import { Badge, Banner, Button, DescriptionList, Dialog, Row, Spinner, Stack, Text } from '@/design'
import { shortDate } from '@/domain/format'
import { useUi } from './store'
import { asText, sections, startLabel } from './runMeta'

export function RunDetailsDialog({ run, meta, loading, open, onClose }: { run: Run; meta: RunDetails; loading: boolean; open: boolean; onClose: () => void }) {
  const showToast = useUi((s) => s.showToast)
  const fromCapture = meta.sources.includes('capture')
  const fromTrace = meta.sources.includes('from_trace') && !meta.trace_error
  return (
    <Dialog open={open} onClose={onClose} title={`Run #${run.id}`} subtitle={`${run.app_name ?? run.app_pkg ?? 'Unknown app'} · ${startLabel(run.path_kind)} · ${shortDate(run.ts, true)}`}>
      <Stack gap={24}>
        <Row gap={8} wrap>
          <Text variant="label">Recorded from</Text>
          {fromCapture && <Badge tone="c1">The device, at capture</Badge>}
          {fromTrace && <Badge tone="c4">The trace</Badge>}
          {!fromCapture && !fromTrace && <Badge>The run only</Badge>}
          {loading && (
            <Row gap={6}>
              <Spinner size={12} />
              <Text variant="caption">Reading the trace…</Text>
            </Row>
          )}
          <Row grow justify="end">
            <Button
              variant="outline"
              onClick={() => {
                void navigator.clipboard?.writeText(asText(run, meta)).catch(() => undefined)
                showToast('Run details copied')
              }}
            >
              Copy details
            </Button>
          </Row>
        </Row>
        {!fromCapture && (
          <Banner tone="neutral" title="App version and device state were not recorded for this run">
            It was captured before runs recorded them (or analysed from a trace file).{' '}
            {fromTrace ? 'The device details below come from the trace itself.' : 'Only what the run itself stored is shown.'} Runs captured from now on record
            the app's version and build number, and the device's battery and thermal state.
          </Banner>
        )}
        {meta.trace_error && (
          <Banner tone="warn" title="The trace could not be read for device details">
            {meta.trace_error}
          </Banner>
        )}
        {sections(run, meta).map((sec) => (
          <Stack as="section" key={sec.title} gap={8}>
            <Row gap={8} align="baseline">
              <Text as="h3" variant="heading-sm">
                {sec.title}
              </Text>
              {sec.note && <Text variant="caption">{sec.note}</Text>}
            </Row>
            <DescriptionList items={sec.items} />
          </Stack>
        ))}
      </Stack>
    </Dialog>
  )
}
