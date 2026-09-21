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

let DATA = null, RANGE = 30, PATH = 'returning_user';
let SORT = { history: { k: 'id', dir: -1 }, steps: { k: 'start_ms', dir: 1 } };
let FILTER = { verdict: 'all', device: 'all', runtime: 'all', q: '' };
let OPEN_STEP = null;   // step drilled into, null = none
let HIDDEN = new Set();  // runtimes toggled off in the step chart
let MODE = 'critical';   // critical | all | grouped
let TAB = 'overview';    // one tab per performance concern in the architecture
let CMP = { run: null, base: null, data: null, loading: false };  // comparison view

const TABS = [
  { id: 'overview', label: 'Overview',  blurb: 'Verdict, budgets and findings for the latest run.' },
  { id: 'startup',  label: 'Startup',   blurb: 'Time to first usable camera frame, and the deferred-work ordering constraint.' },
  { id: 'frames',   label: 'Frame pacing', blurb: 'Slow and frozen frames during sustained scanning, and thermal drift.' },
  { id: 'memory',   label: 'Memory',    blurb: 'Peak RSS with three runtimes resident, and growth suggesting orphaned RN surfaces.' },
  { id: 'steps',    label: 'Steps',     blurb: 'Per-step durations, trailing baselines and child-slice breakdown.' },
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
  peak_rss_mb: 'Peak RSS', rss_growth_mb: 'RSS growth' };
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
  // Path and range define the charted window; the history filters narrow the table
  // only, so the trend charts keep a stable baseline to read against.
  return DATA.runs.filter(r => r.path_kind === PATH).slice(-RANGE);
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

/* ---------- render ---------- */
function tabBar() {
  return `<nav class="tabs" role="tablist">${TABS.map(t => `
    <button role="tab" class="tab${TAB === t.id ? ' on' : ''}" data-tab="${t.id}"
      aria-selected="${TAB === t.id}">${esc(t.label)}</button>`).join('')}</nav>`;
}

function tileHTML(k, v, unit, budget, prevV, d) {
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
        ${tileHTML('Peak RSS', cur.peak_rss_mb, 'MB', gb.peak_rss_mb, prev?.peak_rss_mb, 1)}
        ${tileHTML('RSS growth', cur.rss_growth_mb, 'MB', gb.rss_growth_mb, prev?.rss_growth_mb, 1)}
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
        ${tileHTML('Peak RSS', cur.peak_rss_mb, 'MB', gb.peak_rss_mb, prev?.peak_rss_mb, 1)}
        ${tileHTML('RSS growth', cur.rss_growth_mb, 'MB', gb.rss_growth_mb, prev?.rss_growth_mb, 1)}
        ${hh ? tileHTML('Hermes heap peak', hh.peak_mb, 'MB', null, prev?.memory?.hermes_heap?.peak_mb, 1) : ''}
        ${hh ? tileHTML('Hermes heap growth', hh.growth_mb, 'MB', null, prev?.memory?.hermes_heap?.growth_mb, 1) : ''}
      </div>
      <div class="card"><h2>Three runtimes, one process</h2>
        <p class="hint">Hermes + Fabric, Cronet's Chromium stack, CameraX and ML Kit buffers, Skia and SQLite are all resident at once. Growth that does not return to baseline across a session is the orphaned-surface signature: a Surface started and never stopped keeps its whole JS component tree alive for the life of the process.</p>
        ${hh && cur.rss_growth_mb ? `<div class="readout"><div class="ro"><span class="rok">JS share of growth</span>
          <b>${fmt(hh.growth_mb / cur.rss_growth_mb * 100, 0)}%</b>
          <em>${fmt(hh.growth_mb, 1)}MB of ${fmt(cur.rss_growth_mb, 1)}MB total</em></div></div>` : ''}
      </div>
      <div class="card"><h2>Peak RSS and Hermes heap</h2>
        <p class="hint">Both in MB on one axis. Dashed line is the ${gb.peak_rss_mb}MB RSS ceiling.</p>
        <div class="legend"><span><i style="background:var(--s1)"></i>Peak RSS</span><span><i style="background:var(--s2)"></i>Hermes heap peak</span></div>
        <div id="c6"></div></div>
      <div class="card"><h2>Session growth</h2>
        <p class="hint">Min-to-peak within each run. Dashed line is the ${gb.rss_growth_mb}MB budget.</p>
        <div id="c7"></div></div>
      <div class="card"><h2>Memory findings</h2>
        <div>${findingsHTML(an, { kinds: ['memory', 'budget_breach'],
          about: ['memor', 'rss', 'heap', 'leak', 'surface', 'resident', 'growth'],
          emptyMsg: 'No memory findings for the latest run.' })}</div></div>`;
    post.push(() => {
      $('#c6').appendChild(multiLine(rs, [
        { name: 'Peak RSS', color: 'var(--s1)', get: r => r.peak_rss_mb },
        { name: 'Hermes heap peak', color: 'var(--s2)', get: r => r.memory?.hermes_heap?.peak_mb },
      ], gb.peak_rss_mb, 'peak RSS and Hermes heap (MB)'));
      $('#c7').appendChild(lineChart(rs, 'rss_growth_mb', gb.rss_growth_mb, 'RSS growth (MB)', 'var(--s3)'));
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
            ${th('history', 'thermal_drift_pct', 'Drift %', 'num')}${th('history', 'peak_rss_mb', 'Peak RSS', 'num')}
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
  const kinds = [...new Set(DATA.runs.map(r => r.path_kind))];
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
