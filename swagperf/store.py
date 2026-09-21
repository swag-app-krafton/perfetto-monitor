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
"""


def connect(db=None):
    c = sqlite3.connect(db or DB)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def record(metrics, *, label=None, git_sha=None, app_version=None,
           device=None, trace_path=None, db=None):
    c = connect(db)
    f, mem = metrics["frames"], metrics.get("memory", {})
    cur = c.execute("""insert into runs
        (ts,label,git_sha,app_version,device,path_kind,trace_path,
         ttff_ms,slow_pct,janky_pct,thermal_drift_pct,peak_rss_mb,rss_growth_mb,
         breaches_json,violations_json,frames_json,memory_json)
        values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
        datetime.now(timezone.utc).isoformat(timespec="seconds"), label, git_sha,
        app_version, device, metrics["path_kind"], trace_path,
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


def baseline(step, *, exclude_run=None, window=20, device=None, db=None):
    """Trailing baseline for a step: median + stdev over the last `window` runs."""
    c = connect(db)
    q = """select sm.dur_ms from step_metrics sm join runs r on sm.run_id=r.id
           where sm.step=?"""
    args = [step]
    if exclude_run:
        q += " and sm.run_id != ?"; args.append(exclude_run)
    if device:
        q += " and r.device = ?"; args.append(device)
    q += " order by sm.run_id desc limit ?"; args.append(window)
    vals = [r["dur_ms"] for r in c.execute(q, args)]
    c.close()
    if len(vals) < MIN_BASELINE_RUNS:
        return None
    med = statistics.median(vals)
    sd = statistics.pstdev(vals)
    return {"median_ms": round(med, 2), "stdev_ms": round(sd, 2), "n": len(vals)}


def regressions(run_id, *, z=2.5, min_delta_pct=8.0, db=None):
    """Steps in `run_id` that are slow relative to their own trailing baseline.

    Requires BOTH a z-score breach and a minimum relative delta, so a step with
    a very tight historical variance does not fire on sub-millisecond noise.
    """
    c = connect(db)
    rows = list(c.execute(
        "select step,dur_ms,budget_ms from step_metrics where run_id=?", (run_id,)))
    c.close()
    out = []
    for r in rows:
        b = baseline(r["step"], exclude_run=run_id, db=db)
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
                        "budget_ms": r["budget_ms"]})
    return sorted(out, key=lambda x: -x["delta_pct"])


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
