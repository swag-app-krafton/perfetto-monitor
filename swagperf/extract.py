"""Deterministic metric extraction from a Perfetto trace.

No LLM involvement. Everything here is measurement: TraceProcessor SQL in,
a typed metrics dict out. The LLM only ever sees this output, never a raw trace.
"""
import re

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


SOURCE_PREFIX = "swagperf.source:"


def trace_source(tp):
    """Where a trace was recorded. An iOS trace carries it in one instant the
    converter writes (`swagperf.source:platform=ios;simulator=1;...`); anything
    without one is an Android capture."""
    r = _rows(tp, f"select name from slice where name like '{SOURCE_PREFIX}%' limit 1")
    src = {"platform": "android", "simulator": False}
    if r:
        for part in r[0]["name"][len(SOURCE_PREFIX):].split(";"):
            k, _, v = part.partition("=")
            if k:
                src[k] = v
        src["simulator"] = src.get("simulator") in ("1", "true", "True", True)
    return src


def trace_source_of(trace_path):
    """trace_source for a trace file."""
    tp = TraceProcessor(trace=trace_path)
    try:
        return trace_source(tp)
    finally:
        tp.close()


SIMULATOR_NOTE = ("iOS Simulator run: numbers come from the Mac's CPU with a warm cache, "
                  "so they compare only with other simulator runs and are never judged "
                  "against budgets")


def _with_stability(m, tp, pkg, platform):
    """Add hangs, JS errors and crash state (stability.py)."""
    from .stability import extract_stability
    m["stability"] = extract_stability(tp, pkg, platform)
    return m


def _apply_source(m, src):
    """Stamp the platform on a result, and take budgets out of a simulator run.

    A simulator runs the app on the Mac's CPU: a launch that would miss its
    budget on a phone passes easily there. Showing that as a pass is wrong
    data shown as right, so a simulator run keeps its measurements but has no
    budgets and no breaches. Ordering violations stay: they are about order,
    not speed."""
    m["platform"] = src.get("platform", "android")
    m["simulator"] = bool(src.get("simulator"))
    m["budgets_asserted"] = not m["simulator"]
    if m["simulator"]:
        m["breaches"] = []
        m["startup"]["budget_ms"] = None
        for st in m["steps"]:
            st["budget_ms"] = None
            st["over_budget"] = False
            st["pct_of_budget"] = None
        m["note"] = "; ".join(x for x in (m.get("note"), SIMULATOR_NOTE) if x)
    return m


def extract(trace_path, *, path_kind="returning_user", app_pkg=None):
    tp = TraceProcessor(trace=trace_path)
    try:
        src = trace_source(tp)
        m = _apply_source(_extract(tp, path_kind, pkg=app_pkg, platform=src["platform"]), src)
        return _with_stability(m, tp, app_pkg, src["platform"])
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
    frames = metrics.get("frames") or {}
    # On the iOS Simulator no frames is the platform, not a failed capture.
    if frames.get("total", 0) == 0 and not metrics.get("simulator"):
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
    from .derive import derive_steps, derive_ios_steps, detect_app

    tp = TraceProcessor(trace=trace_path)
    try:
        src = trace_source(tp)
        platform = src["platform"]
        ios = platform == "ios"
        detected = {} if ios else detect_app(tp)
        pkg = app_pkg or detected.get("pkg")
        instrumented = (catalogue.is_instrumented(pkg, platform) if pkg else False) and not force_derive

        fallback_note = None
        if instrumented:
            m = _extract(tp, path_kind or "returning_user", pkg=pkg, platform=platform)
            # "Instrumented" means the app emits *timed* step: spans. A build
            # that only emits instant step: markers (zero-length milestones)
            # gives nothing to measure: every step is 0ms and startup reads as
            # 0ms, which the dashboard would then show as the fastest launch on
            # record. Fall back to deriving the launch from Android's own slices
            # in that case, and say so.
            if (m["startup"]["time_to_first_camera_frame_ms"] or 0) > 0 and \
                    any((st.get("dur_ms") or 0) > 0 for st in m["steps"]):
                m["app_pkg"] = pkg
                m["derived"] = False
                m["startup_metric"] = "time to first camera frame"
                m["detected_app"] = detected
                return _with_stability(_apply_source(m, src), tp, pkg, platform)
            fallback_note = (m.get("note") or
                             "step: markers present but untimed (instants only)") + \
                (", so startup was derived from iOS launch phases" if ios
                 else ", so startup was derived from Android launch slices")

        d = derive_ios_steps(tp, pkg=pkg) if ios else derive_steps(tp, pkg=pkg)
        target_slices = d.get("target_slices", 0)
        upids = _app_upids(tp, pkg, platform)
        if ios and src["simulator"]:
            # The simulator supports none of Instruments' frame instruments
            # (Hitches, Frame Lifetimes, Core Animation FPS all refuse it).
            frames = _unmeasured_frames("not measured on the iOS Simulator")
        else:
            frames = _frames(tp, upids) if (upids or not pkg) else _unmeasured_frames()
        mem = _memory(tp, upids) if (upids or not pkg) else {}
        # Cold vs warm is classified from what was actually derived rather than
        # from the stdlib's label, which can misfire: a process_start phase only
        # exists when the process was genuinely created for this launch (on
        # iOS, a pre-main phase).
        names = {s["step"] for s in d["steps"]}
        started = {"step:process_start", "step:pre_main", "step:to_first_frame"}
        kind = path_kind or ("cold" if names & started else "warm")
        bud = catalogue.budgets_for(pkg, platform)
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
        # Frame budgets are platform-wide (60fps is 60fps for anyone). Memory and
        # thermal budgets are this project's own product decisions, so they are
        # asserted only against our own app, never a competitor's.
        own = (catalogue.get(pkg, platform) or {}).get("role") == "own"
        asserted = ["slow_frame_pct", "janky_frame_pct"]
        if own:
            asserted += ["peak_rss_mb", "rss_growth_mb", "thermal_drift_pct"]
        for k in asserted:
            b = GLOBAL_BUDGETS[k]
            if not checks[k]:
                continue  # unmeasured, not zero: never a breach, never a pass
            if checks[k] > b:
                breaches.append({"metric": k, "value": checks[k], "budget": b,
                                 "over_by_pct": round((checks[k] - b) / b * 100, 1)})

        return _with_stability(_apply_source({
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
            "own_app": own,
            "note": fallback_note,
        }, src), tp, pkg, platform)
    finally:
        tp.close()


