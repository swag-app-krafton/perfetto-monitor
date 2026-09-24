"""Copilot answers, computed deterministically from the run history.

The dashboard's Copilot panel talks to this through a stream of events:

    step   {"text"}                         progress, emitted as work happens
    block  {"type": verdict|heading|para|table|bars|code|cites, ...}
    done   {"elapsed_ms", "steps"}
    error  {"kind": no_data|internal, "title", "message", ...}

For now the answers come from rules over real data rather than a language
model -- the panel, its states and its citations are built against this, and
a model-backed engine can later replace `answer()` without the client
changing. Every number in an answer is read from the run history or a trace;
nothing is invented, and a question this engine cannot answer says so.

Citations are typed and carry the dashboard route and highlight target, so the
client never has to know how a kind maps to a screen.
"""
from __future__ import annotations

import re
import statistics
import time

METRICS = [
    ("ttff_ms", "TTID", "ms", 0),
    ("slow_pct", "Slow frames", "%", 2),
    ("janky_pct", "Janky frames", "%", 2),
    ("peak_rss_mb", "Peak RAM", "MB", 0),
    ("rss_growth_mb", "RAM growth", "MB", 0),
    ("thermal_drift_pct", "Thermal drift", "%", 1),
]
BUDGET_KEY = {"slow_pct": "slow_frame_pct", "janky_pct": "janky_frame_pct",
              "peak_rss_mb": "peak_rss_mb", "rss_growth_mb": "rss_growth_mb",
              "thermal_drift_pct": "thermal_drift_pct"}


# ----------------------------------------------------------------- citations

def cite_run(r):
    return {"kind": "run", "id": r["id"], "label": f"Run #{r['id']}", "path": "/history", "focus": f"run:{r['id']}"}


def cite_finding(i, f):
    return {"kind": "finding", "id": f"F-{i + 1}", "label": f"Finding F-{i + 1}", "path": "/overview", "focus": f"F-{i + 1}"}


def cite_step(step):
    return {"kind": "step", "id": step, "label": f"Step · {step.replace('step:', '')}", "path": "/steps", "focus": step}


def cite_chart(which):
    table = {"ttid": ("TTID chart", "/startup", "ttidChart"), "peak": ("Peak RAM chart", "/memory", "peakChart"),
             "frames": ("Slow-frames chart", "/frames", "framesChart"), "ordering": ("Ordering constraint", "/startup", "order"),
             "strip": ("Verdict by run", "/overview", "strip")}
    label, path, focus = table[which]
    return {"kind": "chart", "id": which, "label": label, "path": path, "focus": focus}


def cite_screen(route, run_id):
    return {"kind": "screen", "id": route, "label": f"Screen · {route}", "path": f"/screens?run={run_id}", "focus": f"screen:{route}"}


def cite_stress(t):
    return {"kind": "stress", "id": t["id"], "label": f"Stress test #{t['id']}", "path": "/stress", "focus": f"stress:{t['id']}"}


def cite_compare(a, b):
    return {"kind": "compare", "id": f"{a}-{b}", "label": f"Compare #{a} vs #{b}", "path": f"/compare?mode=run&a={a}&b={b}", "focus": "compare"}


# ------------------------------------------------------------------ helpers

def _fmt(v, dp=0):
    return "–" if v is None else f"{v:,.{dp}f}"


def _signed(v, dp=0, unit=""):
    if v is None:
        return "–"
    return f"{'+' if v > 0 else '−' if v < 0 else '±'}{abs(v):,.{dp}f}{unit}"


def _tag(delta, pct):
    if delta is None:
        return "same"
    if pct is not None and abs(pct) <= 2:
        return "same"
    return "worse" if delta > 0 else "better" if delta < 0 else "same"


def _val(run, key):
    v = run.get(key)
    if v is None or (key == "ttff_ms" and v <= 0):
        return None
    return v


