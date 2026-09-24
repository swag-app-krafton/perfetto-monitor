"""What the runs since the PM agent's last review say, as facts it can act on.

This is the deterministic half of the run review. The PM agent writes the
observations and opens or updates issues; this supplies what it reasons from.
Every signal is built from data the pipeline stored -- a budget breach, a step
regression, an ordering violation -- never from a finding's wording, which the
rules or a model phrase differently run to run. So the same problem in four
runs gets one key, and lands on one issue instead of four.

A signal's key is `<kind>:<metric or step>:<app>:<path>`. An issue file in
docs/issues declares the key it tracks on a `Signal:` line, which is how a new
run finds the issue already open for it.
"""
from __future__ import annotations

import glob, os, re, statistics
from urllib.parse import quote

from .analyst import METRIC_NAMES, NEXT_STEP
from .budgets import RISK_MAP, STEP_RUNTIME

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TRACKER = os.path.join(ROOT, "docs", "TRACKER.md")
ISSUES = os.path.join(ROOT, "docs", "issues")
DASHBOARD = os.environ.get("SWAGPERF_DASHBOARD_URL", "http://127.0.0.1:8787")

MARKER = re.compile(r"(Runs reviewed through: #)(\d+)")
OPEN = ("needs-review", "confirmed", "in-progress")
RAM = ("peak_rss_mb", "rss_growth_mb")
UNITS = {"peak_rss_mb": "MB", "rss_growth_mb": "MB", "time_to_first_camera_frame_ms": "ms",
         "slow_frame_pct": "%", "janky_frame_pct": "%", "thermal_drift_pct": "%"}
# Where a metric's chart lives on the dashboard, and the id that rings it.
CHART = {"peak_rss_mb": ("/memory", "peakChart"), "rss_growth_mb": ("/memory", "peakChart"),
         "time_to_first_camera_frame_ms": ("/startup", "ttidChart"),
         "slow_frame_pct": ("/frames", "framesChart"), "janky_frame_pct": ("/frames", "framesChart"),
         "thermal_drift_pct": ("/frames", "framesChart")}


def _step(s):
    return s.replace("step:", "")


def _link(label, path, focus=None):
    if focus:
        path += ("&" if "?" in path else "?") + "focus=" + quote(focus, safe=":")
    return {"label": label, "url": DASHBOARD + path}


# ------------------------------------------------------------------ marker

def read_marker(tracker=TRACKER):
    """The newest run the tracker says was reviewed, or None."""
    try:
        with open(tracker) as fh:
            m = MARKER.search(fh.read())
    except FileNotFoundError:
        return None
    return int(m.group(2)) if m else None


def write_marker(n, tracker=TRACKER, force=False):
    """Move "Runs reviewed through: #N" forward to `n`. Never moves it back,
    so a slow review finishing after a newer one cannot un-review runs --
    unless `force`, for a history that was reset and restarted at run #1."""
    with open(tracker) as fh:
        text = fh.read()
    m = MARKER.search(text)
    if not m:
        raise ValueError(f"{tracker} has no 'Runs reviewed through: #N' line")
    if int(m.group(2)) >= n and not force:
        return int(m.group(2))
    with open(tracker, "w") as fh:
        fh.write(MARKER.sub(lambda x: f"{x.group(1)}{n}", text, count=1))
    return n


# ------------------------------------------------------------------ issues

def read_issues(issues_dir=ISSUES):
    """Performance issues on disk, with the signal key and status each declares."""
    out = []
    for f in sorted(glob.glob(os.path.join(issues_dir, "*.md"))):
        with open(f) as fh:
            text = fh.read()
        field = lambda name: re.search(rf"^(?:- )?(?:\*\*)?{name}:(?:\*\*)?\s*`?([^`\s]+)`?", text, re.M)
        sig, st = field("Signal"), field("Status")
        out.append({"id": os.path.splitext(os.path.basename(f))[0],
                    "signal": sig.group(1) if sig else None,
                    "status": st.group(1).lower() if st else None,
                    "file": os.path.relpath(f, ROOT)})
    return out


def _existing(key, issues):
    """The issue tracking `key`: an open one if there is one, else the newest."""
    mine = [i for i in issues if i["signal"] == key]
    if not mine:
        return None
    live = [i for i in mine if i["status"] in OPEN]
    i = (live or mine)[-1]
    return {"id": i["id"], "status": i["status"], "file": i["file"]}


