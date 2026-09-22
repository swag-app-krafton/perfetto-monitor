'use strict';
const $ = s => document.querySelector(s);
const tip = $('#tip');
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const SVG = 'http://www.w3.org/2000/svg';
const el = (n, a = {}, kids = []) => {
  const e = document.createElementNS(SVG, n);
  for (const k in a) if (a[k] != null) e.setAttribute(k, a[k]);
  for (const c of [].concat(kids)) e.appendChild(c);
  return e;
};
const fmt = (v, d = 0) => v == null ? '–' : Number(v).toFixed(d);

// Runtime -> categorical slot. Colour follows the runtime (the entity), never rank.
const RUNTIME = {
  'step:bootstrap': 'native', 'step:session_read': 'native',
  'step:camera_open': 'camera', 'step:first_qr_decode': 'camera',
  'step:compose_shell': 'compose',
  'step:hermes_boot': 'rn', 'step:rn_onboarding_surface': 'rn',
  'step:cronet_init': 'native', 'step:remote_config': 'native',
};
const RC = { compose: 'var(--s1)', rn: 'var(--s2)', camera: 'var(--s3)', native: 'var(--s4)' };
const RLABEL = { compose: 'Compose shell', rn: 'Hermes / RN', camera: 'Native camera', native: 'Native / other' };
const PATH_LABEL = { returning_user: 'Returning user', first_run: 'First run',
  cold: 'Cold start', warm: 'Warm start' };
const pathLabel = k => PATH_LABEL[k] || (k ? k[0].toUpperCase() + k.slice(1) : k);

let DATA = null, RANGE = 30, PATH = 'returning_user', APP = 'all';
let SORT = { history: { k: 'id', dir: -1 }, steps: { k: 'start_ms', dir: 1 } };
let FILTER = { verdict: 'all', device: 'all', runtime: 'all', q: '' };
let OPEN_STEP = null;   // step drilled into, null = none
let HIDDEN = new Set();  // runtimes toggled off in the step chart
let MODE = 'critical';   // critical | all | grouped
let TAB = 'overview';    // one tab per performance concern in the architecture
let CMP = { run: null, base: null, data: null, loading: false };  // comparison view
let CAP = { device: null, loading: false, pkg: '', cold: true, duration: 8000,
            q: '', job: null, polling: false };
let STR = { list: null, open: null, detail: null, job: null, polling: false,
            pkg: '', sessions: 5, cold: true, duration: 8000, q: '' };
// The installed list is long (140+ on a real phone); cap what is rendered but
// say so, rather than silently truncating.
const MAN_LIST_LIMIT = 60;
// Each live poll costs an adb pull plus a trace parse, so keep it well clear
// of the server's own 4s cache rather than hammering it.
const LIVE_POLL_MS = 5000;
let MAN = { status: null, pkg: 'com.swag.pay', cold: false, job: null,
            polling: false, since: null, q: '',
            // Live marker feed while recording. `kinds` is the filter: an empty
            // set would mean "show nothing", so it starts with everything on.
            live: null, liveErr: null, livePolling: false,
            kinds: new Set(['screen', 'action', 'nav', 'step']) };
let SCR = {
  runId: null, data: null, loading: false,
  // Sub-tab inside Screens: 'launch' (startup metrics for the same run) or
  // 'usage' (per-screen attribution). A manual session records both, and the
  // launch half was only reachable from the Startup tab, which is driven by a
  // different run picker -- so after a manual run the numbers looked missing.
  view: 'usage',
  // Which screen's per-visit detail is expanded, and which metric it charts.
  open: null, metric: 'cpu_pct_of_wall',
};

const TABS = [
  { id: 'overview', label: 'Overview',  blurb: 'Verdict, budgets and findings for the latest run.' },
  { id: 'startup',  label: 'Startup',   blurb: 'Time to first usable camera frame, and the deferred-work ordering constraint.' },
  { id: 'frames',   label: 'Frame pacing', blurb: 'Slow and frozen frames during sustained scanning, and thermal drift.' },
  { id: 'memory',   label: 'Memory',    blurb: 'Peak RAM usage with three runtimes resident, and growth suggesting orphaned RN surfaces.' },
  { id: 'steps',    label: 'Steps',     blurb: 'Per-step durations, trailing baselines and child-slice breakdown.' },
  { id: 'capture',  label: 'Capture',   blurb: 'Pick an app installed on the connected device and profile it.' },
  { id: 'stress',   label: 'Stress',    blurb: 'Repeat cold starts to separate a real regression from run-to-run noise.' },
  { id: 'manual',   label: 'Manual',    blurb: 'Drive the app by hand. Start tracing, use it, stop and analyse.' },
  { id: 'screens',  label: 'Screens',   blurb: 'Per-screen CPU and RAM, from the app\u2019s own screen and action markers.' },
  { id: 'compare',  label: 'Compare',   blurb: 'Diff any two runs, or any run against the pinned benchmark.' },
  { id: 'history',  label: 'History',   blurb: 'Every recorded run, sortable and filterable. Pin a run as the benchmark here.' },
];

function benchOf(run) {
  // The pinned reference for a run's scope, preferring an exact device match.
  const bs = DATA.benchmarks || [];
  return bs.find(b => b.path_kind === run.path_kind && b.device === run.device)
      || bs.find(b => b.path_kind === run.path_kind && !b.device)
      || null;
}

async function postJSON(url, body) {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
                               body: JSON.stringify(body) });
  return r.json();
}

async function setBenchmark(runId, note) {
  await postJSON('/api/benchmark/set', { run_id: runId, note: note || null });
  await load();           // reload so every view reflects the new reference
}

async function clearBenchmark(runId) {
  await postJSON('/api/benchmark/clear', { run_id: runId });
  await load();
}

async function loadCompare() {
  if (CMP.run == null || CMP.base == null || CMP.run === CMP.base) { CMP.data = null; return; }
  CMP.loading = true;
  try {
    const r = await fetch(`/api/compare?run=${CMP.run}&base=${CMP.base}`);
    CMP.data = await r.json();
  } catch (e) {
    CMP.data = { error: String(e) };
  }
  CMP.loading = false;
}

const MNAMES = { ttff_ms: 'First camera frame', slow_pct: 'Slow frames',
  janky_pct: 'Janky frames', thermal_drift_pct: 'Thermal drift',
  peak_rss_mb: 'Peak RAM usage', rss_growth_mb: 'RAM growth' };
const MUNITS = { ttff_ms: 'ms', slow_pct: '%', janky_pct: '%',
  thermal_drift_pct: '%', peak_rss_mb: 'MB', rss_growth_mb: 'MB' };
const CRITICAL = {
  returning_user: ['step:bootstrap', 'step:session_read', 'step:compose_shell',
                   'step:camera_open', 'step:first_qr_decode'],
  first_run: ['step:bootstrap', 'step:hermes_boot', 'step:rn_onboarding_surface'],
};
const onCritical = st => (PATH in CRITICAL) ? CRITICAL[PATH].includes(st) : true;

function showTip(html, ev) {
  tip.innerHTML = html; tip.classList.add('on');
  const r = tip.getBoundingClientRect();
  let x = ev.clientX + 14, y = ev.clientY - 10;
  if (x + r.width > innerWidth - 8) x = ev.clientX - r.width - 14;
  if (y + r.height > innerHeight - 8) y = innerHeight - r.height - 8;
  tip.style.left = Math.max(8, x) + 'px'; tip.style.top = Math.max(8, y) + 'px';
}
const hideTip = () => tip.classList.remove('on');

function runs() {
  // App scope comes first: runs from different applications are different
  // series, not one trend. Plotting PhonePe, CRED and Google Pay as a single
  // line because they share a path_kind would be meaningless. Path and range
  // then define the charted window; the history filters narrow the table only,
  // so the trend charts keep a stable baseline to read against.
  return DATA.runs
    .filter(r => APP === 'all' || (r.app_pkg || '') === APP)
    .filter(r => r.path_kind === PATH)
    .slice(-RANGE);
}

function appsInHistory() {
  const seen = new Map();
  DATA.runs.forEach(r => {
    if (!r.app_pkg) return;
    if (!seen.has(r.app_pkg)) seen.set(r.app_pkg, { pkg: r.app_pkg, name: r.app_name || r.app_pkg, role: r.app_role, n: 0 });
    seen.get(r.app_pkg).n++;
  });
  return [...seen.values()].sort((a, b) => (a.role !== 'own') - (b.role !== 'own') || a.name.localeCompare(b.name));
}

