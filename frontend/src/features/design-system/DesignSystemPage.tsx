import { useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { useUi } from '@/app/store'
import { useApplyTheme } from '@/app/useApplyTheme'
import {
  Avatar,
  Badge,
  Banner,
  BarList,
  BarSeries,
  Bubble,
  Button,
  Card,
  Chip,
  ChipButton,
  CodeBlock,
  CompactTable,
  DescriptionList,
  Dialog,
  DiffTag,
  Disclosure,
  DockPanel,
  EmptyState,
  FieldButton,
  FlushCard,
  Eyebrow,
  Grid,
  HelpTip,
  Icon,
  IconButton,
  Kbd,
  KpiTile,
  Legend,
  LineChart,
  ListButton,
  LogConsole,
  Meter,
  MiniBars,
  OptionList,
  PanelBar,
  PanelBody,
  PanelFooter,
  PanelHeader,
  Progress,
  Row,
  SPACE,
  SearchInput,
  Segmented,
  SelectField,
  SeverityPill,
  Spacer,
  Spinner,
  Stack,
  Stat,
  StatGrid,
  StatusPill,
  StepList,
  Stepper,
  Swatch,
  Switch,
  TableCard,
  TableEmptyRow,
  Term,
  TermList,
  Text,
  TextAreaField,
  Toast,
  ToggleChip,
  numCell,
  selectedRow,
  type TextVariant,
} from '@/design'
import s from './DesignSystem.module.css'

/* Colour tokens, grouped as the handoff groups them. */
const GROUPS: [string, string[]][] = [
  ['Surfaces', ['bg', 's1', 's2', 's3', 'line', 'line2']],
  ['Text', ['tx', 'tx2', 'tx3']],
  ['Brand', ['accent', 'accent-tx', 'focus']],
  ['Status', ['pass', 'warn', 'fail']],
  ['Chart series', ['c1', 'c2', 'c3', 'c4']],
]

const TYPE: [TextVariant, string, string][] = [
  ['hero', 'Expanded 800 · clamp 64–104/0.88', 'FAIL'],
  ['stat-xl', 'Expanded 800 · 64/1', '02:41'],
  ['title', 'Expanded 800 · clamp 28–44/1.02', 'Startup'],
  ['stat', 'Expanded 700 · 34/1', '375 ms'],
  ['display-lg', 'Expanded 800 · 26/1.2', 'Three runtimes, one process'],
  ['headline', 'Expanded 700 · clamp 18–24/1.3', 'Peak RAM usage over budget'],
  ['display', 'Expanded 800 · 22/1.2', 'Ask about this run.'],
  ['heading-lg', 'Expanded 700 · 20', 'Findings'],
  ['heading', 'Expanded 700 · 16', 'Critical-path composition'],
  ['heading-sm', 'Expanded 700 · 14', 'Where it stands'],
  ['heading-xs', 'Expanded 700 · 12', 'Swag Pay'],
  ['eyebrow', 'Poppins 600 · 11 · 0.18em · caps', 'Latest run verdict'],
  ['label', 'Poppins 600 · 10.5 · 0.16em · caps', 'Context'],
  ['th', 'Poppins 600 · 11 · 0.08em · caps', 'Step Runtime Current Baseline'],
  ['ui', 'Poppins 400 · 14/1.5', 'bind_application took 190 ms on the main thread.'],
  ['lead', 'Poppins 400 · 13.5/1.65', 'Answers and long-form explanations.'],
  ['body', 'Poppins 400 · 13/1.6', 'Card hints and supporting copy.'],
  ['small', 'Poppins 400 · 12.5/1.5', 'Step lists and compact tables.'],
  ['meta', 'Poppins 400 · 12/1.5', 'Run #81 · V2514 · Cold start'],
  ['caption', 'Poppins 400 · 11/1.45', 'Disclaimers and footnotes.'],
  ['mono', 'Mono 400 · 12/1.6', 'SELECT name, dur / 1e6 AS dur_ms FROM slice'],
]

const RADII: [string, string][] = [
  ['--radius-0', 'Hero, tables, banners'],
  ['--radius-sm', 'Segmented items'],
  ['--radius', 'Cards, buttons, inputs'],
  ['--radius-lg', 'Composer field'],
  ['--radius-bubble', 'User bubble'],
  ['--radius-pill', 'Pills, chips, FAB'],
]

/* Illustrative values for the component demos only. */
const EXAMPLE_RUNS = ['#72', '#73', '#74', '#75', '#76', '#77', '#78', '#79', '#80', '#81']
const EXAMPLE_TTID = [362, 371, 368, 380, 376, 369, 384, 378, 381, 375]
const EXAMPLE_STEPS: [string, string | null, number, number][] = [
  ['process_start', 'The system creating the process the app runs in. Mostly outside the app\'s control.', 0, 3.8],
  ['bind_application', 'The new process loading the app\'s code, then running its Application.onCreate. Heavy SDK set-up there makes it slow.', 4.1, 211.4],
  ['activity_resume', null, 291.2, 51.3],
]

function Section({ id, title, intro, children }: { id: string; title: string; intro?: string; children: ReactNode }) {
  return (
    <Stack as="section" gap={20} aria-labelledby={id}>
      <Stack gap={6}>
        <Text as="h2" id={id} variant="heading-lg">
          {title}
        </Text>
        {intro && (
          <Text as="p" variant="body">
            {intro}
          </Text>
        )}
      </Stack>
      {children}
    </Stack>
  )
}

function Specimen({ name, children }: { name: string; children: ReactNode }) {
  return (
    <Card title={name} className={s.specimen}>
      <Stack gap={16}>{children}</Stack>
    </Card>
  )
}

function ThemeSwatches({ theme }: { theme: 'dark' | 'light' }) {
  return (
    <div data-theme={theme} className={s.themeBox}>
      <Text variant="heading-sm">{theme === 'dark' ? 'Dark · primary' : 'Light'}</Text>
      {GROUPS.map(([name, keys]) => (
        <Stack key={name} gap={8}>
          <Text variant="label">{name}</Text>
          <div className={s.swatches}>
            {keys.map((k) => (
              <Stack key={k} gap={4}>
                <div className={s.chip} style={{ background: `var(--${k})` }} />
                <Text variant="caption" tone="secondary">
                  --{k}
                </Text>
              </Stack>
            ))}
          </div>
        </Stack>
      ))}
    </div>
  )
}

/** The design system's living reference: every token and component, rendered
 *  by the same code the dashboard uses. */
export function DesignSystemPage() {
  const { theme, toggleTheme } = useUi()
  useApplyTheme()
  const [seg, setSeg] = useState<'cold' | 'warm'>('cold')
  const [sel, setSel] = useState('30')
  const [q, setQ] = useState('')
  const [deep, setDeep] = useState(true)
  const [chips, setChips] = useState(['Overview tab', 'Run #81', 'vs Benchmark #79'])
  const [active, setActive] = useState(0)
  const [kinds, setKinds] = useState({ screen: true, action: false })
  const [dialog, setDialog] = useState(false)
  const [toast, setToast] = useState<{ id: number; text: string } | null>(null)

  return (
    <div className={s.page}>
      <div className={s.inner}>
        <Row gap={16} wrap justify="between" align="end">
          <Stack gap={4}>
            <Eyebrow>Swag Pay Performance · Tokens</Eyebrow>
            <h1 className={s.title}>Design system</h1>
            <Text as="p" variant="ui" tone="secondary">
              Colour, type, spacing and components for the regression monitor and its Copilot. Dark is the primary theme; every token has a light counterpart.
            </Text>
          </Stack>
          <Row gap={8}>
            <Button variant="secondary" onClick={toggleTheme}>
              {theme === 'dark' ? 'Dark' : 'Light'} theme
            </Button>
            <Link to="/overview">Open dashboard →</Link>
          </Row>
        </Row>

        <Section id="ds-colour" title="Colour" intro="Brand red is never a status. Fail uses a separate crimson and always pairs with ✕; warn pairs with !, pass with ✓. Text on red, green and amber fills is black.">
          <div className={s.themes}>
            <ThemeSwatches theme="dark" />
            <ThemeSwatches theme="light" />
          </div>
        </Section>

        <Section id="ds-type" title="Type" intro="Display: Zalando Sans Expanded. UI: Poppins. Korean fallback: Noto Sans KR. Logs and SQL: the system monospace. Numerals are tabular everywhere. Text takes a role, not a size.">
          <div>
            {TYPE.map(([v, spec, sample]) => (
              <div key={v} className={s.spec}>
                <Stack gap={2}>
                  <Text variant="small" tone="primary" weight={600}>
                    {v}
                  </Text>
                  <Text variant="caption">{spec}</Text>
                </Stack>
                <Text variant={v}>{sample}</Text>
              </div>
            ))}
          </div>
        </Section>

        <Section id="ds-space" title="Spacing, radii, layers" intro="A 4px base with the half-steps the layouts use. Layout props take a value from this scale, so an off-scale gap does not type-check.">
          <Grid min={320}>
            <Card title="Spacing">
              <Stack gap={8}>
                {SPACE.filter((v) => v > 0).map((v) => (
                  <Row key={v} gap={12}>
                    <Text variant="meta" className={s.spaceLabel}>
                      {v}px
                    </Text>
                    <div className={s.space} style={{ width: v * 4 }} />
                  </Row>
                ))}
              </Stack>
            </Card>
            <Card title="Radii">
              <Stack gap={12}>
                {RADII.map(([token, use]) => (
                  <Row key={token} gap={16}>
                    <div className={s.radius} style={{ borderRadius: `var(${token})` }} />
                    <Stack gap={2}>
                      <Text variant="small" tone="primary" weight={600}>
                        {token}
                      </Text>
                      <Text variant="caption">{use}</Text>
                    </Stack>
                  </Row>
                ))}
              </Stack>
            </Card>
          </Grid>
        </Section>

        <Section id="ds-controls" title="Controls">
          <Grid min={360}>
            <Specimen name="Buttons">
              <Row gap={8} wrap>
                <Button variant="primary">Profile</Button>
                <Button variant="secondary">Open in Compare</Button>
                <Button variant="primary" disabled>
                  Disabled
                </Button>
              </Row>
              <Row gap={8} wrap>
                <Button variant="primary" size="sm">
                  Send ↵
                </Button>
                <Button variant="secondary" size="sm">
                  <Icon name="stop" size={12} />
                  Stop
                </Button>
                <Button variant="mini">Pin as benchmark</Button>
                <Button variant="outline">
                  Run #81 <Icon name="external" size={12} />
                </Button>
                <Button variant="quiet">Export .md</Button>
                <Button variant="inverse">Retry</Button>
              </Row>
              <Row gap={4}>
                <IconButton icon="clock" label="History" />
                <IconButton icon="clock" label="History (on)" pressed />
                <IconButton icon="plus" label="New" />
                <IconButton icon="maximise" label="Maximise" />
                <IconButton icon="close" label="Close" />
                <IconButton icon="thumbUp" label="Helpful" size="sm" pressed />
                <IconButton icon="thumbDown" label="Not helpful" size="sm" />
              </Row>
            </Specimen>
            <Specimen name="Fields">
              <Row gap={8} wrap>
                <Segmented label="Path" value={seg} onChange={setSeg} options={[{ value: 'cold', label: 'Cold' }, { value: 'warm', label: 'Warm' }]} />
                <SelectField label="Range" value={sel} onChange={setSel} options={[{ value: '30', label: 'Last 30 runs' }, { value: '10', label: 'Last 10 runs' }]} />
              </Row>
              <SearchInput label="Search runs" placeholder="Search run, build or device" value={q} onChange={setQ} />
              <Row>
                <FieldButton label="Run" value="#81 · Latest" open={false} onClick={() => undefined} title="Opens a panel of its own (the top bar's Run picker)" />
              </Row>
              <Row gap={12} wrap>
                <Switch checked={deep} onChange={setDeep} label="Deep analysis" />
                <HelpTip label="What is TTID?" text="Time to initial display: from process start to the first frame the app draws." />
                <Kbd>⌘K</Kbd>
              </Row>
              <TextAreaField label="Example composer" placeholder="Ask about runs, steps or findings." rows={2} footer={<><Spacer /><Button variant="primary" size="sm" disabled>Send ↵</Button></>} />
            </Specimen>
            <Specimen name="Chips and menus">
              <Row gap={6} wrap>
                {chips.map((c) => (
                  <Chip key={c} onRemove={() => setChips(chips.filter((x) => x !== c))} removeLabel={`Remove ${c}`}>
                    {c}
                  </Chip>
                ))}
                <ChipButton onClick={() => setChips(['Overview tab', 'Run #81', 'vs Benchmark #79'])}>+ Add</ChipButton>
              </Row>
              <Row gap={6} wrap>
                <ToggleChip pressed={kinds.screen} onClick={() => setKinds({ ...kinds, screen: !kinds.screen })} color="var(--c1)" count={24}>
                  Screens
                </ToggleChip>
                <ToggleChip pressed={kinds.action} onClick={() => setKinds({ ...kinds, action: !kinds.action })} color="var(--c2)" count={12}>
                  Actions
                </ToggleChip>
              </Row>
              <div className={s.menuHost}>
                <OptionList
                  id="ds-options"
                  label="Example options"
                  active={active}
                  onPick={setActive}
                  onHover={setActive}
                  options={[
                    { key: 'r', kind: 'Run', label: 'Run #80', meta: 'Sep 22 · PASS' },
                    { key: 's', kind: 'Step', label: 'Step: bind_application', meta: '+9.7 ms' },
                    { key: 'f', kind: 'Finding', label: 'Finding F-1', meta: 'high' },
                  ]}
                />
              </div>
            </Specimen>
          </Grid>
        </Section>

        <Section id="ds-status" title="Status and feedback">
          <Grid min={360}>
            <Specimen name="Pills, tags, severity">
              <Row gap={8} wrap>
                <StatusPill tone="pass" />
                <StatusPill tone="warn" />
                <StatusPill tone="fail" />
                <StatusPill tone="fail">REAL</StatusPill>
              </Row>
              <Row gap={8} wrap>
                <DiffTag diff="worse" />
                <DiffTag diff="better" />
                <DiffTag diff="same" />
              </Row>
              <Row gap={8} wrap>
                <SeverityPill level="high" />
                <SeverityPill level="medium" />
                <SeverityPill level="low" />
              </Row>
              <Row gap={8} wrap>
                <Badge>B</Badge>
                <Badge tone="accent">Pinned</Badge>
                <Badge tone="c4">Active benchmark</Badge>
              </Row>
              <Legend items={[{ label: 'Pass', color: 'var(--pass)' }, { label: 'Warn', color: 'var(--warn)' }, { label: 'Fail', color: 'var(--fail)' }]} />
              <Row gap={10}>
                <Icon name="sparkle" tone="accent" />
                <Icon name="check" tone="pass" />
                <Icon name="close" tone="fail" />
                <Icon name="clock" tone="muted" />
              </Row>
              <Row gap={10}>
                <Swatch color="var(--c1)" />
                <Swatch color="var(--c2)" shape="circle" />
                <Swatch color="var(--fail)" shape="circle" pulse label="Recording" />
                <Spinner />
              </Row>
            </Specimen>
            <Specimen name="Banners and empty states">
              <Banner tone="pass" title="Run #81 saved">
                Every measured metric is within budget.
              </Banner>
              <Banner tone="warn" title="Different devices">
                Run A is on V2514, Run B on Pixel 7a.
              </Banner>
              <Banner tone="fail" title="Could not answer" actions={<Button variant="inverse">Retry</Button>}>
                The server closed the stream early. Nothing was saved.
              </Banner>
              <Banner tone="neutral" title="No data for run #172" actions={<Button variant="outline">Open History</Button>}>
                Run #172 is not in the history.
              </Banner>
              <EmptyState title="No runs yet">Capture a trace from a connected device.</EmptyState>
            </Specimen>
            <Specimen name="Progress">
              <Progress pct={62} />
              <Meter label="Time to initial display against its budget" value={375} max={420} tone="pass" height={3} />
              <Meter label="bind_application against its baseline" value={190} max={210} marker={180} />
              <Stepper
                steps={[
                  { label: 'Connect', state: 'done' },
                  { label: 'Trace', state: 'active' },
                  { label: 'Analyse', state: 'pending' },
                ]}
              />
              <StepList
                steps={[
                  { text: 'Loaded run #81', state: 'done' },
                  { text: 'Compared 5 steps with the median of recent runs', state: 'active' },
                  { text: 'Found 2 findings', state: 'pending' },
                ]}
              />
              <Row>
                <Button variant="secondary" onClick={() => setToast({ id: Date.now(), text: 'Run #81 pinned as a benchmark' })}>
                  Show a toast
                </Button>
              </Row>
              <Toast message={toast?.text ?? null} id={toast?.id} onDismiss={() => setToast(null)} />
            </Specimen>
          </Grid>
        </Section>

        <Section id="ds-data" title="Data display">
          <Grid min={360}>
            <KpiTile label="TTID" help="Time to initial display." value="375" unit="ms" delta={{ value: -3, text: '−3 ms', against: 'vs 378 ms' }} trend={EXAMPLE_TTID} />
            <Specimen name="Stats">
              <StatGrid variant="hairline" min={110}>
                <Stat label="Battery" value="82" unit="%" size="sm" />
                <Stat label="Temperature" value="31.4" unit="°C" size="sm" />
                <Stat label="Perfetto" value="v49" size="sm" />
              </StatGrid>
              <StatGrid variant="boxes" min={110}>
                <Stat label="P50 · 10 runs" value="180.4" unit="ms" />
                <Stat label="This run" value="190.1" unit="ms" tone="fail" note={<Text variant="caption" tone="fail">▲ +9.7 ms</Text>} />
              </StatGrid>
            </Specimen>
            <Specimen name="Compact table">
              <CompactTable
                columns={['Metric', 'Run #81', 'Run #80', 'Δ']}
                rows={[
                  ['TTID', '375 ms', '378 ms', <Text key="d" variant="small" tone="pass" weight={600}>−3 ms</Text>],
                  ['RAM growth', '391 MB', '292 MB', <Text key="d" variant="small" tone="fail" weight={600}>+100 MB</Text>],
                ]}
              />
            </Specimen>
            <Card title="Term and TermList" hint="A name with what it means. Term puts the description behind a ? for tables, legends and charts; TermList gives it a second line in a short list. No description, no ?.">
              <Stack gap={16}>
                <Row gap={16} wrap>
                  <Term description="Time to initial display: from process start to the first frame the app draws.">TTID</Term>
                  <Term weight={600} description="The new process loading the app's code, then running its Application.onCreate.">
                    bind_application
                  </Term>
                  <Term tone="secondary">no description</Term>
                </Row>
                <TermList
                  label="Example startup steps"
                  items={EXAMPLE_STEPS.map(([name, about, start, dur]) => ({
                    key: name,
                    term: name,
                    description: about,
                    values: [
                      <Text key="start" variant="body">
                        +{start.toFixed(1)} ms
                      </Text>,
                      <Text key="dur" variant="body" tone="primary" weight={600}>
                        {dur.toFixed(1)} ms
                      </Text>,
                    ],
                  }))}
                />
              </Stack>
            </Card>
            <Specimen name="Code and disclosure">
              <Disclosure summary="Queried run data · 3 steps · 12 ms">Loaded run #81 → Compared 5 steps → Found 2 findings</Disclosure>
              <CodeBlock lang="Perfetto SQL" code={'SELECT name, dur / 1e6 AS dur_ms\nFROM slice\nWHERE name GLOB \'step:*\''} />
              <LogConsole lines={[{ t: 0.61, text: 'am start -W -S -n com.example/.Main' }, { t: 1.33, text: 'WARN first frame late' }, { t: 11.87, text: 'ERROR dropped 2 packets' }]} />
            </Specimen>
          </Grid>
        </Section>

        <Section id="ds-cards" title="Cards and tables">
          <Grid min={420}>
            <Card title="Card with an edge" hint="A coloured rule for a verdict, severity or series." edge={{ side: 'top', color: 'var(--c4)', width: 3 }}>
              <Text variant="body">Benchmark #79 · pinned from History.</Text>
            </Card>
            <TableCard title="TableCard" hint="Figures right-aligned; the focused row is selected." minWidth={320}>
              <thead>
                <tr>
                  <th>Test</th>
                  <th className={numCell}>Sessions</th>
                  <th className={numCell}>Median</th>
                </tr>
              </thead>
              <tbody>
                <tr className={selectedRow}>
                  <td>#4</td>
                  <td className={numCell}>10</td>
                  <td className={numCell}>374 ms</td>
                </tr>
                <tr>
                  <td>#3</td>
                  <td className={numCell}>5</td>
                  <td className={numCell}>389 ms</td>
                </tr>
              </tbody>
            </TableCard>
            <TableCard title="Empty table" minWidth={320}>
              <tbody>
                <TableEmptyRow colSpan={3}>No runs match the filter.</TableEmptyRow>
              </tbody>
            </TableCard>
            <Card title="DescriptionList and Dialog" hint="Label/value pairs that say when a value was not recorded; a modal on the native <dialog>.">
              <Stack gap={16}>
                <DescriptionList
                  min={200}
                  items={[
                    { term: 'Model', value: 'vivo V2514' },
                    { term: 'Android', value: '16 (SDK 36)' },
                    { term: 'Build number', value: null },
                    { term: 'Build ID', value: 'BP2A.250605.031', mono: true },
                  ]}
                />
                <Row>
                  <Button variant="outline" onClick={() => setDialog(true)}>
                    Open a dialog
                  </Button>
                </Row>
                <Dialog open={dialog} onClose={() => setDialog(false)} title="Run #81" subtitle="Swag Pay · Cold start · Sep 23, 12:54" width={520}>
                  <Text variant="body">Esc, the close button or a click on the backdrop closes it, and focus returns to the button that opened it.</Text>
                </Dialog>
              </Stack>
            </Card>
            <FlushCard title="FlushCard" hint="The same title bar around any flush body.">
              <div className={s.flushBody}>
                <Text variant="body">A div grid of expandable rows goes here, edge to edge.</Text>
              </div>
            </FlushCard>
          </Grid>
        </Section>

        <Section id="ds-charts" title="Charts" intro="One axis per chart; a null is a gap, never zero; status colour only with a label or glyph beside it.">
          <Grid min={420}>
            <Card title="LineChart" hint="Toggleable legend, nice ticks, a dashed budget line.">
              <LineChart label="Example TTID per run" labels={EXAMPLE_RUNS} unit="ms" budget={420} budgetLabel="Budget 420 ms" series={[{ name: 'TTID', color: 'var(--c1)', values: EXAMPLE_TTID }]} />
            </Card>
            <Card title="BarSeries" hint="Ordered bars with a dashed mean; flagged bars in the fail colour.">
              <BarSeries label="Example session TTIDs" unit="ms" decimals={0} mean={374} bars={EXAMPLE_TTID.map((v, i) => ({ label: `${i + 1}`, value: v, flagged: v > 382 }))} />
            </Card>
            <Card title="BarList" hint="Labelled horizontal bars, largest first, each with its value: for names too long to sit under columns. An item's description sits behind a ? (Term).">
              <BarList
                label="Example CPU by thread"
                unit="%"
                decimals={1}
                items={[
                  { label: 'UI Thread', value: 24.8, description: "The app's main thread: input, layout and drawing." },
                  { label: 'RenderThread', value: 12.4, description: "Turns each frame's drawing commands into GPU work." },
                  { label: 'mqt_v_js', value: 6.1, description: "React Native's JavaScript thread." },
                  { label: 'Jit thread pool', value: 2.6, description: 'Compiles often-run code to machine code while the app runs.' },
                  { label: 'HeapTaskDaemon', value: 0.5, description: 'The background garbage collector.' },
                  { label: 'sync-worker', value: 0.3 },
                ]}
              />
            </Card>
            <Card title="MiniBars" hint="The Copilot's inline chart, from a zero baseline.">
              <MiniBars title="Example peak RAM per run" unit="MB" budget={420} labels={EXAMPLE_RUNS} values={[398, 402, 405, 399, 410, 431, 407, 404, 412, 425]} />
            </Card>
          </Grid>
        </Section>

        <Section id="ds-conversation" title="Conversation" intro="The Copilot's parts, docked beside a page.">
          <div className={s.demoPanel}>
            <div className={s.demoPage}>
              <Text variant="small" tone="muted">
                The page reflows beside the panel.
              </Text>
            </div>
            <DockPanel label="Example panel" width={400}>
              <PanelHeader leading={<Avatar size={28} />} title="Copilot" subtitle="Fast · run data on this dashboard" actions={<IconButton icon="close" label="Close" />} />
              <PanelBar>
                <Text variant="label">Context</Text>
                <Chip onRemove={() => undefined} removeLabel="Remove">
                  Run #81
                </Chip>
                <ChipButton>+ Add</ChipButton>
              </PanelBar>
              <PanelBody>
                <Bubble>Why did TTID regress in the latest run?</Bubble>
                <Row gap={12} align="start">
                  <Avatar />
                  <Stack gap={12} grow>
                    <Row gap={10} align="start">
                      <StatusPill tone="pass" />
                      <Text variant="lead" tone="primary" weight={600}>
                        TTID did not move meaningfully.
                      </Text>
                    </Row>
                    <ListButton title="Which step grew the most?" trailing="→" />
                  </Stack>
                </Row>
              </PanelBody>
              <PanelFooter>
                <TextAreaField label="Example message" rows={2} placeholder="Ask about runs, steps or findings." />
              </PanelFooter>
            </DockPanel>
          </div>
        </Section>
      </div>
    </div>
  )
}
