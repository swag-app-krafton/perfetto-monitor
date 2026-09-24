"""Derive steps from an *uninstrumented* trace.

An instrumented app emits `step:` markers and `extract.py` reads them directly.
Any other app does not, so this module synthesises the same shape from the slice
names every Android app produces anyway. That makes the tool usable on a
competitor's binary, where instrumentation is impossible by definition.

Two sources, in order:

1. Perfetto's own `android.startup.startups` stdlib module, for the package under
   test and the cold/warm/hot classification. These are maintained upstream and
   are more reliable than anything hand-rolled.
2. An explicit phase model over well-known slice names, for the durations. This
   is deliberately not delegated: a derived duration has to be attributable to
   the slices that produced it, and a black-box metric is not.

Derived steps carry no budgets. A budget is a product decision, and asserting one
for someone else's app would be inventing a number. Regression detection against
a trailing baseline or a pinned benchmark works without them.
"""

# Phase model: derived step -> slice names that constitute it, in launch order.
# Matching is case-insensitive; a trailing % means prefix match.
PHASES = [
    ("step:process_start", ["Start proc:%", "ZygoteInit%", "PostFork%",
                            "Zygote.fork", "AppZygote%"]),
    ("step:bind_application", ["bindApplication", "ActivityThread.handleBindApplication",
                              "Application.onCreate", "installProvider%",
                              "makeApplication", "LoadedPackage::Load"]),
    ("step:activity_create", ["activityStart", "performCreate", "performLaunchActivity",
                              "activityCreate", "onCreate", "launchingActivity%",
                              "activityStarting", "%-activityStarting"]),
    ("step:layout_inflate", ["inflate", "setContentView%", "ComposeView.inflate",
                             "Recomposer.firstFrame"]),
    ("step:activity_resume", ["activityResume", "performResume", "onResume"]),
    ("step:first_frame", ["Choreographer#doFrame"]),          # first occurrence only
    ("step:fully_drawn", ["reportFullyDrawn%"]),
]

# Slices that explain ART/dex cost inside bind_application, surfaced as children.
ART_SLICES = ["OpenDexFilesFromOat", "VerifyClass", "JIT compiling%",
              "Compiling%", "ResolveClass%"]

FIRST_FRAME_SLICE = "Choreographer#doFrame"
FRAME_SLICES = ["Choreographer#doFrame", "DrawFrame"]

# iOS launch phases, as convert_ios.py writes them (`swagperf.launch:<phase>`):
# dyld's pre-main, then main() to Apple's first-frame signpost, then to the
# app becoming responsive. `to_first_frame` stands in for the first two when
# dyld's split is missing. Startup time ends with the first frame.
IOS_PHASES = [
    ("step:pre_main", "pre_main"),
    ("step:main_to_first_frame", "main_to_first_frame"),
    ("step:to_first_frame", "to_first_frame"),
    ("step:first_frame_to_responsive", "first_frame_to_responsive"),
]
IOS_TTID_ENDS = {"step:main_to_first_frame", "step:to_first_frame"}


def _like(names):
    """SQL OR-list matching a phase's slice names, prefix-aware."""
    parts = []
    for n in names:
        if n.endswith("%"):
            parts.append(f"s.name like '{n}'")
        else:
            parts.append(f"lower(s.name) = lower('{n}')")
    return "(" + " or ".join(parts) + ")"


def detect_app(tp):
    """Package under test and startup classification, via the Perfetto stdlib.

    Returns {} when the trace has no recognisable launch, which is normal for a
    trace captured while the app was already running.
    """
    try:
        tp.query("INCLUDE PERFETTO MODULE android.startup.startups;")
        rows = list(tp.query("""
            select package, startup_type, ts, ts_end, dur
            from android_startups order by ts limit 1"""))
        if rows:
            r = rows[0]
            return {"pkg": r.package, "startup_type": r.startup_type,
                    "startup_ts": r.ts, "startup_dur_ns": r.dur, "source": "stdlib"}
    except Exception:
        pass
    # Fallback: the atrace launch slice, which is what the stdlib reads anyway.
    try:
        rows = list(tp.query("""
            select name, ts, dur from slice
            where name like 'launching:%' order by ts limit 1"""))
        if rows:
            return {"pkg": rows[0].name.split(":", 1)[1].strip(),
                    "startup_type": None, "startup_ts": rows[0].ts,
                    "startup_dur_ns": rows[0].dur, "source": "launching_slice"}
    except Exception:
        pass
    return {}