def next_issue_id(issues):
    nums = [int(m.group(1)) for i in issues if (m := re.fullmatch(r"P-(\d+)", i["id"]))]
    return f"P-{(max(nums) if nums else 0) + 1:03d}"


# ------------------------------------------------------------------ signals

def _app_key(run):
    """The app part of a signal key. An iOS signal never lands on an Android
    issue for the same id, so it is platform-prefixed (`ios:com.swag.pay`);
    Android keys keep their original form so existing issues still match."""
    app, platform = run.get("app_pkg"), run.get("platform") or "android"
    return app if platform == "android" else f"{platform}:{app}"


def _where(error):
    """`fn (src/money.ts)` for the first resolved app frame of an error, if any."""
    f = next((f for f in error.get("frames") or [] if f.get("resolved") and f.get("in_app")), None)
    return f"{f.get('fn')} ({f.get('path') or f.get('file')})" if f else None


def _key_scope(key):
    """(app, path) of a signal key, `kind:subject:app:path`. Read from the
    end: a subject can hold colons itself (`regression:step:activity_create:...`),
    and an iOS app is `ios:<pkg>`."""
    parts = (key or "").split(":")
    if len(parts) < 4:
        return None
    if len(parts) >= 5 and parts[-3] == "ios":
        return (f"ios:{parts[-2]}", parts[-1])
    return (parts[-2], parts[-1])


def _resolved(run):
    """The run with its JS error stacks resolved against its build's source map."""
    st = run.get("stability") or {}
    if not (st.get("errors") or {}).get("js"):
        return run
    from . import sourcemaps
    try:
        return {**run, "stability": sourcemaps.resolve(st, sourcemaps.map_for_run(run, run.get("meta")))}
    except Exception:
        return run


def signals_of(run, regs):
    """The signals one run raised, from its stored breaches, violations and
    step regressions (`regs`, as store.regressions returns them)."""
    app, path = _app_key(run), run.get("path_kind")
    out = []
    for b in run.get("breaches") or []:
        m = b["metric"]
        over = b.get("over_by_pct")
        out.append({"key": f"budget:{m}:{app}:{path}", "kind": "budget_breach", "subject": m,
                    "title": f"{METRIC_NAMES.get(m, m)} over budget", "unit": UNITS.get(m, ""),
                    "value": b.get("value"), "reference": b.get("budget"), "reference_kind": "budget",
                    "over_pct": over, "severity": "high" if (over or 0) > 25 else "medium"})
    for r in regs:
        s = r["step"]
        pct = r.get("delta_pct")
        out.append({"key": f"regression:{s}:{app}:{path}", "kind": "regression", "subject": s,
                    "title": f"{_step(s)} regressed", "unit": "ms",
                    "value": r.get("dur_ms"), "reference": r.get("baseline_ms"),
                    "reference_kind": "benchmark" if r.get("reference") == "benchmark" else "baseline",
                    "over_pct": pct, "severity": "high" if (pct or 0) > 25 else "medium"})
    st = run.get("stability") or {}
    if (st.get("crash") or {}).get("crashed"):
        out.append({"key": f"crash:app:{app}:{path}", "kind": "crash", "subject": "crash",
                    "title": "The app crashed during the run", "unit": "",
                    "value": None, "reference": None, "reference_kind": None,
                    "over_pct": None, "severity": "high",
                    "detail": (st.get("crash") or {}).get("reason")})
    # One signal per error, by its fingerprint: the resolved function it was
    # thrown in (sourcemaps.resolve), stable across builds where a raw Hermes
    # offset is not. Without a source map, by error class.
    groups = {}
    for e in (st.get("errors") or {}).get("events") or []:
        fp = e.get("fingerprint") or e.get("name") or "Error"
        g = groups.setdefault(fp, {"name": e.get("name") or "Error", "n": 0, "fatal": False,
                                   "where": _where(e)})
        g["n"] += 1
        g["fatal"] = g["fatal"] or bool(e.get("fatal"))
    for fp, g in sorted(groups.items()):
        out.append({"key": f"js_error:{fp}:{app}:{path}", "kind": "js_error", "subject": fp,
                    "title": f"JS error: {g['name']}" + (f" in {g['where']}" if g["where"] else ""),
                    "unit": "", "value": g["n"], "reference": None, "reference_kind": None,
                    "over_pct": None, "severity": "high" if g["fatal"] else "medium"})
    for v in run.get("violations") or []:
        s = v["step"]
        out.append({"key": f"ordering:{s}:{app}:{path}", "kind": "ordering_violation", "subject": s,
                    "title": f"{_step(s)} ran before the first frame", "unit": "ms",
                    "value": v.get("started_at_ms"), "reference": v.get("first_frame_ms"),
                    "reference_kind": "first_frame", "over_pct": None, "severity": "high",
                    "detail": v.get("detail")})
    return out