class Ctx:
    """What one question is about: the runs in scope, and the one it names."""

    def __init__(self, history, scope, chips, text):
        runs = history["runs"]
        app, path, platform = scope.get("app"), scope.get("path"), scope.get("platform")
        self.history = history
        # The lane in view (Android or iOS) is part of the scope: the same id
        # can be an app on both, and their runs are never read together.
        self.scoped = [r for r in runs if (not app or r.get("app_pkg") == app)
                       and (not path or r.get("path_kind") == path)
                       and (not platform or (r.get("platform") or "android") == platform)]
        self.by_id = {r["id"]: r for r in runs}
        mentioned = [int(m) for m in re.findall(r"#(\d{1,5})", text)]
        chip_runs = [c.get("id") for c in chips if c.get("kind") == "run"]
        self.requested = next((i for i in mentioned + chip_runs if i is not None), None)
        self.run = self.by_id.get(self.requested) if self.requested is not None else (self.scoped[-1] if self.scoped else None)
        # Same rule as the dashboard: same app and path, and the same device
        # when the benchmark names one.
        cands = [b for b in history.get("benchmarks", [])
                 if self.run and b.get("app_pkg") == self.run.get("app_pkg")
                 and b.get("path_kind") == self.run.get("path_kind")
                 and (b.get("platform") or "android") == (self.run.get("platform") or "android")]
        bench = (next((b for b in cands if b.get("device") and b.get("device") == self.run.get("device")), None)
                 or next((b for b in cands if not b.get("device")), None))
        self.bench = self.by_id.get(bench["run_id"]) if bench else None
        earlier = [r for r in self.scoped if self.run and r["id"] < self.run["id"]]
        self.base = self.bench or (earlier[-1] if earlier else None)
        self.base_label = (f"Benchmark #{self.bench['id']}" if self.bench else
                           f"previous run #{self.base['id']}" if self.base else "no earlier run")
        self.second = next((i for i in mentioned[1:] if i in self.by_id), None)
        # The Overview lists findings for the newest run in scope only, so a
        # finding citation can land there only when that is the run in question.
        self.on_overview = bool(self.run and self.scoped and self.run["id"] == self.scoped[-1]["id"])
        self.chips = chips

    def named_step(self, text):
        """The step a question is about: a step chip, else a step of this run
        named in the text (longest name first, so `camera_open_x` beats
        `camera_open`)."""
        if not self.run:
            return None
        steps = [st["step"] for st in self.run.get("steps", [])]
        chip = next((c.get("id") for c in self.chips if c.get("kind") == "step" and c.get("id") in steps), None)
        if chip:
            return chip
        t = text.lower()
        return next((st for st in sorted(steps, key=len, reverse=True)
                     if len(st.replace("step:", "")) >= 4 and st.replace("step:", "").lower() in t), None)

    def finding_chip(self):
        for c in self.chips:
            if c.get("kind") == "finding" and (m := re.fullmatch(r"F-(\d+)", str(c.get("id")))):
                return int(m.group(1)) - 1
        return None

    def cite_findings(self, findings, start=0):
        return [cite_finding(start + i, f) for i, f in enumerate(findings)] if self.on_overview else []


# ------------------------------------------------------------------ answers

def _metrics_table(ctx):
    r, b = ctx.run, ctx.base
    rows = []
    for key, label, unit, dp in METRICS:
        v, bv = _val(r, key), (_val(b, key) if b else None)
        if v is None and bv is None:
            continue
        d = v - bv if v is not None and bv is not None else None
        pct = d / bv * 100 if d is not None and bv else None
        rows.append({"cells": [label, f"{_fmt(v, dp)} {unit}" if v is not None else "not measured",
                               f"{_fmt(bv, dp)} {unit}" if bv is not None else "–",
                               _signed(d, dp, f" {unit}")], "tag": _tag(d, pct)})
    return {"type": "table", "cols": ["Metric", f"Run #{r['id']}", ctx.base_label.capitalize(), "Δ"], "rows": rows}


def _step_moves(ctx):
    r = ctx.run
    prior = [x for x in ctx.scoped if x["id"] < r["id"]][-10:]
    out = []
    for st in r.get("steps", []):
        if ctx.bench:
            base = next((s["dur_ms"] for s in ctx.bench.get("steps", []) if s["step"] == st["step"]), None)
        else:
            vals = [s["dur_ms"] for x in prior for s in x.get("steps", []) if s["step"] == st["step"]]
            base = statistics.median(vals) if vals else None
        if base is not None:
            out.append((st["step"], st["dur_ms"], base, st["dur_ms"] - base))
    return sorted(out, key=lambda t: -t[3])


def _verdict_block(run):
    a = run.get("analysis") or {}
    v = a.get("verdict")
    tone = v if v in ("pass", "warn", "fail") else "neutral"
    return {"type": "verdict", "tone": tone, "label": (v or "none").upper(),
            "text": a.get("headline") or f"Run #{run['id']} has no recorded analysis."}


