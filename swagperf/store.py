"""SQLite history store: one row per run, one row per step per run.

Keeps enough history that a regression is defined against the trailing baseline
of the same (app_version-independent) step on the same device, rather than
against a hand-picked number.
"""
import sqlite3, json, os, statistics
from datetime import datetime, timezone

DB = os.environ.get("SWAGPERF_DB", os.path.join(os.path.dirname(__file__), "..", "history.db"))

SCHEMA = """
create table if not exists runs (
  id integer primary key autoincrement,
  ts text not null,
  label text,
  git_sha text,
  app_version text,
  device text,
  path_kind text,
  trace_path text,
  app_pkg text,
  derived int default 0,
  ttff_ms real, slow_pct real, janky_pct real, thermal_drift_pct real,
  peak_rss_mb real, rss_growth_mb real,
  breaches_json text, violations_json text, frames_json text, memory_json text
);
create table if not exists step_metrics (
  id integer primary key autoincrement,
  run_id integer not null references runs(id) on delete cascade,
  step text not null, dur_ms real not null, start_ms real,
  budget_ms real, over_budget int, children_json text
);
create table if not exists analyses (
  id integer primary key autoincrement,
  run_id integer not null references runs(id) on delete cascade,
  created text not null, model text, verdict text, json text
);
create index if not exists idx_step on step_metrics(step);
create index if not exists idx_run on step_metrics(run_id);
-- A pinned reference run, one per (path_kind, device). Scoping it this way keeps
-- a returning-user benchmark from being compared against a first-run trace, and
-- keeps device classes apart, which is the same reason baselines filter on device.
-- A stress test is N cold-start sessions of one app captured back to back.
-- Sessions are ordinary runs (so every existing chart and analysis works on
-- them unchanged); this table just groups them and holds the run-to-run
-- variance, which is the actual point of a stress test.
create table if not exists stress_tests (
  id integer primary key autoincrement,
  ts text not null,
  app_pkg text,
  device text,
  label text,
  sessions_requested integer not null,
  cold int default 1,
  duration_ms integer,
  state text not null default 'running',
  error text,
  finished text
);
create table if not exists stress_sessions (
  id integer primary key autoincrement,
  stress_id integer not null references stress_tests(id) on delete cascade,
  seq integer not null,
  run_id integer references runs(id) on delete set null,
  state text not null default 'pending',
  error text,
  ttid_ms real
);
create index if not exists idx_stress on stress_sessions(stress_id);

-- Copilot conversations. Messages keep the rendered answer blocks, so a
-- thread reopens exactly as it was, and a model-backed engine can later read
-- earlier turns as context.
create table if not exists copilot_threads (
  id integer primary key autoincrement,
  title text not null,
  created text not null,
  updated text not null
);
create table if not exists copilot_messages (
  id integer primary key autoincrement,
  thread_id integer not null references copilot_threads(id) on delete cascade,
  role text not null,
  json text not null,
  created text not null,
  feedback text
);
-- A Copilot answer pinned to the Overview as a finding on the run it is about.
create table if not exists copilot_pins (
  id integer primary key autoincrement,
  message_id integer not null unique references copilot_messages(id) on delete cascade,
  run_id integer not null references runs(id) on delete cascade,
  title text not null,
  severity text not null,
  evidence text not null,
  created text not null
);

create table if not exists benchmarks (
  scope text primary key,
  run_id integer not null references runs(id) on delete cascade,
  note text,
  set_at text not null
);

-- A Flashlight audit: one app's cold start measured N times by Flashlight.
-- Flashlight never runs while Perfetto records (it breaks the trace; see
-- docs/flashlight-perfetto-observations.html), so an audit is never part of a
-- run. It has its own table and its own ids, and its numbers are Flashlight's
-- definitions, not Perfetto's: they are never compared with a run's.
create table if not exists flashlight_audits (
  id integer primary key autoincrement,
  ts text not null,
  app_pkg text not null,
  device text,
  label text,
  iterations integer not null,
  duration_ms integer not null,
  state text not null default 'running',
  error text,
  finished text,
  results_path text,
  flashlight_version text,
  score real, cpu_pct real, ram_mb real, fps real,
  summary_json text,
  meta_json text
);
"""

BENCH_ANY = "*"


def _scope(path_kind, device, app_pkg=None, platform="android"):
    """Benchmark scope key. app_pkg is part of it because a reference run for one
    application says nothing about another, and so is the platform: an iOS
    bundle id can equal the Android package name. Android keys keep their
    original form so existing pins still resolve."""
    key = f"{app_pkg or BENCH_ANY}|{path_kind or BENCH_ANY}|{device or BENCH_ANY}"
    return key if (platform or "android") == "android" else f"{platform}:{key}"


