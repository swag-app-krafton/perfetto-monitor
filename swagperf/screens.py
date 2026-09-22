"""Per-screen and per-action metrics from SwagTrace markers.

The app emits markers via `SwagTrace` (see swag-pay's
`commonMain/.../trace/SwagTrace.kt`):

  screen:<Route>        async slice, open for the whole screen visit
  action:<name>         instant or span for a discrete user action
  nav:<From>-><To>      the navigation transition itself
  step:<name>           startup milestones

This module attributes CPU and RAM to those spans. That attribution is the
point: a screen that is merely slow is a number, but a screen that is slow
*and* holds 40MB more RAM than the one before it is a diagnosis.

Everything here is deterministic SQL, like the rest of extraction. No model.
"""
from .extract import _rows

SCREEN_PREFIX = "screen:"
ACTION_PREFIX = "action:"
NAV_PREFIX = "nav:"


def _has(tp, prefix):
    r = _rows(tp, f"select count(*) c from slice where name like '{prefix}%'")
    return bool(r and (r[0].get("c") or 0) > 0)


def has_markers(tp):
    """Whether this trace carries SwagTrace markers at all."""
    return _has(tp, SCREEN_PREFIX) or _has(tp, ACTION_PREFIX)


def screen_visits(tp):
    """One row per screen visit, with CPU and RAM attributed to its span.

    CPU comes from `sched_slice` overlapped with the visit rather than from
    wall time: a screen that is merely *open* while the device idles has not
    cost anything, and wall time cannot tell that apart from real work.
    """
    visits = _rows(tp, f"""
        select s.id as sid, s.name as nm, s.ts as ts, s.dur as dur
        from slice s
        where s.name like '{SCREEN_PREFIX}%' and s.dur > 0
        order by s.ts
    """)
    if not visits:
        return []

    out = []
    for v in visits:
        route = v["nm"][len(SCREEN_PREFIX):]
        start, end = v["ts"], v["ts"] + v["dur"]

        # CPU time actually scheduled during the visit, across all threads of
        # whichever process owns the app. Clipped to the visit window so a
        # thread that spans the boundary is not double-counted into it.
        cpu = _rows(tp, f"""
            select sum(min(ss.ts + ss.dur, {end}) - max(ss.ts, {start})) as cpu_ns
            from sched_slice ss
            where ss.ts < {end} and (ss.ts + ss.dur) > {start}
              and ss.utid in (
                select utid from thread where upid in (
                  select upid from process where name is not null
                    and name = (select p2.name from slice s2
                      join thread_track tt2 on s2.track_id = tt2.id
                      join thread th2 on tt2.utid = th2.utid
                      join process p2 on th2.upid = p2.upid
                      where s2.id = {v['sid']} limit 1)))
        """)
        cpu_ms = round((cpu[0]["cpu_ns"] or 0) / 1e6, 2) if cpu else None

        # RAM across the visit. A screen that leaves RSS higher than it found
        # it is the orphaned-surface signature the shell architecture names.
        mem = _rows(tp, f"""
            select min(c.value) as lo, max(c.value) as hi,
                   (select value from counter c2 join counter_track t2
                      on c2.track_id = t2.id
                    where t2.name like 'mem.rss%' and c2.ts <= {end}
                    order by c2.ts desc limit 1) as at_end
            from counter c join counter_track t on c.track_id = t.id
            where t.name like 'mem.rss%' and c.ts >= {start} and c.ts <= {end}
        """)
        mb = 1024 * 1024
        rss = {}
        if mem and mem[0].get("hi") is not None:
            rss = {"min_mb": round(mem[0]["lo"] / mb, 1),
                   "peak_mb": round(mem[0]["hi"] / mb, 1),
                   "delta_mb": round((mem[0]["hi"] - mem[0]["lo"]) / mb, 1)}

        frames = _rows(tp, f"""
            select count(*) as n,
                   sum(case when dur > 16666667 then 1 else 0 end) as slow
            from slice
            where name = 'Choreographer#doFrame' and ts >= {start} and ts <= {end}
        """)
        f = frames[0] if frames else {}
        n = f.get("n") or 0

        out.append({
            "route": route,
            "start_ms": round(start / 1e6, 2),
            "duration_ms": round(v["dur"] / 1e6, 2),
            "cpu_ms": cpu_ms,
            # CPU as a share of wall time says whether the screen was busy or
            # just on screen -- the number an engineer actually acts on.
            "cpu_pct_of_wall": (round(cpu_ms / (v["dur"] / 1e6) * 100, 1)
                                if cpu_ms and v["dur"] else None),
            "rss": rss or None,
            "frames": n,
            "slow_frames": f.get("slow") or 0,
            "slow_frame_pct": round((f.get("slow") or 0) / n * 100, 2) if n else None,
        })
    return out