def why(ctx, emit_step, text=""):
    r = ctx.run
    emit_step(f"Loaded run #{r['id']} · {r.get('device') or 'unknown device'} · {r.get('path_kind')}")
    blocks = [_verdict_block(r)]
    # Answer the metric the question names before the verdict's own reason:
    # "why did TTID regress" deserves "it did not" when it did not.
    if re.search(r"\bttid\b|startup", text.lower()) and ctx.base:
        v, bv = _val(r, "ttff_ms"), _val(ctx.base, "ttff_ms")
        if v is not None and bv is not None:
            d = v - bv
            moved = "regressed" if d >= 5 else "improved" if d <= -5 else "did not move meaningfully"
            blocks.append({"type": "para", "text": f"TTID {moved}: {v:.0f} ms against {bv:.0f} ms for {ctx.base_label} ({_signed(d, 0, ' ms')})."
                           + ("" if d >= 5 else " The verdict comes from the metrics below, not from startup.")})
    emit_step(f"Compared {len(METRICS)} metrics with {ctx.base_label}")
    blocks.append({"type": "heading", "text": "Where it stands"})
    blocks.append(_metrics_table(ctx))
    moves = _step_moves(ctx)
    emit_step(f"Compared {len(moves)} startup steps")
    findings = (r.get("analysis") or {}).get("findings") or []
    worst = [m for m in moves if m[3] >= 5]
    paras = []
    if findings:
        f = findings[0]
        # Paragraphs are plain text; only code blocks carry Markdown.
        paras.append(f"The leading finding is {f['title']}: {f['evidence'].rstrip('.')}. {f.get('recommendation') or ''}".strip())
    if worst:
        s, cur, base, d = worst[0]
        paras.append(f"The step that moved most is {s.replace('step:', '')}: {cur:.1f} ms against {base:.1f} ms ({_signed(d, 1, ' ms')}).")
    elif moves:
        paras.append("No startup step moved by 5 ms or more, so startup is not what changed the verdict.")
    for p in paras:
        blocks.append({"type": "para", "text": p})
    emit_step(f"Found {len(findings)} finding{'s' if len(findings) != 1 else ''}")
    cites = [cite_run(r)] + ctx.cite_findings(findings[:3])
    if worst:
        cites.append(cite_step(worst[0][0]))
    blocks.append({"type": "cites", "items": cites})
    return blocks


def which_step(ctx, emit_step):
    r = ctx.run
    emit_step(f"Loaded run #{r['id']}")
    moves = _step_moves(ctx)
    emit_step(f"Compared {len(moves)} steps with {'the benchmark' if ctx.bench else 'the median of recent runs'}")
    if not moves:
        return [{"type": "para", "text": f"Run #{r['id']} has no steps with a baseline to compare against."}]
    top = moves[0]
    blocks = [{"type": "verdict", "tone": "fail" if top[3] >= 5 else "pass", "label": "GREW" if top[3] >= 5 else "STEADY",
               "text": f"{top[0].replace('step:', '')} moved most: {_signed(top[3], 1, ' ms')}." if top[3] >= 5
               else "No step grew by 5 ms or more."},
              {"type": "table", "cols": ["Step", "This run", "Baseline", "Δ"],
               "rows": [{"cells": [s.replace("step:", ""), f"{c:.1f} ms", f"{b:.1f} ms", _signed(d, 1, " ms")],
                         "tag": "worse" if d >= 5 else "better" if d <= -5 else "same"} for s, c, b, d in moves[:6]]},
              {"type": "cites", "items": [cite_step(s) for s, *_ in moves[:3]]}]
    return blocks