def _trend(values):
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return "single run"
    first, last = vals[0], vals[-1]
    if first and last > first * 1.05:
        return "rising"
    if first and last < first * 0.95:
        return "falling"
    return "flat"


def child_moves(run, prior, step):
    """A step's child slices in `run` against their median over `prior` runs,
    largest increase first -- which part of the step moved."""
    row = next((s for s in run.get("steps", []) if s["step"] == step), None)
    if not row:
        return []
    base = {}
    for p in prior:
        for s in p.get("steps", []):
            if s["step"] == step:
                for c in s.get("children", []):
                    base.setdefault(c["name"], []).append(c["dur_ms"])
    out = []
    for c in row.get("children", []):
        if c["name"] in base:
            b = statistics.median(base[c["name"]])
            out.append({"child": c["name"], "ms": round(c["dur_ms"], 2), "baseline_ms": round(b, 2),
                        "delta_ms": round(c["dur_ms"] - b, 2)})
    return sorted(out, key=lambda x: -x["delta_ms"])


def _context(sig, run, prior, screens_of):
    """Where to look and what the architecture says, from the newest run."""
    kind, subj, rid = sig["kind"], sig["subject"], run["id"]
    links = [_link(f"Run #{rid}", "/history", f"run:{rid}")]
    ctx = {}
    if kind == "budget_breach":
        ctx["risk"] = RISK_MAP.get(subj)
        ctx["next_check"] = NEXT_STEP.get(subj)
        if subj in CHART:
            links.append(_link("Chart", *CHART[subj]))
        if subj in RAM or subj.endswith("frame_pct"):
            links.append(_link("Screens", f"/screens?run={rid}"))
    elif kind == "regression":
        ctx["runtime"] = STEP_RUNTIME.get(subj)
        ctx["child_moves"] = child_moves(run, prior, subj)[:3]
        ctx["next_check"] = "Open the step on the Steps tab and compare its child slices with the previous run."
        links.append(_link("Step", "/steps", subj))
        if prior:
            links.append(_link(f"Compare #{rid} with #{prior[-1]['id']}", f"/compare?mode=run&a={rid}&b={prior[-1]['id']}"))
    else:
        ctx["runtime"] = STEP_RUNTIME.get(subj)
        ctx["risk"] = RISK_MAP.get("deferred_leak")
        ctx["next_check"] = "Find what starts this step before the first frame; deferred work must wait for it."
        links.append(_link("Ordering constraint", "/startup", "order"))
    if screens_of and subj in RAM and run.get("trace_path"):
        ctx["screens"] = _ram_screens(run, screens_of)
    ctx["links"] = links
    return {k: v for k, v in ctx.items() if v not in (None, [])}


def _ram_screens(run, screens_of):
    """The screens whose visits grew RAM most, when the trace has screen markers."""
    p = run["trace_path"]
    p = p if os.path.isabs(p) else os.path.join(ROOT, p)
    try:
        d = screens_of(p)
    except Exception as e:  # a trace gone from disk, or one the processor cannot open
        return {"error": str(e)[:200]}
    if not d.get("instrumented"):
        return {"error": "the trace has no screen markers"}
    rows = sorted(d.get("screen_summary", []), key=lambda x: -(x.get("max_rss_delta_mb") or 0))[:3]
    return [{"route": x["route"], "visits": x["visits"], "max_ram_growth_mb": x.get("max_rss_delta_mb"),
             "peak_ram_mb": x.get("peak_rss_mb")} for x in rows]


# ------------------------------------------------------------------ review