def screen_summary(visits):
    """Aggregate repeated visits to the same screen.

    A route is usually visited more than once in a session, and the interesting
    figure is the total cost of being on that screen plus the worst single
    visit, not an average that hides a single bad one.
    """
    by = {}
    for v in visits:
        s = by.setdefault(v["route"], {
            "route": v["route"], "visits": 0, "total_ms": 0.0, "total_cpu_ms": 0.0,
            "worst_ms": 0.0, "frames": 0, "slow_frames": 0, "peak_rss_mb": None,
            "max_rss_delta_mb": None})
        s["visits"] += 1
        s["total_ms"] += v["duration_ms"]
        s["total_cpu_ms"] += v["cpu_ms"] or 0.0
        s["worst_ms"] = max(s["worst_ms"], v["duration_ms"])
        s["frames"] += v["frames"]
        s["slow_frames"] += v["slow_frames"]
        if v.get("rss"):
            s["peak_rss_mb"] = max(s["peak_rss_mb"] or 0, v["rss"]["peak_mb"])
            s["max_rss_delta_mb"] = max(s["max_rss_delta_mb"] or 0, v["rss"]["delta_mb"])
    for s in by.values():
        s["total_ms"] = round(s["total_ms"], 2)
        s["total_cpu_ms"] = round(s["total_cpu_ms"], 2)
        s["slow_frame_pct"] = (round(s["slow_frames"] / s["frames"] * 100, 2)
                               if s["frames"] else None)
    return sorted(by.values(), key=lambda s: -s["total_cpu_ms"])


def actions(tp):
    """User actions, aggregated by name.

    Instant markers have no duration, so count is the signal for those; spans
    additionally carry timing. Both shapes are reported through one table so a
    caller does not need to know which the app emitted.
    """
    rows = _rows(tp, f"""
        select name as nm, count(*) as n,
               sum(case when dur > 0 then dur else 0 end) as total_dur,
               max(dur) as max_dur
        from slice where name like '{ACTION_PREFIX}%'
        group by name order by n desc
    """)
    out = []
    for r in rows:
        total = (r["total_dur"] or 0) / 1e6
        out.append({
            "action": r["nm"][len(ACTION_PREFIX):],
            "count": r["n"],
            "total_ms": round(total, 2) if total else None,
            "max_ms": round((r["max_dur"] or 0) / 1e6, 2) if (r["max_dur"] or 0) > 0 else None,
            "mean_ms": round(total / r["n"], 2) if total and r["n"] else None,
        })
    return out


def navigations(tp):
    """Screen-to-screen transitions and what each one cost."""
    rows = _rows(tp, f"""
        select name as nm, count(*) as n,
               sum(case when dur > 0 then dur else 0 end) as total_dur,
               max(dur) as max_dur
        from slice where name like '{NAV_PREFIX}%'
        group by name order by n desc
    """)
    out = []
    for r in rows:
        label = r["nm"][len(NAV_PREFIX):]
        frm, _, to = label.partition("->")
        total = (r["total_dur"] or 0) / 1e6
        out.append({
            "transition": label,
            "from": frm or None, "to": to or None,
            "count": r["n"],
            "total_ms": round(total, 2) if total else None,
            "max_ms": round((r["max_dur"] or 0) / 1e6, 2) if (r["max_dur"] or 0) > 0 else None,
        })
    return out


def extract_screens(trace_path):
    """Screen, action and navigation metrics for one trace."""
    from perfetto.trace_processor import TraceProcessor
    tp = TraceProcessor(trace=trace_path)
    try:
        if not has_markers(tp):
            return {"instrumented": False, "screens": [], "screen_summary": [],
                    "actions": [], "navigations": [],
                    "note": "This trace carries no SwagTrace screen/action markers. "
                            "Screen attribution needs the app to emit them; see "
                            "SwagTrace in the swag-pay repo."}
        visits = screen_visits(tp)
        return {"instrumented": True,
                "screens": visits,
                "screen_summary": screen_summary(visits),
                "actions": actions(tp),
                "navigations": navigations(tp)}
    finally:
        tp.close()
