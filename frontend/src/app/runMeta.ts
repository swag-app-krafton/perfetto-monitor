import type { Run, RunDetails } from '@/api/types'
import type { Description } from '@/design'
import { fmt, pathLabel, shortDate } from '@/domain/format'

/** What kind of run this was, from how it was recorded. */
export function runKind(run: Run): string {
  const stress = /^stress(\d+)-s(\d+)$/.exec(run.label ?? '')
  if (stress) return `Stress test #${stress[1]}, session ${Number(stress[2])}`
  if (run.label === 'manual-session') return 'Manual session'
  if (/^(cold|warm)-capture$/.test(run.label ?? '')) return 'Dashboard capture'
  return run.label ? `Label: ${run.label}` : 'Analysed trace'
}

export const startLabel = (kind: string) => `${pathLabel(kind)}${/^(cold|warm)$/.test(kind) ? ' start' : ''}`

/** "vivo V2514 · Android 16", or "iPhone 17 · iOS 27.0 · Simulator on Apple M5 Pro",
 *  from whatever was recorded. */
export function deviceSummary(m: RunDetails, fallback: string | null): string {
  const d = m.device
  if (d.platform === 'ios') {
    const sim = d.simulator ? `Simulator${m.host?.chip ? ` on ${m.host.chip}` : ''}` : null
    return [d.model ?? fallback ?? 'Unknown device', d.os_version ? `iOS ${d.os_version}` : null, sim].filter(Boolean).join(' · ')
  }
  const name = [d.manufacturer && !(d.market_name ?? d.model ?? '').toLowerCase().startsWith(d.manufacturer.toLowerCase()) ? d.manufacturer : null, d.market_name ?? d.model ?? fallback]
    .filter(Boolean)
    .join(' ')
  return [name || 'Unknown device', d.android_release ? `Android ${d.android_release}` : null].filter(Boolean).join(' · ')
}

/** "Swag Pay 2.3.1 (231)", or the app with "version not recorded". */
export function appSummary(m: RunDetails, fallbackName: string | null): string {
  const a = m.app
  const name = a.name ?? fallbackName ?? a.package ?? 'Unknown app'
  const ver = [a.version_name, a.version_code != null ? `(${a.version_code})` : null].filter(Boolean).join(' ')
  return ver ? `${name} ${ver}` : `${name} · version not recorded`
}


const yesNo = (v: boolean | undefined) => (v == null ? null : v ? 'Yes' : 'No')
const withUnit = (v: number | undefined, unit: string, dp = 0) => (v == null ? null : `${fmt(v, dp)} ${unit}`)

/** Every recorded fact about a run, grouped: the run, the app build, the
 *  device, its state when measured, and the trace. */
