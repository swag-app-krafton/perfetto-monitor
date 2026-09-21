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
create table if not exists benchmarks (
  scope text primary key,
  run_id integer not null references runs(id) on delete cascade,
  note text,
  set_at text not null
);
"""

BENCH_ANY = "*"


def _scope(path_kind, device, app_pkg=None):
    """Benchmark scope key. app_pkg is part of it because a reference run for one
    application says nothing about another."""
    return f"{app_pkg or BENCH_ANY}|{path_kind or BENCH_ANY}|{device or BENCH_ANY}"


# Columns added after the first release. sqlite has no "add column if not
# exists", so they are applied idempotently on every connect; an existing
# history.db upgrades in place rather than needing a rebuild.
MIGRATIONS = [
    ("runs", "app_pkg", "text"),
    ("runs", "derived", "int default 0"),
]


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
           device=None, trace_path=None, app_pkg=None, db=None):
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
    for s in metrics["steps"]:
        c.execute("""insert into step_metrics
            (run_id,step,dur_ms,start_ms,budget_ms,over_budget,children_json)
            values (?,?,?,?,?,?,?)""",
            (rid, s["step"], s["dur_ms"], s["start_ms"], s["budget_ms"],
             int(s["over_budget"]), json.dumps(s["children"])))
    c.commit(); c.close()
    return rid


from .budgets import MIN_BASELINE_RUNS


def baseline(step, *, exclude_run=None, window=20, device=None, app_pkg=None, db=None):
    """Trailing baseline for a step: median + stdev over the last `window` runs."""
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


def regressions(run_id, *, z=2.5, min_delta_pct=8.0, db=None, use_benchmark=True,
                bench_min_delta_pct=None):
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
    meta = c.execute("select path_kind, device, app_pkg from runs where id=?",
                     (run_id,)).fetchone()
    rows = list(c.execute(
        "select step,dur_ms,budget_ms from step_metrics where run_id=?", (run_id,)))
    c.close()
    app_pkg = meta["app_pkg"] if meta else None

    bench = None
    if use_benchmark and meta:
        bench = get_benchmark(path_kind=meta["path_kind"], device=meta["device"],
                              app_pkg=app_pkg, db=db)
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
            if pct >= gate:
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
        b = baseline(r["step"], exclude_run=run_id, app_pkg=app_pkg, db=db)
        if not b:
            continue
        delta = r["dur_ms"] - b["median_ms"]
        pct = (delta / b["median_ms"] * 100) if b["median_ms"] else 0.0
        zs = (delta / b["stdev_ms"]) if b["stdev_ms"] > 0.01 else (99.0 if pct > min_delta_pct else 0.0)
        if zs >= z and pct >= min_delta_pct:
            out.append({"step": r["step"], "dur_ms": r["dur_ms"],
                        "baseline_ms": b["median_ms"], "stdev_ms": b["stdev_ms"],
                        "n_baseline": b["n"], "delta_ms": round(delta, 2),
                        "delta_pct": round(pct, 1), "z": round(zs, 2),
                        "budget_ms": r["budget_ms"], "reference": "trailing_baseline"})
    return sorted(out, key=lambda x: -x["delta_pct"])


def set_benchmark(run_id, *, note=None, db=None):
    """Pin a run as the reference for its own (path_kind, device) scope."""
    c = connect(db)
    r = c.execute("select id, path_kind, device, label, app_pkg from runs where id=?",
                  (run_id,)).fetchone()
    if not r:
        c.close()
        raise ValueError(f"no run with id {run_id}")
    sc = _scope(r["path_kind"], r["device"], r["app_pkg"])
    c.execute("""insert into benchmarks (scope, run_id, note, set_at)
                 values (?,?,?,?)
                 on conflict(scope) do update set
                   run_id=excluded.run_id, note=excluded.note, set_at=excluded.set_at""",
              (sc, run_id, note, datetime.now(timezone.utc).isoformat(timespec="seconds")))
    c.commit(); c.close()
    return {"scope": sc, "run_id": run_id, "label": r["label"],
            "path_kind": r["path_kind"], "device": r["device"],
            "app_pkg": r["app_pkg"]}


def clear_benchmark(*, path_kind=None, device=None, app_pkg=None, run_id=None, db=None):
    """Unpin by scope, or by the run that is pinned."""
    c = connect(db)
    if run_id is not None:
        n = c.execute("delete from benchmarks where run_id=?", (run_id,)).rowcount
    else:
        n = c.execute("delete from benchmarks where scope=?",
                      (_scope(path_kind, device, app_pkg),)).rowcount
    c.commit(); c.close()
    return n


def get_benchmark(*, path_kind=None, device=None, app_pkg=None, db=None):
    """The pinned run for this scope, narrowest match first.

    Falls back from (app, path, device) to (app, path, any device), but never
    across applications: a benchmark is only ever a reference for its own app.
    """
    c = connect(db)
    row = None
    for sc in (_scope(path_kind, device, app_pkg),
               _scope(path_kind, None, app_pkg)):
        row = c.execute("""select b.*, r.label, r.ts, r.git_sha, r.app_version,
                                  r.device, r.path_kind, r.app_pkg
                           from benchmarks b join runs r on b.run_id = r.id
                           where b.scope=?""", (sc,)).fetchone()
        if row:
            break
    c.close()
    return dict(row) if row else None


def benchmarks(db=None):
    c = connect(db)
    rows = [dict(r) for r in c.execute(
        """select b.*, r.label, r.ts, r.device, r.path_kind, r.app_version, r.app_pkg
           from benchmarks b join runs r on b.run_id = r.id order by b.scope""")]
    c.close()
    return rows


# Metrics where a LOWER value is better, with how to read each off a run row.
METRIC_DIRECTION = {
    "ttff_ms": "lower", "slow_pct": "lower", "janky_pct": "lower",
    "thermal_drift_pct": "lower", "peak_rss_mb": "lower", "rss_growth_mb": "lower",
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
        "run": {k: a.get(k) for k in ("id", "ts", "label", "git_sha", "app_version", "device", "path_kind")},
        "base": {k: b.get(k) for k in ("id", "ts", "label", "git_sha", "app_version", "device", "path_kind")},
        "comparable": a.get("path_kind") == b.get("path_kind"),
        "same_device": a.get("device") == b.get("device"),
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
        from .extract import extract as extractor
    c = connect(db)
    rows = list(c.execute(
        "select id, trace_path, path_kind from runs where trace_path is not null order by id"))
    done, missing = 0, []
    for r in rows:
        if not r["trace_path"] or not os.path.exists(r["trace_path"]):
            missing.append(r["id"])
            continue
        m = extractor(r["trace_path"], path_kind=r["path_kind"] or "returning_user")
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
                     breaches_json=?, violations_json=?, frames_json=?, memory_json=?
                     where id=?""",
                  (m["startup"]["time_to_first_camera_frame_ms"], f["slow_pct"],
                   f["janky_pct"], f["thermal_drift_pct"],
                   mem.get("rss", {}).get("peak_mb"), mem.get("rss", {}).get("growth_mb"),
                   json.dumps(m["breaches"]), json.dumps(m["ordering_violations"]),
                   json.dumps(f), json.dumps(mem), r["id"]))
        done += 1
    c.commit(); c.close()
    return {"reextracted": done, "missing_trace": missing}


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