def step_detail(ctx, emit_step, step):
    r = ctx.run
    name = step.replace("step:", "")
    emit_step(f"Loaded {name} from run #{r['id']}")
    row = next(st for st in r.get("steps", []) if st["step"] == step)
    prior = [x for x in ctx.scoped if x["id"] < r["id"]][-10:]
    if ctx.bench:
        base_row = next((st for st in ctx.bench.get("steps", []) if st["step"] == step), None)
        base_label = f"Benchmark #{ctx.bench['id']}"
        base = base_row["dur_ms"] if base_row else None
        child_base = {c["name"]: c["dur_ms"] for c in (base_row or {}).get("children", [])}
    else:
        rows = [st for x in prior for st in x.get("steps", []) if st["step"] == step]
        base = statistics.median([st["dur_ms"] for st in rows]) if rows else None
        base_label = f"the median of {len(rows)} earlier run{'s' if len(rows) != 1 else ''}"
        names = {c["name"] for st in rows for c in st.get("children", [])}
        child_base = {n: statistics.median([c["dur_ms"] for st in rows for c in st.get("children", []) if c["name"] == n]) for n in names}
    emit_step(f"Compared it with {base_label}")
    if base is None:
        return [{"type": "para", "text": f"{name} took {row['dur_ms']:.1f} ms in run #{r['id']}; there is no earlier measurement of it to compare against."},
                {"type": "cites", "items": [cite_step(step), cite_run(r)]}]
    d = row["dur_ms"] - base
    tone, label = ("fail", "GREW") if d >= 5 else ("pass", "SHRANK") if d <= -5 else ("neutral", "STEADY")
    blocks = [{"type": "verdict", "tone": tone, "label": label,
               "text": f"{name} took {row['dur_ms']:.1f} ms against {base:.1f} ms for {base_label} ({_signed(d, 1, ' ms')})."}]
    kids = []
    for c in row.get("children", []):
        b = child_base.get(c["name"])
        kids.append((c["name"], c["dur_ms"], b, c["dur_ms"] - b if b is not None else None))
    kids.sort(key=lambda k: -abs(k[3]) if k[3] is not None else 0)
    if kids:
        emit_step(f"Compared {len(kids)} child slice{'s' if len(kids) != 1 else ''}")
        moved = [k for k in kids if k[3] is not None and abs(k[3]) >= 5]
        if moved and d >= 5:
            blocks.append({"type": "para", "text": f"Most of the change is in {moved[0][0]} ({_signed(moved[0][3], 1, ' ms')})."})
        blocks.append({"type": "table", "cols": ["Child slice", "This run", "Baseline", "Δ"],
                       "rows": [{"cells": [n, f"{c:.1f} ms", f"{b:.1f} ms" if b is not None else "–", _signed(dd, 1, " ms")],
                                 "tag": "same" if dd is None else "worse" if dd >= 5 else "better" if dd <= -5 else "same"}
                                for n, c, b, dd in kids[:6]]})
    elif abs(d) >= 5:
        blocks.append({"type": "para", "text": "The step records no child slices, so the trace cannot say which part of it moved."})
    blocks.append({"type": "cites", "items": [cite_step(step), cite_run(r)]})
    return blocks


def summarise_pr(ctx, emit_step):
    r = ctx.run
    emit_step(f"Loaded run #{r['id']}")
    a = r.get("analysis") or {}
    lines = [f"### Performance · run #{r['id']} · {(a.get('verdict') or 'no verdict').upper()}", "",
             a.get("headline") or "", "", f"| Metric | #{r['id']} | {ctx.base_label} | Δ |", "|---|---|---|---|"]
    for row in _metrics_table(ctx)["rows"]:
        lines.append("| " + " | ".join(row["cells"]) + " |")
    findings = a.get("findings") or []
    if findings:
        lines += ["", "**Findings**"] + [f"- {f['title']} — {f['evidence']}" for f in findings[:5]]
    emit_step("Drafted the summary")
    return [_verdict_block(r),
            {"type": "para", "text": "A summary you can paste into the pull request:"},
            {"type": "code", "lang": "Markdown", "open": True, "code": "\n".join(lines).strip()},
            {"type": "cites", "items": [cite_run(r)] + ctx.cite_findings(findings[:3])}]


