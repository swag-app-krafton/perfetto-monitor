"""Each metric across app versions, per device, against the pinned benchmark (F-026).

The dashboard's run history holds only the newest 100 runs, and a dashboard
capture keeps its app version only in the run details, so the trend is built
here, over every run of one app, start path and platform. A point is the
median of one version's runs on one device; a missing value is a gap, never 0.

Scopes never mix: one app, one start path, one platform per trend, and every
line is one device (a simulator is its own device, with no benchmark and no
targets). Startup is split by what it measured when a device has both kinds:
a derived run's startup is time to initial display, an instrumented run's is
time to first camera frame, and the two are not one line.
"""
import json, re, statistics

from . import catalogue, runmeta, store
from .budgets import GLOBAL_BUDGETS, STEP_BUDGETS_MS, startup_target

# The top-line metrics a trend can plot: runs column -> the key its North
# Star target has in GLOBAL_BUDGETS (None: no target).
TOP_LINE = {"ttff_ms": "time_to_first_camera_frame_ms", "janky_pct": "janky_frame_pct",
            "slow_pct": "slow_frame_pct", "peak_rss_mb": "peak_rss_mb", "rss_growth_mb": "rss_growth_mb"}
# Targets that are this project's own product decisions, asserted only
# against our own app (as extraction does).
OWN_APP_ONLY = {"peak_rss_mb", "rss_growth_mb"}


def _natural(s):
    """'2.10.0' after '2.9.1': digits compare as numbers. Tagged tuples, so a
    number never meets a string in a comparison."""
    return [(0, int(t), "") if t.isdigit() else (1, 0, t) for t in re.split(r"(\d+)", s or "") if t]


def _code(build):
    try:
        return int(build)
    except (TypeError, ValueError):
        return None


def _order(versions):
    """Oldest first: by build number when every version has a numeric one,
    else by name, numbers compared as numbers; ties by first run."""
    vs = list(versions)
    if vs and all(_code(v["build"]) is not None for v in vs):
        return sorted(vs, key=lambda v: (_code(v["build"]), _natural(v["name"]), v["first_run"]))
    return sorted(vs, key=lambda v: (v["name"] is None, _natural(v["name"] or str(v["build"] or "")),
                                     _code(v["build"]) or 0, v["first_run"]))


def _device_label(device, details, simulator):
    d = details.get("device") or {}
    name = d.get("market_name") or d.get("model") or device or "Unknown device"
    maker = d.get("manufacturer")
    if maker and not name.lower().startswith(maker.lower()):
        name = f"{maker} {name}"
    return f"{name} · Simulator" if simulator else name


def _median(values):
    vals = [v for v in values if v is not None]
    return round(statistics.median(vals), 2) if vals else None


def _value(run, metric, steps):
    if metric.startswith("step:"):
        return steps.get(metric)
    v = run[metric]
    if metric == "ttff_ms" and (v is None or v <= 0):
        return None   # not measured, never the fastest launch on record
    return v


def _target(metric, app, platform, *, derived, simulator):
    if simulator:
        return None
    if metric == "ttff_ms":
        return startup_target(app, platform, derived=derived, simulator=False)[0]
    if metric.startswith("step:"):
        return None if derived else STEP_BUDGETS_MS.get(metric)
    if metric in OWN_APP_ONLY and (app or {}).get("role") != "own":
        return None
    return GLOBAL_BUDGETS.get(TOP_LINE[metric])