export function sections(run: Run, m: RunDetails): { title: string; note?: string; items: Description[] }[] {
  const d = m.device
  const a = m.app
  const st = m.state
  const t = m.trace
  const h = m.host ?? {}
  const ios = run.platform === 'ios'
  // A simulator run executed on the Mac, so the Mac's state is the device state that matters.
  const mac = run.simulator
    ? [
        {
          title: 'Mac',
          note: 'The simulator ran on this Mac, so its CPU and load were the run\'s.',
          items: [
            { term: 'Model', value: h.model },
            { term: 'Chip', value: h.chip },
            { term: 'RAM', value: withUnit(h.ram_gb, 'GB') },
            { term: 'macOS', value: h.macos },
            { term: 'Xcode', value: st.xcode },
            { term: 'Power', value: st.host_power === 'ac' ? 'Mains' : st.host_power === 'battery' ? `Battery${st.host_battery_pct != null ? `, ${st.host_battery_pct}%` : ''}` : undefined },
            { term: 'Load (1 min)', value: st.host_load_1m != null ? fmt(st.host_load_1m, 2) : undefined },
            { term: 'Thermal warning', value: yesNo(st.host_thermal_warning) },
          ],
        },
      ]
    : []
  return [
    {
      title: 'Run',
      items: [
        { term: 'Run ID', value: `#${run.id}` },
        { term: 'Recorded', value: shortDate(run.ts, true) + ` (${run.ts})` },
        { term: 'Start', value: startLabel(run.path_kind) },
        { term: 'Kind', value: runKind(run) },
        { term: 'Label', value: run.label },
        { term: 'Verdict', value: run.analysis?.verdict?.toUpperCase() },
        { term: 'Steps from', value: run.derived ? (ios ? "iOS's own launch phases (derived)" : "Android's own slices (derived)") : 'the app\'s step: markers' },
      ],
    },
    {
      title: 'App',
      items: [
        { term: 'App', value: a.name },
        { term: 'Package', value: a.package, mono: true },
        { term: 'Version', value: a.version_name },
        { term: 'Build number', value: a.version_code },
        { term: 'Git SHA', value: a.git_sha, mono: true },
        { term: 'Debuggable build', value: yesNo(a.debuggable) },
        { term: 'Build', value: a.build_type === 'release' ? 'Release' : a.build_type === 'debug' ? 'Debug' : undefined },
        { term: 'JS bundle', value: a.js_bundle === 'hermes' ? 'Hermes bytecode' : a.js_bundle ?? undefined },
        { term: 'Target SDK', value: a.target_sdk },
        { term: 'Min SDK', value: a.min_sdk },
        { term: 'Installed by', value: a.installer, mono: true },
        { term: 'First installed', value: a.first_install },
        { term: 'Last updated', value: a.last_update },
      ],
    },
    {
      title: 'Device',
      items: [
        { term: 'Manufacturer', value: d.manufacturer },
        { term: 'Model', value: d.market_name && d.model && d.market_name !== d.model ? `${d.market_name} (${d.model})` : (d.market_name ?? d.model) },
        { term: 'Codename', value: d.codename },
        { term: 'Android', value: d.android_release && (d.sdk != null ? `${d.android_release} (SDK ${d.sdk})` : d.android_release) },
        { term: 'iOS', value: d.os_version },
        { term: 'Simulator', value: ios ? yesNo(d.simulator) : undefined },
        { term: 'UDID', value: d.udid, mono: true },
        { term: 'Security patch', value: d.security_patch },
        { term: 'Build ID', value: d.build_id, mono: true },
        { term: 'Build type', value: d.build_type },
        { term: 'SoC', value: d.soc },
        { term: 'Hardware', value: d.hardware },
        { term: 'CPU cores', value: d.cpu_cores },
        { term: 'ABI', value: d.abi, mono: true },
        { term: 'RAM', value: withUnit(d.ram_gb, 'GB', 1) },
        { term: 'Screen', value: d.screen && (d.density_dpi ? `${d.screen} · ${d.density_dpi} dpi` : d.screen) },
        { term: 'Refresh rate', value: withUnit(d.refresh_hz, 'Hz') },
        { term: 'Kernel', value: d.kernel, mono: true },
        { term: 'Serial', value: d.serial, mono: true },
        { term: 'Build fingerprint', value: d.fingerprint, mono: true },
      ],
    },
    {
      title: 'Device state',
      note: m.state_moment ? `Read ${m.state_moment}.` : undefined,
      items: [
        { term: 'Battery', value: withUnit(st.battery_pct, '%') },
        { term: 'Battery temperature', value: withUnit(st.battery_temp_c, '°C', 1) },
        { term: 'Charging', value: st.charging },
        { term: 'Thermal status', value: st.thermal_status },
      ],
    },
    ...mac,
    {
      title: 'Trace',
      items: [
        { term: 'File', value: t.path, mono: true },
        { term: 'Size', value: withUnit(t.size_mb, 'MB', 1) },
        { term: 'Length', value: withUnit(t.duration_s, 's', 1) },
        { term: 'Perfetto', value: t.perfetto_version },
        { term: 'Instruments', value: t.xctrace_version },
        { term: 'Trace ID', value: t.uuid, mono: true },
      ],
    },
  ]
}

export const asText = (run: Run, m: RunDetails) =>
  sections(run, m)
    .map((sec) => [`## ${sec.title}`, ...sec.items.filter((i) => i.value != null && i.value !== '').map((i) => `${i.term}: ${String(i.value)}`)].join('\n'))
    .join('\n\n')

