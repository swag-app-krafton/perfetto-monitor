"""Deterministic metric extraction from a Perfetto trace.

No LLM involvement. Everything here is measurement: TraceProcessor SQL in,
a typed metrics dict out. The LLM only ever sees this output, never a raw trace.
"""
from perfetto.trace_processor import TraceProcessor
from .budgets import (FRAME_NS, ORDERING_TOLERANCE_MS, STEP_BUDGETS_MS, GLOBAL_BUDGETS, DEFERRED_STEPS,
                      CRITICAL_PATH_RETURNING, CRITICAL_PATH_FIRST_RUN)

STEP_PREFIX = "step:"


def _with_self_time(children, step_dur_ms):
    """Append unattributed self-time so a breakdown sums to the step duration."""
    kids = sorted(children, key=lambda c: -c["dur_ms"])
    acc = sum(c["dur_ms"] for c in kids)
    self_ms = round(step_dur_ms - acc, 2)
    if self_ms > 0.5 and step_dur_ms:
        kids.append({"name": "(self / untraced)", "dur_ms": self_ms, "count": None,
                     "pct_of_step": round(self_ms / step_dur_ms * 100, 1),
                     "self_time": True})
    return kids


def _rows(tp, q):
    return [dict(r.__dict__) if hasattr(r, "__dict__") else dict(r) for r in tp.query(q)]


def extract(trace_path, *, path_kind="returning_user"):
    tp = TraceProcessor(trace=trace_path)
    try:
        return _extract(tp, path_kind)
    finally:
        tp.close()


def capture_problems(metrics, *, requested_pkg=None):
    """Signals that a capture did not actually observe the app under test.

    A trace can be pulled successfully and parse cleanly while containing
    nothing about the target app -- the launch was intercepted by a lock
    screen, the app never reached the foreground, or the trace window missed
    it. Left unchecked that reads as a flawless run: zero steps, zero
    findings, verdict "pass". These checks exist so an empty capture is
    reported as a failure instead of a clean bill of health.
    """
    problems = []
    # The decisive check: if the target package's own process contributed no
    # slices, the capture never saw the app, and anything derived came from
    # other processes on a busy device.
    if requested_pkg and metrics.get("derived") and metrics.get("target_slices") == 0:
        problems.append(
            f"no slices at all were recorded for {requested_pkg}'s own process -- "
            "the capture did not observe this app, so every number here came from "
            "unrelated processes and none of it describes the app under test")
    detected = (metrics.get("detected_app") or {}).get("pkg")
    if requested_pkg and detected and detected != requested_pkg:
        problems.append(
            f"the trace's launch belongs to {detected}, not {requested_pkg} -- the "
            "target app probably never came to the foreground (a lock screen, "
            "biometric prompt or permission dialog can intercept an adb launch)")
    if not metrics.get("steps"):
        problems.append("no startup phases could be derived from this trace")
    if metrics["startup"].get("time_to_first_camera_frame_ms") in (None, 0, 0.0):
        problems.append("startup time could not be measured")
    if (metrics.get("frames") or {}).get("total", 0) == 0:
        problems.append(
            "no frame slices were recorded, so frame pacing and thermal drift "
            "are unavailable for this run")
    return problems