def trend(app_pkg, path_kind, platform="android", *, db=None):
    platform = platform or "android"
    app_pkg = None if app_pkg in (None, "", "unknown") else app_pkg
    empty = {"app": app_pkg, "path": path_kind, "platform": platform, "versions": [],
             "unversioned": 0, "devices": [], "steps": [], "series": [], "benchmarks": {}}
    if not path_kind:
        return empty
    c = store.connect(db)
    q = ("select * from runs where path_kind = ? and coalesce(platform, 'android') = ? and "
         + ("app_pkg = ?" if app_pkg else "app_pkg is null") + " order by id")
    runs = [dict(r) for r in c.execute(q, (path_kind, platform, *([app_pkg] if app_pkg else [])))]
    steps_of = {}
    if runs:
        marks = ",".join("?" * len(runs))
        for s in c.execute(f"select run_id, step, dur_ms, start_ms from step_metrics "
                           f"where run_id in ({marks})", [r["id"] for r in runs]):
            steps_of.setdefault(s["run_id"], []).append(dict(s))
    c.close()
    if not runs:
        return empty

    app = catalogue.get(app_pkg, platform) if app_pkg else None
    versions, unversioned, rows = {}, 0, []
    devices = {}
    for r in runs:
        raw = json.loads(r.get("meta_json") or "{}") if r.get("meta_json") else {}
        name, build = runmeta.version_of(r, raw)
        sim = bool(r["simulator"])
        dev = r["device"] or "unknown"
        d = devices.setdefault(dev, {"name": dev, "simulator": sim, "runs": 0, "_newest": None})
        d["runs"] += 1
        d["_newest"] = (r, raw)
        if name is None and build is None:
            unversioned += 1
            continue
        key = runmeta.version_key(name, build)
        v = versions.setdefault(key, {"key": key, "name": name, "build": build,
                                      "label": runmeta.version_label(name, build),
                                      "runs": 0, "first_run": r["id"]})
        v["runs"] += 1
        rows.append((key, dev, r, {s["step"]: s["dur_ms"] for s in steps_of.get(r["id"], [])}))

    ordered = _order(versions.values())
    # Launch steps in the order they happen: by their median start in the runs.
    starts = {}
    for key, dev, r, _ in rows:
        for s in steps_of.get(r["id"], []):
            starts.setdefault(s["step"], []).append(s["start_ms"] or 0)
    first = min((min(v) for v in starts.values()), default=0)
    step_names = sorted(starts, key=lambda n: (statistics.median(starts[n]) - first, n))

    # One series per (device, metric), and per startup kind for ttff.
    grouped = {}
    for key, dev, r, steps in rows:
        derived = bool(r["derived"])
        for metric in [*TOP_LINE, *step_names]:
            value = _value(r, metric, steps)
            if value is None:
                continue
            kind = ("derived" if derived else "instrumented") if metric == "ttff_ms" else None
            g = grouped.setdefault((dev, metric, kind), {"derived": derived, "points": {}})
            g["points"].setdefault(key, []).append((value, r["id"]))

    kinds = {}
    for (dev, metric, kind) in grouped:
        if metric == "ttff_ms":
            kinds.setdefault(dev, set()).add(kind)
    series = []
    for (dev, metric, kind), g in grouped.items():
        pts = []
        for v in ordered:
            vals = g["points"].get(v["key"], [])
            pts.append({"version": v["key"], "value": _median([x for x, _ in vals]),
                        "n": len(vals), "run_ids": [rid for _, rid in vals]} if vals else
                       {"version": v["key"], "value": None, "n": 0, "run_ids": []})
        series.append({
            "device": dev, "metric": metric,
            # Named only where a device has both kinds of startup.
            "kind": kind if metric == "ttff_ms" and len(kinds.get(dev, ())) > 1 else None,
            "startup_metric": ("time to initial display" if g["derived"] else "time to first camera frame")
            if metric == "ttff_ms" else None,
            "target": _target(metric, app, platform, derived=g["derived"],
                              simulator=devices[dev]["simulator"]),
            "points": pts,
        })

    benchmarks = {}
    for dev, d in devices.items():
        if d["simulator"]:
            continue
        pin = store.get_benchmark(path_kind=path_kind, device=None if dev == "unknown" else dev,
                                  app_pkg=app_pkg, platform=platform, db=db)
        if not pin:
            continue
        b = next((r for r in runs if r["id"] == pin["run_id"]), None)
        if b is None:
            continue
        raw = json.loads(b.get("meta_json") or "{}") if b.get("meta_json") else {}
        name, build = runmeta.version_of(b, raw)
        bsteps = {s["step"]: s["dur_ms"] for s in steps_of.get(b["id"], [])}
        values = {m: _value(b, m, bsteps) for m in [*TOP_LINE, *step_names]}
        benchmarks[dev] = {"run_id": b["id"], "device": b["device"], "derived": bool(b["derived"]),
                           "version": runmeta.version_label(name, build) if (name or build is not None) else None,
                           "values": {k: v for k, v in values.items() if v is not None}}

    out_devices = []
    for dev, d in sorted(devices.items(), key=lambda kv: -kv[1]["runs"]):
        r, raw = d["_newest"]
        out_devices.append({"name": dev, "simulator": d["simulator"], "runs": d["runs"],
                            "label": _device_label(dev, runmeta.merge(r, raw), d["simulator"])})
    return {**empty,
            "versions": [{k: v[k] for k in ("key", "name", "build", "label", "runs")} for v in ordered],
            "unversioned": unversioned, "devices": out_devices, "steps": step_names,
            "series": series, "benchmarks": benchmarks,
            "startup_target_reason": startup_target(app, platform, derived=True, simulator=False)[1]
            if any(r["derived"] for r in runs) else None}
