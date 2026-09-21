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
                              "Application.onCreate", "installProvider%"]),
    ("step:activity_create", ["activityStart", "performCreate", "performLaunchActivity",
                              "activityCreate", "onCreate"]),
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

    # The launch window is computed here rather than taken from the stdlib. The
    # stdlib's own window is derived for its metric definitions and can begin
    # after the earliest launch work (it classified a synthetic cold start as
    # "hot" and started 138ms late), which would silently drop whole phases.
    # Identity comes from the stdlib; the window does not.
    first_frame = list(tp.query(f"""
        select ts, dur from slice
        where name = '{FIRST_FRAME_SLICE}' order by ts limit 1"""))
    ff_end = (first_frame[0].ts + max(first_frame[0].dur or 0, 0)) if first_frame else None

    # Start at the earliest pre-frame launch slice, or the atrace launch slice.
    pre_frame = [pat for nm, pats in PHASES
                 if nm not in ("step:first_frame", "step:fully_drawn")
                 for pat in pats]
    cands = []
    rows = list(tp.query(f"select min(s.ts) a from slice s where {_like(pre_frame)}"))
    if rows and rows[0].a is not None:
        cands.append(rows[0].a)
    rows = list(tp.query("select min(ts) a from slice where name like 'launching:%'"))
    if rows and rows[0].a is not None:
        cands.append(rows[0].a)
    if not cands:
        rows = list(tp.query("select min(ts) a from slice"))
        cands.append(rows[0].a if rows and rows[0].a is not None else 0)
    win_start = min(cands)
    win_end = ff_end if ff_end is not None else win_start

    steps = []
    for name, patterns in PHASES:
        first_only = name == "step:first_frame"
        q = f"""
            select s.name as nm, s.ts as ts, s.dur as dur, s.id as sid
            from slice s
            where {_like(patterns)} and s.ts >= {win_start}
              {'' if first_only else f'and s.ts <= {max(win_end, win_start)}'}
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
    ttid_ms = round((win_end - win_start) / 1e6, 2) if ff_end is not None else None
    return {"steps": steps, "app": app,
            "ttid_ms": ttid_ms,          # time to initial display
            "window": {"start_ms": round(win_start / 1e6, 2),
                       "end_ms": round(win_end / 1e6, 2)}}