function filteredRuns(rs) {
  const q = FILTER.q.trim().toLowerCase();
  return rs.filter(r => {
    if (FILTER.verdict !== 'all' && (r.analysis?.verdict || 'none') !== FILTER.verdict) return false;
    if (FILTER.device !== 'all' && (r.device || '') !== FILTER.device) return false;
    if (q) {
      const hay = [r.label, r.git_sha, r.app_version, r.device, r.analysis?.headline]
        .filter(Boolean).join(' ').toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

/* ---------- chart: stacked step durations over runs ---------- */
function stepChart(rs) {
  const W = 1180, H = 330, L = 62, R = 16, T = 14, B = 46;
  const iw = W - L - R, ih = H - T - B;
  const vis = st => !HIDDEN.has(RUNTIME[st] || 'native');

  // Which steps each mode plots. 'critical' is the honest default: it sums only
  // the steps a user actually waits through on this path, so the bar height is a
  // number they experience rather than a cumulative total across parallel tracks.
  const keep = st => (MODE === 'critical' ? onCritical(st) : true) && vis(st);

  const order = [];
  rs.forEach(r => r.steps.forEach(x => { if (keep(x.step) && !order.includes(x.step)) order.push(x.step); }));

  if (MODE === 'grouped') return groupedChart(rs, order, W, L, R, T, iw);

  const totals = rs.map(r => r.steps.filter(x => keep(x.step)).reduce((a, x) => a + x.dur_ms, 0));
  // The budget line belongs to the app under test, not a hardcoded Swag Pay
  // constant -- a derived (competitor) run only gets one if the catalogue states
  // one for that package, which most do not.
  const budget = MODE === 'critical' ? rs.at(-1)?.ttid_budget_ms : null;
  const max = Math.max(...totals, budget || 0, 1) * 1.12;
  const bw = Math.min(30, iw / Math.max(rs.length, 1) * 0.66);
  const x = i => L + (i + 0.5) * (iw / Math.max(rs.length, 1));
  const y = v => T + ih - (v / max) * ih;
  const g = el('g');
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img',
    'aria-label': 'Step durations per run, stacked by runtime' });

  // 45-degree hatch marks a deferred step: the CVD/print-safe secondary encoding,
  // so "off the critical path" is never carried by position alone.
  const defs = el('defs');
  const pat = el('pattern', { id: 'hatch', width: 6, height: 6,
    patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' });
  pat.appendChild(el('rect', { width: 6, height: 6, fill: 'var(--surface-1)', opacity: .001 }));
  pat.appendChild(el('line', { x1: 0, y1: 0, x2: 0, y2: 6,
    stroke: 'var(--surface-1)', 'stroke-width': 2.2, opacity: .55 }));
  defs.appendChild(pat);
  g.appendChild(defs);

  for (let i = 0; i <= 4; i++) {
    const v = max * i / 4;
    g.appendChild(el('line', { x1: L, x2: W - R, y1: y(v), y2: y(v), class: 'gl' }));
    g.appendChild(el('text', { x: L - 9, y: y(v) + 4, class: 'ax', 'text-anchor': 'end' },
      [document.createTextNode(fmt(v))]));
  }
  if (budget) {
    g.appendChild(el('line', { x1: L, x2: W - R, y1: y(budget), y2: y(budget), class: 'bl' }));
    g.appendChild(el('text', { x: W - R, y: y(budget) - 6, class: 'ax',
      'text-anchor': 'end', fill: 'var(--crit)' },
      [document.createTextNode(`budget ${budget}`)]));
  }

  rs.forEach((r, i) => {
    let acc = 0;
    const cx = x(i) - bw / 2;
    const ss = order.map(n => r.steps.find(z => z.step === n)).filter(Boolean);
    ss.forEach((st, k) => {
      const h = (st.dur_ms / max) * ih;
      const top = y(acc + st.dur_ms);
      const last = k === ss.length - 1;
      const hh = Math.max(h - 2, 0.5);
      const rt = last ? 4 : 0;
      const d = last
        ? `M${cx},${top + hh} L${cx},${top + rt} Q${cx},${top} ${cx + rt},${top} L${cx + bw - rt},${top} Q${cx + bw},${top} ${cx + bw},${top + rt} L${cx + bw},${top + hh} Z`
        : `M${cx},${top} h${bw} v${hh} h${-bw} Z`;
      g.appendChild(el('path', { d, fill: RC[RUNTIME[st.step] || 'native'] }));
      if (MODE === 'all' && !onCritical(st.step))
        g.appendChild(el('path', { d, fill: 'url(#hatch)' }));
      acc += st.dur_ms;
    });
    const over = budget && acc > budget;
    const hit = el('rect', { x: cx - 4, y: T, width: bw + 8, height: ih, class: 'hit' });
    hit.addEventListener('mousemove', e => showTip(
      `<b>run ${r.id} &middot; ${esc(r.label || '')}</b>` +
      ss.map(z => `<div class="r"><span>${esc(z.step.replace('step:', ''))}` +
        `${MODE === 'all' && !onCritical(z.step) ? ' <i style="opacity:.6">deferred</i>' : ''}` +
        `</span><b>${fmt(z.dur_ms, 1)} ms</b></div>`).join('') +
      `<div class="r" style="margin-top:5px;border-top:1px solid var(--border);padding-top:4px">` +
      `<span>${MODE === 'critical' ? 'critical path' : 'total'}</span><b>${fmt(acc, 1)} ms</b></div>` +
      (budget ? `<div class="r"><span>budget</span><b>${budget} ms</b></div>` : ''), e));
    hit.addEventListener('mouseleave', hideTip);
    g.appendChild(hit);
    if (over) g.appendChild(el('circle', { cx: x(i), cy: y(acc) - 9, r: 2.8, fill: 'var(--crit)' }));
    if (rs.length <= 22 || i % Math.ceil(rs.length / 18) === 0)
      g.appendChild(el('text', { x: x(i), y: H - B + 17, class: 'ax', 'text-anchor': 'middle' },
        [document.createTextNode(String(r.id))]));
  });
  g.appendChild(el('text', { x: L + iw / 2, y: H - 5, class: 'ax', 'text-anchor': 'middle' },
    [document.createTextNode('run')]));
  g.appendChild(el('text', { x: 13, y: T + ih / 2, class: 'ax', 'text-anchor': 'middle',
    transform: `rotate(-90 13 ${T + ih / 2})` },
    [document.createTextNode(MODE === 'critical' ? 'critical-path time (ms)' : 'cumulative step time (ms)')]));
  svg.appendChild(g);
  return svg;
}

/* Small multiples: one panel per step, each on its own scale, so a 40ms step's
   movement is as readable as a 200ms step's. Stacking hides exactly that. */
function groupedChart(rs, order, W, L, R, T, iw) {
  const cols = Math.min(4, order.length) || 1;
  const rows = Math.ceil(order.length / cols);
  const pw = iw / cols, ph = 112;
  // Height follows the panel count so the card does not reserve dead space.
  const HH = T + rows * ph + 22;
  const svg = el('svg', { viewBox: `0 0 ${W} ${HH}`, role: 'img',
    'aria-label': 'Per-step duration trends, one panel per step' });
  const g = el('g');
  order.forEach((name, idx) => {
    const c = idx % cols, rw = Math.floor(idx / cols);
    const ox = L + c * pw, oy = T + rw * ph;
    const gh = ph - 34, gw = pw - 26;
    const vals = rs.map(r => r.steps.find(z => z.step === name)?.dur_ms ?? null);
    const present = vals.filter(v => v != null);
    if (!present.length) return;
    const bud = rs.at(-1).steps.find(z => z.step === name)?.budget_ms;
    const hi = Math.max(...present, bud || 0) * 1.14, lo = Math.min(...present) * 0.82;
    const xx = i => ox + (rs.length === 1 ? gw / 2 : (i * gw) / (rs.length - 1));
    const yy = v => oy + gh - ((v - lo) / (hi - lo || 1)) * gh;
    const color = RC[RUNTIME[name] || 'native'];
    g.appendChild(el('line', { x1: ox, x2: ox + gw, y1: oy + gh, y2: oy + gh, class: 'gl' }));
    if (bud && bud <= hi)
      g.appendChild(el('line', { x1: ox, x2: ox + gw, y1: yy(bud), y2: yy(bud), class: 'bl' }));
    const pts = vals.map((v, i) => v == null ? null : [xx(i), yy(v)]).filter(Boolean);
    g.appendChild(el('path', { d: 'M' + pts.map(p => p.join(',')).join(' L'), fill: 'none',
      stroke: color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
    const lastV = present.at(-1);
    g.appendChild(el('circle', { cx: pts.at(-1)[0], cy: pts.at(-1)[1], r: 3.4, fill: color,
      stroke: 'var(--surface-1)', 'stroke-width': 2 }));
    g.appendChild(el('text', { x: ox, y: oy - 3, class: 'ax', fill: 'var(--text-primary)',
      'font-weight': '650' }, [document.createTextNode(name.replace('step:', ''))]));
    g.appendChild(el('text', { x: ox + gw, y: oy - 3, class: 'ax', 'text-anchor': 'end' },
      [document.createTextNode(`${fmt(lastV, 1)} ms${bud ? ' / ' + bud : ''}`)]));
    rs.forEach((r, i) => {
      if (vals[i] == null) return;
      const hit = el('rect', { x: xx(i) - 7, y: oy, width: 14, height: gh, class: 'hit' });
      hit.addEventListener('mousemove', e => showTip(
        `<b>${esc(name.replace('step:', ''))} &middot; run ${r.id}</b>` +
        `<div class="r"><span>duration</span><b>${fmt(vals[i], 1)} ms</b></div>` +
        (bud ? `<div class="r"><span>budget</span><b>${bud} ms</b></div>` : ''), e));
      hit.addEventListener('mouseleave', hideTip);
      g.appendChild(hit);
    });
  });
  svg.appendChild(g);
  return svg;
}

/* ---------- chart: TTFF line with budget ---------- */
function lineChart(rs, key, budget, label, color) {
  const W = 1180, H = 210, L = 54, R = 16, T = 14, B = 38;
  const iw = W - L - R, ih = H - T - B;
  const vals = rs.map(r => r[key]).filter(v => v != null);
  if (!vals.length) return el('svg');
  let hi = Math.max(...vals, budget || 0) * 1.14;
  let lo = Math.min(...vals, budget || Infinity) * 0.86;
  if (!(hi > lo)) { hi = (hi || 1) * 1.2 + 1; lo = 0; }
  // Label precision follows tick spacing, so a near-zero series does not print
  // four identical ticks.
  const dec = (hi - lo) / 3 < 0.5 ? 2 : (hi - lo) / 3 < 5 ? 1 : 0;
  const x = i => L + (rs.length === 1 ? iw / 2 : (i * iw) / (rs.length - 1));
  const y = v => T + ih - ((v - lo) / (hi - lo || 1)) * ih;
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': label });
  const g = el('g');
  for (let i = 0; i <= 3; i++) {
    const v = lo + (hi - lo) * i / 3;
    g.appendChild(el('line', { x1: L, x2: W - R, y1: y(v), y2: y(v), class: 'gl' }));
    g.appendChild(el('text', { x: L - 9, y: y(v) + 4, class: 'ax', 'text-anchor': 'end' },
      [document.createTextNode(fmt(v, dec))]));
  }
  if (budget) {
    g.appendChild(el('line', { x1: L, x2: W - R, y1: y(budget), y2: y(budget), class: 'bl' }));
    g.appendChild(el('text', { x: W - R, y: y(budget) - 6, class: 'ax', 'text-anchor': 'end',
      fill: 'var(--crit)' }, [document.createTextNode(`budget ${budget}`)]));
  }
  const pts = rs.map((r, i) => [x(i), y(r[key])]);
  g.appendChild(el('path', { d: 'M' + pts.map(p => p.join(',')).join(' L'), fill: 'none',
    stroke: color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
  rs.forEach((r, i) => {
    const over = budget && r[key] > budget;
    // 2px surface ring keeps overlapping markers separable
    g.appendChild(el('circle', { cx: x(i), cy: y(r[key]), r: over ? 5 : 4,
      fill: over ? 'var(--crit)' : color, stroke: 'var(--surface-1)', 'stroke-width': 2 }));
    const hit = el('rect', { x: x(i) - 11, y: T, width: 22, height: ih, class: 'hit' });
    hit.addEventListener('mousemove', e => showTip(
      `<b>run ${r.id} &middot; ${esc(r.label || '')}</b>` +
      `<div class="r"><span>${esc(label)}</span><b>${fmt(r[key], 1)}</b></div>` +
      (budget ? `<div class="r"><span>budget</span><b>${budget}</b></div>` : '') +
      (r.git_sha ? `<div class="r"><span>sha</span><b>${esc(r.git_sha)}</b></div>` : ''), e));
    hit.addEventListener('mouseleave', hideTip);
    g.appendChild(hit);
  });
  // direct-label the last point: identity is never colour-alone
  const lastV = rs[rs.length - 1][key];
  g.appendChild(el('text', { x: x(rs.length - 1) + 9, y: y(lastV) + 4, class: 'ax',
    fill: 'var(--text-primary)', 'font-weight': '650' }, [document.createTextNode(fmt(lastV, 1))]));
  svg.appendChild(g);
  return svg;
}

/* ---------- multi-series line (same unit, one axis) ---------- */
function multiLine(rs, series, budget, label) {
  const W = 1180, H = 230, L = 58, R = 16, T = 16, B = 40;
  const iw = W - L - R, ih = H - T - B;
  const all = series.flatMap(sr => rs.map(sr.get)).filter(v => v != null);
  if (!all.length) return el('svg');
  const hi = Math.max(...all, budget || 0) * 1.12, lo = Math.min(...all, 0) * 0.9;
  const x = i => L + (rs.length === 1 ? iw / 2 : (i * iw) / (rs.length - 1));
  const y = v => T + ih - ((v - lo) / (hi - lo || 1)) * ih;
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': label });
  const g = el('g');
  for (let i = 0; i <= 3; i++) {
    const v = lo + (hi - lo) * i / 3;
    g.appendChild(el('line', { x1: L, x2: W - R, y1: y(v), y2: y(v), class: 'gl' }));
    g.appendChild(el('text', { x: L - 9, y: y(v) + 4, class: 'ax', 'text-anchor': 'end' },
      [document.createTextNode(fmt(v))]));
  }
  if (budget) {
    g.appendChild(el('line', { x1: L, x2: W - R, y1: y(budget), y2: y(budget), class: 'bl' }));
    g.appendChild(el('text', { x: W - R, y: y(budget) - 6, class: 'ax', 'text-anchor': 'end',
      fill: 'var(--crit)' }, [document.createTextNode(`budget ${budget}`)]));
  }
  series.forEach(sr => {
    const pts = rs.map((r, i) => { const v = sr.get(r); return v == null ? null : [x(i), y(v)]; }).filter(Boolean);
    if (pts.length < 1) return;
    g.appendChild(el('path', { d: 'M' + pts.map(p => p.join(',')).join(' L'), fill: 'none',
      stroke: sr.color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
    g.appendChild(el('circle', { cx: pts.at(-1)[0], cy: pts.at(-1)[1], r: 4, fill: sr.color,
      stroke: 'var(--surface-1)', 'stroke-width': 2 }));
    // direct label so identity never rests on colour alone
    g.appendChild(el('text', { x: pts.at(-1)[0] + 9, y: pts.at(-1)[1] + 4, class: 'ax',
      fill: 'var(--text-primary)', 'font-weight': '650' },
      [document.createTextNode(fmt(sr.get(rs.at(-1)), 1))]));
  });
  rs.forEach((r, i) => {
    const hit = el('rect', { x: x(i) - 11, y: T, width: 22, height: ih, class: 'hit' });
    hit.addEventListener('mousemove', e => showTip(
      `<b>run ${r.id} &middot; ${esc(r.label || '')}</b>` +
      series.map(sr => `<div class="r"><span>${esc(sr.name)}</span><b>${fmt(sr.get(r), 1)}</b></div>`).join('') +
      (budget ? `<div class="r"><span>budget</span><b>${budget}</b></div>` : ''), e));
    hit.addEventListener('mouseleave', hideTip);
    g.appendChild(hit);
  });
  svg.appendChild(g);
  return svg;
}

/* ---------- sortable tables ---------- */
function sortRows(rows, table, accessors) {
  const { k, dir } = SORT[table];
  const get = accessors[k] || (r => r[k]);
  return [...rows].sort((a, b) => {
    const x = get(a), y = get(b);
    if (x == null && y == null) return 0;
    if (x == null) return 1;            // nulls always last
    if (y == null) return -1;
    if (typeof x === 'string' || typeof y === 'string')
      return String(x).localeCompare(String(y)) * dir;
    return (x - y) * dir;
  });
}

function th(table, key, label, cls = '') {
  const a = SORT[table].k === key;
  const arrow = a ? (SORT[table].dir === 1 ? ' \u2191' : ' \u2193') : '';
  return `<th class="sortable ${cls}${a ? ' active' : ''}" data-table="${table}" data-key="${key}"
    role="button" tabindex="0" aria-sort="${a ? (SORT[table].dir === 1 ? 'ascending' : 'descending') : 'none'}"
    >${esc(label)}<span class="arrow">${arrow}</span></th>`;
}

function wireSort() {
  document.querySelectorAll('th.sortable').forEach(h => {
    const go = () => {
      const t = h.dataset.table, k = h.dataset.key;
      // First click on a new column sorts descending for numbers, ascending for text.
      if (SORT[t].k === k) SORT[t].dir *= -1;
      else SORT[t] = { k, dir: (k === 'label' || k === 'step' || k === 'ts') ? 1 : -1 };
      render();
    };
    h.addEventListener('click', go);
    h.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
  });
}

/* ---------- step drill-down ---------- */
function stepDetail(rs, stepName) {
  const series = rs.map(r => ({ run: r, s: r.steps.find(x => x.step === stepName) }))
                   .filter(o => o.s);
  if (!series.length) return '';
  const cur = series[series.length - 1];
  const vals = series.map(o => o.s.dur_ms);
  const med = [...vals].sort((a, b) => a - b)[Math.floor(vals.length / 2)];
  const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
  const sd = Math.sqrt(vals.reduce((a, b) => a + (b - mean) ** 2, 0) / vals.length);
  const mn = Math.min(...vals), mx = Math.max(...vals);
  const delta = cur.s.dur_ms - med;
  const z = sd > 0.01 ? delta / sd : 0;
  const rt = RUNTIME[stepName] || 'native';

  // Per-child history: which child is driving the step's movement.
  const childNames = [];
  series.forEach(o => (o.s.children || []).forEach(c => {
    if (!childNames.includes(c.name)) childNames.push(c.name);
  }));
  const childRows = childNames.map(n => {
    const cv = series.map(o => (o.s.children || []).find(c => c.name === n)?.dur_ms ?? null);
    const present = cv.filter(v => v != null);
    const cmed = present.length ? [...present].sort((a, b) => a - b)[Math.floor(present.length / 2)] : null;
    const now = cv[cv.length - 1];
    return { name: n, now, med: cmed, delta: (now != null && cmed != null) ? now - cmed : null,
             pct: (cur.s.children || []).find(c => c.name === n)?.pct_of_step ?? null,
             spark: cv };
  }).sort((a, b) => (b.now ?? -1) - (a.now ?? -1));

  const stat = (k, v, unit = 'ms', d = 1) =>
    `<div class="mini"><div class="k">${esc(k)}</div><div class="v">${fmt(v, d)}<span>${unit}</span></div></div>`;

  return `<div class="drill">
    <div class="drill-head">
      <div><i style="background:${RC[rt]}"></i><b>${esc(stepName.replace('step:', ''))}</b>
        <span class="tag">${esc(RLABEL[rt])}</span></div>
      <button class="close" id="closedrill">Close</button>
    </div>
    <div class="minis">
      ${stat('this run', cur.s.dur_ms)}
      ${stat('median', med)}
      ${stat('delta', delta)}
      ${stat('z-score', z, '', 2)}
      ${stat('stdev', sd)}
      ${stat('min', mn)}
      ${stat('max', mx)}
      ${cur.s.budget_ms ? stat('% of budget', cur.s.dur_ms / cur.s.budget_ms * 100, '%', 0) : ''}
    </div>
    <div class="sparkwrap" id="stepspark"></div>
    <h3>Child slices in run ${cur.run.id}</h3>
    <p class="hint">Direct children only, plus untraced self-time, so the breakdown sums to ${fmt(cur.s.dur_ms, 1)} ms.</p>
    <div class="scroll"><table class="tight">
      <thead><tr><th>Child slice</th><th class="num">This run</th><th class="num">Median</th>
        <th class="num">Delta</th><th class="num">% of step</th><th>Trend</th></tr></thead>
      <tbody>${childRows.map(c => `<tr${c.name.startsWith('(self') ? ' class="selfrow"' : ''}>
        <td>${esc(c.name)}</td>
        <td class="num">${c.now == null ? '\u2013' : fmt(c.now, 1) + ' ms'}</td>
        <td class="num" style="color:var(--text-muted)">${c.med == null ? '\u2013' : fmt(c.med, 1)}</td>
        <td class="num ${c.delta > 0.5 ? 'up' : c.delta < -0.5 ? 'dn' : ''}">${c.delta == null ? '\u2013' : (c.delta > 0 ? '+' : '') + fmt(c.delta, 1)}</td>
        <td class="num">${c.pct == null ? '\u2013' : fmt(c.pct, 0) + '%'}</td>
        <td class="sparkcell" data-spark="${esc(JSON.stringify(c.spark))}"></td>
      </tr>`).join('')}</tbody>
    </table></div>
  </div>`;
}

function sparkline(vals, w = 110, h = 22) {
  const v = vals.filter(x => x != null);
  if (v.length < 2) return el('svg', { width: w, height: h });
  const lo = Math.min(...v), hi = Math.max(...v), rng = (hi - lo) || 1;
  const svg = el('svg', { width: w, height: h, viewBox: `0 0 ${w} ${h}` });
  const pts = vals.map((x, i) => x == null ? null
    : [2 + (i * (w - 4)) / (vals.length - 1), h - 3 - ((x - lo) / rng) * (h - 6)]);
  const segs = [];
  let run = [];
  pts.forEach(p => { if (p) run.push(p); else { if (run.length > 1) segs.push(run); run = []; } });
  if (run.length > 1) segs.push(run);
  segs.forEach(sg => svg.appendChild(el('path', {
    d: 'M' + sg.map(p => p.join(',')).join(' L'), fill: 'none',
    stroke: 'var(--text-secondary)', 'stroke-width': 1.5, 'stroke-linecap': 'round' })));
  const last = pts.filter(Boolean).pop();
  if (last) svg.appendChild(el('circle', { cx: last[0], cy: last[1], r: 2.6,
    fill: 'var(--text-primary)' }));
  return svg;
}

/* ---------- capture ---------- */
async function loadDevice(force) {
  if (CAP.device && !force) return;
  CAP.loading = true;
  try {
    CAP.device = await (await fetch('/api/device')).json();
  } catch (e) {
    CAP.device = { connected: false, error: String(e) };
  }
  CAP.loading = false;
}

async function startCapture() {
  const body = { pkg: CAP.pkg, cold: CAP.cold, duration_ms: CAP.duration };
  const r = await postJSON('/api/capture/start', body);
  if (r.error) { CAP.job = { state: 'error', error: r.error, log: [] }; render(); return; }
  CAP.job = { id: r.job_id, state: 'queued', log: [] };
  render();
  pollCapture(r.job_id);
}

async function pollCapture(jid) {
  if (CAP.polling) return;
  CAP.polling = true;
  // The capture runs on the server; poll until it settles. A capture is
  // seconds-to-a-minute of work, so 1s is frequent enough to feel live without
  // hammering the endpoint.
  while (true) {
    await new Promise(r => setTimeout(r, 1000));
    let j;
    try {
      j = await (await fetch(`/api/jobs?id=${encodeURIComponent(jid)}`)).json();
    } catch (e) { break; }
    CAP.job = j;
    render();
    if (j.state === 'done' || j.state === 'error') break;
  }
  CAP.polling = false;
  // A finished capture adds a run, so refresh history and jump to it.
  if (CAP.job && CAP.job.state === 'done' && CAP.job.result) {
    const res = CAP.job.result;
    await load();
    PATH = res.path_kind || PATH;
    render();
  }
}

/* ---------- stress tests ---------- */
async function loadStress(force) {
  if (STR.list && !force) return;
  try { STR.list = (await (await fetch('/api/stress')).json()).stress_tests || []; }
  catch (e) { STR.list = []; }
}

async function loadStressDetail(id) {
  try { STR.detail = await (await fetch(`/api/stress?id=${id}`)).json(); }
  catch (e) { STR.detail = { error: String(e) }; }
}

async function startStress() {
  const r = await postJSON('/api/stress/start', {
    pkg: STR.pkg, sessions: STR.sessions, cold: STR.cold, duration_ms: STR.duration });
  if (r.error) { STR.job = { state: 'error', error: r.error, log: [] }; render(); return; }
  STR.job = { id: r.job_id, state: 'queued', log: [] };
  render();
  pollStress(r.job_id);
}

async function pollStress(jid) {
  if (STR.polling) return;
  STR.polling = true;
  while (true) {
    await new Promise(r => setTimeout(r, 1200));
    let j;
    try { j = await (await fetch(`/api/jobs?id=${encodeURIComponent(jid)}`)).json(); }
    catch (e) { break; }
    STR.job = j;
    // A stress test writes rows as it goes, so the live table fills in.
    if (j.stress_id) { STR.open = j.stress_id; await loadStressDetail(j.stress_id); }
    render();
    if (j.state === 'done' || j.state === 'error') break;
  }
  STR.polling = false;
  await loadStress(true);
  if (STR.job && STR.job.result && STR.job.result.stress_id) {
    STR.open = STR.job.result.stress_id;
    await loadStressDetail(STR.open);
  }
  await load();
}

/* Sparkline-style dot plot of session values, so spread is visible at a glance
   rather than hidden behind a mean. */
function sessionPlot(sessions, key, budget, label, color) {
  const W = 1180, H = 200, L = 54, R = 20, T = 16, B = 40;
  const iw = W - L - R, ih = H - T - B;
  const vals = sessions.map(s => s[key]).filter(v => v != null && v > 0);
  if (!vals.length) return el('svg');
  let hi = Math.max(...vals, budget || 0) * 1.12, lo = Math.min(...vals) * 0.85;
  if (!(hi > lo)) { hi = (hi || 1) * 1.2 + 1; lo = 0; }
  const dec = (hi - lo) / 3 < 5 ? 1 : 0;
  const x = i => L + (sessions.length === 1 ? iw / 2 : (i * iw) / (sessions.length - 1));
  const y = v => T + ih - ((v - lo) / (hi - lo || 1)) * ih;
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': label });
  const g = el('g');
  for (let i = 0; i <= 3; i++) {
    const v = lo + (hi - lo) * i / 3;
    g.appendChild(el('line', { x1: L, x2: W - R, y1: y(v), y2: y(v), class: 'gl' }));
    g.appendChild(el('text', { x: L - 9, y: y(v) + 4, class: 'ax', 'text-anchor': 'end' },
      [document.createTextNode(fmt(v, dec))]));
  }
  const med = [...vals].sort((a, b) => a - b)[Math.floor(vals.length / 2)];
  g.appendChild(el('line', { x1: L, x2: W - R, y1: y(med), y2: y(med),
    stroke: 'var(--text-muted)', 'stroke-width': 1.5, 'stroke-dasharray': '5 4' }));
  g.appendChild(el('text', { x: W - R, y: y(med) - 6, class: 'ax', 'text-anchor': 'end' },
    [document.createTextNode(`median ${fmt(med, dec)}`)]));
  if (budget) {
    g.appendChild(el('line', { x1: L, x2: W - R, y1: y(budget), y2: y(budget), class: 'bl' }));
  }
  const pts = sessions.map((s, i) => s[key] != null && s[key] > 0 ? [x(i), y(s[key])] : null);
  const seq = pts.filter(Boolean);
  if (seq.length > 1)
    g.appendChild(el('path', { d: 'M' + seq.map(p => p.join(',')).join(' L'), fill: 'none',
      stroke: color, 'stroke-width': 2, 'stroke-linejoin': 'round', opacity: .55 }));
  sessions.forEach((s, i) => {
    if (!pts[i]) {
      // A failed session is drawn as a gap marker rather than omitted, so the
      // reader can see it was attempted.
      g.appendChild(el('text', { x: x(i), y: T + ih + 16, class: 'ax',
        'text-anchor': 'middle', fill: 'var(--crit)' }, [document.createTextNode('✗')]));
      return;
    }
    g.appendChild(el('circle', { cx: pts[i][0], cy: pts[i][1], r: 5, fill: color,
      stroke: 'var(--surface-1)', 'stroke-width': 2 }));
    const hit = el('rect', { x: x(i) - 13, y: T, width: 26, height: ih, class: 'hit' });
    hit.addEventListener('mousemove', e => showTip(
      `<b>session ${s.seq}</b><div class="r"><span>${esc(label)}</span><b>${fmt(s[key], 1)}</b></div>`
      + (s.run_id ? `<div class="r"><span>run</span><b>${s.run_id}</b></div>` : ''), e));
    hit.addEventListener('mouseleave', hideTip);
    g.appendChild(hit);
  });
  sessions.forEach((s, i) => g.appendChild(el('text', { x: x(i), y: H - B + 17,
    class: 'ax', 'text-anchor': 'middle' }, [document.createTextNode(String(s.seq))])));
  g.appendChild(el('text', { x: L + iw / 2, y: H - 5, class: 'ax', 'text-anchor': 'middle' },
    [document.createTextNode('session')]));
  svg.appendChild(g);
  return svg;
}

/* ---------- manual mode ---------- */
async function loadManualStatus(force) {
  if (MAN.status && !force) return;
  try { MAN.status = await (await fetch('/api/manual/status')).json(); }
  catch (e) { MAN.status = { device: false, recording: false }; }
}

async function manualStart() {
  const r = await postJSON('/api/manual/start', { pkg: MAN.pkg, cold: MAN.cold });
  if (r.error) { MAN.job = { state: 'error', error: r.error, log: [] }; render(); return; }
  MAN.since = Date.now();
  MAN.job = null;
  MAN.live = null; MAN.liveErr = null;
  await loadManualStatus(true);
  render();
  pollLiveMarkers();
}

async function manualStop() {
  const r = await postJSON('/api/manual/stop', { pkg: MAN.pkg });
  if (r.error) { MAN.job = { state: 'error', error: r.error, log: [] }; render(); return; }
  MAN.job = { id: r.job_id, state: 'queued', log: [] };
  MAN.since = null;
  render();
  pollManual(r.job_id);
}

async function manualAbort() {
  await postJSON('/api/manual/abort', {});
  MAN.since = null; MAN.job = null;
  await loadManualStatus(true);
  render();
}

/* Live marker feed.

   Each poll pulls the partial trace off the device and parses it, which costs
   real time on a long session, so this is a self-rescheduling loop rather than
   a fixed interval: the next poll is scheduled only once the previous one has
   answered. A setInterval would pile overlapping requests onto a capture that
   is already busy. */
async function pollLiveMarkers() {
  if (MAN.livePolling) return;
  MAN.livePolling = true;
  while (MAN.status && MAN.status.recording) {
    try {
      const r = await (await fetch('/api/manual/live')).json();
      if (!r.recording) break;
      MAN.live = r; MAN.liveErr = null;
    } catch (e) {
      // A dropped poll is not worth tearing the view down over: keep the last
      // markers on screen and say the feed is stale.
      MAN.liveErr = String(e);
    }
    if (TAB === 'manual') renderLiveFeed();
    await new Promise(r => setTimeout(r, LIVE_POLL_MS));
  }
  MAN.livePolling = false;
}

/* Repaint only the feed, not the whole page.

   A full render() would rebuild the package search box and steal focus, and
   restart the elapsed timer, every few seconds while the user is trying to
   drive the app. */
function renderLiveFeed() {
  const host = $('#manlive');
  if (host) host.innerHTML = liveFeedHTML();
  bindLiveFilters();
}

function liveFeedHTML() {
  const L = MAN.live;
  if (!L) return '<p class="empty">Waiting for the first markers\u2026</p>';
  const counts = L.counts || {};
  const all = L.events || [];
  const shown = all.filter(e => MAN.kinds.has(e.kind));
  const KINDS = [['screen', 'Screens'], ['action', 'Actions'],
                 ['nav', 'Navigations'], ['step', 'Steps']];
  return `
    <div class="ctl" style="margin-bottom:10px;flex-wrap:wrap">
      ${KINDS.map(([k, l]) => `<button class="seg${MAN.kinds.has(k) ? ' on' : ''}"
        data-lk="${k}">${l} <span class="count">${counts[k] || 0}</span></button>`).join('')}
      <span class="count">${shown.length} of ${all.length} shown</span>
      ${L.current_screen ? `<span class="pill pass">on ${esc(L.current_screen)}${
          L.current_screen_kind ? ` \u00b7 ${esc(L.current_screen_kind)}` : ''}</span>` : ''}
    </div>
    ${MAN.liveErr ? `<p class="hint" style="color:var(--warn)">Feed stale: ${esc(MAN.liveErr)}</p>` : ''}
    ${L.note ? `<p class="hint">${esc(L.note)}</p>` : ''}
    ${L.truncated ? `<p class="hint">Showing the most recent ${all.length} of ${L.total} markers.</p>` : ''}
    <div class="scroll" style="max-height:320px"><table>
      <thead><tr><th>At</th><th>Kind</th><th>Marker</th><th>Duration</th></tr></thead>
      <tbody>${shown.slice().reverse().map(e => `<tr>
        <td style="color:var(--text-secondary);font-size:12px">${(e.at_ms / 1000).toFixed(1)}s</td>
        <td><span class="tag">${e.kind}</span>${e.screen_kind_label
            ? ` <span class="tag">${esc(e.screen_kind_label)}</span>` : ''}</td>
        <td>${e.step ? '<span style="color:var(--text-secondary)">\u21b3 </span>' : ''}${esc(e.name)}${e.open_ended ? ' <span class="pill pass">open</span>' : ''}</td>
        <td style="color:var(--text-secondary);font-size:12px">${e.duration_ms != null ? e.duration_ms + 'ms' : '\u2014'}</td>
      </tr>`).join('') || `<tr><td colspan="4" class="empty">${all.length
          ? 'No markers of the selected kinds yet.'
          : 'No markers yet. Drive the app to produce some.'}</td></tr>`}</tbody>
    </table></div>`;
}

function bindLiveFilters() {
  document.querySelectorAll('[data-lk]').forEach(b => b.onclick = () => {
    const k = b.dataset.lk;
    // Never let the filter empty out completely: an empty set renders a blank
    // table that looks like "no markers found", which is the bug this whole
    // view exists to make impossible to misread.
    if (MAN.kinds.has(k)) { if (MAN.kinds.size > 1) MAN.kinds.delete(k); }
    else MAN.kinds.add(k);
    renderLiveFeed();
  });
}

async function pollManual(jid) {
  if (MAN.polling) return;
  MAN.polling = true;
  while (true) {
    await new Promise(r => setTimeout(r, 1200));
    let j;
    try { j = await (await fetch(`/api/jobs?id=${encodeURIComponent(jid)}`)).json(); }
    catch (e) { break; }
    MAN.job = j;
    render();
    if (j.state === 'done' || j.state === 'error') break;
  }
  MAN.polling = false;
  await loadManualStatus(true);
  if (MAN.job && MAN.job.state === 'done' && MAN.job.result) {
    const res = MAN.job.result;
    await load();
    // A manual session usually carries screen markers; if it does, that view
    // is more informative than the startup one, so land there.
    if (res.screens) { SCR.runId = res.run_id; SCR.data = null; TAB = 'screens'; }
    else if (res.path_kind) { PATH = res.path_kind; }
    render();
  }
}

async function loadScreens(runId) {
  SCR.loading = true; render();
  try { SCR.data = await (await fetch(`/api/screens?run=${runId}`)).json(); }
  catch (e) { SCR.data = { error: String(e) }; }
  SCR.loading = false;
}

/* One bar per visit to a single screen.

   A per-screen total cannot distinguish twelve even visits from eleven cheap
   ones and a pathological twelfth, and it is nearly always the twelfth that is
   the bug. Visits are drawn in the order they happened so a trend -- a screen
   that gets more expensive each time it is opened, the signature of state
   accumulating across visits -- is visible as a slope rather than hidden in a
   sum. The mean is drawn as a reference line, and any visit more than two
   standard deviations from it is called out. */
const METRICS = {
  cpu_pct_of_wall: { label: 'CPU % of wall', unit: '%', dp: 1 },
  cpu_ms: { label: 'CPU time', unit: ' ms', dp: 1 },
  peak_rss_mb: { label: 'Peak RAM', unit: ' MB', dp: 1 },
  rss_delta_mb: { label: 'RAM growth', unit: ' MB', dp: 1 },
  duration_ms: { label: 'Wall time', unit: ' ms', dp: 1 },
};

function visitBars(row, metric) {
  const m = METRICS[metric] || METRICS.cpu_pct_of_wall;
  const visits = row.visit_list || [];
  const stat = (row.stats || {})[metric] || {};
  const W = 1180, H = 240, L = 58, R = 18, T = 16, B = 42;
  const iw = W - L - R, ih = H - T - B;
  const vals = visits.map(v => v[metric]).filter(x => x != null);
  const max = Math.max(...vals, stat.mean || 0, 1);
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img',
    'aria-label': `${m.label} for each visit to ${row.route}` });
  const g = el('g');
  const y = v => T + ih - (v / max) * ih;

  // Horizontal grid, so a bar can be read against a value without a tooltip.
  for (let i = 0; i <= 4; i++) {
    const gv = (max / 4) * i;
    g.appendChild(el('line', { x1: L, x2: W - R, y1: y(gv), y2: y(gv),
      stroke: 'var(--grid)', 'stroke-width': 1 }));
    g.appendChild(el('text', { x: L - 8, y: y(gv) + 4, class: 'ax',
      'text-anchor': 'end' }, [document.createTextNode(fmt(gv, m.dp))]));
  }

  const bw = Math.max(iw / Math.max(visits.length, 1) - 6, 3);
  visits.forEach((v, i) => {
    const val = v[metric];
    const x = L + (iw / Math.max(visits.length, 1)) * i + 3;
    if (val == null) {
      // Absent is not zero: a visit with no RAM samples must not read as a
      // visit that used none.
      g.appendChild(el('text', { x: x + bw / 2, y: T + ih - 4, class: 'ax',
        'text-anchor': 'middle', fill: 'var(--text-muted)' },
        [document.createTextNode('–')]));
    } else {
      const isOut = (v.outlier || {})[metric];
      g.appendChild(el('rect', {
        x, y: y(val), width: bw, height: Math.max(T + ih - y(val), 1), rx: 3,
        fill: isOut ? 'var(--crit)' : 'var(--s2)' }));
    }
    g.appendChild(el('text', { x: x + bw / 2, y: H - B + 16, class: 'ax',
      'text-anchor': 'middle' }, [document.createTextNode(String(v.index))]));

    const hit = el('rect', { x: x - 3, y: T, width: bw + 6, height: ih, class: 'hit' });
    hit.addEventListener('mousemove', e => {
      const dev = (stat.mean != null && val != null && stat.stdev)
        ? (val - stat.mean) / stat.stdev : null;
      showTip(
        `<b>${esc(row.route)} · visit ${v.index}</b>` +
        `<div class="r"><span>${m.label}</span><b>${val == null ? 'no data' : fmt(val, m.dp) + m.unit}</b></div>` +
        (stat.mean != null ? `<div class="r"><span>mean of ${row.visits} visits</span><b>${fmt(stat.mean, m.dp)}${m.unit}</b></div>` : '') +
        (dev != null ? `<div class="r"><span>deviation</span><b>${dev >= 0 ? '+' : ''}${fmt(dev, 1)} sd</b></div>` : '') +
        ((v.outlier || {})[metric] ? '<div class="r"><span>flagged</span><b>outlier, &gt;2 sd from mean</b></div>' : '') +
        `<div class="r"><span>avg CPU</span><b>${v.cpu_pct_of_wall == null ? '–' : fmt(v.cpu_pct_of_wall, 1) + '%'} of wall</b></div>` +
        `<div class="r"><span>avg RAM</span><b>${v.peak_rss_mb == null ? '–' : fmt(v.peak_rss_mb, 1) + ' MB peak'}</b></div>` +
        `<div class="r"><span>wall time</span><b>${fmt(v.duration_ms, 1)} ms</b></div>` +
        (v.stack && v.stack.length > 1
          ? `<div class="r"><span>stack</span><b>${esc(v.stack.join(' \u203a '))}</b></div>` +
            `<div class="r"><span>held beneath</span><b>${esc((v.beneath || []).join(', '))}</b></div>`
          : '<div class="r"><span>stack</span><b>root, nothing beneath</b></div>') +
        (v.open_ended ? '<div class="r"><span>note</span><b>still open when tracing stopped</b></div>' : ''), e);
    });
    hit.addEventListener('mouseleave', hideTip);
    g.appendChild(hit);
  });

  if (stat.mean != null && vals.length > 1) {
    g.appendChild(el('line', { x1: L, x2: W - R, y1: y(stat.mean), y2: y(stat.mean),
      stroke: 'var(--text-secondary)', 'stroke-width': 1.5, 'stroke-dasharray': '5 4' }));
    g.appendChild(el('text', { x: W - R, y: y(stat.mean) - 6, class: 'ax',
      'text-anchor': 'end', fill: 'var(--text-secondary)' },
      [document.createTextNode(`mean ${fmt(stat.mean, m.dp)}${m.unit}`)]));
  }

  g.appendChild(el('text', { x: L + iw / 2, y: H - 6, class: 'ax', 'text-anchor': 'middle' },
    [document.createTextNode(`visit number (in the order they happened) — ${m.label}`)]));
  svg.appendChild(g);
  return svg;
}

/* Cost grouped by how deep the screen sat in the navigation stack.

   A per-screen number says what the screen on top cost. It cannot say what was
   still held open underneath it -- and a screen pushed onto two others has not
   replaced them: those are still alive, still holding their views and bitmaps.
   That is usually the answer when a screen's own work looks cheap but RAM is
   high while it is showing. */
function stackViewHTML(d) {
  const rows = d.stack_summary || [];
  if (!rows.length) return '';
  const deepest = rows[rows.length - 1];
  return `
    <div class="card">
      <h2>Navigation stack</h2>
      <p class="hint">Reconstructed by replaying the app's own push, pop and tab-reset
        markers, so this is the same back stack the app held \u2014 not an inference from
        overlapping slices (screen slices never overlap; only one is open at a time).
        Deepest stack reached: <b>${d.max_depth}</b>.</p>
      <div class="scroll"><table>
        <thead><tr><th>Depth</th><th class="num">Visits</th><th class="num">Wall ms</th>
          <th class="num">CPU % of wall</th><th class="num">Peak RAM</th>
          <th>Screens at this depth</th><th>Held open beneath</th></tr></thead>
        <tbody>${rows.map(r => `<tr>
          <td><b>${r.depth}</b></td>
          <td class="num">${r.visits}</td>
          <td class="num">${fmt(r.total_ms, 1)}</td>
          <td class="num">${r.mean_cpu_pct == null ? '\u2013' : fmt(r.mean_cpu_pct, 1) + '%'}</td>
          <td class="num ${(r.peak_rss_mb || 0) > 400 ? 'up' : ''}">${r.peak_rss_mb == null ? '\u2013' : fmt(r.peak_rss_mb, 1) + ' MB'}</td>
          <td style="font-size:12px">${r.routes.map(([k, n]) => `${esc(k)}${n > 1 ? ` \u00d7${n}` : ''}`).join(', ')}</td>
          <td style="font-size:12px;color:var(--text-secondary)">${r.beneath.length
            ? r.beneath.map(([k, n]) => `${esc(k)}${n > 1 ? ` \u00d7${n}` : ''}`).join(', ')
            : '\u2014 nothing, this is the root'}</td>
        </tr>`).join('')}</tbody>
      </table></div>
      ${deepest && deepest.depth > 1 && deepest.mean_cpu_pct != null
          && deepest.peak_rss_mb != null && deepest.mean_cpu_pct < 25 ? `
        <p class="hint" style="margin-top:9px">At depth ${deepest.depth} the screen on top is
          using only ${fmt(deepest.mean_cpu_pct, 1)}% CPU yet ${fmt(deepest.peak_rss_mb, 1)} MB is
          resident. Work is not what is costing memory there \u2014
          ${deepest.beneath.map(([k]) => esc(k)).join(' and ')}
          ${deepest.beneath.length === 1 ? 'is' : 'are'} still held open beneath it.</p>` : ''}
    </div>`;
}

/* Launch metrics for the run selected in the Screens tab.

   A manual session produces one trace that carries both halves: the startup
   steps and the screen markers. The Startup tab reads the *globally* selected
   run, so after a manual capture the user had to switch tabs and re-pick the
   same run to see its launch numbers -- which read as the numbers not existing.
   This shows them beside the usage view, for the run already chosen here. */
function launchViewHTML(run) {
  if (!run) {
    return '<div class="card"><p class="empty">Select a run to see its launch metrics.</p></div>';
  }
  const steps = run.steps || [];
  const ttff = run.ttff_ms;
  const label = run.derived ? 'Time to initial display' : 'First camera frame';
  if (!ttff && !steps.length) {
    return `<div class="card"><h2>No launch in this trace</h2>
      <p class="hint">This run records no startup steps. A manual session that begins with the
        app already open has no launch to measure \u2014 trace a cold start to capture one.
        The screen usage view is unaffected.</p></div>`;
  }
  const worst = steps.reduce((a, b) => (b.dur_ms > (a?.dur_ms || 0) ? b : a), null);
  // Step timestamps are boot-relative, which is a number in the tens of
  // millions and says nothing. Rebase on the first step so the column reads as
  // "this far into the launch", which is the only comparison worth making.
  const t0 = steps.length ? Math.min(...steps.map(st => st.start_ms || 0)) : 0;
  return `
    <div class="tiles">
      ${tileHTML(label, ttff, 'ms', run.ttid_budget_ms, null, 1)}
      ${tileHTML('Startup steps', steps.length, '', null, null, 0)}
      ${tileHTML('Slowest step', worst ? worst.dur_ms : null, 'ms', null, null, 1)}
    </div>
    <div class="card">
      <h2>Startup steps</h2>
      <p class="hint">Each stage of the launch this trace recorded, in order, with the
        slices that dominate it. Path: ${esc(run.path_kind || 'unknown')}.</p>
      <div class="scroll"><table>
        <thead><tr><th>Step</th><th class="num">Start</th><th class="num">Duration</th>
          <th>Dominated by</th></tr></thead>
        <tbody>${steps.map(st => {
          const kids = (st.children || []).slice(0, 2)
            .map(k => `${esc(k.name)} ${fmt(k.dur_ms, 1)}ms`).join(', ');
          return `<tr>
            <td>${esc(String(st.step || '').replace(/^step:/, ''))}</td>
            <td class="num" style="color:var(--text-secondary)">+${fmt((st.start_ms || 0) - t0, 1)} ms</td>
            <td class="num ${st.over_budget ? 'up' : ''}">${fmt(st.dur_ms, 2)} ms</td>
            <td style="color:var(--text-secondary);font-size:12px">${kids || '\u2014'}</td>
          </tr>`; }).join('')}</tbody>
      </table></div>
      <p class="hint" style="margin-top:9px">Start is relative to the first step. For the full
        critical-path breakdown, budgets and ordering checks, open the <b>Startup</b> tab.</p>
    </div>`;
}

/* ---------- render ---------- */
function tabBar() {
  return `<nav class="tabs" role="tablist">${TABS.map(t => `
    <button role="tab" class="tab${TAB === t.id ? ' on' : ''}" data-tab="${t.id}"
      aria-selected="${TAB === t.id}">${esc(t.label)}</button>`).join('')}</nav>`;
}

function memBudget(key) {
  // Memory ceilings are our own product decisions, not universal facts, so they
  // are not asserted against a derived (competitor) run.
  const cur = runs().at(-1);
  if (!cur || cur.derived) return null;
  return DATA.global_budgets[key];
}

function tileHTML(k, v, unit, budget, prevV, d) {
  // A startup metric of exactly 0 means it could not be measured, not that it
  // was instant. Rendering it as a value -- and worse, as a large improvement
  // over the previous run -- presents a failed measurement as a win.
  if ((v === 0 || v == null) && /camera frame|initial display/i.test(k)) {
    return `<div class="tile">
      <div class="k">${esc(k)}</div>
      <div class="v" style="font-size:19px;color:var(--text-muted)">not measured</div>
      <div class="m">no startup marker in this trace</div></div>`;
  }
  const bad = budget != null && v > budget;
  const warnb = budget != null && v > budget * 0.9 && !bad;
  const dl = (a, b) => {
    if (b == null || a == null) return '';
    const diff = a - b;
    if (Math.abs(diff) < Math.pow(10, -d) / 2)
      return '<span style="color:var(--text-muted)">no change</span> vs prev';
    return `<span class="${diff > 0 ? 'up' : 'dn'}">${diff > 0 ? '▲' : '▼'} ${fmt(Math.abs(diff), d)}</span> vs prev`;
  };
  return `<div class="tile ${bad ? 'bad' : warnb ? 'warnb' : ''}">
    <div class="k">${esc(k)}</div>
    <div class="v">${fmt(v, d)}<span style="font-size:13px;color:var(--text-muted)">${unit}</span></div>
    <div class="m">${budget != null ? `budget ${budget}${unit} &middot; ` : ''}${dl(v, prevV)}</div></div>`;
}

function findingsHTML(an, opts = {}) {
  let fs = an.findings || [];
  if (opts.kinds) fs = fs.filter(f => opts.kinds.includes(f.kind));
  if (opts.runtimes) fs = fs.filter(f => opts.runtimes.includes(f.runtime));
  // A budget_breach can be about startup, frames or memory, so tab views also
  // match on subject keywords rather than trusting `kind` alone.
  if (opts.about) {
    const hay = f => [f.title, f.evidence, f.kind, f.architectural_risk].join(' ');
    const rx = new RegExp(opts.about.join('|'), 'i');
    fs = fs.filter(f => rx.test(hay(f)));
    // "first camera frame" contains "frame" but is a startup finding, so each view
    // also excludes the phrases that belong to another tab.
    if (opts.notAbout) {
      const nrx = new RegExp(opts.notAbout.join('|'), 'i');
      fs = fs.filter(f => !nrx.test(hay(f)));
    }
  }
  if (!fs.length) return `<p class="empty">${esc(opts.emptyMsg || 'No findings in this area for the latest run.')}</p>`;
  return fs.map(f => `<div class="find ${esc(f.severity || 'low')}">
    <div class="t">${esc(f.title)}<span class="tag">${esc(RLABEL[f.runtime] || f.runtime || 'unknown')}</span><span class="tag">${esc(f.kind || '')}</span></div>
    <div class="e">${esc(f.evidence)}</div>
    ${f.recommendation ? `<div class="r">&rarr; ${esc(f.recommendation)}</div>` : ''}
    ${f.architectural_risk ? `<div class="rk">risk: ${esc(f.architectural_risk)}</div>` : ''}
  </div>`).join('');
}

function verdictBar(cur, an) {
  return `<div class="card" style="display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap;justify-content:space-between">
    <div style="flex:1;min-width:260px">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:5px;flex-wrap:wrap">
        <span class="pill ${esc(an.verdict || 'unknown')}">${esc(an.verdict || 'no analysis')}</span>
        ${cur.app_name ? `<span class="tag" style="${cur.app_role === 'own' ? 'border-color:var(--s1);color:var(--s1)' : ''}">${esc(cur.app_name)}${cur.derived ? ' \u00b7 derived' : ''}</span>` : ''}
        <span style="font-size:12.5px;color:var(--text-muted)">run ${cur.id} &middot; ${esc(cur.ts)}${cur.git_sha ? ' &middot; ' + esc(cur.git_sha) : ''}${cur.device ? ' &middot; ' + esc(cur.device) : ''}</span>
        ${an._heuristic ? '<span class="tag">rules only</span>' : an._model ? `<span class="tag">${esc(an._model)}</span>` : ''}
      </div>
      <div style="font-size:15px;font-weight:600">${esc(an.headline || 'No analysis recorded for this run.')}</div>
    </div>
  </div>`;
}

function render() {
  const rs = runs();
  const app = $('#app');
  $('#tabbar').innerHTML = tabBar();
  document.querySelectorAll('.tab').forEach(b => b.onclick = () => { TAB = b.dataset.tab; render(); });

  if (!rs.length) {
    app.innerHTML = '<div class="card"><p class="empty">No runs recorded for this path yet. Run <code>swagperf analyse &lt;trace&gt;</code>.</p></div>';
    return;
  }
  const cur = rs.at(-1), prev = rs.length > 1 ? rs.at(-2) : null;
  // A drill-down must always correspond to a step present in the current run.
  if (OPEN_STEP && !cur.steps.some(x => x.step === OPEN_STEP)) OPEN_STEP = null;
  const gb = DATA.global_budgets, an = cur.analysis || {};
  const seen = [];
  rs.forEach(r => r.steps.forEach(x => { const k = RUNTIME[x.step] || 'native'; if (!seen.includes(k)) seen.push(k); }));
  const fr = filteredRuns(rs);
  const devices = [...new Set(DATA.runs.map(r => r.device).filter(Boolean))];
  const blurb = TABS.find(t => t.id === TAB)?.blurb || '';
  const head = `<p class="tabblurb">${esc(blurb)}</p>`;
  const post = [];   // deferred DOM work (charts, listeners)

  /* ---------------- OVERVIEW ---------------- */
  if (TAB === 'overview') {
    app.innerHTML = head + verdictBar(cur, an) + `
      <div class="tiles">
        ${tileHTML(cur.derived ? 'Time to initial display' : 'First camera frame', cur.ttff_ms, 'ms', cur.ttid_budget_ms, prev?.ttff_ms, 1)}
        ${tileHTML('Slow frames', cur.slow_pct, '%', gb.slow_frame_pct, prev?.slow_pct, 2)}
        ${tileHTML('Janky frames', cur.janky_pct, '%', gb.janky_frame_pct, prev?.janky_pct, 2)}
        ${tileHTML('Thermal drift', cur.thermal_drift_pct, '%', gb.thermal_drift_pct, prev?.thermal_drift_pct, 2)}
        ${tileHTML('Peak RAM usage', cur.peak_rss_mb, 'MB', memBudget('peak_rss_mb'), prev?.peak_rss_mb, 1)}
        ${tileHTML('RAM growth', cur.rss_growth_mb, 'MB', memBudget('rss_growth_mb'), prev?.rss_growth_mb, 1)}
      </div>
      <div class="card"><h2>All findings</h2>
        <p class="hint">Attributed to a runtime and, where it applies, to a named architectural risk.</p>
        <div>${findingsHTML(an, { emptyMsg: 'No findings. Every measured metric is within budget and baseline.' })}</div>
        ${(an.dismissed || []).length ? `<details><summary>${an.dismissed.length} signal(s) reviewed and dismissed</summary>${an.dismissed.map(d => `<div class="srow"><span>${esc(d)}</span></div>`).join('')}</details>` : ''}
      </div>
      <div class="card"><h2>Verdict by run</h2>
        <p class="hint">Every recorded run on this path, newest last. Click a bar to jump to its detail.</p>
        <div id="vstrip"></div></div>`;
    post.push(() => {
      const w = $('#vstrip');
      w.innerHTML = rs.map(r => {
        const v = r.analysis?.verdict || 'unknown';
        return `<div class="vcell ${v}" title="run ${r.id} — ${v}" data-run="${r.id}">
          <span class="vid">${r.id}</span></div>`;
      }).join('');
    });
  }

  /* ---------------- STARTUP ---------------- */
  if (TAB === 'startup') {
    const viol = cur.violations || [];
    const critCount = (PATH in CRITICAL) ? CRITICAL[PATH].length : cur.steps.length;
    app.innerHTML = head + `
      <div class="tiles">
        ${tileHTML(cur.derived ? 'Time to initial display' : 'First camera frame', cur.ttff_ms, 'ms', cur.ttid_budget_ms, prev?.ttff_ms, 1)}
        ${tileHTML('Critical-path steps', critCount, '', null, null, 0)}
        ${!cur.derived ? tileHTML('Ordering violations', viol.length, '', 0, prev ? (prev.violations || []).length : null, 0) : ''}
      </div>
      ${cur.derived ? `<div class="card"><h2>No stated architecture for this app</h2>
        <p class="hint">${esc(cur.app_name || cur.app_pkg || 'This app')} is not instrumented, so its steps are derived from ordinary Android launch slices rather than read from declared markers. There is no known deferred-work ordering constraint to check for an app whose architecture is not documented here — only Swag Pay's own runs are checked against that rule.</p></div>`
      : viol.length ? `<div class="card" style="border-color:var(--crit)">
        <h2 style="color:var(--crit)">Ordering violations</h2>
        <p class="hint">The architecture's strongest decision: no RN, Cronet, analytics or remote config before the camera is usable.</p>
        ${viol.map(v => `<div class="find high"><div class="t">${esc(v.step)}</div><div class="e">${esc(v.detail)}</div></div>`).join('')}
      </div>` : `<div class="card"><h2>Ordering constraint</h2>
        <p class="hint">No deferred work ran before the first usable camera frame. The constraint holds for this run.</p></div>`}
      <div class="card">
        <h2>Time to first usable camera frame</h2>
        <p class="hint">${cur.ttid_budget_ms ? `Dashed line is the ${cur.ttid_budget_ms}ms budget.` : 'No budget is set for this app — none is asserted for a competitor unless one is explicitly entered in the catalogue.'} ${cur.derived ? `App: ${esc(cur.app_name || cur.app_pkg || 'unknown')} (${esc(pathLabel(PATH))}).` : `Path: ${PATH === 'returning_user' ? 'returning user — camera on the critical path' : 'first run — onboarding is an RN surface, camera is not'}.`}</p>
        <div id="c2"></div>
      </div>
      <div class="card">
        <h2>Critical-path composition</h2>
        <p class="hint">Only the steps a user waits through on this path. Toggle a runtime in the legend to isolate it.</p>
        <div class="legend" id="lg"></div>
        <div class="ctl" style="margin:0 0 12px"><span class="flabel">View</span><div id="modebtns"></div></div>
        <div id="c1"></div>
      </div>
      <div class="card"><h2>Startup findings</h2>
        <div>${findingsHTML(an, { kinds: ['ordering_violation', 'regression', 'budget_breach'],
          about: ['startup', 'camera frame', 'first frame', 'ttfcf', 'ttff', 'boot', 'ordering',
                  'deferred', 'critical path', 'step:'],
          emptyMsg: 'No startup findings for the latest run.' })}</div></div>`;
    post.push(() => {
      $('#c2').appendChild(lineChart(rs, 'ttff_ms', cur.ttid_budget_ms, cur.derived ? 'time to initial display (ms)' : 'first camera frame (ms)', 'var(--s1)'));
      $('#c1').appendChild(stepChart(rs));
      renderLegend(seen, rs); renderModes();
    });
  }

  /* ---------------- FRAME PACING ---------------- */
  if (TAB === 'frames') {
    const f = cur.frames || {};
    app.innerHTML = head + `
      <div class="tiles">
        ${tileHTML('Slow frames', cur.slow_pct, '%', gb.slow_frame_pct, prev?.slow_pct, 2)}
        ${tileHTML('Janky frames', cur.janky_pct, '%', gb.janky_frame_pct, prev?.janky_pct, 2)}
        ${tileHTML('Thermal drift', cur.thermal_drift_pct, '%', gb.thermal_drift_pct, prev?.thermal_drift_pct, 2)}
        ${tileHTML('Avg frame', f.avg_ms, 'ms', 16.67, prev?.frames?.avg_ms, 2)}
        ${tileHTML('Worst frame', f.max_ms, 'ms', null, prev?.frames?.max_ms, 1)}
        ${tileHTML('Frames measured', f.total, '', null, null, 0)}
      </div>
      <div class="card"><h2>Reading these two together</h2>
        <p class="hint">Progressive drift across a session means thermal throttling. Scattered spikes with flat drift point at the CMP &times; RN interop seam. They need different fixes, so the dashboard keeps them apart.</p>
        <div class="readout">
          <div class="ro"><span class="rok">Drift</span><b>${fmt(cur.thermal_drift_pct, 2)}%</b>
            <em>${cur.thermal_drift_pct > gb.thermal_drift_pct ? 'progressive — thermal likely' : 'flat — not thermal'}</em></div>
          <div class="ro"><span class="rok">Slow frames</span><b>${fmt(cur.slow_pct, 2)}%</b>
            <em>${cur.slow_pct > gb.slow_frame_pct ? 'over budget' : 'within budget'}</em></div>
          <div class="ro"><span class="rok">Indication</span><b>${
            cur.thermal_drift_pct > gb.thermal_drift_pct && cur.slow_pct > gb.slow_frame_pct ? 'Thermal'
            : cur.slow_pct > gb.slow_frame_pct ? 'Seam or workload' : 'Healthy'}</b>
            <em>needs per-surface tags to confirm the seam</em></div>
        </div>
      </div>
      <div class="card"><h2>Slow frames</h2><p class="hint">Percentage of frames over the 16.67ms budget.</p><div id="c3"></div></div>
      <div class="card"><h2>Janky frames</h2><p class="hint">Frames over three budgets — user-visible stutter.</p><div id="c4"></div></div>
      <div class="card"><h2>Thermal drift</h2><p class="hint">Second-half mean frame time vs first half. Rising means the device is throttling.</p><div id="c5"></div></div>
      <div class="card"><h2>Frame findings</h2>
        <div>${findingsHTML(an, { kinds: ['thermal', 'budget_breach', 'regression'],
          about: ['slow frame', 'janky', 'jank', 'thermal', 'drift', 'fps', 'pacing',
                  'seam', 'throttl', 'frame rate', 'frame pacing', 'frame time'],
          notAbout: ['camera frame', 'first frame', 'ttfcf', 'ttff', 'startup', 'critical path'],
          emptyMsg: 'No frame-pacing findings for the latest run.' })}</div></div>`;
    post.push(() => {
      $('#c3').appendChild(lineChart(rs, 'slow_pct', gb.slow_frame_pct, 'slow frames (%)', 'var(--s2)'));
      $('#c4').appendChild(lineChart(rs, 'janky_pct', gb.janky_frame_pct, 'janky frames (%)', 'var(--s4)'));
      $('#c5').appendChild(lineChart(rs, 'thermal_drift_pct', gb.thermal_drift_pct, 'thermal drift (%)', 'var(--s3)'));
    });
  }

  /* ---------------- MEMORY ---------------- */
  if (TAB === 'memory') {
    const hh = cur.memory?.hermes_heap;
    app.innerHTML = head + `
      <div class="tiles">
        ${tileHTML('Peak RAM usage', cur.peak_rss_mb, 'MB', memBudget('peak_rss_mb'), prev?.peak_rss_mb, 1)}
        ${tileHTML('RAM growth', cur.rss_growth_mb, 'MB', memBudget('rss_growth_mb'), prev?.rss_growth_mb, 1)}
        ${hh ? tileHTML('Hermes heap peak', hh.peak_mb, 'MB', null, prev?.memory?.hermes_heap?.peak_mb, 1) : ''}
        ${hh ? tileHTML('Hermes heap growth', hh.growth_mb, 'MB', null, prev?.memory?.hermes_heap?.growth_mb, 1) : ''}
      </div>
      <div class="card"><h2>Three runtimes, one process</h2>
        <p class="hint">Hermes + Fabric, Cronet's Chromium stack, CameraX and ML Kit buffers, Skia and SQLite are all resident at once. Growth that does not return to baseline across a session is the orphaned-surface signature: a Surface started and never stopped keeps its whole JS component tree alive for the life of the process.</p>
        ${hh && cur.rss_growth_mb ? `<div class="readout"><div class="ro"><span class="rok">JS share of growth</span>
          <b>${fmt(hh.growth_mb / cur.rss_growth_mb * 100, 0)}%</b>
          <em>${fmt(hh.growth_mb, 1)}MB of ${fmt(cur.rss_growth_mb, 1)}MB total</em></div></div>` : ''}
      </div>
      <div class="card"><h2>Peak RAM usage and Hermes heap</h2>
        <p class="hint">Both in MB on one axis. RAM usage is the physical memory the app actually occupies, which is what Android's low-memory killer acts on.${memBudget('peak_rss_mb') ? ` Dashed line is the ${gb.peak_rss_mb}MB ceiling.` : ''}</p>
        <div class="legend"><span><i style="background:var(--s1)"></i>Peak RAM usage</span><span><i style="background:var(--s2)"></i>Hermes heap peak</span></div>
        <div id="c6"></div></div>
      <div class="card"><h2>Session growth</h2>
        <p class="hint">Min-to-peak RAM within each run. Growth that never returns to baseline is the leak signature.${memBudget('rss_growth_mb') ? ` Dashed line is the ${gb.rss_growth_mb}MB budget.` : ''}</p>
        <div id="c7"></div></div>
      <div class="card"><h2>Memory findings</h2>
        <div>${findingsHTML(an, { kinds: ['memory', 'budget_breach'],
          about: ['memor', 'ram', 'rss', 'heap', 'leak', 'surface', 'resident', 'growth'],
          emptyMsg: 'No memory findings for the latest run.' })}</div></div>`;
    post.push(() => {
      $('#c6').appendChild(multiLine(rs, [
        { name: 'Peak RAM usage', color: 'var(--s1)', get: r => r.peak_rss_mb },
        { name: 'Hermes heap peak', color: 'var(--s2)', get: r => r.memory?.hermes_heap?.peak_mb },
      ], memBudget('peak_rss_mb'), 'peak RAM usage and Hermes heap (MB)'));
      $('#c7').appendChild(lineChart(rs, 'rss_growth_mb', memBudget('rss_growth_mb'), 'RAM growth (MB)', 'var(--s3)'));
    });
  }

  /* ---------------- STEPS ---------------- */
  if (TAB === 'steps') {
    const visible = cur.steps.filter(x => FILTER.runtime === 'all' || (RUNTIME[x.step] || 'native') === FILTER.runtime);
    const medOf = st => {
      const v = rs.map(r => r.steps.find(z => z.step === st)?.dur_ms).filter(x => x != null);
      return v.length ? [...v].sort((a, b) => a - b)[Math.floor(v.length / 2)] : null;
    };
    const sorted = sortRows(visible, 'steps', {
      runtime: x => RLABEL[RUNTIME[x.step] || 'native'],
      step: x => x.step,
      pct: x => x.budget_ms ? x.dur_ms / x.budget_ms * 100 : null,
      vs_median: x => { const m = medOf(x.step); return m == null ? null : x.dur_ms - m; },
    });
    app.innerHTML = head + `
      <div class="card">
        <h2>Step duration by run</h2>
        <p class="hint">Toggle a runtime in the legend to hide it. <b>Critical path</b> sums only the steps a user waits through; <b>all steps</b> adds deferred work (hatched); <b>per step</b> gives each step its own scale.</p>
        <div class="legend" id="lg"></div>
        <div class="ctl" style="margin:0 0 12px"><span class="flabel">View</span><div id="modebtns"></div></div>
        <div id="c1"></div>
      </div>
      <div class="card">
        <h2>Steps in run ${cur.id}</h2>
        <p class="hint">Click a step for its history and full child breakdown. Sort by any column.</p>
        <div class="ctl" style="margin-bottom:12px">
          <span class="flabel">Runtime</span>
          <select id="rtfilter" aria-label="Filter steps by runtime">
            <option value="all"${FILTER.runtime === 'all' ? ' selected' : ''}>All runtimes</option>
            ${seen.map(k => `<option value="${esc(k)}"${FILTER.runtime === k ? ' selected' : ''}>${esc(RLABEL[k])}</option>`).join('')}
          </select>
          <span class="count">${visible.length} of ${cur.steps.length} steps</span>
        </div>
        <div class="scroll"><table>
          <thead><tr>
            ${th('steps', 'step', 'Step')}${th('steps', 'runtime', 'Runtime')}
            ${th('steps', 'dur_ms', 'Duration', 'num')}${th('steps', 'budget_ms', 'Budget', 'num')}
            ${th('steps', 'pct', '% of budget', 'num')}${th('steps', 'vs_median', 'vs median', 'num')}
            <th>Slowest children</th>
          </tr></thead>
          <tbody>${sorted.map(x => {
            const rt = RUNTIME[x.step] || 'native';
            const pct = x.budget_ms ? (x.dur_ms / x.budget_ms * 100) : null;
            const m = medOf(x.step), vs = m == null ? null : x.dur_ms - m;
            const kids = (x.children || []).filter(c => !c.self_time);
            return `<tr class="steprow${OPEN_STEP === x.step ? ' open' : ''}" data-step="${esc(x.step)}" tabindex="0">
              <td><i style="display:inline-block;width:9px;height:9px;border-radius:2px;background:${RC[rt]};margin-right:7px"></i>${esc(x.step.replace('step:', ''))}${onCritical(x.step) ? '' : ' <span class="tag">deferred</span>'}</td>
              <td style="color:var(--text-secondary)">${esc(RLABEL[rt])}</td>
              <td class="num">${fmt(x.dur_ms, 1)} ms</td>
              <td class="num" style="color:var(--text-muted)">${x.budget_ms ?? '–'}</td>
              <td class="num" style="${pct > 100 ? 'color:var(--crit);font-weight:650' : ''}">${pct ? fmt(pct, 0) + '%' : '–'}</td>
              <td class="num ${vs > 0.5 ? 'up' : vs < -0.5 ? 'dn' : ''}">${vs == null ? '–' : (vs > 0 ? '+' : '') + fmt(vs, 1)}</td>
              <td style="color:var(--text-secondary)">${kids.slice(0, 3).map(c => `${esc(c.name)} ${fmt(c.dur_ms, 1)}ms`).join(' &middot; ') || '–'}</td>
            </tr>`; }).join('')}</tbody>
        </table></div>
        <div id="stepdrill"></div>
      </div>`;
    post.push(() => {
      $('#c1').appendChild(stepChart(rs));
      renderLegend(seen, rs); renderModes(); wireSort(); wireStepRows(rs, cur);
      const rf = $('#rtfilter');
      if (rf) rf.onchange = () => {
        FILTER.runtime = rf.value;
        // Drop an open drill-down whose step the new filter hides, so the panel
        // can never describe a step that is not in the table below it.
        if (OPEN_STEP && FILTER.runtime !== 'all' &&
            (RUNTIME[OPEN_STEP] || 'native') !== FILTER.runtime) OPEN_STEP = null;
        render();
      };
    });
  }

  /* ---------------- CAPTURE ---------------- */
  if (TAB === 'capture') {
    const d = CAP.device;
    const job = CAP.job;
    const busy = job && (job.state === 'running' || job.state === 'queued');

    if (!d) {
      app.innerHTML = head + '<div class="card"><p class="empty">Checking for a connected device…</p></div>';
      post.push(() => loadDevice().then(render));
    } else if (!d.connected) {
      app.innerHTML = head + `<div class="card">
        <h2>No device connected</h2>
        <p class="hint">Connect an Android device over USB and enable <b>USB debugging</b>
        (Settings → About phone → tap Build number seven times → Developer options).
        Then accept the "Allow USB debugging?" prompt on the device.</p>
        <div class="ctl"><button id="recheck">Check again</button></div></div>`;
      post.push(() => { const b = $('#recheck'); if (b) b.onclick = () => loadDevice(true).then(render); });
    } else {
      const q = CAP.q.trim().toLowerCase();
      const pkgs = (d.packages || []).filter(p => p.installed &&
        (!q || p.pkg.toLowerCase().includes(q) || (p.name || '').toLowerCase().includes(q)));
      const roleLabel = { own: 'your app', competitor: 'competitor', reference: 'reference' };

      app.innerHTML = head + `
        <div class="card">
          <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:4px">
            <span class="pill pass">device connected</span>
            <span style="font-size:13px"><b>${esc(d.model || d.device || 'unknown')}</b>
              <span style="color:var(--text-muted)">· Android ${esc(d.release || '?')} (API ${esc(d.sdk || '?')})
              · ${esc(d.serial || '')}</span></span>
            <button id="recheck" class="mini-btn">Refresh</button>
          </div>
          <p class="hint" style="margin:6px 0 0">${(d.packages || []).filter(p => p.installed).length} app(s) installed${q ? `, ${pkgs.length} matching "${esc(CAP.q)}"` : ''}.
            Apps already in the catalogue are listed first.</p>
        </div>

        <div class="card">
          <h2>Profile an app</h2>
          <p class="hint">A cold start force-stops the app and launches it inside the trace
            window — the only way to measure a real cold start. Some apps (payment apps
            especially) show a lock or biometric prompt that an adb launch cannot dismiss;
            if the capture never observes the app it is reported as a failure, not a pass.</p>

          <div class="ctl" style="margin-bottom:12px">
            <input id="pkgsearch" type="search" placeholder="Search installed apps…"
                   value="${esc(CAP.q)}" aria-label="Search installed apps" ${busy ? 'disabled' : ''}>
            <span class="flabel">Start</span>
            <div id="coldbtns"></div>
            <span class="flabel">Duration</span>
            <select id="capdur" aria-label="Trace duration" ${busy ? 'disabled' : ''}>
              ${[5000, 8000, 10000, 15000, 20000, 30000].map(v =>
                `<option value="${v}"${CAP.duration === v ? ' selected' : ''}>${v / 1000}s</option>`).join('')}
            </select>
          </div>

          <div class="scroll" style="max-height:330px">
            <table>
              <thead><tr><th>App</th><th>Package</th><th>Role</th><th></th></tr></thead>
              <tbody>${pkgs.slice(0, 60).map(p => `<tr class="${CAP.pkg === p.pkg ? 'cur' : ''}">
                <td>${esc(p.name || p.pkg)}${p.instrumented ? ' <span class="tag">instrumented</span>' : ''}${!p.in_catalogue ? ' <span class="tag">new</span>' : ''}</td>
                <td style="color:var(--text-secondary);font-size:12px">${esc(p.pkg)}</td>
                <td style="color:var(--text-secondary)">${esc(roleLabel[p.role] || p.role || '')}</td>
                <td><button class="mini-btn" data-cappkg="${esc(p.pkg)}" ${busy ? 'disabled' : ''}>${busy && CAP.pkg === p.pkg ? 'Running…' : 'Profile'}</button></td>
              </tr>`).join('') || '<tr><td colspan="4" class="empty">No installed apps match that search.</td></tr>'}</tbody>
            </table>
          </div>
          ${pkgs.length > 60 ? `<p class="hint" style="margin-top:9px">Showing 60 of ${pkgs.length}. Narrow the search to see the rest.</p>` : ''}
        </div>

        ${job ? `<div class="card" style="${job.state === 'error' ? 'border-color:var(--crit)' : job.state === 'done' ? 'border-color:var(--good)' : ''}">
          <h2>${job.state === 'running' || job.state === 'queued' ? 'Capturing…'
                : job.state === 'done' ? 'Capture complete' : 'Capture failed'}</h2>
          ${job.pkg ? `<p class="hint">${esc(job.pkg)} · ${job.cold ? 'cold start' : 'warm'} · ${(job.duration_ms || 0) / 1000}s</p>` : ''}
          <div class="joblog">${(job.log || []).map(l => `<div class="jl ${/^FATAL|^ERROR/.test(l.text) ? 'bad' : /^warning/.test(l.text) ? 'warn' : ''}">
            <span class="jt">${l.t}s</span>${esc(l.text)}</div>`).join('')
            || '<div class="jl"><span class="jt">…</span>starting</div>'}</div>
          ${job.error ? `<div class="find high" style="margin-top:10px"><div class="t">Capture failed</div>
            <div class="e">${esc(job.error)}</div></div>` : ''}
          ${job.state === 'done' && job.result ? `<div class="readout" style="margin-top:12px">
            <div class="ro"><span class="rok">Run</span><b>${job.result.run_id}</b><em>${esc(job.result.path_kind || '')}</em></div>
            <div class="ro"><span class="rok">Verdict</span><b>${esc(job.result.verdict || '?')}</b><em>${esc(job.result.headline || '')}</em></div>
          </div>
          <div class="ctl" style="margin-top:12px"><button id="gotorun">View this run</button></div>` : ''}
        </div>` : ''}`;

      post.push(() => {
        const rb = $('#recheck');
        if (rb) rb.onclick = () => loadDevice(true).then(render);
        const sw = $('#pkgsearch');
        if (sw) sw.oninput = () => {
          CAP.q = sw.value; clearTimeout(sw._t);
          sw._t = setTimeout(() => { render(); const n = $('#pkgsearch');
            if (n) { n.focus(); n.setSelectionRange(n.value.length, n.value.length); } }, 200);
        };
        const dd = $('#capdur');
        if (dd) dd.onchange = () => { CAP.duration = +dd.value; render(); };
        const cb = $('#coldbtns');
        if (cb) {
          cb.innerHTML = [[true, 'Cold'], [false, 'Warm']].map(([v, l]) =>
            `<button class="seg${CAP.cold === v ? ' on' : ''}" data-cold="${v}" ${busy ? 'disabled' : ''}>${l}</button>`).join('');
          cb.querySelectorAll('.seg').forEach(b => b.onclick = () => {
            CAP.cold = b.dataset.cold === 'true'; render();
          });
        }
        document.querySelectorAll('[data-cappkg]').forEach(b => b.onclick = () => {
          CAP.pkg = b.dataset.cappkg;
          startCapture();
        });
        const gr = $('#gotorun');
        if (gr) gr.onclick = () => {
          PATH = CAP.job.result.path_kind || PATH;
          TAB = 'overview'; render();
        };
      });
    }
  }

  /* ---------------- STRESS ---------------- */
  if (TAB === 'stress') {
    const job = STR.job;
    const busy = job && (job.state === 'running' || job.state === 'queued');
    const dev = CAP.device;
    const det = STR.detail;

    if (STR.list === null) {
      app.innerHTML = head + '<div class="card"><p class="empty">Loading stress tests…</p></div>';
      post.push(() => Promise.all([loadStress(), loadDevice()]).then(render));
    } else {
      const installed = ((dev && dev.packages) || []).filter(p => p.installed);
      const q = STR.q.trim().toLowerCase();
      const pkgs = installed.filter(p => !q || p.pkg.toLowerCase().includes(q)
                                      || (p.name || '').toLowerCase().includes(q));
      const stat = (s, unit, d = 1) => s
        ? `<div class="ro"><span class="rok">${esc(unit)}</span><b>${fmt(s.median, d)}</b>
             <em>median · ${fmt(s.min, d)}–${fmt(s.max, d)} · σ ${fmt(s.stdev, d)}</em></div>`
        : '';

      app.innerHTML = head + `
        <div class="card">
          <h2>Run a stress test</h2>
          <p class="hint">One cold start is a noisy measurement — cache state, background work
            and thermal condition all move it. Repeating it is the only way to tell a real
            regression from that noise, so a stress test reports the <b>spread</b>, not an average.
            Each session is also recorded as an ordinary run, so every other tab can see it.</p>
          ${!dev ? '<p class="empty">Checking for a device…</p>'
            : !dev.connected ? '<p class="empty">No device connected. Connect one over USB with USB debugging enabled.</p>'
            : `<div class="ctl" style="margin-bottom:12px">
              <input id="strsearch" type="search" placeholder="Search installed apps…"
                     value="${esc(STR.q)}" ${busy ? 'disabled' : ''} aria-label="Search apps">
              <span class="flabel">Sessions</span>
              <select id="strn" ${busy ? 'disabled' : ''} aria-label="Session count">
                ${[3, 5, 10, 15, 20].map(v => `<option value="${v}"${STR.sessions === v ? ' selected' : ''}>${v}</option>`).join('')}
              </select>
              <span class="flabel">Start</span><div id="strcold"></div>
              <span class="flabel">Each</span>
              <select id="strdur" ${busy ? 'disabled' : ''} aria-label="Duration per session">
                ${[5000, 8000, 10000, 15000].map(v => `<option value="${v}"${STR.duration === v ? ' selected' : ''}>${v / 1000}s</option>`).join('')}
              </select>
              <span class="count">~${Math.round(STR.sessions * (STR.duration + 4000) / 1000)}s total
                \u00b7 ${pkgs.length} of ${installed.length} apps</span>
            </div>
            <div class="scroll" style="max-height:300px"><table>
              <thead><tr><th>App</th><th>Package</th><th></th></tr></thead>
              <tbody>${pkgs.slice(0, MAN_LIST_LIMIT).map(p => `<tr>
                <td>${esc(p.name || p.pkg)}${p.instrumented ? ' <span class="tag">instrumented</span>' : ''}</td>
                <td style="color:var(--text-secondary);font-size:12px">${esc(p.pkg)}</td>
                <td><button class="mini-btn" data-strpkg="${esc(p.pkg)}" ${busy ? 'disabled' : ''}>${busy && STR.pkg === p.pkg ? 'Running\u2026' : 'Stress test'}</button></td>
              </tr>`).join('') || '<tr><td colspan="3" class="empty">No installed apps match that search.</td></tr>'}</tbody>
            </table></div>
            ${pkgs.length > MAN_LIST_LIMIT ? `<p class="hint" style="margin-top:9px">Showing ${MAN_LIST_LIMIT} of ${pkgs.length} matches. Narrow the search to see the rest.</p>` : ''}`}
        </div>

        ${job ? `<div class="card" style="${job.state === 'error' ? 'border-color:var(--crit)' : job.state === 'done' ? 'border-color:var(--good)' : ''}">
          <h2>${busy ? `Running… session ${(job.progress || {}).current || 0} of ${(job.progress || {}).total || job.sessions || '?'}`
                : job.state === 'done' ? 'Stress test complete' : 'Stress test failed'}</h2>
          <div class="joblog">${(job.log || []).map(l => `<div class="jl ${/FAILED|^ERROR/.test(l.text) ? 'bad' : ''}">
            <span class="jt">${l.t}s</span>${esc(l.text)}</div>`).join('') || '<div class="jl">starting</div>'}</div>
          ${job.error ? `<div class="find high" style="margin-top:10px"><div class="t">Failed</div><div class="e">${esc(job.error)}</div></div>` : ''}
        </div>` : ''}

        ${det && !det.error ? `<div class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap">
            <h2 style="margin:0">Stress test #${det.id} · ${esc(det.app_pkg || '')}</h2>
            <button class="mini-btn" id="closestress">Close</button>
          </div>
          <p class="hint">${det.completed} of ${det.sessions_requested} session(s) captured${det.failed ? `, ${det.failed} failed` : ''}
            · ${det.cold ? 'cold' : 'warm'} · ${esc(det.device || '')} · ${esc(det.ts || '')}</p>
          ${det.stats && det.stats.ttid_ms ? `<div class="readout">
            ${stat(det.stats.ttid_ms, 'startup ms')}
            <div class="ro"><span class="rok">spread</span><b>${fmt(det.stats.ttid_ms.spread_pct, 1)}%</b>
              <em>max over min, relative to median</em></div>
            ${stat(det.stats.peak_rss_mb, 'peak RAM MB')}
            ${stat(det.stats.slow_pct, 'slow frames %', 2)}
          </div>` : '<p class="empty">No completed sessions yet.</p>'}
          ${(det.sessions || []).some(x => x.ttid_ms) ? `<h3 style="font-size:13px;margin:18px 0 2px">Startup per session</h3>
            <p class="hint">Dashed line is the median. A wide spread means the number is not repeatable, and a single capture would have been misleading.</p>
            <div id="sp1"></div>` : ''}
          <h3 style="font-size:13px;margin:18px 0 6px">Sessions</h3>
          <div class="scroll"><table>
            <thead><tr><th>#</th><th>State</th><th class="num">Startup</th><th class="num">vs median</th>
              <th class="num">Slow %</th><th class="num">Peak RAM</th><th>Run</th></tr></thead>
            <tbody>${(det.sessions || []).map(x => {
              const med = det.stats && det.stats.ttid_ms ? det.stats.ttid_ms.median : null;
              const dv = (x.ttid_ms && med) ? x.ttid_ms - med : null;
              return `<tr>
                <td>${x.seq}</td>
                <td>${x.state === 'done' ? '<span class="cv better">ok</span>'
                     : x.state === 'error' ? '<span class="cv worse">failed</span>'
                     : '<span class="cv same">pending</span>'}</td>
                <td class="num">${x.ttid_ms ? fmt(x.ttid_ms, 1) + ' ms' : '–'}</td>
                <td class="num ${dv > 0.5 ? 'up' : dv < -0.5 ? 'dn' : ''}">${dv == null ? '–' : (dv > 0 ? '+' : '') + fmt(dv, 1)}</td>
                <td class="num">${x.slow_pct != null ? fmt(x.slow_pct, 2) : '–'}</td>
                <td class="num">${x.peak_rss_mb != null ? fmt(x.peak_rss_mb, 1) + ' MB' : '–'}</td>
                <td>${x.run_id ? `<button class="mini-btn" data-strrun="${x.run_id}" data-strpath="${esc(x.path_kind || '')}" data-strapp="${esc(det.app_pkg || '')}">View run ${x.run_id}</button>`
                     : x.error ? `<span style="color:var(--crit);font-size:12px">${esc(x.error.slice(0, 90))}</span>` : '–'}</td>
              </tr>`; }).join('')}</tbody>
          </table></div>
        </div>` : ''}

        <div class="card">
          <h2>Stress test history</h2>
          <p class="hint">Separate from the run history: each row is a whole test, not one capture.</p>
          <div class="scroll"><table>
            <thead><tr><th>#</th><th>When</th><th>App</th><th>Label</th><th class="num">Sessions</th>
              <th class="num">Median</th><th class="num">Spread</th><th>State</th><th></th></tr></thead>
            <tbody>${(STR.list || []).map(t => {
              const st = (t.stats || {}).ttid_ms;
              return `<tr${STR.open === t.id ? ' class="cur"' : ''}>
                <td>${t.id}</td><td style="color:var(--text-secondary)">${esc(t.ts || '')}</td>
                <td>${esc(t.app_pkg || '')}</td><td>${esc(t.label || '')}</td>
                <td class="num">${t.completed}/${t.sessions_requested}${t.failed ? ` <span style="color:var(--crit)">(${t.failed}✗)</span>` : ''}</td>
                <td class="num">${st ? fmt(st.median, 1) + ' ms' : '–'}</td>
                <td class="num ${st && st.spread_pct > 25 ? 'up' : ''}">${st && st.spread_pct != null ? fmt(st.spread_pct, 1) + '%' : '–'}</td>
                <td><span class="pill ${t.state === 'done' ? 'pass' : t.state === 'error' ? 'fail' : 'warn'}">${esc(t.state)}</span></td>
                <td><button class="mini-btn" data-stropen="${t.id}">Open</button></td>
              </tr>`; }).join('') || '<tr><td colspan="9" class="empty">No stress tests yet.</td></tr>'}</tbody>
          </table></div>
        </div>`;

      post.push(() => {
        if (det && !det.error && (det.sessions || []).some(x => x.ttid_ms)) {
          const w = $('#sp1');
          if (w) w.appendChild(sessionPlot(det.sessions, 'ttid_ms', null,
                                           'startup (ms)', 'var(--s1)'));
        }
        const ss = $('#strsearch');
        if (ss) ss.oninput = () => {
          STR.q = ss.value; clearTimeout(ss._t);
          ss._t = setTimeout(() => { render(); const n = $('#strsearch');
            if (n) { n.focus(); n.setSelectionRange(n.value.length, n.value.length); } }, 200);
        };
        const sn = $('#strn'); if (sn) sn.onchange = () => { STR.sessions = +sn.value; render(); };
        const sd = $('#strdur'); if (sd) sd.onchange = () => { STR.duration = +sd.value; render(); };
        const sc = $('#strcold');
        if (sc) {
          sc.innerHTML = [[true, 'Cold'], [false, 'Warm']].map(([v, l]) =>
            `<button class="seg${STR.cold === v ? ' on' : ''}" data-sc="${v}" ${busy ? 'disabled' : ''}>${l}</button>`).join('');
          sc.querySelectorAll('.seg').forEach(b => b.onclick = () => { STR.cold = b.dataset.sc === 'true'; render(); });
        }
        document.querySelectorAll('[data-strpkg]').forEach(b => b.onclick = () => {
          STR.pkg = b.dataset.strpkg; startStress();
        });
        document.querySelectorAll('[data-stropen]').forEach(b => b.onclick = async () => {
          STR.open = +b.dataset.stropen; await loadStressDetail(STR.open); render();
          $('#sp1')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        });
        const cs = $('#closestress');
        if (cs) cs.onclick = () => { STR.open = null; STR.detail = null; render(); };
        document.querySelectorAll('[data-strrun]').forEach(b => b.onclick = () => {
          // Jump to that session's run in the normal views.
          APP = b.dataset.strapp || APP;
          PATH = b.dataset.strpath || PATH;
          TAB = 'steps';
          load();
        });
      });
    }
  }

  /* ---------------- MANUAL ---------------- */
  if (TAB === 'manual') {
    const st = MAN.status;
    const job = MAN.job;
    const busy = job && (job.state === 'running' || job.state === 'queued');
    const dev = CAP.device;

    if (!st) {
      app.innerHTML = head + '<div class="card"><p class="empty">Checking session state…</p></div>';
      post.push(() => Promise.all([loadManualStatus(), loadDevice()]).then(render));
    } else if (!st.device) {
      app.innerHTML = head + `<div class="card"><h2>No device connected</h2>
        <p class="hint">Connect a device over USB with USB debugging enabled, then re-check.</p>
        <div class="ctl"><button id="manrecheck">Check again</button></div></div>`;
      post.push(() => { const b = $('#manrecheck');
        if (b) b.onclick = () => loadManualStatus(true).then(render); });
    } else {
      const installed = ((dev && dev.packages) || []).filter(p => p.installed);
      const q = MAN.q.trim().toLowerCase();
      const pkgs = installed.filter(p => !q || p.pkg.toLowerCase().includes(q)
                                      || (p.name || '').toLowerCase().includes(q));
      app.innerHTML = head + `
        <div class="card">
          <h2>Manual tracing session</h2>
          <p class="hint">Tracing runs as a <b>detached</b> perfetto session, so it keeps
            recording between requests and has no fixed duration — you decide when to stop.
            The buffer is drained to the device every few seconds, so a long session
            accumulates rather than failing — but the trace file grows with it, so stop
            when you are done. Use this to trace a flow no script can reproduce: a real payment, a
            biometric unlock, a specific sequence of screens.</p>
          <div class="ctl" style="margin-bottom:10px">
            <span class="pill ${st.recording ? 'fail' : 'pass'}">${st.recording ? 'recording' : 'idle'}</span>
            <span style="font-size:12.5px;color:var(--text-muted)">${esc(st.serial || '')}</span>
            ${st.recording && MAN.since ? `<span class="count" id="mantimer">elapsed ${Math.round((Date.now() - MAN.since) / 1000)}s</span>` : ''}
          </div>
          ${!st.recording ? `
            <div class="ctl" style="margin-bottom:10px">
              <span class="flabel">App</span>
              <input id="manpkg" type="text" value="${esc(MAN.pkg)}" aria-label="Package to trace"
                     style="min-width:300px" ${busy ? 'disabled' : ''}>
              <span class="flabel">Start</span><div id="mancold"></div>
              <button id="manstart" ${busy ? 'disabled' : ''}>Start tracing</button>
            </div>
            <p class="hint">Cold force-stops the app and launches it once tracing is live.
              Warm traces whatever is already running \u2014 open the app yourself first.</p>
            <div class="ctl" style="margin:14px 0 10px">
              <input id="mansearch" type="search" placeholder="Search installed apps\u2026"
                     value="${esc(MAN.q)}" aria-label="Search installed apps"
                     style="min-width:260px" ${busy ? 'disabled' : ''}>
              <span class="count">${pkgs.length} of ${installed.length} installed</span>
            </div>
            <div class="scroll" style="max-height:300px"><table>
              <thead><tr><th>App</th><th>Package</th><th></th></tr></thead>
              <tbody>${pkgs.slice(0, MAN_LIST_LIMIT).map(p => `<tr class="${MAN.pkg === p.pkg ? 'cur' : ''}">
                <td>${esc(p.name || p.pkg)}${p.instrumented ? ' <span class="tag">instrumented</span>' : ''}</td>
                <td style="color:var(--text-secondary);font-size:12px">${esc(p.pkg)}</td>
                <td><button class="mini-btn" data-manpick="${esc(p.pkg)}" ${busy ? 'disabled' : ''}>${MAN.pkg === p.pkg ? 'Selected' : 'Use'}</button></td>
              </tr>`).join('') || '<tr><td colspan="3" class="empty">No installed apps match that search.</td></tr>'}</tbody>
            </table></div>
            ${pkgs.length > MAN_LIST_LIMIT ? `<p class="hint" style="margin-top:9px">Showing ${MAN_LIST_LIMIT} of ${pkgs.length} matches. Narrow the search to see the rest.</p>` : ''}`
          : `<div class="ctl">
              <button id="manstop" ${busy ? 'disabled' : ''}>${busy ? 'Stopping…' : 'Stop and analyse'}</button>
              <button id="manabort" class="mini-btn" ${busy ? 'disabled' : ''}>Discard</button>
            </div>
            <p class="hint" style="margin-top:10px">Drive the app on the device now.
              Stop when you are done and the trace will be pulled, analysed and recorded.</p>`}
        </div>
        ${st.recording ? `<div class="card">
          <h2>Live markers</h2>
          <p class="hint">Markers as they land, read from the partial trace on the device
            every few seconds. A screen marked <b>open</b> is the one currently on display.
            If this stays empty while you use the app, the build you are tracing is not
            emitting SwagTrace markers \u2014 check the package above is the instrumented one.</p>
          <div id="manlive">${liveFeedHTML()}</div>
        </div>` : ''}
        ${job ? `<div class="card" style="${job.state === 'error' ? 'border-color:var(--crit)' : job.state === 'done' ? 'border-color:var(--good)' : ''}">
          <h2>${busy ? 'Processing the session…' : job.state === 'done' ? 'Session recorded' : 'Failed'}</h2>
          <div class="joblog">${(job.log || []).map(l => `<div class="jl ${/^ERROR/.test(l.text) ? 'bad' : /^note/.test(l.text) ? 'warn' : ''}">
            <span class="jt">${l.t}s</span>${esc(l.text)}</div>`).join('') || '<div class="jl">starting</div>'}</div>
          ${job.error ? `<div class="find high" style="margin-top:10px"><div class="t">Failed</div><div class="e">${esc(job.error)}</div></div>` : ''}
          ${job.state === 'done' && job.result ? `<div class="readout" style="margin-top:12px">
            <div class="ro"><span class="rok">Run</span><b>${job.result.run_id}</b><em>${esc(job.result.app_pkg || '')}</em></div>
            <div class="ro"><span class="rok">Screens seen</span><b>${job.result.screens || 0}</b>
              <em>${job.result.screens ? 'SwagTrace markers found' : 'no screen markers in this trace'}</em></div>
          </div>` : ''}
        </div>` : ''}`;

      post.push(() => {
        const rb = $('#manrecheck');
        if (rb) rb.onclick = () => loadManualStatus(true).then(render);
        const pk = $('#manpkg');
        if (pk) pk.oninput = () => { MAN.pkg = pk.value.trim(); };
        const sr = $('#mansearch');
        if (sr) sr.oninput = () => {
          MAN.q = sr.value; clearTimeout(sr._t);
          sr._t = setTimeout(() => { render(); const n = $('#mansearch');
            if (n) { n.focus(); n.setSelectionRange(n.value.length, n.value.length); } }, 200);
        };
        const cb = $('#mancold');
        if (cb) {
          cb.innerHTML = [[true, 'Cold'], [false, 'Warm']].map(([v, l]) =>
            `<button class="seg${MAN.cold === v ? ' on' : ''}" data-mc="${v}">${l}</button>`).join('');
          cb.querySelectorAll('.seg').forEach(b => b.onclick = () => { MAN.cold = b.dataset.mc === 'true'; render(); });
        }
        document.querySelectorAll('[data-manpick]').forEach(b => b.onclick = () => {
          MAN.pkg = b.dataset.manpick; render();
        });
        bindLiveFilters();
        // A page reload mid-session leaves the loop dead but the device still
        // recording, so restart it from whatever state the status reports.
        if (st.recording && !MAN.livePolling) pollLiveMarkers();
        const s1 = $('#manstart'); if (s1) s1.onclick = () => manualStart();
        const s2 = $('#manstop'); if (s2) s2.onclick = () => manualStop();
        const s3 = $('#manabort'); if (s3) s3.onclick = () => manualAbort();
        // Live elapsed counter while recording, without re-rendering the page.
        const tm = $('#mantimer');
        if (tm && MAN.since) {
          clearInterval(window.__manTimer);
          window.__manTimer = setInterval(() => {
            const n = $('#mantimer');
            if (!n || !MAN.since) { clearInterval(window.__manTimer); return; }
            n.textContent = `elapsed ${Math.round((Date.now() - MAN.since) / 1000)}s`;
          }, 1000);
        }
      });
    }
  }

  /* ---------------- SCREENS ---------------- */
  if (TAB === 'screens') {
    const withTraces = DATA.runs.filter(r => r.trace_path);
    if (SCR.runId == null && withTraces.length) SCR.runId = withTraces.at(-1).id;
    const d = SCR.data;
    // The launch half reads the same run the Screens picker selected, rather
    // than the global run selection the Startup tab uses. A manual session
    // records startup steps and screen markers from one trace, so making the
    // user change tabs and re-pick the run to see the other half of their own
    // capture was the gap that made launch metrics look absent.
    const scrRun = DATA.runs.find(r => r.id === SCR.runId) || null;

    app.innerHTML = head + `
      <div class="card">
        <div class="ctl">
          <span class="flabel">Run</span>
          <select id="scrrun" aria-label="Run to inspect">
            ${withTraces.map(r => `<option value="${r.id}"${r.id === SCR.runId ? ' selected' : ''}>
              run ${r.id} · ${esc(r.app_name || r.app_pkg || '')} · ${esc(r.label || '')}</option>`).join('')
              || '<option>no runs with a trace file</option>'}
          </select>
          <button id="scrload">Load</button>
        </div>
        <p class="hint" style="margin-top:10px">Screen attribution needs the app to emit
          <code>screen:</code> and <code>action:</code> markers via SwagTrace. CPU here is
          scheduled CPU time overlapped with each visit, not wall time — a screen that is
          merely open while the device idles has not cost anything.</p>
        <div class="ctl" style="margin-top:12px">
          <span class="flabel">View</span><div id="scrview"></div>
        </div>
      </div>
      ${SCR.loading ? '<div class="card"><p class="empty">Reading the trace…</p></div>' : ''}
      ${d && d.error ? `<div class="card"><p class="empty">${esc(d.error)}</p></div>` : ''}
      ${d && !d.error && !d.instrumented && SCR.view === 'usage' ? `<div class="card">
        <h2>No screen markers in this trace</h2>
        <p class="hint">${esc(d.note || '')}</p></div>` : ''}
      ${/* Launch metrics come from the run record, not from screen markers, so an
            uninstrumented app still has them. Gating this on `instrumented`
            would hide the half of the page that does work for exactly the apps
            -- competitors -- where it is the only half available. */''
        }${d && !d.error && SCR.view === 'launch' ? launchViewHTML(scrRun) : ''}
      ${d && d.instrumented && SCR.view === 'usage' ? `
        ${stackViewHTML(d)}
        <div class="card"><h2>Screens</h2>
          <p class="hint">Select a row to chart every visit to that screen separately.
            <b>Depth</b> is how far down the navigation stack the screen sat; a screen that is
            cheap on its own can still be expensive three deep, because everything beneath it
            is still alive.</p>
          <div class="scroll"><table>
            <thead><tr><th>Route</th><th>Rendered by</th><th class="num">Depth</th><th class="num">Visits</th><th class="num">Total ms</th>
              <th class="num">CPU ms</th><th class="num">CPU % of wall</th>
              <th class="num">Slow frames</th><th class="num">Worst RAM growth</th></tr></thead>
            <tbody>${d.screen_summary.map(r => {
              const cpuPct = r.total_ms ? (r.total_cpu_ms / r.total_ms * 100) : null;
              const isOpen = SCR.open === r.route;
              return `<tr class="rowbtn${isOpen ? ' cur' : ''}" data-scrrow="${esc(r.route)}">
                <td>${r.step ? '<span style="color:var(--text-secondary)">\u21b3 </span>' : ''}<span style="color:var(--text-secondary)">${isOpen ? '\u25be' : '\u25b8'}</span> ${esc(r.route)}</td>
                <td><span class="tag">${esc(r.kind_label || 'Unknown')}</span></td>
                <td class="num" title="${esc((r.depths || []).join(', '))}">${
                  r.depth_label || '\u2013'}</td>
                <td class="num">${r.visits}</td>
                <td class="num">${fmt(r.total_ms, 1)}</td>
                <td class="num">${fmt(r.total_cpu_ms, 1)}</td>
                <td class="num" style="color:var(--text-secondary)">${cpuPct == null ? '–' : fmt(cpuPct, 1) + '%'}</td>
                <td class="num ${(r.slow_frame_pct || 0) > 5 ? 'up' : ''}">${r.slow_frame_pct == null ? '–' : fmt(r.slow_frame_pct, 2) + '%'}</td>
                <td class="num ${(r.max_rss_delta_mb || 0) > 10 ? 'up' : ''}">${r.max_rss_delta_mb == null ? '–' : fmt(r.max_rss_delta_mb, 1) + ' MB'}</td>
              </tr>${isOpen ? `<tr><td colspan="9" style="background:var(--surface-1)">
                <div class="ctl" style="margin:4px 0 10px">
                  <span class="flabel">Chart</span><div id="scrmetric"></div>
                  <span class="count">${r.visits} visit${r.visits === 1 ? '' : 's'}</span>
                  ${(r.visit_list || []).some(v => Object.values(v.outlier || {}).some(Boolean))
                    ? '<span class="pill fail">has outliers</span>' : ''}
                </div>
                <div id="scrvisits"></div>
                <p class="hint">One bar per visit, in the order they happened. The dashed line is
                  the mean; a bar in red sits more than two standard deviations from it, which is
                  the visit worth opening. A rising slope across visits is state accumulating
                  between them.</p>
              </td></tr>` : ''}`; }).join('')}</tbody>
          </table></div>
          <p class="hint" style="margin-top:9px">RAM growth is min-to-peak within a single
            visit. A screen that repeatedly leaves RAM higher than it found it is the
            orphaned-surface signature the shell architecture names.</p>
          <p class="hint">Indented rows (\u21b3) are steps <em>inside</em> the route above them,
            so their time is already counted in the parent and the column does not sum.
            <b>Rendered by</b> says what drew the screen \u2014 the comparison worth making in a
            hybrid app is React Native against Compose.</p>
        </div>
        ${d.navigations.length ? `<div class="card"><h2>Transitions</h2>
          <p class="hint">Cost of the navigation itself, separate from the screens either side.</p>
          <div class="scroll"><table>
            <thead><tr><th>From</th><th>To</th><th class="num">Count</th><th class="num">Worst ms</th></tr></thead>
            <tbody>${d.navigations.map(n2 => `<tr>
              <td>${esc(n2.from || '')}</td><td>${esc(n2.to || '')}</td>
              <td class="num">${n2.count}</td>
              <td class="num ${(n2.max_ms || 0) > 32 ? 'up' : ''}">${n2.max_ms == null ? '–' : fmt(n2.max_ms, 1)}</td>
            </tr>`).join('')}</tbody>
          </table></div></div>` : ''}
        ${d.actions.length ? `<div class="card"><h2>Actions</h2>
          <p class="hint">Discrete user actions the app marked. Counts alone are meaningful
            for instant markers; spans also carry timing.</p>
          <div class="scroll"><table>
            <thead><tr><th>Action</th><th class="num">Count</th><th class="num">Mean ms</th><th class="num">Worst ms</th></tr></thead>
            <tbody>${d.actions.map(a => `<tr>
              <td>${esc(a.action)}</td><td class="num">${a.count}</td>
              <td class="num">${a.mean_ms == null ? '–' : fmt(a.mean_ms, 2)}</td>
              <td class="num">${a.max_ms == null ? '–' : fmt(a.max_ms, 2)}</td>
            </tr>`).join('')}</tbody>
          </table></div></div>` : ''}` : ''}`;

    post.push(() => {
      const sel = $('#scrrun');
      if (sel) sel.onchange = () => { SCR.runId = +sel.value; SCR.data = null; render(); };
      const lb = $('#scrload');
      if (lb) lb.onclick = () => loadScreens(SCR.runId).then(render);
      const vb = $('#scrview');
      if (vb) {
        vb.innerHTML = [['usage', 'Screen usage'], ['launch', 'Launch metrics']]
          .map(([v, l]) => `<button class="seg${SCR.view === v ? ' on' : ''}" data-scrview="${v}">${l}</button>`).join('');
        vb.querySelectorAll('.seg').forEach(b => b.onclick = () => {
          SCR.view = b.dataset.scrview; render();
        });
      }
      if (d && d.instrumented && SCR.view === 'usage') {
        document.querySelectorAll('[data-scrrow]').forEach(tr => tr.onclick = () => {
          const route = tr.dataset.scrrow;
          SCR.open = SCR.open === route ? null : route;
          render();
        });
        const mb = $('#scrmetric');
        const row = (d.screen_summary || []).find(r => r.route === SCR.open);
        if (mb && row) {
          mb.innerHTML = Object.entries(METRICS)
            .map(([k, m]) => `<button class="seg${SCR.metric === k ? ' on' : ''}" data-scrm="${k}">${m.label}</button>`).join('');
          mb.querySelectorAll('.seg').forEach(b => b.onclick = e => {
            e.stopPropagation(); SCR.metric = b.dataset.scrm; render();
          });
        }
        const vis = $('#scrvisits');
        if (vis && row) vis.appendChild(visitBars(row, SCR.metric));
        // The detail row sits inside a clickable row, so stop clicks in it from
        // collapsing the thing the user is trying to read.
        [mb, vis].forEach(n => n && n.closest('td') &&
          n.closest('td').addEventListener('click', e => e.stopPropagation()));
      }
      if (!d && !SCR.loading && SCR.runId != null) loadScreens(SCR.runId).then(render);
    });
  }

  /* ---------------- COMPARE ---------------- */
  if (TAB === 'compare') {
    const bench = benchOf(cur);
    if (CMP.run == null) CMP.run = cur.id;
    if (CMP.base == null) CMP.base = bench ? bench.run_id : (rs.length > 1 ? rs.at(-2).id : cur.id);
    const opt = (rid, sel) => DATA.runs.map(r =>
      `<option value="${r.id}"${r.id === sel ? ' selected' : ''}>run ${r.id} \u00b7 ${esc(r.label || 'no label')}${r.app_version ? ' \u00b7 ' + esc(r.app_version) : ''}${bench && bench.run_id === r.id ? '  \u2605 benchmark' : ''}</option>`).join('');
    const d = CMP.data;
    const verdictCell = v => `<span class="cv ${v || ''}">${v === 'worse' ? '\u25b2 worse' : v === 'better' ? '\u25bc better' : 'same'}</span>`;

    app.innerHTML = head + `
      <div class="card">
        <div class="cmpbar">
          <div><span class="flabel">Run</span><select id="cmprun">${opt(CMP.run, CMP.run)}</select></div>
          <div class="vs">vs</div>
          <div><span class="flabel">Baseline</span><select id="cmpbase">${opt(CMP.base, CMP.base)}</select></div>
          <button id="cmpswap" title="Swap the two runs">\u21c4 Swap</button>
          ${bench ? `<button id="cmpbench" title="Compare against the pinned benchmark">Use benchmark (run ${bench.run_id})</button>` : ''}
        </div>
        ${bench ? `<p class="hint" style="margin-top:10px">Benchmark for ${esc(cur.path_kind)} / ${esc(bench.device || 'any device')} is run ${bench.run_id} (${esc(bench.label || 'no label')})${bench.note ? ' \u2014 ' + esc(bench.note) : ''}.</p>`
                : '<p class="hint" style="margin-top:10px">No benchmark pinned. Pin one from the History tab to make it the default baseline here and the reference for regression detection.</p>'}
      </div>
      ${CMP.loading ? '<div class="card"><p class="empty">Comparing\u2026</p></div>' : ''}
      ${d && d.error ? `<div class="card"><p class="empty">${esc(d.error)}</p></div>` : ''}
      ${d && !d.error ? `
        ${!d.comparable ? `<div class="card" style="border-color:var(--crit)">
          <h2 style="color:var(--crit)">Not comparable</h2>
          <p class="hint">Run ${d.run.id} is a <b>${esc(d.run.path_kind)}</b> trace and run ${d.base.id} is a <b>${esc(d.base.path_kind)}</b> trace. The two startup paths have different critical paths and different budgets, so these numbers do not mean the same thing. Pick two runs on the same path.</p></div>` : ''}
        ${d.comparable && !d.same_device ? `<div class="card" style="border-color:var(--warn)">
          <h2 style="color:var(--warn)">Different devices</h2>
          <p class="hint">${esc(d.run.device || 'unknown')} vs ${esc(d.base.device || 'unknown')}. Run-to-run variance across device classes is much wider than within one, so treat small deltas as noise.</p></div>` : ''}
        <div class="card">
          <h2>Top-line metrics</h2>
          <p class="hint">run ${d.run.id} (${esc(d.run.label || 'no label')}) against run ${d.base.id} (${esc(d.base.label || 'no label')}) &mdash;
            ${d.summary.worse} worse, ${d.summary.better} better, ${d.summary.same} unchanged.</p>
          <div class="scroll"><table>
            <thead><tr><th>Metric</th><th class="num">Run ${d.run.id}</th><th class="num">Run ${d.base.id}</th><th class="num">Delta</th><th class="num">Change</th><th></th></tr></thead>
            <tbody>${d.metrics.map(m => `<tr>
              <td>${esc(MNAMES[m.metric] || m.metric)}</td>
              <td class="num">${fmt(m.value, 2)}<span class="u">${esc(MUNITS[m.metric] || '')}</span></td>
              <td class="num" style="color:var(--text-secondary)">${fmt(m.base_value, 2)}</td>
              <td class="num ${m.verdict === 'worse' ? 'up' : m.verdict === 'better' ? 'dn' : ''}">${m.delta > 0 ? '+' : ''}${fmt(m.delta, 2)}</td>
              <td class="num" style="color:var(--text-secondary)">${m.delta_pct == null ? (m.signed ? 'n/a' : '\u2013') : (m.delta_pct > 0 ? '+' : '') + fmt(m.delta_pct, 1) + '%'}</td>
              <td>${verdictCell(m.verdict)}</td></tr>`).join('')}</tbody>
          </table></div>
          ${d.metrics.some(m => m.signed) ? '<p class="hint" style="margin-top:9px">Thermal drift can be negative, so a percentage change across zero would be meaningless; only the absolute move is shown.</p>' : ''}
        </div>
        <div class="card">
          <h2>Steps</h2>
          <p class="hint">Sorted by duration in run ${d.run.id}. A step that got worse expands to show which child slices moved.</p>
          <div class="scroll"><table>
            <thead><tr><th>Step</th><th class="num">Run ${d.run.id}</th><th class="num">Run ${d.base.id}</th><th class="num">Delta</th><th class="num">Change</th><th></th></tr></thead>
            <tbody>${d.steps.map(st => {
              if (st.only_in) return `<tr><td>${esc(st.step.replace('step:', ''))}</td>
                <td colspan="5" style="color:var(--warn)">only present in ${st.only_in === 'run' ? 'run ' + d.run.id : 'run ' + d.base.id}</td></tr>`;
              const rt = RUNTIME[st.step] || 'native';
              const kids = (st.children || []).filter(k => k.delta_ms != null && Math.abs(k.delta_ms) >= 0.5);
              return `<tr>
                <td><i style="display:inline-block;width:9px;height:9px;border-radius:2px;background:${RC[rt]};margin-right:7px"></i>${esc(st.step.replace('step:', ''))}</td>
                <td class="num">${fmt(st.dur_ms, 1)}<span class="u">ms</span></td>
                <td class="num" style="color:var(--text-secondary)">${fmt(st.base_dur_ms, 1)}</td>
                <td class="num ${st.verdict === 'worse' ? 'up' : st.verdict === 'better' ? 'dn' : ''}">${st.delta_ms > 0 ? '+' : ''}${fmt(st.delta_ms, 1)}</td>
                <td class="num" style="color:var(--text-secondary)">${st.delta_pct == null ? '\u2013' : (st.delta_pct > 0 ? '+' : '') + fmt(st.delta_pct, 1) + '%'}</td>
                <td>${verdictCell(st.verdict)}</td></tr>` +
                (st.verdict === 'worse' && kids.length ? kids.slice(0, 4).map(k => `<tr class="kidrow">
                  <td>\u21b3 ${esc(k.name)}</td>
                  <td class="num">${k.dur_ms == null ? '\u2013' : fmt(k.dur_ms, 1)}</td>
                  <td class="num" style="color:var(--text-secondary)">${k.base_dur_ms == null ? '\u2013' : fmt(k.base_dur_ms, 1)}</td>
                  <td class="num ${k.delta_ms > 0 ? 'up' : 'dn'}">${k.delta_ms > 0 ? '+' : ''}${fmt(k.delta_ms, 1)}</td>
                  <td class="num" style="color:var(--text-secondary)">${k.delta_pct == null ? '\u2013' : (k.delta_pct > 0 ? '+' : '') + fmt(k.delta_pct, 1) + '%'}</td>
                  <td></td></tr>`).join('') : '');
            }).join('')}</tbody>
          </table></div>
        </div>` : (CMP.run === CMP.base ? '<div class="card"><p class="empty">Pick two different runs.</p></div>' : '')}`;
    post.push(() => {
      const rsel = $('#cmprun'), bsel = $('#cmpbase');
      if (rsel) rsel.onchange = async () => { CMP.run = +rsel.value; await loadCompare(); render(); };
      if (bsel) bsel.onchange = async () => { CMP.base = +bsel.value; await loadCompare(); render(); };
      const sw = $('#cmpswap');
      if (sw) sw.onclick = async () => { [CMP.run, CMP.base] = [CMP.base, CMP.run]; await loadCompare(); render(); };
      const cb = $('#cmpbench');
      if (cb) cb.onclick = async () => { CMP.base = bench.run_id; await loadCompare(); render(); };
      if (!CMP.data && !CMP.loading && CMP.run !== CMP.base) loadCompare().then(render);
    });
  }

  /* ---------------- HISTORY ---------------- */
  if (TAB === 'history') {
    const benchRun = benchOf(cur);
    app.innerHTML = head + `
      ${(DATA.benchmarks || []).length ? `<div class="card">
        <h2>Pinned benchmarks</h2>
        <p class="hint">A benchmark is the reference a run's regressions are measured against, replacing the trailing baseline for its scope. One per startup path and device.</p>
        <div class="scroll"><table class="tight">
          <thead><tr><th>Scope</th><th class="num">Run</th><th>Label</th><th>Pinned</th><th>Note</th><th></th></tr></thead>
          <tbody>${DATA.benchmarks.map(b => `<tr>
            <td>${esc(b.path_kind)} / ${esc(b.device || 'any device')}</td>
            <td class="num">${b.run_id}</td><td>${esc(b.label || '')}</td>
            <td style="color:var(--text-secondary)">${esc(b.set_at)}</td>
            <td style="color:var(--text-secondary)">${esc(b.note || '')}</td>
            <td><button class="mini-btn" data-unbench="${b.run_id}">Unpin</button></td></tr>`).join('')}</tbody>
        </table></div></div>` : ''}
      <div class="card">
        <h2>Run history</h2>
        <p class="hint">${rs.length} run(s) in the current window. Sort by any column; filters narrow this table only.</p>
        <div class="ctl" style="margin-bottom:12px">
          <input id="qfilter" type="search" placeholder="Search label, sha, version…" value="${esc(FILTER.q)}" aria-label="Search runs">
          <select id="vfilter" aria-label="Filter by verdict">
            <option value="all"${FILTER.verdict === 'all' ? ' selected' : ''}>All verdicts</option>
            ${['pass', 'warn', 'fail', 'unknown'].map(v => `<option value="${v}"${FILTER.verdict === v ? ' selected' : ''}>${v}</option>`).join('')}
          </select>
          <select id="dfilter" aria-label="Filter by device">
            <option value="all"${FILTER.device === 'all' ? ' selected' : ''}>All devices</option>
            ${devices.map(d => `<option value="${esc(d)}"${FILTER.device === d ? ' selected' : ''}>${esc(d)}</option>`).join('')}
          </select>
          ${(FILTER.q || FILTER.verdict !== 'all' || FILTER.device !== 'all') ? '<button id="clearf">Clear</button>' : ''}
          <span class="count">${fr.length} of ${rs.length} run${rs.length === 1 ? '' : 's'}</span>
        </div>
        <div class="scroll"><table>
          <thead><tr>
            ${th('history', 'id', 'Run')}${th('history', 'ts', 'When')}${th('history', 'app_name', 'App')}${th('history', 'label', 'Label')}
            ${th('history', 'app_version', 'Version')}${th('history', 'device', 'Device')}
            ${th('history', 'ttff_ms', 'First frame', 'num')}${th('history', 'slow_pct', 'Slow %', 'num')}
            ${th('history', 'thermal_drift_pct', 'Drift %', 'num')}${th('history', 'peak_rss_mb', 'Peak RAM', 'num')}
            ${th('history', 'verdict', 'Verdict')}<th>Actions</th>
          </tr></thead>
          <tbody>${sortRows(fr, 'history', { verdict: r => r.analysis?.verdict || 'zzz', app_name: r => r.app_name || '' }).map(r => `<tr${r.id === cur.id ? ' class="cur"' : ''}>
            <td>${r.id}</td><td style="color:var(--text-secondary)">${esc(r.ts)}</td>
            <td>${esc(r.app_name || '')}${r.derived ? ' <span class="tag">derived</span>' : ''}</td>
            <td>${esc(r.label || '')}</td><td style="color:var(--text-secondary)">${esc(r.app_version || '')}</td>
            <td style="color:var(--text-secondary)">${esc(r.device || '')}</td>
            <td class="num" style="${r.ttid_budget_ms && r.ttff_ms > r.ttid_budget_ms ? 'color:var(--crit);font-weight:650' : ''}">${fmt(r.ttff_ms, 1)} ms</td>
            <td class="num">${fmt(r.slow_pct, 2)}</td>
            <td class="num" style="${r.thermal_drift_pct > gb.thermal_drift_pct ? 'color:var(--crit)' : ''}">${fmt(r.thermal_drift_pct, 2)}</td>
            <td class="num">${fmt(r.peak_rss_mb, 1)} MB</td>
            <td><span class="pill ${esc(r.analysis?.verdict || 'unknown')}">${esc(r.analysis?.verdict || '–')}</span></td>
            <td class="acts">
              ${benchRun && benchRun.run_id === r.id
                ? `<span class="bpin on" title="${esc(benchRun.note || 'Pinned benchmark')}">★ benchmark</span>
                   <button class="mini-btn" data-unbench="${r.id}" title="Unpin this benchmark">Unpin</button>`
                : `<button class="mini-btn" data-bench="${r.id}" title="Pin run ${r.id} as the benchmark for ${esc(r.path_kind)} / ${esc(r.device || 'any device')}">Set benchmark</button>`}
              <button class="mini-btn" data-cmp="${r.id}" title="Compare run ${r.id} against the current baseline">Compare</button>
            </td>
          </tr>`).join('') || '<tr><td colspan="12" class="empty">No runs match these filters.</td></tr>'}</tbody>
        </table></div>
      </div>`;
    post.push(() => {
      wireSort();
      document.querySelectorAll('[data-bench]').forEach(b => b.onclick = async e => {
        e.stopPropagation();
        b.disabled = true; b.textContent = 'Pinning\u2026';
        await setBenchmark(+b.dataset.bench);
      });
      document.querySelectorAll('[data-unbench]').forEach(b => b.onclick = async e => {
        e.stopPropagation();
        b.disabled = true; b.textContent = 'Unpinning\u2026';
        await clearBenchmark(+b.dataset.unbench);
      });
      document.querySelectorAll('[data-cmp]').forEach(b => b.onclick = async e => {
        e.stopPropagation();
        CMP.run = +b.dataset.cmp;
        // Always prefer the current benchmark as the baseline; fall back to the
        // nearest earlier run. A stale CMP.base from a previous comparison would
        // otherwise silently win after the benchmark is re-pinned.
        const bch = benchOf(cur);
        CMP.base = (bch && bch.run_id !== CMP.run)
          ? bch.run_id
          : ([...rs].reverse().find(r => r.id < CMP.run)?.id ?? cur.id);
        TAB = 'compare';
        await loadCompare();
        render();
      });
      const vf = $('#vfilter'); if (vf) vf.onchange = () => { FILTER.verdict = vf.value; render(); };
      const df = $('#dfilter'); if (df) df.onchange = () => { FILTER.device = df.value; render(); };
      const cf = $('#clearf'); if (cf) cf.onclick = () => { FILTER.q = ''; FILTER.verdict = 'all'; FILTER.device = 'all'; render(); };
      const qf = $('#qfilter');
      if (qf) qf.oninput = () => {
        FILTER.q = qf.value; clearTimeout(qf._t);
        qf._t = setTimeout(() => { render(); const n = $('#qfilter'); if (n) { n.focus(); n.setSelectionRange(n.value.length, n.value.length); } }, 220);
      };
    });
  }

  post.forEach(fn => fn());
}

function renderLegend(seen, rs) {
  const lg = $('#lg');
  if (!lg) return;
  // Runtimes that the CURRENT mode actually plots. In critical-path mode the
  // deferred runtimes are out of scope, so their toggles are marked inert rather
  // than looking broken when clicking them changes nothing.
  const inScope = new Set();
  (rs || []).forEach(r => r.steps.forEach(x => {
    if (MODE !== 'critical' || onCritical(x.step)) inScope.add(RUNTIME[x.step] || 'native');
  }));
  const shown = seen.filter(k => !HIDDEN.has(k) && inScope.has(k));
  // Legend doubles as the show/hide control, so identity and filtering share one affordance.
  lg.innerHTML = seen.map(k => {
    const off = HIDDEN.has(k);
    const oos = !inScope.has(k);
    const lastOne = !off && shown.length <= 1 && !oos;
    return `<button class="lgi${off ? ' off' : ''}${oos ? ' oos' : ''}" data-rt="${esc(k)}"
      aria-pressed="${!off}" ${lastOne ? 'disabled' : ''}
      title="${oos ? RLABEL[k] + ' has no steps in this view' : lastOne ? 'At least one runtime must stay visible' : 'Show or hide ' + RLABEL[k]}">
      <i style="background:${RC[k]}"></i>${esc(RLABEL[k])}${oos ? '<em>not in view</em>' : ''}</button>`;
  }).join('') + (HIDDEN.size ? '<button class="lgi reset" id="lgreset">Show all</button>' : '');
  lg.querySelectorAll('.lgi[data-rt]').forEach(b => b.onclick = () => {
    if (b.disabled) return;
    const k = b.dataset.rt;
    HIDDEN.has(k) ? HIDDEN.delete(k) : HIDDEN.add(k);
    render();
  });
  const rst = $('#lgreset');
  if (rst) rst.onclick = () => { HIDDEN.clear(); render(); };
}

function renderModes() {
  const w = $('#modebtns');
  if (!w) return;
  const modes = [['critical', 'Critical path'], ['all', 'All steps'], ['grouped', 'Per step']];
  w.innerHTML = modes.map(([m, l]) => `<button class="seg${MODE === m ? ' on' : ''}" data-mode="${m}"
    aria-pressed="${MODE === m}">${l}</button>`).join('');
  w.querySelectorAll('.seg').forEach(b => b.onclick = () => { MODE = b.dataset.mode; render(); });
}

function wireStepRows(rs, cur) {
  // Escape closes the panel, matching the Close button.
  if (!wireStepRows._esc) {
    wireStepRows._esc = true;
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && OPEN_STEP) { OPEN_STEP = null; render(); }
    });
  }
  if (OPEN_STEP && cur.steps.some(x => x.step === OPEN_STEP)) {
    $('#stepdrill').innerHTML = stepDetail(rs, OPEN_STEP);
    const sp = $('#stepspark');
    if (sp) {
      const series = rs.map(r => r.steps.find(x => x.step === OPEN_STEP)).map(x => x ? x.dur_ms : null);
      const budget = cur.steps.find(x => x.step === OPEN_STEP)?.budget_ms;
      sp.appendChild(lineChart(rs.map((r, i) => ({ ...r, _v: series[i] })).filter(r => r._v != null),
        '_v', budget, `${OPEN_STEP.replace('step:', '')} duration (ms)`, RC[RUNTIME[OPEN_STEP] || 'native']));
    }
    document.querySelectorAll('.sparkcell').forEach(c => {
      try { c.appendChild(sparkline(JSON.parse(c.dataset.spark))); } catch (e) {}
    });
    const cd = $('#closedrill');
    if (cd) cd.onclick = () => { OPEN_STEP = null; render(); };
  }
  document.querySelectorAll('.steprow').forEach(tr => {
    const go = () => {
      OPEN_STEP = OPEN_STEP === tr.dataset.step ? null : tr.dataset.step;
      render();
      if (OPEN_STEP) {
        const d = $('#stepdrill');
        if (d) d.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      } else {
        // On close, keep the row that was open in view rather than jumping.
        document.querySelector(`tr.steprow[data-step="${tr.dataset.step}"]`)
          ?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    };
    tr.addEventListener('click', go);
    tr.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
  });
}

/* ---------- boot ---------- */
async function load() {
  DATA = await (await fetch('/api/history')).json();

  // App scope first, since it constrains which path kinds are even meaningful.
  const apps = appsInHistory();
  if (APP !== 'all' && !apps.some(a => a.pkg === APP)) APP = 'all';
  const asel = $('#appsel');
  asel.innerHTML = `<option value="all"${APP === 'all' ? ' selected' : ''}>All apps</option>`
    + apps.map(a => `<option value="${esc(a.pkg)}"${a.pkg === APP ? ' selected' : ''}>`
        + `${esc(a.name)}${a.role === 'own' ? ' (ours)' : ''} \u00b7 ${a.n}</option>`).join('');
  asel.onchange = () => {
    APP = asel.value;
    // The selected path may not exist for the newly scoped app.
    const ks = [...new Set(DATA.runs.filter(r => APP === 'all' || r.app_pkg === APP)
                                    .map(r => r.path_kind))];
    if (!ks.includes(PATH) && ks.length) PATH = ks[0];
    load();
  };

  const scoped = DATA.runs.filter(r => APP === 'all' || (r.app_pkg || '') === APP);
  const kinds = [...new Set(scoped.map(r => r.path_kind))];
  if (!kinds.includes(PATH) && kinds.length) PATH = kinds[0];
  const sel = $('#pathsel');
  sel.innerHTML = kinds.map(k => `<option value="${esc(k)}"${k === PATH ? ' selected' : ''}>${esc(pathLabel(k))}</option>`).join('');
  sel.onchange = () => { PATH = sel.value; render(); };
  render();
}
$('#rangebtn').onclick = e => {
  RANGE = RANGE === 30 ? 100 : RANGE === 100 ? 10 : 30;
  e.target.textContent = `Last ${RANGE}`; render();
};
$('#themebtn').onclick = () => {
  const d = document.documentElement;
  const dark = d.getAttribute('data-theme') === 'dark' ||
    (!d.getAttribute('data-theme') && matchMedia('(prefers-color-scheme: dark)').matches);
  d.setAttribute('data-theme', dark ? 'light' : 'dark');
};
load();