def over_time(ctx, emit_step, key="peak_rss_mb", n=10):
    label = next(l for k, l, _, _ in METRICS if k == key)
    unit = next(u for k, _, u, _ in METRICS if k == key)
    runs = [r for r in ctx.scoped if _val(r, key) is not None][-n:]
    emit_step(f"Read {label} for the last {len(runs)} runs")
    if not runs:
        return [{"type": "para", "text": f"No run in scope recorded {label}."}]
    g = ctx.history.get("global_budgets", {})
    budget = runs[-1].get("ttid_budget_ms") if key == "ttff_ms" else (g.get(BUDGET_KEY[key]) if runs[-1].get("app_role") == "own" else None)
    vals = [_val(r, key) for r in runs]
    over = [r for r in runs if budget and _val(r, key) > budget]
    lo, hi = min(vals), max(vals)
    text = f"{label} ranged {lo:,.0f}–{hi:,.0f} {unit} over the last {len(runs)} runs."
    if budget:
        text += f" {len(over)} of {len(runs)} were over the {budget:g} {unit} budget."
    return [{"type": "verdict", "tone": "fail" if over else "pass", "label": "OVER" if over else "WITHIN", "text": text},
            {"type": "bars", "title": f"{label} per run", "unit": unit, "labels": [f"#{r['id']}" for r in runs],
             "values": vals, "budget": budget},
            {"type": "cites", "items": [cite_chart("peak" if key.startswith(("peak", "rss")) else "ttid")] + [cite_run(r) for r in over[-2:]]}]


def first_over_budget(ctx, emit_step):
    runs = [r for r in ctx.scoped if _val(r, "ttff_ms") is not None and r.get("ttid_budget_ms")]
    emit_step(f"Scanned {len(runs)} runs for TTID against the budget")
    if not runs:
        # Simulator runs and uninstrumented apps have no budget: "never over"
        # would be a verdict on nothing.
        return [{"type": "para", "text": "No run in scope has a TTID budget to be over "
                 "(simulator runs, and apps without one in the catalogue, are never judged)."}]
    for r in runs:
        b = r.get("ttid_budget_ms")
        if b and r["ttff_ms"] > b:
            return [{"type": "verdict", "tone": "fail", "label": "FIRST", "text": f"Run #{r['id']} was the first over budget: {r['ttff_ms']:.0f} ms against {b} ms."},
                    {"type": "cites", "items": [cite_run(r), cite_chart("ttid")]}]
    return [{"type": "verdict", "tone": "pass", "label": "NEVER", "text": f"No run in scope has gone over its TTID budget ({len(runs)} checked)."},
            {"type": "cites", "items": [cite_chart("ttid")]}]


def stress_noise(ctx, emit_step, stress_tests):
    app = ctx.run.get("app_pkg") if ctx.run else None
    tests = [t for t in stress_tests if t.get("app_pkg") == app and t.get("state") == "done"]
    emit_step(f"Loaded {len(tests)} completed stress test{'s' if len(tests) != 1 else ''}")
    if len(tests) < 2:
        return [{"type": "verdict", "tone": "neutral", "label": "NOT ENOUGH",
                 "text": "Separating a real regression from noise needs two completed stress tests of this app."},
                {"type": "para", "text": "Run a stress test now and another after the change; the Stress tab compares them."},
                {"type": "cites", "items": [cite_stress(t) for t in tests]}]
    cur, base = tests[0], tests[1]
    a = [s["ttid_ms"] for s in cur.get("sessions", []) if s.get("ttid_ms")]
    b = [s["ttid_ms"] for s in base.get("sessions", []) if s.get("ttid_ms")]
    p = mann_whitney_p(a, b)
    emit_step("Ran a Mann-Whitney U test on session TTIDs")
    ma, mb = statistics.median(a), statistics.median(b)
    q = statistics.quantiles(b, n=4) if len(b) >= 4 else [min(b), max(b)]
    iqr = max(q[-1] - q[0], 1e-9)
    real = p is not None and p < 0.05 and abs(ma - mb) > iqr
    label = "REAL" if real else "NOISE"
    return [{"type": "verdict", "tone": "fail" if real and ma > mb else "pass", "label": label,
             "text": f"Median {ma:.0f} ms vs {mb:.0f} ms ({_signed(ma - mb, 0, ' ms')}), {abs(ma - mb) / iqr:.1f}× the earlier test's spread, p {'< 0.001' if p is not None and p < 0.001 else f'= {p:.3f}' if p is not None else 'n/a'}."},
            {"type": "table", "cols": ["Test", "Sessions", "Median", "Spread"],
             "rows": [{"cells": [f"#{t['id']}", str(len(v)), f"{statistics.median(v):.0f} ms", f"{min(v):.0f}–{max(v):.0f} ms"], "tag": "same"} for t, v in ((cur, a), (base, b))]},
            *([{"type": "para", "text": "Fewer than ten sessions per test: treat this as low confidence."}] if min(len(a), len(b)) < 10 else []),
            {"type": "cites", "items": [cite_stress(cur), cite_stress(base)]}]