def review(history, *, after, regressions=None, issues=None, lookback=10, screens_of=None):
    """Everything the PM agent needs about the runs newer than `after`.

    `history` is shaped like the dashboard's /api/history payload.
    `regressions(run_id)` defaults to store.regressions; `issues` to the files
    in docs/issues; `screens_of(trace_path)`, when given, attributes RAM
    signals to screens (it reads the trace, so it is slow).
    """
    if regressions is None:
        from . import store
        regressions = store.regressions
    issues = read_issues() if issues is None else issues
    runs = sorted(history["runs"], key=lambda r: r["id"])
    # `swagperf reset` restarts run ids at #1. A marker past the newest run
    # means that happened: review from the start rather than wait for the new
    # ids to climb past the old marker, which would skip every run until then.
    marker = after
    history_reset = after > max((r["id"] for r in runs), default=0)
    if history_reset:
        after = 0
    window = [_resolved(r) for r in runs if r["id"] > after]
    mine = [r for r in window if r.get("app_role") == "own" and not r.get("simulator")]
    skipped = [{"id": r["id"], "app": r.get("app_name") or r.get("app_pkg"),
                "reason": "not an own app: no budgets to hold it to, nothing to fix here"}
               for r in window if r.get("app_role") != "own"]
    # A simulator run is indicative only: its numbers are the Mac's, so it
    # opens no performance issue.
    skipped += [{"id": r["id"], "app": r.get("app_name") or r.get("app_pkg"),
                 "reason": "simulator run: indicative only, never judged"}
                for r in window if r.get("app_role") == "own" and r.get("simulator")]

    def scope(r):
        return (_app_key(r), r.get("path_kind"))

    def prior_of(r, n):
        return [p for p in runs if p["id"] < r["id"] and p.get("app_role") == "own" and scope(p) == scope(r)][-n:]

    by_key, per_run = {}, []
    for r in mine:
        sigs = signals_of(r, regressions(r["id"]))
        a = r.get("analysis") or {}
        per_run.append({"id": r["id"], "ts": r.get("ts"), "app": r.get("app_pkg"), "app_name": r.get("app_name"),
                        "path": r.get("path_kind"), "device": r.get("device"), "label": r.get("label"),
                        "verdict": a.get("verdict"), "headline": a.get("headline"),
                        "signals": [s["key"] for s in sigs]})
        for s in sigs:
            g = by_key.setdefault(s["key"], {k: s[k] for k in ("key", "kind", "subject", "title", "unit")}
                                  | {"app": r.get("app_pkg"), "app_name": r.get("app_name"), "path": r.get("path_kind"),
                                     "scope_app": _app_key(r), "severity": "medium", "runs": []})
            g["runs"].append({"run": r["id"], "ts": r.get("ts"), "device": r.get("device"),
                              "value": s["value"], "reference": s["reference"],
                              "reference_kind": s["reference_kind"], "over_pct": s["over_pct"],
                              **({"detail": s["detail"]} if s.get("detail") else {})})
            if s["severity"] == "high":
                g["severity"] = "high"

    # Did each signal also fire just before this window? Then it is ongoing,
    # not new -- the difference between "this change broke it" and "still broken".
    earlier, firsts = {}, {}
    for r in mine:
        firsts.setdefault(scope(r), r)
    for r in firsts.values():
        for p in prior_of(r, lookback):
            for s in signals_of(p, regressions(p["id"])):
                earlier.setdefault(s["key"], []).append(p["id"])

    newest = {r["id"]: r for r in mine}
    signals = []
    for key, g in by_key.items():
        ids = [x["run"] for x in g["runs"]]
        last = newest[ids[-1]]
        in_scope = [r["id"] for r in mine if scope(r) == (g["scope_app"], g["path"])]
        g.update({"first_seen": ids[0], "last_seen": ids[-1], "count": len(ids),
                  "of_runs": len(in_scope),
                  # Runs of its scope after it last fired: it may have stopped.
                  "runs_since_last_seen": sum(1 for i in in_scope if i > ids[-1]),
                  "fired_before_window": earlier.get(key, []),
                  "trend": _trend([x["value"] for x in g["runs"]]),
                  "context": _context(g, last, prior_of(last, 10), screens_of),
                  "existing": _existing(key, issues)})
        signals.append(g)
    signals.sort(key=lambda g: (g["severity"] != "high", g["kind"], g["key"]))

    # Open issues whose signal did not fire in any run of their scope here:
    # candidates for "possibly fixed", for a developer to confirm.
    fired = set(by_key)
    quiet = []
    for i in issues:
        if i["status"] not in OPEN or not i["signal"] or i["signal"] in fired:
            continue
        checked = [r["id"] for r in mine if scope(r) == _key_scope(i["signal"])]
        if checked:
            quiet.append({"id": i["id"], "signal": i["signal"], "status": i["status"], "file": i["file"],
                          "runs_checked": checked})

    through = max([r["id"] for r in window], default=after)
    open_issues = [i["id"] for i in issues if i["status"] in OPEN]
    return {"after": after, "marker": marker, "history_reset": history_reset,
            "through": through, "runs": per_run, "skipped": skipped,
            "clean_runs": [r["id"] for r in per_run if not r["signals"]],
            "signals": signals, "quiet": quiet, "open_issues": open_issues,
            # A reset leaves open issues citing run numbers that now mean other
            # runs; the agent has to say so on each of them.
            "actionable": bool(signals or quiet or (history_reset and open_issues)),
            "next_issue_id": next_issue_id(issues), "dashboard": DASHBOARD}