def derive_steps(tp, *, pkg=None):
    """Build `step:`-shaped rows from ordinary Android slices.

    Each phase becomes at most one step, spanning from the earliest to the latest
    matching slice within the launch window, with the matching slices as children.
    Phases with no matching slices are omitted rather than reported as zero, so a
    missing phase is visibly missing instead of silently fast.
    """
    app = detect_app(tp)
    pkg = pkg or app.get("pkg")

    # Phase slices are scoped to the target package's OWN process. A busy device
    # runs several launches at once -- one real capture had bindApplication
    # present simultaneously for the target app (255ms), com.jio.myjio (984ms)
    # and a Google process (243ms). Matching by slice name alone across all
    # processes would silently measure whichever app happened to be slowest.
    #
    # The process is found by the same resolver extract.py uses, which falls
    # back to "whoever emitted the app's own markers" when the trace never
    # recorded the process's name. Matching by name alone lost the app on a
    # capture without the gfx category and then read phases from every process:
    # a 334ms layout_inflate that belonged to some other app.
    from .extract import _app_upids
    proc_filter = ""
    target_slices = 0
    upids = _app_upids(tp, pkg) if pkg else []
    if upids:
        ids = ",".join(str(int(u)) for u in upids)
        rows = list(tp.query(f"""
            select count(*) c from slice s
            join thread_track tt on s.track_id = tt.id
            join thread th on tt.utid = th.utid
            where th.upid in ({ids})"""))
        target_slices = (rows[0].c or 0) if rows else 0
        if target_slices > 0:
            proc_filter = f"""
                and s.track_id in (
                  select tt.id from thread_track tt
                  join thread th on tt.utid = th.utid
                  where th.upid in ({ids}))"""

    # The launch window: prefer the platform's own `launching:` async slice,
    # which IS the launch by the framework's definition. Only fall back to
    # "trace start until the first frame" when that slice is absent -- and
    # never collapse the window to zero width, which an earlier version did
    # whenever Choreographer#doFrame was missing (some vendor builds do not
    # emit it), silently yielding no steps at all.
    win_start = win_end = None
    lq = f"where name like 'launching: {pkg}%'" if pkg else "where name like 'launching:%'"
    rows = list(tp.query(f"select ts, dur from slice {lq} order by ts limit 1"))
    if rows and rows[0].dur and rows[0].dur > 0:
        win_start, win_end = rows[0].ts, rows[0].ts + rows[0].dur

    if win_start is None:
        # Prefix match: Android 12+ suffixes doFrame with a vsync id.
        frame_like = " or ".join(f"name like '{n}%'" for n in FRAME_SLICES)
        first_frame = list(tp.query(f"""
            select ts, dur from slice where {frame_like} order by ts limit 1"""))
        ff_end = (first_frame[0].ts + max(first_frame[0].dur or 0, 0)) if first_frame else None
        pre_frame = [pat for nm, pats in PHASES
                     if nm not in ("step:first_frame", "step:fully_drawn")
                     for pat in pats]
        cands = []
        rows = list(tp.query(f"select min(s.ts) a from slice s where {_like(pre_frame)}"))
        if rows and rows[0].a is not None:
            cands.append(rows[0].a)
        if not cands:
            rows = list(tp.query("select min(ts) a from slice"))
            cands.append(rows[0].a if rows and rows[0].a is not None else 0)
        win_start = min(cands)
        # Without a frame marker, bound the window by the latest phase slice
        # rather than by win_start itself.
        rows = list(tp.query(f"select max(s.ts + s.dur) b from slice s where {_like(pre_frame)}"))
        latest = rows[0].b if rows and rows[0].b is not None else None
        win_end = ff_end if ff_end is not None else (latest or win_start)

    steps = []
    for name, patterns in PHASES:
        first_only = name == "step:first_frame"
        q = f"""
            select s.name as nm, s.ts as ts, s.dur as dur, s.id as sid
            from slice s
            where {_like(patterns)} and s.ts >= {win_start}
              {'' if first_only else f'and s.ts <= {max(win_end, win_start)}'}
              {proc_filter}
            order by s.ts {'limit 1' if first_only else ''}"""
        rows = [r for r in tp.query(q)]
        rows = [r for r in rows if (r.dur or 0) >= 0]
        if not rows:
            continue
        start = min(r.ts for r in rows)
        end = max(r.ts + (r.dur or 0) for r in rows)
        dur_ms = round((end - start) / 1e6, 2)
        if dur_ms <= 0:
            continue
        # Children: the matching slices themselves, plus ART work where relevant.
        kids = {}
        for r in rows:
            kids[r.nm] = kids.get(r.nm, 0) + (r.dur or 0)
        if name == "step:bind_application":
            for r in tp.query(f"""
                select s.name nm, sum(s.dur) d from slice s
                where {_like(ART_SLICES)} and s.ts >= {start} and s.ts <= {end}
                group by 1"""):
                if r.d:
                    kids[r.nm] = r.d
        children = sorted(
            ({"name": k, "dur_ms": round(v / 1e6, 2), "count": None,
              "pct_of_step": round(v / (end - start) * 100, 1) if end > start else None}
             for k, v in kids.items() if v > 0),
            key=lambda c: -c["dur_ms"])
        steps.append({"step": name, "dur_ms": dur_ms,
                      "start_ms": round(start / 1e6, 2),
                      "track": "derived", "budget_ms": None,
                      "over_budget": False, "pct_of_budget": None,
                      "children": children, "derived": True})

    steps.sort(key=lambda s: s["start_ms"])

    # Startup time is measured to the end of the last observed startup phase,
    # not to the end of the platform's `launching:` slice. That slice stays open
    # until the framework closes it, which for an app that never calls
    # reportFullyDrawn() can be a fixed timeout: two real captures both landed
    # at almost exactly 3000ms, while an app that does report fully-drawn
    # measured 640ms. Using the slice width would have reported the timeout as
    # though it were the app's startup cost.
    ttid_ms = None
    if steps:
        last_end_ms = max(s["start_ms"] + s["dur_ms"] for s in steps)
        ttid_ms = round(last_end_ms - win_start / 1e6, 2)
    if ttid_ms is None and win_end > win_start:
        ttid_ms = round((win_end - win_start) / 1e6, 2)
    if ttid_ms is not None and ttid_ms <= 0:
        ttid_ms = None
    return {"steps": steps, "app": app,
            "ttid_ms": ttid_ms,          # time to initial display
            # How many slices the target package's own process contributed. Zero
            # means the capture never observed the app at all, and any numbers
            # derived here came from unrelated processes -- the caller must treat
            # that as a failed capture, not as data.
            "target_slices": target_slices,
            "window": {"start_ms": round(win_start / 1e6, 2),
                       "end_ms": round(win_end / 1e6, 2)}}