def mann_whitney_p(a, b):
    """Two-sided Mann-Whitney U p-value, normal approximation with tie correction."""
    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return None
    allv = sorted([(v, 0) for v in a] + [(v, 1) for v in b])
    ranks, tie, i = [0.0] * len(allv), 0.0, 0
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        for k in range(i, j + 1):
            ranks[k] = (i + j + 2) / 2
        t = j - i + 1
        tie += t ** 3 - t
        i = j + 1
    r1 = sum(r for r, (_, g) in zip(ranks, allv) if g == 0)
    u1 = r1 - n1 * (n1 + 1) / 2
    n = n1 + n2
    sd = ((n1 * n2 / 12) * (n + 1 - tie / (n * (n - 1)))) ** 0.5
    if sd == 0:
        return 1.0
    z = (abs(u1 - n1 * n2 / 2) - 0.5) / sd
    return min(1.0, 2 * (1 - statistics.NormalDist().cdf(z)))


def ordering(ctx, emit_step):
    r = ctx.run
    v = r.get("violations") or []
    emit_step(f"Checked deferred work against the first frame in run #{r['id']}")
    if r.get("derived"):
        return [{"type": "verdict", "tone": "neutral", "label": "NO RULE",
                 "text": "This run's steps are derived from Android's own launch slices, which do not say which work is deferred, so the ordering constraint cannot be checked."},
                {"type": "cites", "items": [cite_chart("ordering")]}]
    return [{"type": "verdict", "tone": "fail" if v else "pass", "label": f"{len(v)} VIOLATION{'S' if len(v) != 1 else ''}" if v else "OK",
             "text": "; ".join(x["detail"] for x in v) if v else "No deferred work started before the first frame."},
            {"type": "cites", "items": [cite_chart("ordering")] + [cite_step(x["step"]) for x in v[:3]]}]


def compare_runs(ctx, emit_step, store_compare):
    a = ctx.run
    b_id = ctx.second or (ctx.base["id"] if ctx.base else None)
    if not a or not b_id:
        return [{"type": "para", "text": "Name two runs to compare, e.g. “compare #81 with #79”."}]
    emit_step(f"Compared run #{a['id']} with #{b_id}")
    d = store_compare(a["id"], b_id)
    s = d["summary"]
    rows = [{"cells": [m["metric"], _fmt(m["value"], 1), _fmt(m["base_value"], 1), _signed(m["delta"], 1)],
             "tag": m.get("verdict") or "same"} for m in d["metrics"]]
    worst = sorted([x for x in d["steps"] if x.get("delta_ms") is not None], key=lambda x: -x["delta_ms"])[:1]
    blocks = [{"type": "verdict", "tone": "fail" if s["worse"] > s["better"] else "pass", "label": f"{s['worse']} WORSE",
               "text": f"{s['worse']} worse · {s['better']} better · {s['same']} same" + ("" if d["comparable"] else " — different startup paths, so not directly comparable")},
              {"type": "table", "cols": ["Metric", f"#{a['id']}", f"#{b_id}", "Δ"], "rows": rows}]
    if worst:
        blocks.append({"type": "para", "text": f"The step that grew most is {worst[0]['step'].replace('step:', '')} ({_signed(worst[0]['delta_ms'], 1, ' ms')})."})
    blocks.append({"type": "cites", "items": [cite_compare(a["id"], b_id)]})
    return blocks


