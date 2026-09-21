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

    # --- frame pacing ------------------------------------------------------
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

    # --- thermal drift: does frame time degrade over sustained scanning? ----
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

    # --- memory ------------------------------------------------------------
    mem = {}
    for key, track in (("rss", "mem.rss"), ("hermes_heap", "mem.hermes_heap")):
        r = _rows(tp, f"""
            select max(c.value) mx, min(c.value) mn,
                   (select value from counter c2 join counter_track t2
                     on c2.track_id=t2.id where t2.name='{track}'
                     order by c2.ts desc limit 1) last
            from counter c join counter_track t on c.track_id=t.id
            where t.name = '{track}'
        """)
        if r and r[0].get("mx") is not None:
            mb = 1024 * 1024
            mem[key] = {
                "peak_mb": round(r[0]["mx"] / mb, 1),
                "min_mb": round(r[0]["mn"] / mb, 1),
                "growth_mb": round((r[0]["mx"] - r[0]["mn"]) / mb, 1),
            }

    # --- breaches against architecture budgets -----------------------------
    checks = {
        "time_to_first_camera_frame_ms": ttff,
        "slow_frame_pct": frames["slow_pct"],
        "janky_frame_pct": frames["janky_pct"],
        "peak_rss_mb": mem.get("rss", {}).get("peak_mb", 0),
        "rss_growth_mb": mem.get("rss", {}).get("growth_mb", 0),
        "thermal_drift_pct": drift,
    }
    breaches = [
        {"metric": k, "value": v, "budget": GLOBAL_BUDGETS[k],
         "over_by_pct": round((v - GLOBAL_BUDGETS[k]) / GLOBAL_BUDGETS[k] * 100, 1)}
        for k, v in checks.items() if v > GLOBAL_BUDGETS[k]
    ]

    return {
        "path_kind": path_kind,
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