def _app_upids(tp, pkg, platform="android"):
    """Process ids (upid) belonging to the app under test, or [] if unknown.

    Device traces carry every process on the phone. Anything not scoped to the
    app measures the device instead: an unscoped RAM peak was system_server's
    803MB against the app's real 456MB, and the "growth" subtracted one
    process's minimum from a different process's maximum. A relaunch gives the
    same package a second upid, so all of them are returned.
    """
    if not pkg:
        return []
    ids = [r["upid"] for r in _rows(tp, f"""
        select upid from process where name = '{pkg.replace("'", "''")}'""")]
    if ids:
        return ids
    # These markers are SwagTrace's, emitted only by apps the catalogue marks
    # instrumented. For any other package, a marker-emitting process belongs
    # to some other app, so there is nothing to fall back to.
    from . import catalogue
    if not catalogue.is_instrumented(pkg, platform):
        return []
    # A process's name is not always recorded: on a V2514, a capture without the
    # gfx atrace category never named the app's process at all. The app still
    # identifies itself through the markers it emits (screen:/step:/action:
    # via atrace_apps), so the process that owns those is the app.
    #
    # Only processes without an app name of their own qualify: unnamed, or
    # still wearing the name of the zygote they were forked from (run B's app
    # was `zygote64` for its whole life, because the rename event was never
    # captured). A process that carries a different package's name emitted
    # those markers for that package; accepting it reported one app's frames
    # under another's name.
    return [r["upid"] for r in _rows(tp, """
        select distinct coalesce(pt.upid, th.upid) as upid from slice s
        left join process_track pt on s.track_id = pt.id
        left join thread_track tt on s.track_id = tt.id
        left join thread th on tt.utid = th.utid
        join process p on p.upid = coalesce(pt.upid, th.upid)
        where (s.name like 'screen:%' or s.name like 'step:%' or s.name like 'action:%')
          and (p.name is null or p.name like 'zygote%' or p.name like 'usap%'
               or p.name = '<pre-initialized>')""")]


def _unmeasured_frames(note="app process not found in trace"):
    """Frame metrics when they cannot be measured: the app's process is not in
    the trace, or the platform records no frames (the iOS Simulator).

    The alternative -- counting every process's frames -- is what reported a
    device-wide 876MB "peak" and other processes' launch steps as the app's. A
    known app that cannot be located is unmeasured, never the whole device.
    """
    return {"total": 0, "slow": 0, "janky": 0, "slow_pct": None, "janky_pct": None,
            "avg_ms": None, "max_ms": None, "thermal_drift_pct": None,
            "note": note}


