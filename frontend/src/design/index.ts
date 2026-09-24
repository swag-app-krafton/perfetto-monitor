/**
 * The Swag Pay Performance design system.
 *
 * Everything the app renders is built from what this module exports; feature
 * code imports from '@/design' only, never from a file inside it. The layers:
 *
 *   foundations  tokens (colour per theme, type, radii, layers, motion) and
 *                the global stylesheet; imported once by the app entry
 *   primitives   layout (Stack, Row, Spacer), Text, Swatch, Kbd, the spacing scale
 *   components   controls, status, containers, overlays, conversation parts
 *   charts       LineChart, StackedBars, BandedTimeline, BarSeries, BarList, MiniBars, Sparkline,
 *                DotBoxPlot, SpanTimeline
 *   hooks        behaviour shared by components (sorting, list keyboard nav)
 *
 * Components are generic: they take data and callbacks as props and know
 * nothing about runs, apps or the API. The living reference is /design-system.
 */

// primitives
export * from './primitives/space'
export * from './primitives/Stack'
export * from './primitives/Text'
export * from './primitives/Swatch'
export * from './primitives/Kbd'

// components
export * from './components/Badge'
export * from './components/Button'
export * from './components/Chat'
export * from './components/Chip'
export * from './components/ChoiceList'
export * from './components/CodeBlock'
export * from './components/DataTable'
export * from './components/DescriptionList'
export * from './components/Dialog'
export * from './components/tableClasses'
export * from './components/Disclosure'
export * from './components/ExpandableTable'
export * from './components/Field'
export * from './components/FlowList'
export * from './components/HelpTip'
export * from './components/Icon'
export * from './components/KpiTile'
export * from './components/Layout'
export * from './components/Legend'
export * from './components/LogConsole'
export * from './components/logLevel'
export * from './components/Menu'
export * from './components/Meter'
export * from './components/Panel'
export * from './components/Popover'
export * from './components/Segmented'
export * from './components/SortHeader'
export * from './components/Stat'
export * from './components/Status'
export * from './components/StatusStrip'
export * from './components/tone'
export * from './components/Stepper'
export * from './components/Switch'
export * from './components/Term'
export * from './components/TermList'
export * from './components/Toast'

// charts
export * from './charts/scale'
export * from './charts/LineChart'
export * from './charts/StackedBars'
export * from './charts/BandedTimeline'
export * from './charts/BarSeries'
export * from './charts/BarList'
export * from './charts/MiniBars'
export * from './charts/Sparkline'
export * from './charts/DotBoxPlot'
export * from './charts/SpanTimeline'

// hooks
export * from './hooks/useSort'
export * from './hooks/useListNav'