def screens_answer(ctx, emit_step, extract_screens, trace_path_of, leak=False):
    runs = [r for r in ctx.scoped if r.get("trace_path")]
    r = ctx.run if ctx.run and ctx.run.get("trace_path") else (runs[-1] if runs else None)
    if not r:
        return [{"type": "para", "text": "No traced run in scope has screen markers to read."}]
    emit_step(f"Read screen markers from run #{r['id']}'s trace")
    d = extract_screens(trace_path_of(r))
    if not d.get("instrumented"):
        return [{"type": "para", "text": f"Run #{r['id']}'s trace has no screen markers."}]
    rows = d["screen_summary"]
    emit_step(f"Attributed CPU and RAM to {len(rows)} screens")
    if leak:
        rows = sorted(rows, key=lambda x: -(x.get("max_rss_delta_mb") or 0))
        top = rows[0]
        text = f"{top['route']} grows RAM most within a visit: up to {top.get('max_rss_delta_mb') or 0:.0f} MB across {top['visits']} visit(s)."
        cols = ["Screen", "Visits", "Worst RAM growth", "Peak RAM"]
        cells = [[x["route"], str(x["visits"]), f"{x.get('max_rss_delta_mb') or 0:.1f} MB", f"{x.get('peak_rss_mb') or 0:.0f} MB"] for x in rows[:6]]
    else:
        if all(x.get("total_cpu_ms") is None for x in rows):
            # No scheduler data in this trace (an iOS run, or a capture without
            # sched): CPU is unmeasured, and ranking screens by it would be 0 vs 0.
            return [{"type": "para", "text": f"Run #{r['id']}'s trace has no scheduler data, so per-screen CPU is not measured."}]
        rows = [x for x in rows if x.get("total_cpu_ms") is not None]
        rate = lambda x: (x["total_cpu_ms"] / x["total_ms"] * 100) if x["total_ms"] else 0
        rows = sorted(rows, key=lambda x: -x["total_cpu_ms"])
        top = rows[0]
        text = f"{top['route']} used the most CPU: {top['total_cpu_ms']:,.0f} ms over {top['visits']} visit(s), {rate(top):.0f}% busy while on screen."
        cols = ["Screen", "CPU time", "CPU busy", "Visits"]
        cells = [[x["route"], f"{x['total_cpu_ms']:,.0f} ms", f"{rate(x):.0f}%", str(x["visits"])] for x in rows[:6]]
    return [{"type": "verdict", "tone": "warn", "label": "TOP", "text": text},
            {"type": "table", "cols": cols, "rows": [{"cells": c, "tag": "same"} for c in cells]},
            {"type": "cites", "items": [cite_screen(x["route"], r["id"]) for x in rows[:3]]}]


def frames_answer(ctx, emit_step):
    r = ctx.run
    f = r.get("frames") or {}
    emit_step(f"Read frame pacing for run #{r['id']}")
    if not f.get("total"):
        why = f": {f['note']}" if f.get("note") else ""
        return [{"type": "para", "text": f"Run #{r['id']} recorded no frames for the app, so frame pacing is not measured{why}."}]
    return [{"type": "verdict", "tone": "warn" if (f.get("janky_pct") or 0) > 0.5 else "pass", "label": "FRAMES",
             "text": f"{f['total']:,} frames: {f.get('slow_pct')}% slow, {f.get('janky_pct')}% janky, worst {f.get('max_ms')} ms."},
            {"type": "para", "text": "Per-screen app jank on the Screens tab separates frames the app was late with from compositor and display misses."},
            {"type": "cites", "items": [cite_chart("frames"), cite_run(r)]}]


def explain_finding(ctx, emit_step, idx):
    r = ctx.run
    findings = (r.get("analysis") or {}).get("findings") or []
    emit_step(f"Loaded findings for run #{r['id']}")
    if idx >= len(findings):
        return [{"type": "para", "text": f"Run #{r['id']} has no finding F-{idx + 1}."}]
    f = findings[idx]
    return [{"type": "verdict", "tone": {"high": "fail", "medium": "warn"}.get(f.get("severity"), "neutral"),
             "label": (f.get("severity") or "").upper(), "text": f["title"]},
            {"type": "heading", "text": "Evidence"}, {"type": "para", "text": f["evidence"]},
            *([{"type": "heading", "text": "What to do"}, {"type": "para", "text": f["recommendation"]}] if f.get("recommendation") else []),
            *([{"type": "para", "text": f"Risk: {f['architectural_risk']}"}] if f.get("architectural_risk") else []),
            {"type": "cites", "items": ctx.cite_findings([f], idx) + [cite_run(r)]}]


def fallback(ctx, emit_step):
    r = ctx.run
    emit_step(f"Loaded run #{r['id']}")
    return [_verdict_block(r), _metrics_table(ctx),
            {"type": "para", "text": "This Copilot answers from rules over the run data for now. It can explain a verdict, find the step that grew, "
                                     "compare two runs, check stress tests for noise, rank screens by CPU or RAM growth, and draft a PR summary."},
            {"type": "cites", "items": [cite_run(r)]}]