def _in(col, ids):
    return f" and {col} in ({','.join(str(int(i)) for i in ids)})" if ids else ""


# Matched by prefix: Android 12+ names the slice `Choreographer#doFrame <vsync>`,
# so an exact match on the bare name counted zero frames on every real device --
# and a frame count of zero then reported 0% slow, which reads as perfect.
DOFRAME = "Choreographer#doFrame%"
# Every name an app frame goes by, matched by prefix: Android's Choreographer
# callback, and the platform-neutral slice the iOS converter writes. Giving iOS
# frames Android's name would mislabel them in the Perfetto UI.
IOS_FRAME = "swagperf.frame%"
FRAME_SLICE_PATTERNS = (DOFRAME, IOS_FRAME)


def frame_like(col="s.name"):
    """SQL predicate matching any app frame slice in `col`."""
    return "(" + " or ".join(f"{col} like '{p}'" for p in FRAME_SLICE_PATTERNS) + ")"


DRIFT_SKIP_NS = 1_000_000_000   # launch + first composition
DRIFT_MIN_FRAMES = 120          # two seconds of sustained 60fps


def _workload_changed(tp):
    """Whether the app moved between screens during the trace.

    Thermal drift compares later frames with earlier ones on the premise that
    the work is the same -- a sustained scan -- so a slowdown can only be heat.
    In a manual session that walks Home -> Store -> Send the frames differ
    because the screens do: one real session read -41% "drift", shown as an
    improvement, purely from spending the second half on lighter screens. With
    more than one screen in the trace, drift is not a thermal signal at all.
    """
    r = _rows(tp, """
        select count(distinct substr(name, 1, instr(name || '#', '#') - 1)) as n
        from slice where name like 'screen:%'""")
    return bool(r and (r[0].get("n") or 0) > 1)


def _frames(tp, upids=None):
    """Frame-pacing metrics. Shared by the instrumented and derived paths."""
    scope = ""
    if upids:
        scope = f""" and s.track_id in (select tt.id from thread_track tt
                     join thread th using(utid) where 1=1{_in('th.upid', upids)})"""
    fr = _rows(tp, f"""
        select count(*) total,
               sum(case when dur > {FRAME_NS} then 1 else 0 end) slow,
               sum(case when dur > {3 * FRAME_NS} then 1 else 0 end) janky,
               cast(avg(dur) as int) avg_dur,
               cast(max(dur) as int) max_dur
        from slice s where {frame_like()}{scope}
    """)
    f = fr[0] if fr else {}
    total = f.get("total") or 0
    frames = {
        "total": total,
        "slow": f.get("slow") or 0,
        "janky": f.get("janky") or 0,
        # No frames counted is "unmeasured", not "perfect". Reporting 0.0% here
        # is what hid the Android 12+ doFrame naming bug for every device run:
        # zero frames read as zero slow frames, which looks like a clean pass.
        "slow_pct": round((f.get("slow") or 0) / total * 100, 2) if total else None,
        "janky_pct": round((f.get("janky") or 0) / total * 100, 2) if total else None,
        # Unmeasured when no frames were counted, for the same reason as above.
        "avg_ms": round(f["avg_dur"] / 1e6, 2) if total else None,
        "max_ms": round(f["max_dur"] / 1e6, 2) if total else None,
    }
    # Thermal drift: second-half mean frame time against the first half. A rising
    # value means the device is throttling, which is a different problem from
    # scattered jank and needs a different fix.
    #
    # The first second after the first frame is excluded. On a cold start it is
    # launch and first composition, whose frames are far heavier than anything
    # sustained -- comparing halves then measured startup, not heat: a PhonePe
    # cold start read -98.55% "drift". Fewer than DRIFT_MIN_FRAMES sustained
    # frames is too short a window to see throttling at all, so drift is
    # reported as unmeasured (None) rather than as a number.
    halves = _rows(tp, f"""
        with a as (
          select s.ts, s.dur from slice s where {frame_like()}{scope}),
        f as (
          select dur, row_number() over (order by ts) rn, count(*) over () n
          from a where ts >= (select min(ts) from a) + {DRIFT_SKIP_NS})
        select avg(case when rn <= n/2 then dur end) first_half,
               avg(case when rn >  n/2 then dur end) second_half,
               max(n) n from f
    """)
    drift = None
    if halves and (halves[0].get("n") or 0) >= DRIFT_MIN_FRAMES and halves[0].get("first_half") \
            and not _workload_changed(tp):
        a, b = halves[0]["first_half"], halves[0]["second_half"]
        drift = round((b - a) / a * 100, 2)
    frames["thermal_drift_pct"] = drift
    return frames