# Columns added after the first release. sqlite has no "add column if not
# exists", so they are applied idempotently on every connect; an existing
# history.db upgrades in place rather than needing a rebuild.
MIGRATIONS = [
    ("runs", "app_pkg", "text"),
    ("runs", "derived", "int default 0"),
    # Where a run was measured: {"capture": device/app/state read over adb at
    # capture time, "from_trace": what the trace itself records}.
    ("runs", "meta_json", "text"),
    # Which platform a run measured, and whether on a simulator. Simulator runs
    # are compared only with each other and never judged against budgets.
    ("runs", "platform", "text default 'android'"),
    ("runs", "simulator", "int default 0"),
    ("stress_tests", "platform", "text default 'android'"),
    # Stability (stability.py): hangs after the first frame, JS errors, and
    # whether the app died on its own. Columns for sorting; the detail is JSON.
    ("runs", "hang_count", "int"),
    ("runs", "longest_hang_ms", "real"),
    ("runs", "js_errors", "int"),
    ("runs", "crashed", "int default 0"),
    ("runs", "stability_json", "text"),
]


def _stability_cols(metrics):
    st = metrics.get("stability") or {}
    h, e, cr = st.get("hangs") or {}, st.get("errors") or {}, st.get("crash") or {}
    return (h.get("count"), h.get("longest_ms"), e.get("js"), int(bool(cr.get("crashed"))),
            json.dumps(st) if st else None)


def connect(db=None):
    c = sqlite3.connect(db or DB)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    for table, col, decl in MIGRATIONS:
        have = {r["name"] for r in c.execute(f"pragma table_info({table})")}
        if col not in have:
            c.execute(f"alter table {table} add column {col} {decl}")
    c.commit()
    return c


