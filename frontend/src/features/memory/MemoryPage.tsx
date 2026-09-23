import { Link } from 'react-router'
import type { Run } from '@/api/types'
import { Card, EmptyState, Eyebrow, Grid, LineChart } from '@/design/components'
import { fmt, signed } from '@/domain/format'
import { metricByKey, valueOf } from '@/domain/metrics'
import { useScope } from '@/domain/scope'

/** What the trace can say about where the memory is. Real device traces carry
 *  the app's total resident memory; a per-runtime split exists only where the
 *  app reports a runtime's own heap (the Hermes heap counter). */
function breakdown(r: Run | null) {
  const rss = r?.memory?.rss?.peak_mb ?? null
  const hermes = r?.memory?.hermes_heap?.peak_mb ?? null
  if (rss == null) return null
  const parts = hermes != null ? [{ name: 'Hermes heap', color: 'var(--c2)', mb: hermes }, { name: 'Rest of process', color: 'var(--c1)', mb: Math.max(0, rss - hermes) }] : [{ name: 'App process', color: 'var(--c1)', mb: rss }]
  return { total: rss, parts }
}

function Bar({ label, b, max, dim }: { label: string; b: NonNullable<ReturnType<typeof breakdown>>; max: number; dim?: boolean }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr 80px', gap: 12, alignItems: 'center', opacity: dim ? 0.6 : 1 }}>
      <span style={{ fontSize: 13, fontWeight: 600 }}>{label}</span>
      <div style={{ display: 'flex', height: 28, background: 'var(--s2)' }}>
        {b.parts.map((p) => (
          <div key={p.name} title={`${p.name} · ${fmt(p.mb)} MB`} style={{ width: `${(p.mb / max) * 100}%`, background: p.color, borderRight: '1px solid var(--s1)', color: '#000', font: '600 11px var(--font-ui)', display: 'flex', alignItems: 'center', paddingLeft: 6, overflow: 'hidden', whiteSpace: 'nowrap' }}>
            {p.mb / max > 0.08 ? fmt(p.mb) : ''}
          </div>
        ))}
      </div>
      <span style={{ textAlign: 'right', fontWeight: 700 }}>{fmt(b.total)} MB</span>
    </div>
  )
}

export function MemoryPage() {
  const { scope, isLoading } = useScope()
  if (isLoading || !scope) return <EmptyState>Loading runs…</EmptyState>
  const { latest, runs, allRuns, benchmarkRun, history } = scope
  if (!latest) return <EmptyState title="No runs yet">Capture a trace to see memory.</EmptyState>
  const base = benchmarkRun ?? allRuns.filter((r) => r.id < latest.id).pop() ?? null
  const cur = breakdown(latest)
  const prev = breakdown(base)
  const max = Math.max(cur?.total ?? 0, prev?.total ?? 0, metricByKey('peak_rss_mb').budget(latest, history.global_budgets) ?? 0) * 1.05 || 1
  const labels = runs.map((r) => `#${r.id}`)
  const hasHermes = runs.some((r) => r.memory?.hermes_heap)
  const perRuntime = !!cur && cur.parts.length > 1

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <Card data-hl="memHero" style={{ padding: 28 }}>
        <Eyebrow>PEAK MEMORY BREAKDOWN</Eyebrow>
        <h2 style={{ margin: '12px 0 20px', font: '800 26px/1.2 var(--font-display)' }}>Three runtimes, one process</h2>
        {cur ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <Bar label={`Run #${latest.id}`} b={cur} max={max} />
            {prev && base && <Bar label={benchmarkRun ? `Benchmark #${base.id}` : `Previous #${base.id}`} b={prev} max={max} dim />}
          </div>
        ) : (
          <EmptyState>No memory samples were recorded for run #{latest.id}.</EmptyState>
        )}
        {cur && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 1, background: 'var(--line)', border: '1px solid var(--line)', marginTop: 20 }}>
            {cur.parts.map((p) => {
              const was = prev?.parts.find((q) => q.name === p.name)?.mb
              const d = was != null ? p.mb - was : null
              return (
                <div key={p.name} style={{ background: 'var(--s1)', padding: 16 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--tx2)' }}>
                    <span style={{ width: 10, height: 10, background: p.color }} />
                    {p.name}
                  </div>
                  <div style={{ font: '700 22px var(--font-display)', marginTop: 8 }}>
                    {fmt(p.mb)} <span style={{ fontSize: 12, color: 'var(--tx3)' }}>MB</span>
                  </div>
                  {d != null && (
                    <div style={{ fontSize: 12, marginTop: 4, fontWeight: 600, color: Math.abs(d) < 2 ? 'var(--tx2)' : d > 0 ? 'var(--fail)' : 'var(--pass)' }}>
                      {Math.abs(d) < 2 ? '= ' : d > 0 ? '▲ ' : '▼ '}
                      {signed(d, 0, ' MB')}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
        {!perRuntime && (
          <p style={{ margin: '16px 0 0', fontSize: 13, lineHeight: 1.6, color: 'var(--tx3)', maxWidth: 760 }}>
            This trace records the app's total resident memory only, so it cannot be split by runtime. A per-runtime breakdown needs the app to
            report each runtime's own heap as a trace counter, as the Hermes heap counter does.
          </p>
        )}
      </Card>
      <Grid min={440}>
        <Card data-hl="peakChart" title="Peak RAM" hint="Highest resident memory of the app's own process, per run.">
          <LineChart
            label="Peak RAM per run"
            labels={labels}
            series={[{ name: 'Peak RAM', color: 'var(--c1)', values: runs.map((r) => valueOf(r, 'peak_rss_mb')) }]}
            budget={metricByKey('peak_rss_mb').budget(latest, history.global_budgets)}
            unit="MB"
          />
        </Card>
        <Card title="RAM growth" hint="Lowest to highest resident memory within each run.">
          <LineChart
            label="RAM growth per run"
            labels={labels}
            series={[{ name: 'RAM growth', color: 'var(--c2)', values: runs.map((r) => valueOf(r, 'rss_growth_mb')) }]}
            budget={metricByKey('rss_growth_mb').budget(latest, history.global_budgets)}
            unit="MB"
          />
        </Card>
      </Grid>
      {hasHermes && (
        <Card title="Hermes heap" hint="The React Native runtime's own heap at its peak, per run.">
          <LineChart label="Hermes heap per run" labels={labels} series={[{ name: 'Hermes heap', color: 'var(--c3)', values: runs.map((r) => r.memory?.hermes_heap?.peak_mb ?? null) }]} unit="MB" />
        </Card>
      )}
      <Card title="Where the growth happens" hint="Growth within a session is attributed to screens on the Screens tab: RAM over time with each screen visit behind it, and the navigation stack held open beneath each screen.">
        <Link to="/screens">Open the session timeline →</Link>
      </Card>
    </section>
  )
}