def load_history(after, lookback=10):
    """The dashboard's history payload, deep enough to cover the window and
    the lookback before it."""
    from . import store
    from .server import _payload
    c = store.connect()
    newest = c.execute("select max(id) as n from runs").fetchone()["n"] or 0
    c.close()
    return _payload(limit=max(100, newest - after + lookback + 10))


def summary_line(t):
    """One line for a capture job's log."""
    ids = [r["id"] for r in t["runs"]]
    runs = (f"run #{ids[0]}" if len(ids) == 1 else f"runs #{ids[0]}–#{ids[-1]}") if ids else "no own-app runs"
    if not t["actionable"]:
        return f"{runs}: nothing for the tracker (no budget breach, regression or ordering violation)"
    parts = [f"{len(t['signals'])} signal{'s' if len(t['signals']) != 1 else ''}"]
    if t["quiet"]:
        parts.append(f"{len(t['quiet'])} open issue{'s' if len(t['quiet']) != 1 else ''} quiet")
    titles = ", ".join(s["title"] for s in t["signals"][:3])
    return f"{runs}: {' · '.join(parts)}" + (f" ({titles})" if titles else "")


def format_text(t):
    """The review for a terminal."""
    fmt = lambda v: "–" if v is None else f"{v:g}"
    lines = [f"The tracker's marker (#{t['marker']}) is past the newest run: the run history was reset, "
             "so runs are reviewed from #1."] if t["history_reset"] else []
    lines += [f"Runs after #{t['after']} (through #{t['through']}): {len(t['runs'])} own-app, "
             f"{len(t['skipped'])} skipped, {len(t['clean_runs'])} clean."]
    for r in t["runs"]:
        lines.append(f"  #{r['id']}  {r['ts'] or ''}  {r['app_name'] or r['app']} · {r['path']}  "
                     f"{(r['verdict'] or 'none').upper()}  {len(r['signals'])} signal(s)")
    if t["signals"]:
        lines.append(f"\nSignals ({len(t['signals'])}):")
    for s in t["signals"]:
        x = s["runs"][-1]
        ref = f" vs {fmt(x['reference'])} {s['unit']} {x['reference_kind']}" if x["reference"] is not None else ""
        over = f" ({x['over_pct']:+g}%)" if x.get("over_pct") is not None else ""
        known = f"  → {s['existing']['id']} ({s['existing']['status']})" if s["existing"] else "  → no issue yet"
        seen = f"#{s['first_seen']}" if s["count"] == 1 else f"#{s['first_seen']}–#{s['last_seen']}"
        if s["runs_since_last_seen"]:
            seen += f", not in the {s['runs_since_last_seen']} since"
        lines.append(f"  [{s['severity']}] {s['title']} · {s['app_name'] or s['app']} {s['path']} · "
                     f"{s['count']} of {s['of_runs']} runs ({seen}), {s['trend']}"
                     f"{', ongoing' if s['fired_before_window'] else ', new'} · latest {fmt(x['value'])} {s['unit']}{ref}{over}{known}")
    for q in t["quiet"]:
        lines.append(f"  quiet: {q['id']} ({q['status']}) did not fire in runs {', '.join('#' + str(i) for i in q['runs_checked'])}")
    lines.append(f"\nNext issue id: {t['next_issue_id']}")
    return "\n".join(lines)