def _memory(tp, upids=None):
    """RAM usage (resident set size) and, where present, the Hermes heap.

    `mem.rss` is the counter this project's own captures emit. A trace from
    `process_stats` instead exposes per-process resident size, so that is used as a
    fallback -- otherwise memory would silently read as zero on any trace not
    produced by our own capture config.
    """
    mem = {}
    mb = 1024 * 1024
    for key, track in (("rss", "mem.rss"), ("hermes_heap", "mem.hermes_heap")):
        r = None
        if upids:
            r = _rows(tp, f"""
                select max(c.value) mx, min(c.value) mn
                from counter c join process_counter_track t on c.track_id=t.id
                where t.name = '{track}'{_in('t.upid', upids)}
            """)
        if not (r and r[0].get("mx") is not None):
            # No per-process track for the app (a synthetic or app-emitted
            # global counter): only then read a track not owned by any process.
            r = _rows(tp, f"""
                select max(c.value) mx, min(c.value) mn
                from counter c join counter_track t on c.track_id=t.id
                where t.name = '{track}'
                  and t.id not in (select id from process_counter_track)
            """)
        if r and r[0].get("mx") is not None:
            mem[key] = {"peak_mb": round(r[0]["mx"] / mb, 1),
                        "min_mb": round(r[0]["mn"] / mb, 1),
                        "growth_mb": round((r[0]["mx"] - r[0]["mn"]) / mb, 1)}
    if "rss" not in mem:
        try:
            tp.query("INCLUDE PERFETTO MODULE android.memory.process;")
            r = _rows(tp, f"""
                select max(rss_and_swap) mx, min(rss_and_swap) mn
                from memory_rss_and_swap_per_process where 1=1{_in('upid', upids)}""")
            if r and r[0].get("mx") is not None:
                mem["rss"] = {"peak_mb": round(r[0]["mx"] / mb, 1),
                              "min_mb": round(r[0]["mn"] / mb, 1),
                              "growth_mb": round((r[0]["mx"] - r[0]["mn"]) / mb, 1),
                              "source": "process_stats"}
        except Exception:
            pass
    return mem


def _extract(tp, path_kind, pkg=None, platform="android"):
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
    # Every critical-path step must be present. With one missing, the latest end
    # among the rest is not the time to first camera frame, just the end of
    # whatever happened to be recorded -- a shorter path read as a faster one.
    # The iOS Simulator has no camera, so its camera steps never appear.
    #
    # The ordering check still uses the end of the path that *was* recorded:
    # deferred work that started before it started before any camera frame.
    missing = [c for c in crit if c not in {s["step"] for s in crit_steps}]
    crit_end = round(max((s["start_ms"] + s["dur_ms"] for s in crit_steps), default=0.0), 2)
    note = None
    if missing and crit_steps:
        ttff = None
        note = f"critical path incomplete (no {', '.join(missing)})"
    else:
        ttff = crit_end

    # --- deferred-work violation: the architecture's ordering constraint ----
    violations = []
    if path_kind == "returning_user":
        for s in step_metrics:
            # 1ms tolerance: a deferred step legitimately starts *at* the first
            # frame boundary, and float rounding can place it a hair before.
            if s["step"] in DEFERRED_STEPS and s["start_ms"] < crit_end - ORDERING_TOLERANCE_MS:
                violations.append({
                    "step": s["step"],
                    "started_at_ms": s["start_ms"],
                    "first_frame_ms": crit_end,
                    "detail": f"{s['step']} began {round(crit_end - s['start_ms'], 2)}ms "
                              "before first usable camera frame",
                })

    upids = _app_upids(tp, pkg, platform)
    frames = _frames(tp, upids) if (upids or not pkg) else _unmeasured_frames()
    mem = _memory(tp, upids) if (upids or not pkg) else {}

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
        for k, v in checks.items() if v is not None and v > GLOBAL_BUDGETS[k]
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
        "note": note,
    }


# ------------------------------------------------------------ tracing coverage

# Scheduler events arrive many times a second on every CPU, so a device trace
# whose sched_switch events stop well before it ends -- or never start -- had
# its kernel tracing taken away. Flashlight does exactly that when it starts on
# the same device, and Perfetto says nothing: the trace pulls and parses, and
# its first minutes can even look normal. A capture like that must not become
# a run. Two seconds is far above the gap between two scheduler events.
TRACING_TAIL_S = 2.0