def route(text):
    t = text.lower()
    if m := re.search(r"\bf-?(\d+)\b", t):
        if "finding" in t or "explain" in t:
            return ("finding", int(m.group(1)) - 1)
    if "pr comment" in t or "summar" in t:
        return ("pr", None)
    if "noise" in t or "stress" in t or "sessions do i need" in t:
        return ("stress", None)
    if "first go over" in t or "first went over" in t:
        return ("first_over", None)
    if "deferred" in t or "ordering" in t or "before the first frame" in t:
        return ("ordering", None)
    if "compare" in t and ("run" in t or "#" in t) or "differences between" in t:
        return ("compare", None)
    w = lambda word: re.search(rf"\b{word}\b", t) is not None  # "frames" must not match "ram"
    if w("leak") or w("leaking"):
        return ("screens_leak", None)
    if w("screen") and (w("cpu") or w("burns")):
        return ("screens", None)
    if w("frame") or w("frames") or w("jank") or w("janky") or w("thermal"):
        return ("frames", None)
    if w("step") and (w("grew") or w("grow") or w("most")):
        return ("step", None)
    if w("ram") or w("memory") or w("heap"):
        return ("peak", None)
    if "why" in t or "regress" in t or "verdict" in t:
        return ("why", None)
    return ("fallback", None)


def answer(text, *, history, scope=None, chips=None, deep=False, emit, services):
    """Answer `text`, emitting step/block/done/error events through `emit`.

    `services` supplies the data this needs beyond the run history, so the
    engine can be tested without a server: `stress_tests()`,
    `compare(a, b)`, `extract_screens(path)`, `trace_path(run)`.
    """
    t0 = time.time()
    steps = []

    def step(txt):
        steps.append(txt)
        emit("step", {"text": txt})

    ctx = Ctx(history, scope or {}, chips or [], text)
    if ctx.requested is not None and ctx.run is None:
        kept = sorted(ctx.by_id)
        return emit("error", {"kind": "no_data", "title": f"No data for run #{ctx.requested}",
                              "message": f"Run #{ctx.requested} is not in the history ({len(kept)} runs kept, #{kept[0]}–#{kept[-1]})." if kept else "No runs are recorded yet.",
                              "oldest_run_id": kept[0] if kept else None})
    if ctx.run is None:
        return emit("error", {"kind": "no_data", "title": "No runs yet", "message": "Capture a trace first; there is nothing to answer from."})

    intent, arg = route(text)
    # Context chips narrow a general question to the step or finding they name.
    named = ctx.named_step(text)
    if named and (intent in ("why", "fallback") or (intent == "step" and "most" not in text.lower())):
        intent, arg = "step_detail", named
    if intent in ("why", "fallback") and re.search(r"\bfinding\b", text.lower()) and ctx.finding_chip() is not None:
        intent, arg = "finding", ctx.finding_chip()
    try:
        if intent == "why":
            blocks = why(ctx, step, text)
        elif intent == "step":
            blocks = which_step(ctx, step)
        elif intent == "step_detail":
            blocks = step_detail(ctx, step, arg)
        elif intent == "pr":
            blocks = summarise_pr(ctx, step)
        elif intent == "peak":
            blocks = over_time(ctx, step, "peak_rss_mb")
        elif intent == "first_over":
            blocks = first_over_budget(ctx, step)
        elif intent == "stress":
            blocks = stress_noise(ctx, step, services["stress_tests"]())
        elif intent == "ordering":
            blocks = ordering(ctx, step)
        elif intent == "compare":
            blocks = compare_runs(ctx, step, services["compare"])
        elif intent in ("screens", "screens_leak"):
            blocks = screens_answer(ctx, step, services["extract_screens"], services["trace_path"], leak=intent == "screens_leak")
        elif intent == "frames":
            blocks = frames_answer(ctx, step)
        elif intent == "finding":
            blocks = explain_finding(ctx, step, arg)
        else:
            blocks = fallback(ctx, step)
        if deep and intent not in ("stress",):
            # Deep analysis cross-checks the answer against the stress tests.
            extra = stress_noise(ctx, step, services["stress_tests"]())
            blocks += [{"type": "heading", "text": "Cross-check against stress tests"}] + [b for b in extra if b["type"] != "cites"]
    except Exception as e:  # an answer must fail visibly, never half-render
        return emit("error", {"kind": "internal", "title": "Could not answer", "message": str(e)})

    for b in blocks:
        emit("block", b)
    emit("done", {"elapsed_ms": round((time.time() - t0) * 1000), "steps": steps, "run_id": ctx.run["id"]})