def extract_any(trace_path, *, app_pkg=None, path_kind=None, force_derive=False):
    """Extract from any trace, instrumented or not.

    An app in the catalogue marked `instrumented` is read through the `step:`
    markers it emits. Everything else -- notably a competitor's binary, where
    instrumentation is impossible -- is read through `derive.py`, which builds
    the same shape from ordinary Android slice names.

    The returned dict has the same keys either way, so the store, the analyst
    and the dashboard do not need to care which path produced it. Derived runs
    are flagged `derived: True` and carry no per-step budgets.
    """
    from . import catalogue
    from .derive import derive_steps, detect_app

    tp = TraceProcessor(trace=trace_path)
    try:
        detected = detect_app(tp)
        pkg = app_pkg or detected.get("pkg")
        instrumented = (catalogue.is_instrumented(pkg) if pkg else False) and not force_derive

        if instrumented:
            m = _extract(tp, path_kind or "returning_user")
            m["app_pkg"] = pkg
            m["derived"] = False
            m["startup_metric"] = "time to first camera frame"
            m["detected_app"] = detected
            return m

        d = derive_steps(tp, pkg=pkg)
        target_slices = d.get("target_slices", 0)
        frames = _frames(tp)
        mem = _memory(tp)
        # Cold vs warm is classified from what was actually derived rather than
        # from the stdlib's label, which can misfire: a process_start phase only
        # exists when the process was genuinely created for this launch.
        names = {s["step"] for s in d["steps"]}
        kind = path_kind or ("cold" if "step:process_start" in names else "warm")
        bud = catalogue.budgets_for(pkg)
        ttid = d["ttid_ms"] or 0.0
        ttid_budget = bud.get("ttid_ms")

        breaches = []
        checks = {"time_to_first_camera_frame_ms": ttid,
                  "slow_frame_pct": frames["slow_pct"],
                  "janky_frame_pct": frames["janky_pct"],
                  "peak_rss_mb": mem.get("rss", {}).get("peak_mb", 0),
                  "rss_growth_mb": mem.get("rss", {}).get("growth_mb", 0),
                  "thermal_drift_pct": frames["thermal_drift_pct"]}
        # Only budgets the catalogue actually states are asserted. Inventing a
        # startup budget for someone else's app would be making up a number.
        if ttid_budget and ttid > ttid_budget:
            breaches.append({"metric": "time_to_first_camera_frame_ms", "value": ttid,
                             "budget": ttid_budget,
                             "over_by_pct": round((ttid - ttid_budget) / ttid_budget * 100, 1)})
        for k in ("slow_frame_pct", "janky_frame_pct"):
            b = GLOBAL_BUDGETS[k]
            if checks[k] > b:
                breaches.append({"metric": k, "value": checks[k], "budget": b,
                                 "over_by_pct": round((checks[k] - b) / b * 100, 1)})

        return {
            "path_kind": kind,
            "app_pkg": pkg,
            "derived": True,
            "startup_metric": "time to initial display",
            "detected_app": detected,
            "steps": d["steps"],
            "startup": {"time_to_first_camera_frame_ms": ttid,
                        "budget_ms": ttid_budget,
                        "critical_path": [s["step"] for s in d["steps"]]},
            "ordering_violations": [],
            "frames": frames,
            "memory": mem,
            "budget_checks": checks,
            "breaches": breaches,
            "derive_window": d["window"],
            "target_slices": target_slices,
        }
    finally:
        tp.close()


def _frames(tp):
    """Frame-pacing metrics. Shared by the instrumented and derived paths."""
    fr = _rows(tp, f"""
        select count(*) total,
               sum(case when dur > {FRAME_NS} then 1 else 0 end) slow,
               sum(case when dur > {3 * FRAME_NS} then 1 else 0 end) janky,
               cast(avg(dur) as int) avg_dur,
               cast(max(dur) as int) max_dur
        from slice where name = 'Choreographer#doFrame'
    """)
    f = fr[0] if fr else {}
    total = f.get("total") or 0
    frames = {
        "total": total,
        "slow": f.get("slow") or 0,
        "janky": f.get("janky") or 0,
        "slow_pct": round((f.get("slow") or 0) / total * 100, 2) if total else 0.0,
        "janky_pct": round((f.get("janky") or 0) / total * 100, 2) if total else 0.0,
        "avg_ms": round((f.get("avg_dur") or 0) / 1e6, 2),
        "max_ms": round((f.get("max_dur") or 0) / 1e6, 2),
    }
    # Thermal drift: second-half mean frame time against the first half. A rising
    # value means the device is throttling, which is a different problem from
    # scattered jank and needs a different fix.
    halves = _rows(tp, """
        with f as (
          select dur, row_number() over (order by ts) rn, count(*) over () n
          from slice where name = 'Choreographer#doFrame')
        select avg(case when rn <= n/2 then dur end) first_half,
               avg(case when rn >  n/2 then dur end) second_half from f
    """)
    drift = 0.0
    if halves and halves[0].get("first_half"):
        a, b = halves[0]["first_half"], halves[0]["second_half"]
        drift = round((b - a) / a * 100, 2)
    frames["thermal_drift_pct"] = drift
    return frames


def _memory(tp):
    """RAM usage (resident set size) and, where present, the Hermes heap.

    `mem.rss` is the counter this project's own captures emit. A trace from
    `process_stats` instead exposes per-process resident size, so that is used as a
    fallback -- otherwise memory would silently read as zero on any trace not
    produced by our own capture config.
    """
    mem = {}
    mb = 1024 * 1024
    for key, track in (("rss", "mem.rss"), ("hermes_heap", "mem.hermes_heap")):
        r = _rows(tp, f"""
            select max(c.value) mx, min(c.value) mn
            from counter c join counter_track t on c.track_id=t.id
            where t.name = '{track}'
        """)
        if r and r[0].get("mx") is not None:
            mem[key] = {"peak_mb": round(r[0]["mx"] / mb, 1),
                        "min_mb": round(r[0]["mn"] / mb, 1),
                        "growth_mb": round((r[0]["mx"] - r[0]["mn"]) / mb, 1)}
    if "rss" not in mem:
        try:
            tp.query("INCLUDE PERFETTO MODULE android.memory.process;")
            r = _rows(tp, """
                select max(rss_and_swap) mx, min(rss_and_swap) mn
                from memory_rss_and_swap_per_process""")
            if r and r[0].get("mx") is not None:
                mem["rss"] = {"peak_mb": round(r[0]["mx"] / mb, 1),
                              "min_mb": round(r[0]["mn"] / mb, 1),
                              "growth_mb": round((r[0]["mx"] - r[0]["mn"]) / mb, 1),
                              "source": "process_stats"}
        except Exception:
            pass
    return mem