def tracing_problem(trace_start_ns, trace_end_ns, sched_events, last_sched_ns):
    """Why kernel tracing did not cover the trace, or None when it did."""
    if not sched_events:
        return ("kernel tracing recorded nothing: the trace has no scheduler events. "
                "Another tool using the kernel trace buffer, such as Flashlight, was "
                "probably running on the device.")
    tail = (trace_end_ns - last_sched_ns) / 1e9
    if tail > TRACING_TAIL_S:
        return (f"kernel tracing stopped {tail:.1f}s before the trace ended, so scheduler "
                "events, app slices and markers after that point are missing. Another "
                "tool, such as Flashlight starting during the capture, switched it off.")
    return None


def tracing_lost(trace_path):
    """`tracing_problem` for a trace file. For device captures only: a
    synthetic trace has no reason to carry scheduler events."""
    tp = TraceProcessor(trace=trace_path)
    try:
        b = _rows(tp, "select start_ts, end_ts from trace_bounds")[0]
        s = _rows(tp, "select count(*) n, max(ts) last from sched_slice")[0]
    finally:
        tp.close()
    return tracing_problem(b["start_ts"], b["end_ts"], s["n"], s["last"])


# ------------------------------------------------------------ trace metadata

def parse_fingerprint(fp):
    """`brand/product/device:release/build_id/incremental:type/tags`."""
    m = re.match(r"([^/]+)/([^/]+)/([^:]+):([^/]+)/([^/]+)/([^:]+):([^/]+)/", fp or "")
    if not m:
        return {}
    brand, product, codename, release, build_id, _incr, build_type = m.groups()
    return {"brand": brand, "product": product, "codename": codename,
            "android_release": release, "build_id": build_id, "build_type": build_type}


def trace_metadata(trace_path, app_pkg=None):
    """What the trace itself says about where it was recorded: the device's
    build, SoC and kernel, the Perfetto version, and the trace's own size and
    length. When the trace carries the package list, the app's version code
    too. This is how a run recorded before capture-time metadata existed
    still gets its device details."""
    tp = TraceProcessor(trace=trace_path)
    try:
        meta = {r.name: (r.str_value if r.str_value is not None else r.int_value)
                for r in tp.query("select name, str_value, int_value from metadata")}
        src = trace_source(tp)
        app = {}
        if app_pkg and src["platform"] == "android":
            try:
                row = next(iter(tp.query(
                    "select version_code, debuggable from package_list "
                    f"where package_name = '{app_pkg.replace(chr(39), '')}' limit 1")), None)
                if row is not None:
                    app = {"package": app_pkg, "version_code": row.version_code,
                           "debuggable": bool(row.debuggable)}
            except Exception:
                pass  # older trace processors have no package_list table
    finally:
        tp.close()
    fp = meta.get("android_build_fingerprint")
    device = {k: v for k, v in {
        "manufacturer": meta.get("android_device_manufacturer"),
        **parse_fingerprint(fp),
        "sdk": meta.get("android_sdk_version"),
        "soc": meta.get("android_soc_model"),
        "fingerprint": fp,
        "kernel": meta.get("system_release"),
        "abi": meta.get("system_machine"),
    }.items() if v not in (None, "")}
    started, stopped = meta.get("tracing_started_ns"), meta.get("tracing_disabled_ns")
    trace = {k: v for k, v in {
        "perfetto_version": (meta.get("tracing_service_version") or "").replace("Perfetto", "").replace("(N/A)", "").strip() or None,
        "size_mb": round(meta["trace_size_bytes"] / 1e6, 1) if meta.get("trace_size_bytes") else None,
        "duration_s": round((stopped - started) / 1e9, 1) if started and stopped and stopped > started else None,
        "utc_offset_min": meta.get("timezone_off_mins"),
        "uuid": meta.get("trace_uuid"),
    }.items() if v is not None}
    if src["platform"] == "ios":
        # A converted iOS trace has none of Android's metadata keys; what it
        # knows about the device is in its provenance marker.
        device = {k: v for k, v in {
            "platform": "ios", "model": src.get("device"), "os_version": src.get("os"),
            "simulator": src.get("simulator")}.items() if v not in (None, "")}
        if src.get("xctrace"):
            trace["xctrace_version"] = src["xctrace"]
    out = {"device": device, "trace": trace, "source": "trace"}
    if app:
        out["app"] = app
    return out