def derive_ios_steps(tp, *, pkg=None):
    """The same shape as derive_steps, from an iOS trace's launch phases.

    Each phase is one `swagperf.launch:` slice on the Launch track; its
    children are the dyld intervals nested inside it (static initializers by
    library, image mapping, fixups), summed by name. Startup time (TTID) is
    process start to the first frame on screen.
    """
    from .convert_ios import LAUNCH_PREFIX
    from .extract import _app_upids
    upids = _app_upids(tp, pkg) if pkg else []
    target_slices = 0
    if upids:
        ids = ",".join(str(int(u)) for u in upids)
        rows = list(tp.query(f"""
            select count(*) c from slice s
            left join thread_track tt on s.track_id = tt.id
            left join thread th on tt.utid = th.utid
            left join process_track pt on s.track_id = pt.id
            where coalesce(th.upid, pt.upid) in ({ids})
              and s.name not like 'swagperf.source:%'
              and s.name != 'swagperf.recording_end'"""))
        target_slices = (rows[0].c or 0) if rows else 0

    phases = {r.nm: r for r in tp.query(f"""
        select s.id as sid, s.name as nm, s.ts as ts, s.dur as dur, s.track_id as tid
        from slice s where s.name like '{LAUNCH_PREFIX}%' and s.depth = 0""")}
    steps = []
    for step, phase in IOS_PHASES:
        r = phases.get(LAUNCH_PREFIX + phase)
        if r is None or (r.dur or 0) <= 0:
            continue
        kids = {}
        for k in tp.query(f"""
                select s.name as nm, sum(s.dur) as d, count(*) as n from slice s
                where s.parent_id = {int(r.sid)} group by 1"""):
            kids[k.nm] = (k.d or 0, k.n)
        children = sorted(
            ({"name": k, "dur_ms": round(d / 1e6, 2), "count": n,
              "pct_of_step": round(d / r.dur * 100, 1)}
             for k, (d, n) in kids.items() if d > 0),
            key=lambda c: -c["dur_ms"])
        steps.append({"step": step, "dur_ms": round(r.dur / 1e6, 2),
                      "start_ms": round(r.ts / 1e6, 2),
                      "track": "derived", "budget_ms": None,
                      "over_budget": False, "pct_of_budget": None,
                      "children": children, "derived": True})
    steps.sort(key=lambda s: s["start_ms"])

    ttid_ms = None
    win = {"start_ms": 0.0, "end_ms": 0.0}
    if steps:
        start = steps[0]["start_ms"]
        ends = [s["start_ms"] + s["dur_ms"] for s in steps if s["step"] in IOS_TTID_ENDS]
        if ends:
            ttid_ms = round(max(ends) - start, 2)
        win = {"start_ms": start, "end_ms": round(max(s["start_ms"] + s["dur_ms"] for s in steps), 2)}
    return {"steps": steps,
            "app": {"pkg": pkg, "startup_type": "cold" if any(
                s["step"] in ("step:pre_main", "step:to_first_frame") for s in steps) else None,
                    "source": "ios_launch"},
            "ttid_ms": ttid_ms, "target_slices": target_slices, "window": win}