def _extract(tp, path_kind):
    # --- steps: top-level automation markers -------------------------------
    steps = _rows(tp, f"""
        select s.name, s.ts, s.dur, s.depth, s.id,
               coalesce(th.name, 'unknown') as track_name
        from slice s
        left join thread_track tt on s.track_id = tt.id
        left join thread th on tt.utid = th.utid
        where s.name like '{STEP_PREFIX}%'
        order by s.ts
    """)

    # --- children of each step, for attribution ----------------------------
    # Direct children only (depth = parent depth + 1): grandchildren are already
    # accounted for inside their own parent, so including them would double-count.
    children = _rows(tp, """
        select p.name as step, p.dur as step_dur, c.name as child,
               sum(c.dur) as dur, count(*) as n
        from slice p join slice c
          on c.ts >= p.ts and (c.ts + c.dur) <= (p.ts + p.dur)
         and c.id != p.id and c.track_id = p.track_id and c.depth = p.depth + 1
        where p.name like 'step:%' and c.name not like 'step:%'
        group by p.name, c.name
        order by dur desc
    """)
    by_step = {}
    for c in children:
        by_step.setdefault(c["step"], []).append({
            "name": c["child"],
            "dur_ms": round(c["dur"] / 1e6, 2),
            "count": c["n"],
            "pct_of_step": round(c["dur"] / c["step_dur"] * 100, 1) if c["step_dur"] else None,
        })

    step_metrics = []
    for s in steps:
        name = s["name"]
        dur_ms = round(s["dur"] / 1e6, 2)
        budget = STEP_BUDGETS_MS.get(name)
        step_metrics.append({
            "step": name,
            "dur_ms": dur_ms,
            "start_ms": round(s["ts"] / 1e6, 2),
            "track": s["track_name"],
            "budget_ms": budget,
            "over_budget": bool(budget and dur_ms > budget),
            "pct_of_budget": round(dur_ms / budget * 100, 1) if budget else None,
            "children": _with_self_time(by_step.get(name, []), dur_ms),
        })

    # --- startup: time to first usable camera frame ------------------------
    crit = (CRITICAL_PATH_RETURNING if path_kind == "returning_user"
            else CRITICAL_PATH_FIRST_RUN)
    crit_steps = [s for s in step_metrics if s["step"] in crit]
    ttff = round(max((s["start_ms"] + s["dur_ms"] for s in crit_steps), default=0.0), 2)

    # --- deferred-work violation: the architecture's ordering constraint ----
    violations = []
    if path_kind == "returning_user":
        for s in step_metrics:
            # 1ms tolerance: a deferred step legitimately starts *at* the first
            # frame boundary, and float rounding can place it a hair before.
            if s["step"] in DEFERRED_STEPS and s["start_ms"] < ttff - ORDERING_TOLERANCE_MS:
                violations.append({
                    "step": s["step"],
                    "started_at_ms": s["start_ms"],
                    "first_frame_ms": ttff,
                    "detail": f"{s['step']} began {round(ttff - s['start_ms'], 2)}ms "
                              "before first usable camera frame",
                })

    frames = _frames(tp)
    mem = _memory(tp)

    # --- breaches against architecture budgets -----------------------------
    checks = {
        "time_to_first_camera_frame_ms": ttff,
        "slow_frame_pct": frames["slow_pct"],
        "janky_frame_pct": frames["janky_pct"],
        "peak_rss_mb": mem.get("rss", {}).get("peak_mb", 0),
        "rss_growth_mb": mem.get("rss", {}).get("growth_mb", 0),
        "thermal_drift_pct": frames["thermal_drift_pct"],
    }
    breaches = [
        {"metric": k, "value": v, "budget": GLOBAL_BUDGETS[k],
         "over_by_pct": round((v - GLOBAL_BUDGETS[k]) / GLOBAL_BUDGETS[k] * 100, 1)}
        for k, v in checks.items() if v > GLOBAL_BUDGETS[k]
    ]

    return {
        "path_kind": path_kind,
        "derived": False,
        "startup_metric": "time to first camera frame",
        "steps": step_metrics,
        "startup": {"time_to_first_camera_frame_ms": ttff,
                    "budget_ms": GLOBAL_BUDGETS["time_to_first_camera_frame_ms"],
                    "critical_path": crit},
        "ordering_violations": violations,
        "frames": frames,
        "memory": mem,
        "budget_checks": checks,
        "breaches": breaches,
    }