def record(metrics, *, label=None, git_sha=None, app_version=None,
           device=None, trace_path=None, app_pkg=None, meta=None, db=None):
    c = connect(db)
    f, mem = metrics["frames"], metrics.get("memory", {})
    app_pkg = app_pkg or metrics.get("app_pkg")
    cur = c.execute("""insert into runs
        (ts,label,git_sha,app_version,device,path_kind,trace_path,app_pkg,derived,
         ttff_ms,slow_pct,janky_pct,thermal_drift_pct,peak_rss_mb,rss_growth_mb,
         breaches_json,violations_json,frames_json,memory_json)
        values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
        datetime.now(timezone.utc).isoformat(timespec="seconds"), label, git_sha,
        app_version, device, metrics["path_kind"], trace_path, app_pkg,
        int(bool(metrics.get("derived"))),
        metrics["startup"]["time_to_first_camera_frame_ms"], f["slow_pct"],
        f["janky_pct"], f["thermal_drift_pct"],
        mem.get("rss", {}).get("peak_mb"), mem.get("rss", {}).get("growth_mb"),
        json.dumps(metrics["breaches"]), json.dumps(metrics["ordering_violations"]),
        json.dumps(f), json.dumps(mem)))
    rid = cur.lastrowid
    c.execute("update runs set platform=?, simulator=? where id=?",
              (metrics.get("platform") or "android", int(bool(metrics.get("simulator"))), rid))
    c.execute("""update runs set hang_count=?, longest_hang_ms=?, js_errors=?, crashed=?,
                 stability_json=? where id=?""", (*_stability_cols(metrics), rid))
    if meta:
        c.execute("update runs set meta_json=? where id=?", (json.dumps({"capture": meta}), rid))
    for s in metrics["steps"]:
        c.execute("""insert into step_metrics
            (run_id,step,dur_ms,start_ms,budget_ms,over_budget,children_json)
            values (?,?,?,?,?,?,?)""",
            (rid, s["step"], s["dur_ms"], s["start_ms"], s["budget_ms"],
             int(s["over_budget"]), json.dumps(s["children"])))
    c.commit(); c.close()
    return rid


from .budgets import MIN_BASELINE_RUNS


def baseline(step, *, exclude_run=None, window=20, device=None, app_pkg=None,
             platform=None, simulator=None, db=None):
    """Trailing baseline for a step: median + stdev over the last `window` runs.

    `platform` and `simulator` keep baselines apart: an iOS run judged against
    Android history, or a phone against the Mac's simulator, would read noise
    or a hardware difference as a regression."""
    c = connect(db)
    q = """select sm.dur_ms from step_metrics sm join runs r on sm.run_id=r.id
           where sm.step=?"""
    args = [step]
    if exclude_run:
        q += " and sm.run_id != ?"; args.append(exclude_run)
    if device:
        q += " and r.device = ?"; args.append(device)
    if app_pkg:
        q += " and r.app_pkg = ?"; args.append(app_pkg)
    if platform:
        q += " and coalesce(r.platform, 'android') = ?"; args.append(platform)
    if simulator is not None:
        q += " and coalesce(r.simulator, 0) = ?"; args.append(int(bool(simulator)))
    q += " order by sm.run_id desc limit ?"; args.append(window)
    vals = [r["dur_ms"] for r in c.execute(q, args)]
    c.close()
    if len(vals) < MIN_BASELINE_RUNS:
        return None
    med = statistics.median(vals)
    sd = statistics.pstdev(vals)
    return {"median_ms": round(med, 2), "stdev_ms": round(sd, 2), "n": len(vals)}


# A benchmark comparison has no variance to reason about, so it needs a wider
# relative gate than the trailing baseline to avoid firing on run-to-run noise.
# Measured against this project's own seeded history, a clean run sits within
# ~15% of any single other clean run on the smaller steps.
BENCH_MIN_DELTA_PCT = 20.0


# A step must also move by at least this much in absolute terms. Relative and
# z-score gates alone fire on steps so small that noise doubles them: a real
# device run failed on process_start "regressing 136%" -- 6.17ms against
# 2.61ms, a 3.5ms move no user can perceive in a launch. 5ms is under a third
# of a 60fps frame.
MIN_DELTA_MS = 5.0


def regressions(run_id, *, z=2.5, min_delta_pct=8.0, db=None, use_benchmark=True,
                bench_min_delta_pct=None, min_delta_ms=MIN_DELTA_MS):
    """Steps in `run_id` that are slow relative to their reference.

    Two reference modes:

    * **trailing baseline** (default): median of the last runs for that step.
      Requires BOTH a z-score breach and a minimum relative delta, so a step with
      very tight historical variance does not fire on sub-millisecond noise.
    * **pinned benchmark**: if a benchmark run is pinned for this run's scope, the
      comparison is against that single run instead. A single run has no variance,
      so the z-score gate cannot apply and only the relative delta is used. The
      returned rows say which mode produced them via `reference`.
    """
    c = connect(db)
    meta = c.execute("select path_kind, device, app_pkg, platform, simulator from runs where id=?",
                     (run_id,)).fetchone()
    rows = list(c.execute(
        "select step,dur_ms,budget_ms from step_metrics where run_id=?", (run_id,)))
    c.close()
    app_pkg = meta["app_pkg"] if meta else None
    platform = (meta["platform"] if meta else None) or "android"
    simulator = bool(meta["simulator"]) if meta else False

    bench = None
    if use_benchmark and meta:
        bench = get_benchmark(path_kind=meta["path_kind"], device=meta["device"],
                              app_pkg=app_pkg, platform=platform, db=db)
        if bench and bench["run_id"] == run_id:
            # This run IS the reference for its scope. Pinning it declares it the
            # definition of acceptable, so it cannot regress. Returning [] here
            # rather than falling through to the trailing baseline keeps the
            # benchmark's own verdict stable as later runs shift that baseline.
            return []

    if bench:
        gate = bench_min_delta_pct if bench_min_delta_pct is not None else BENCH_MIN_DELTA_PCT
        c = connect(db)
        bsteps = {r["step"]: r["dur_ms"] for r in c.execute(
            "select step, dur_ms from step_metrics where run_id=?", (bench["run_id"],))}
        c.close()
        out = []
        for r in rows:
            bv = bsteps.get(r["step"])
            if bv is None or not bv:
                continue
            delta = r["dur_ms"] - bv
            pct = delta / bv * 100
            if pct >= gate and delta >= min_delta_ms:
                out.append({"step": r["step"], "dur_ms": r["dur_ms"],
                            "baseline_ms": round(bv, 2), "stdev_ms": None,
                            "n_baseline": 1, "delta_ms": round(delta, 2),
                            "delta_pct": round(pct, 1), "z": None,
                            "budget_ms": r["budget_ms"],
                            "reference": "benchmark", "gate_pct": gate,
                            "benchmark_run_id": bench["run_id"],
                            "benchmark_label": bench.get("label")})
        return sorted(out, key=lambda x: -x["delta_pct"])

    out = []
    for r in rows:
        b = baseline(r["step"], exclude_run=run_id, app_pkg=app_pkg,
                     platform=platform, simulator=simulator, db=db)
        if not b:
            continue
        delta = r["dur_ms"] - b["median_ms"]
        pct = (delta / b["median_ms"] * 100) if b["median_ms"] else 0.0
        zs = (delta / b["stdev_ms"]) if b["stdev_ms"] > 0.01 else (99.0 if pct > min_delta_pct else 0.0)
        if zs >= z and pct >= min_delta_pct and delta >= min_delta_ms:
            out.append({"step": r["step"], "dur_ms": r["dur_ms"],
                        "baseline_ms": b["median_ms"], "stdev_ms": b["stdev_ms"],
                        "n_baseline": b["n"], "delta_ms": round(delta, 2),
                        "delta_pct": round(pct, 1), "z": round(zs, 2),
                        "budget_ms": r["budget_ms"], "reference": "trailing_baseline"})
    return sorted(out, key=lambda x: -x["delta_pct"])


def set_benchmark(run_id, *, note=None, db=None):
    """Pin a run as the reference for its own (path_kind, device) scope."""
    c = connect(db)
    r = c.execute("select id, path_kind, device, label, app_pkg, platform, simulator "
                  "from runs where id=?", (run_id,)).fetchone()
    if not r:
        c.close()
        raise ValueError(f"no run with id {run_id}")
    if r["simulator"]:
        c.close()
        raise ValueError(f"run {run_id} was measured on a simulator. A benchmark defines "
                         "acceptable performance, and a simulator's numbers come from the "
                         "Mac's CPU, so it cannot be one.")
    sc = _scope(r["path_kind"], r["device"], r["app_pkg"], r["platform"] or "android")
    c.execute("""insert into benchmarks (scope, run_id, note, set_at)
                 values (?,?,?,?)
                 on conflict(scope) do update set
                   run_id=excluded.run_id, note=excluded.note, set_at=excluded.set_at""",
              (sc, run_id, note, datetime.now(timezone.utc).isoformat(timespec="seconds")))
    c.commit(); c.close()
    return {"scope": sc, "run_id": run_id, "label": r["label"],
            "path_kind": r["path_kind"], "device": r["device"],
            "app_pkg": r["app_pkg"]}


def clear_benchmark(*, path_kind=None, device=None, app_pkg=None, run_id=None,
                    platform="android", db=None):
    """Unpin by scope, or by the run that is pinned."""
    c = connect(db)
    if run_id is not None:
        n = c.execute("delete from benchmarks where run_id=?", (run_id,)).rowcount
    else:
        n = c.execute("delete from benchmarks where scope=?",
                      (_scope(path_kind, device, app_pkg, platform),)).rowcount
    c.commit(); c.close()
    return n


def get_benchmark(*, path_kind=None, device=None, app_pkg=None, platform="android", db=None):
    """The pinned run for this scope, narrowest match first.

    Falls back from (app, path, device) to (app, path, any device), but never
    across applications or platforms: a benchmark is only ever a reference for
    its own app on its own platform.
    """
    c = connect(db)
    row = None
    for sc in (_scope(path_kind, device, app_pkg, platform),
               _scope(path_kind, None, app_pkg, platform)):
        row = c.execute("""select b.*, r.label, r.ts, r.git_sha, r.app_version,
                                  r.device, r.path_kind, r.app_pkg, r.platform
                           from benchmarks b join runs r on b.run_id = r.id
                           where b.scope=?""", (sc,)).fetchone()
        if row:
            break
    c.close()
    return dict(row) if row else None


def benchmarks(db=None):
    c = connect(db)
    rows = [dict(r) for r in c.execute(
        """select b.*, r.label, r.ts, r.device, r.path_kind, r.app_version, r.app_pkg,
                  coalesce(r.platform, 'android') as platform
           from benchmarks b join runs r on b.run_id = r.id order by b.scope""")]
    c.close()
    return rows


# Metrics where a LOWER value is better, with how to read each off a run row.
METRIC_DIRECTION = {
    "ttff_ms": "lower", "slow_pct": "lower", "janky_pct": "lower",
    "thermal_drift_pct": "lower", "peak_rss_mb": "lower", "rss_growth_mb": "lower",
    "hang_count": "lower", "longest_hang_ms": "lower", "js_errors": "lower",
}

# Metrics that can legitimately be negative. A percentage change across zero is
# meaningless (-10% -> +24% is not "-330%"), so these report absolute deltas only
# and are judged on the absolute move instead of a ratio.
SIGNED_METRICS = {"thermal_drift_pct"}
SIGNED_SAME_BAND = {"thermal_drift_pct": 3.0}   # absolute units considered unchanged


def compare(run_id, base_id, *, db=None, min_delta_pct=5.0):
    """Diff two runs: top-line metrics, per-step durations and child slices.

    Symmetric and purely descriptive -- it reports what changed between two
    specific runs. It does not decide whether a change is a regression; that
    stays with `regressions`, which reasons about variance across many runs.
    A two-run delta has no variance to reason about, so it is labelled a
    difference, not a verdict.
    """
    c = connect(db)
    a = c.execute("select * from runs where id=?", (run_id,)).fetchone()
    b = c.execute("select * from runs where id=?", (base_id,)).fetchone()
    if not a or not b:
        c.close()
        raise ValueError(f"run {run_id if not a else base_id} not found")
    a, b = dict(a), dict(b)

    metrics = []
    for k, direction in METRIC_DIRECTION.items():
        av, bv = a.get(k), b.get(k)
        if av is None or bv is None:
            continue
        delta = av - bv
        signed = k in SIGNED_METRICS
        # A ratio is only meaningful when the base is non-zero and same-signed.
        pct = None if (signed or not bv or (av < 0) != (bv < 0)) else delta / bv * 100
        worse = (delta > 0) if direction == "lower" else (delta < 0)
        if signed:
            same = abs(delta) < SIGNED_SAME_BAND.get(k, 1.0)
        elif pct is not None:
            same = abs(pct) < min_delta_pct
        else:
            same = abs(delta) < 1e-9
        metrics.append({
            "metric": k, "value": av, "base_value": bv,
            "delta": round(delta, 3),
            "delta_pct": None if pct is None else round(pct, 1),
            "direction": direction, "signed": signed,
            "verdict": "same" if same else ("worse" if worse else "better"),
        })

    def steps_of(rid):
        return {r["step"]: dict(r) for r in c.execute(
            "select step, dur_ms, budget_ms, children_json from step_metrics where run_id=?",
            (rid,))}
    sa, sb = steps_of(run_id), steps_of(base_id)
    c.close()

    steps = []
    for name in sorted(set(sa) | set(sb), key=lambda n: -(sa.get(n, {}).get("dur_ms") or 0)):
        x, y = sa.get(name), sb.get(name)
        av = x["dur_ms"] if x else None
        bv = y["dur_ms"] if y else None
        row = {"step": name, "dur_ms": av, "base_dur_ms": bv,
               "budget_ms": (x or y).get("budget_ms"),
               "only_in": None if (x and y) else ("run" if x else "base")}
        if av is not None and bv is not None:
            row["delta_ms"] = round(av - bv, 2)
            row["delta_pct"] = round((av - bv) / bv * 100, 1) if bv else None
            row["verdict"] = ("same" if row["delta_pct"] is not None and abs(row["delta_pct"]) < min_delta_pct
                              else ("worse" if av > bv else "better"))
        # Child-level diff, so a step delta can be attributed rather than just reported.
        ca = {k["name"]: k["dur_ms"] for k in json.loads((x or {}).get("children_json") or "[]")}
        cb = {k["name"]: k["dur_ms"] for k in json.loads((y or {}).get("children_json") or "[]")}
        kids = []
        for kn in sorted(set(ca) | set(cb), key=lambda n: -(ca.get(n) or 0)):
            kav, kbv = ca.get(kn), cb.get(kn)
            kids.append({"name": kn, "dur_ms": kav, "base_dur_ms": kbv,
                         "delta_ms": None if (kav is None or kbv is None) else round(kav - kbv, 2),
                         "delta_pct": None if (kav is None or not kbv) else round((kav - kbv) / kbv * 100, 1)})
        row["children"] = kids
        steps.append(row)

    worse = [m for m in metrics if m["verdict"] == "worse"]
    better = [m for m in metrics if m["verdict"] == "better"]
    return {
        "run": {k: a.get(k) for k in ("id", "ts", "label", "git_sha", "app_version", "device", "path_kind", "platform", "simulator")},
        "base": {k: b.get(k) for k in ("id", "ts", "label", "git_sha", "app_version", "device", "path_kind", "platform", "simulator")},
        # Two runs are comparable on the same start path, platform and kind of
        # device: an iOS launch against an Android one, or a simulator against
        # a phone, differs for reasons no code change explains.
        "comparable": (a.get("path_kind") == b.get("path_kind")
                       and (a.get("platform") or "android") == (b.get("platform") or "android")
                       and bool(a.get("simulator")) == bool(b.get("simulator"))),
        "same_device": a.get("device") == b.get("device"),
        "same_platform": (a.get("platform") or "android") == (b.get("platform") or "android"),
        "metrics": metrics, "steps": steps,
        "summary": {"worse": len(worse), "better": len(better),
                    "same": len(metrics) - len(worse) - len(better)},
    }


def reextract(db=None, extractor=None):
    """Recompute step metrics for every run whose trace file still exists.

    Needed after the extractor changes shape (new child fields, self-time, and
    so on) so historical rows are comparable with new ones rather than silently
    mixing two formats in one baseline.
    """
    import os
    if extractor is None:
        # extract_any, not extract: a derived (competitor) run has no step:
        # markers, so re-extracting it with the instrumented-only extractor
        # silently zeroes its metrics. app_pkg decides which path each run takes.
        from .extract import extract_any as extractor
    c = connect(db)
    rows = list(c.execute(
        """select id, trace_path, path_kind, app_pkg, derived from runs
           where trace_path is not null order by id"""))
    done, missing, fresh = 0, [], {}
    for r in rows:
        if not r["trace_path"] or not os.path.exists(r["trace_path"]):
            missing.append(r["id"])
            continue
        # The stored `derived` flag, not re-detection, decides which extractor
        # runs. Re-detecting would flip an instrumented run whose app_pkg was
        # never recorded over to the derived path, silently replacing its
        # step: metrics with generic ones.
        if r["derived"]:
            m = extractor(r["trace_path"], app_pkg=r["app_pkg"], path_kind=None)
        else:
            from .extract import extract as _extract_instrumented
            m = _extract_instrumented(r["trace_path"],
                                      path_kind=r["path_kind"] or "returning_user",
                                      app_pkg=r["app_pkg"])
            m.setdefault("app_pkg", r["app_pkg"])
            m.setdefault("derived", False)
        c.execute("delete from step_metrics where run_id=?", (r["id"],))
        for s in m["steps"]:
            c.execute("""insert into step_metrics
                (run_id,step,dur_ms,start_ms,budget_ms,over_budget,children_json)
                values (?,?,?,?,?,?,?)""",
                (r["id"], s["step"], s["dur_ms"], s["start_ms"], s["budget_ms"],
                 int(s["over_budget"]), json.dumps(s["children"])))
        f, mem = m["frames"], m.get("memory", {})
        c.execute("""update runs set ttff_ms=?, slow_pct=?, janky_pct=?,
                     thermal_drift_pct=?, peak_rss_mb=?, rss_growth_mb=?,
                     breaches_json=?, violations_json=?, frames_json=?, memory_json=?,
                     platform=?, simulator=?
                     where id=?""",
                  (m["startup"]["time_to_first_camera_frame_ms"], f["slow_pct"],
                   f["janky_pct"], f["thermal_drift_pct"],
                   mem.get("rss", {}).get("peak_mb"), mem.get("rss", {}).get("growth_mb"),
                   json.dumps(m["breaches"]), json.dumps(m["ordering_violations"]),
                   json.dumps(f), json.dumps(mem),
                   m.get("platform") or "android", int(bool(m.get("simulator"))), r["id"]))
        c.execute("""update runs set hang_count=?, longest_hang_ms=?, js_errors=?, crashed=?,
                     stability_json=? where id=?""", (*_stability_cols(m), r["id"]))
        fresh[r["id"]] = m
        done += 1
    c.commit(); c.close()
    return {"reextracted": done, "missing_trace": missing, "metrics": fresh}


# ---------------------------------------------------------------- stress tests

def stress_create(*, app_pkg, device=None, label=None, sessions=5, cold=True,
                  duration_ms=8000, platform="android", db=None):
    c = connect(db)
    cur = c.execute("""insert into stress_tests
        (ts, app_pkg, device, label, sessions_requested, cold, duration_ms, state, platform)
        values (?,?,?,?,?,?,?,'running',?)""",
        (datetime.now(timezone.utc).isoformat(timespec="seconds"), app_pkg, device,
         label, int(sessions), int(bool(cold)), int(duration_ms), platform))
    sid = cur.lastrowid
    for i in range(int(sessions)):
        c.execute("insert into stress_sessions (stress_id, seq, state) values (?,?,'pending')",
                  (sid, i + 1))
    c.commit(); c.close()
    return sid


def stress_session_done(stress_id, seq, *, run_id=None, ttid_ms=None,
                        state="done", error=None, db=None):
    c = connect(db)
    c.execute("""update stress_sessions set run_id=?, ttid_ms=?, state=?, error=?
                 where stress_id=? and seq=?""",
              (run_id, ttid_ms, state, error, stress_id, seq))
    c.commit(); c.close()


def stress_finish(stress_id, *, state="done", error=None, db=None):
    c = connect(db)
    c.execute("update stress_tests set state=?, error=?, finished=? where id=?",
              (state, error, datetime.now(timezone.utc).isoformat(timespec="seconds"),
               stress_id))
    c.commit(); c.close()


def stress_mark_interrupted(db=None):
    """Close out stress tests left 'running' by a server that stopped.

    Jobs run on threads inside the dashboard process, so a restart kills them
    mid-test. Without this, such a test reads RUNNING forever (one sat at 0/5
    for a day), and the UI keeps treating it as live. Called once at startup,
    when by definition nothing can still be running.
    """
    c = connect(db)
    n = c.execute(
        """update stress_tests set state='interrupted',
               error=coalesce(error, 'the dashboard stopped while this test was running'),
               finished=coalesce(finished, ?)
           where state in ('running', 'queued')""",
        (datetime.now(timezone.utc).isoformat(timespec="seconds"),)).rowcount
    c.commit(); c.close()
    return n


def stress_stats(values):
    """Spread across sessions. A stress test exists to expose variance, so the
    summary leads with spread rather than a single average that hides it."""
    vals = sorted(v for v in values if v is not None and v > 0)
    if not vals:
        return None
    n = len(vals)
    def pct(p):
        if n == 1:
            return vals[0]
        k = (n - 1) * p
        lo, hi = int(k), min(int(k) + 1, n - 1)
        return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)
    mean = sum(vals) / n
    return {
        "n": n, "min": round(vals[0], 1), "max": round(vals[-1], 1),
        "mean": round(mean, 1), "median": round(pct(0.5), 1),
        "p90": round(pct(0.9), 1),
        "stdev": round(statistics.pstdev(vals), 1) if n > 1 else 0.0,
        # Spread as a share of the median: the honest headline for "how
        # repeatable is this app's cold start".
        "spread_pct": round((vals[-1] - vals[0]) / pct(0.5) * 100, 1) if pct(0.5) else None,
    }


def stress_get(stress_id, db=None):
    c = connect(db)
    t = c.execute("select * from stress_tests where id=?", (stress_id,)).fetchone()
    if not t:
        c.close()
        return None
    t = dict(t)
    rows = [dict(r) for r in c.execute(
        """select ss.*, r.label as run_label, r.ts as run_ts, r.slow_pct,
                  r.peak_rss_mb, r.rss_growth_mb, r.path_kind
           from stress_sessions ss left join runs r on ss.run_id = r.id
           where ss.stress_id=? order by ss.seq""", (stress_id,))]
    c.close()
    t["sessions"] = rows
    t["stats"] = {"ttid_ms": stress_stats([r["ttid_ms"] for r in rows]),
                  "peak_rss_mb": stress_stats([r["peak_rss_mb"] for r in rows]),
                  "slow_pct": stress_stats([r["slow_pct"] for r in rows])}
    t["completed"] = sum(1 for r in rows if r["state"] == "done")
    t["failed"] = sum(1 for r in rows if r["state"] == "error")
    return t


def stress_list(limit=50, db=None):
    c = connect(db)
    ids = [r["id"] for r in c.execute(
        "select id from stress_tests order by id desc limit ?", (limit,))]
    c.close()
    return [stress_get(i, db=db) for i in ids]


def history(limit=100, db=None):
    c = connect(db)
    runs = [dict(r) for r in c.execute(
        "select * from runs order by id desc limit ?", (limit,))]
    ids = [r["id"] for r in runs] or [-1]
    ph = ",".join("?" * len(ids))
    steps = [dict(r) for r in c.execute(
        f"select * from step_metrics where run_id in ({ph})", ids)]
    c.close()
    per = {}
    for s in steps:
        per.setdefault(s["run_id"], []).append(s)
    for r in runs:
        r["steps"] = sorted(per.get(r["id"], []), key=lambda x: x["start_ms"] or 0)
    return list(reversed(runs))


# ---------------------------------------------------------------- run metadata

def run_row(run_id, db=None):
    c = connect(db)
    r = c.execute("select * from runs where id=?", (run_id,)).fetchone()
    c.close()
    return dict(r) if r else None


def run_id_for_trace(trace_path, db=None):
    """The newest run recorded from a trace file."""
    c = connect(db)
    r = c.execute("select max(id) as id from runs where trace_path=?", (trace_path,)).fetchone()
    c.close()
    return r["id"] if r else None


def set_run_meta(run_id, key, value, db=None):
    """Set one section ("capture" or "from_trace") of a run's metadata."""
    c = connect(db)
    row = c.execute("select meta_json from runs where id=?", (run_id,)).fetchone()
    if row is None:
        c.close()
        raise ValueError(f"no run {run_id}")
    meta = json.loads(row["meta_json"] or "{}")
    meta[key] = value
    c.execute("update runs set meta_json=? where id=?", (json.dumps(meta), run_id))
    c.commit(); c.close()
    return meta


# ---------------------------------------------------------------- flashlight audits

def audit_create(*, app_pkg, device=None, label=None, iterations, duration_ms,
                 meta=None, db=None):
    c = connect(db)
    aid = c.execute("""insert into flashlight_audits
        (ts, app_pkg, device, label, iterations, duration_ms, state, meta_json)
        values (?,?,?,?,?,?,'running',?)""",
        (_now(), app_pkg, device, label, int(iterations), int(duration_ms),
         json.dumps(meta) if meta else None)).lastrowid
    c.commit(); c.close()
    return aid


def audit_finish(audit_id, *, state="done", error=None, results_path=None,
                 summary=None, db=None):
    """Close an audit. `summary` is what flashlight.run_audit returned; its
    headline numbers are copied into columns so lists need not parse it."""
    m = (summary or {}).get("metrics") or {}
    c = connect(db)
    c.execute("""update flashlight_audits set state=?, error=?, finished=?, results_path=?,
                 flashlight_version=?, score=?, cpu_pct=?, ram_mb=?, fps=?, summary_json=?
                 where id=?""",
              (state, error, _now(), results_path, (summary or {}).get("flashlight_version"),
               (summary or {}).get("score"), m.get("cpu_pct"), m.get("ram_mb"), m.get("fps"),
               json.dumps(summary) if summary else None, audit_id))
    c.commit(); c.close()


def _audit(row, full):
    a = dict(row)
    summary, meta = a.pop("summary_json"), a.pop("meta_json")
    a["meta"] = json.loads(meta) if meta else None
    if full:
        a["summary"] = json.loads(summary) if summary else None
    else:
        # A list shows headline numbers; the per-iteration table and time
        # series stay on the detail call.
        s = json.loads(summary) if summary else {}
        a["summary"] = {k: s.get(k) for k in ("successful", "failed", "metrics", "key_threads")} if s else None
    return a


def audit_get(audit_id, db=None):
    c = connect(db)
    r = c.execute("select * from flashlight_audits where id=?", (audit_id,)).fetchone()
    c.close()
    return _audit(r, full=True) if r else None


def audit_list(app_pkg=None, limit=100, db=None):
    c = connect(db)
    q, args = "select * from flashlight_audits", []
    if app_pkg:
        q += " where app_pkg=?"; args.append(app_pkg)
    q += " order by id desc limit ?"; args.append(limit)
    rows = [_audit(r, full=False) for r in c.execute(q, args)]
    c.close()
    return rows


def audit_mark_interrupted(db=None):
    """Close audits left running by a server that stopped, as stress tests are."""
    c = connect(db)
    n = c.execute(
        """update flashlight_audits set state='interrupted',
               error=coalesce(error, 'the dashboard stopped while this audit was running'),
               finished=coalesce(finished, ?)
           where state in ('running', 'queued')""", (_now(),)).rowcount
    c.commit(); c.close()
    return n


# ---------------------------------------------------------------- copilot

def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def copilot_thread_new(title, db=None):
    c = connect(db)
    tid = c.execute("insert into copilot_threads (title, created, updated) values (?,?,?)",
                    (title[:120], _now(), _now())).lastrowid
    c.commit(); c.close()
    return tid


def copilot_message_add(thread_id, role, payload, db=None):
    c = connect(db)
    mid = c.execute("insert into copilot_messages (thread_id, role, json, created) values (?,?,?,?)",
                    (thread_id, role, json.dumps(payload), _now())).lastrowid
    c.execute("update copilot_threads set updated=? where id=?", (_now(), thread_id))
    c.commit(); c.close()
    return mid


def copilot_threads(limit=30, db=None):
    c = connect(db)
    rows = [dict(r) for r in c.execute(
        "select id, title, created, updated from copilot_threads order by updated desc limit ?", (limit,))]
    c.close()
    return rows


def copilot_thread(thread_id, db=None):
    c = connect(db)
    t = c.execute("select id, title, created, updated from copilot_threads where id=?", (thread_id,)).fetchone()
    if not t:
        c.close()
        return None
    msgs = [{"id": r["id"], "role": r["role"], "feedback": r["feedback"], **json.loads(r["json"])}
            for r in c.execute("select * from copilot_messages where thread_id=? order by id", (thread_id,))]
    c.close()
    return {**dict(t), "messages": msgs}


def copilot_pin(message_id, db=None):
    """Pin a saved Copilot answer as a finding on the run it answered about.

    The finding is built from the saved answer (its verdict and the question
    that prompted it), not from anything the client sends. Pinning the same
    answer twice returns the existing pin.
    """
    c = connect(db)
    try:
        m = c.execute("select * from copilot_messages where id=? and role='assistant'", (message_id,)).fetchone()
        if not m:
            raise ValueError(f"no saved answer {message_id}")
        if old := c.execute("select * from copilot_pins where message_id=?", (message_id,)).fetchone():
            return dict(old)
        body = json.loads(m["json"])
        run_id = (body.get("result") or {}).get("run_id")
        if run_id is None:
            raise ValueError("that answer is not about a run")
        q = c.execute("select json from copilot_messages where thread_id=? and id<? and role='user' "
                      "order by id desc limit 1", (m["thread_id"], message_id)).fetchone()
        title = json.loads(q["json"])["text"] if q else "Copilot answer"
        verdict = next((b for b in body.get("blocks", []) if b.get("type") == "verdict"), None)
        paras = [b["text"] for b in body.get("blocks", []) if b.get("type") == "para"]
        severity = {"fail": "high", "warn": "medium"}.get((verdict or {}).get("tone"), "low")
        evidence = (verdict or {}).get("text") or (paras[0] if paras else "See the Copilot thread.")
        pid = c.execute("insert into copilot_pins (message_id, run_id, title, severity, evidence, created) "
                        "values (?,?,?,?,?,?)", (message_id, run_id, title[:200], severity, evidence, _now())).lastrowid
        c.commit()
        return dict(c.execute("select * from copilot_pins where id=?", (pid,)).fetchone())
    finally:
        c.close()


def copilot_pins(run_id=None, db=None):
    c = connect(db)
    sql, args = "select * from copilot_pins", ()
    if run_id is not None:
        sql, args = sql + " where run_id=?", (run_id,)
    rows = [dict(r) for r in c.execute(sql + " order by id", args)]
    c.close()
    return rows


def copilot_unpin(pin_id, db=None):
    c = connect(db)
    n = c.execute("delete from copilot_pins where id=?", (pin_id,)).rowcount
    c.commit(); c.close()
    return n


def copilot_feedback(message_id, value, db=None):
    if value not in ("up", "down", None):
        raise ValueError("feedback must be 'up', 'down' or null")
    c = connect(db)
    n = c.execute("update copilot_messages set feedback=? where id=?", (value, message_id)).rowcount
    c.commit(); c.close()
    return n
