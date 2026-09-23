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

# The app tags each screen marker with what renders it -- `screen:Home#compose`,
# `screen:Onboarding.otp#rn`. This app is a hybrid, so "is the React Native
# screen slower than the native ones?" is the first question asked of a profile,
# and without the tag answering it means reading the app source.
KIND_SEPARATOR = "#"

# A sub-screen is a step inside a route that is one screen natively but several
# to the user: `Onboarding.otp` is a step of `Onboarding`.
SUBSCREEN_SEPARATOR = "."

KIND_LABELS = {"compose": "Compose", "rn": "React Native",
               "native_view": "Native view", "unknown": "Unknown"}


def parse_route(raw):
    """Split a marker's route into (route, parent, step, kind).

    Tolerates an untagged name so a trace from an older build still parses:
    the kind is then unknown rather than the whole visit being dropped.
    """
    route, sep, kind = raw.partition(KIND_SEPARATOR)
    kind = kind if sep else "unknown"
    parent, sub_sep, step = route.partition(SUBSCREEN_SEPARATOR)
    return {
        "route": route,
        "parent": parent if sub_sep else None,
        "step": step if sub_sep else None,
        "kind": kind,
        "kind_label": KIND_LABELS.get(kind, kind),
    }


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
    # A screen that is still on display when tracing stops is an *unfinished*
    # slice: Perfetto stores dur = -1 for it, because the closing event never
    # arrived. That is the normal shape of the last visit in a manual session
    # -- and, since nothing closes the slice when the app is backgrounded, of
    # every session that ends with the app open. Filtering on dur > 0 therefore
    # discarded the one visit the user actually cared about and reported zero.
    # Clamp those to the end of the trace instead, and mark them, so the visit
    # is measured over the window it was genuinely on screen.
    trace_end = _rows(tp, "select max(ts + max(dur, 0)) as e from slice")
    end_ts = (trace_end[0].get("e") if trace_end else None) or 0

    # Resolve the process that owns each screen slice up front. Screen visits
    # are *async* slices, so they sit on a process_track -- not the thread_track
    # a synchronous slice would use. Looking the owner up only through
    # thread_track therefore found nothing and every CPU figure came back 0.0.
    # Cover both shapes so the attribution works whichever the app emitted.
    visits = _rows(tp, f"""
        select s.id as sid, s.name as nm, s.ts as ts, s.dur as dur,
               coalesce(pt.upid, th.upid) as upid
        from slice s
        left join process_track pt on s.track_id = pt.id
        left join thread_track tt on s.track_id = tt.id
        left join thread th on tt.utid = th.utid
        where s.name like '{SCREEN_PREFIX}%' and s.dur != 0
        order by s.ts
    """)
    if not visits:
        return []

    out = []
    for v in visits:
        meta = parse_route(v["nm"][len(SCREEN_PREFIX):])
        route = meta["route"]
        start = v["ts"]
        # dur < 0 means the slice never closed; treat the trace end as its end.
        open_ended = (v["dur"] or 0) < 0
        end = end_ts if open_ended else start + v["dur"]
        if end <= start:
            # Nothing to attribute: the slice opened at or after the last event
            # we have, so any window we invented would be noise.
            continue
        dur = end - start

        # CPU time actually scheduled during the visit, across all threads of
        # whichever process owns the app. Clipped to the visit window so a
        # thread that spans the boundary is not double-counted into it.
        upid = v.get("upid")
        cpu_ms = None
        if upid is not None:
            cpu = _rows(tp, f"""
                select sum(min(ss.ts + ss.dur, {end}) - max(ss.ts, {start})) as cpu_ns
                from sched_slice ss
                where ss.ts < {end} and (ss.ts + ss.dur) > {start}
                  and ss.utid in (select utid from thread where upid = {upid})
            """)
            cpu_ms = round((cpu[0]["cpu_ns"] or 0) / 1e6, 2) if cpu else None

        # RAM across the visit. A screen that leaves RAM usage higher than it
        # found it is the orphaned-surface signature the shell architecture names.
        #
        # Scoped to the owning process, and to the `mem.rss` counter exactly.
        # Matching `mem.rss%` across all processes summed init, ueventd and
        # every unrelated app on the device into a ~1.3GB "peak" for one
        # screen, and the `mem.rss.*` breakdown tracks double-count `mem.rss`.
        # Prefer the owning process's own counter track. Device traces emit
        # mem.rss per process; a trace that carries only a single global
        # mem.rss track (as synthetic fixtures do) has no process to scope to,
        # and there the global track *is* the app's, so fall back to it rather
        # than reporting no RAM at all.
        mem = []
        if upid is not None:
            mem = _rows(tp, f"""
                select min(c.value) as lo, max(c.value) as hi
                from counter c
                join process_counter_track t on c.track_id = t.id
                where t.name = 'mem.rss' and t.upid = {upid}
                  and c.ts >= {start} and c.ts <= {end}
            """)
        if not (mem and mem[0].get("hi") is not None):
            mem = _rows(tp, f"""
                select min(c.value) as lo, max(c.value) as hi
                from counter c
                join counter_track t on c.track_id = t.id
                where t.name = 'mem.rss' and c.ts >= {start} and c.ts <= {end}
                  and t.id not in (select id from process_counter_track)
            """)
        mb = 1024 * 1024
        rss = {}
        if mem and mem[0].get("hi") is not None:
            rss = {"min_mb": round(mem[0]["lo"] / mb, 1),
                   "peak_mb": round(mem[0]["hi"] / mb, 1),
                   "delta_mb": round((mem[0]["hi"] - mem[0]["lo"]) / mb, 1)}

        # Frames belong to the app's own main thread; counting every process's
        # doFrame in the window would credit this screen with the launcher's
        # and every background app's rendering.
        frames = _rows(tp, f"""
            select count(*) as n,
                   sum(case when s.dur > 16666667 then 1 else 0 end) as slow
            from slice s
            join thread_track tt on s.track_id = tt.id
            join thread th on tt.utid = th.utid
            where s.name like 'Choreographer#doFrame%'
              and s.ts >= {start} and s.ts <= {end}
              {f"and th.upid = {upid}" if upid is not None else ""}
        """)
        f = frames[0] if frames else {}
        n = f.get("n") or 0

        out.append({
            "route": route,
            # What rendered it, and its place in the screen hierarchy.
            "kind": meta["kind"],
            "kind_label": meta["kind_label"],
            "parent": meta["parent"],
            "step": meta["step"],
            "start_ms": round(start / 1e6, 2),
            "duration_ms": round(dur / 1e6, 2),
            # An open-ended visit was still on screen when tracing stopped, so
            # its duration is a lower bound. Callers that rank screens by cost
            # need to know the difference between "took this long" and "had not
            # finished yet".
            "open_ended": open_ended,
            "cpu_ms": cpu_ms,
            # CPU as a share of wall time says whether the screen was busy or
            # just on screen -- the number an engineer actually acts on.
            "cpu_pct_of_wall": (round(cpu_ms / (dur / 1e6) * 100, 1)
                                if cpu_ms and dur else None),
            "rss": rss or None,
            "frames": n,
            "slow_frames": f.get("slow") or 0,
            "slow_frame_pct": round((f.get("slow") or 0) / n * 100, 2) if n else None,
        })
    return out


def screen_summary(visits, include_substeps=True):
    """Aggregate repeated visits to the same screen.

    A route is usually visited more than once in a session, and the interesting
    figure is the total cost of being on that screen plus the worst single
    visit, not an average that hides a single bad one.

    Sub-screens are summarised as their own rows, never folded into the parent.
    A sub-screen slice is open *inside* its parent's slice, so adding the two
    together would count the same milliseconds twice and report an onboarding
    flow as costing about double its real wall time. Callers that want only
    top-level routes pass include_substeps=False.
    """
    by = {}
    for v in visits:
        if not include_substeps and v.get("step"):
            continue
        s = by.setdefault(v["route"], {
            "route": v["route"], "visits": 0, "total_ms": 0.0, "total_cpu_ms": 0.0,
            "worst_ms": 0.0, "frames": 0, "slow_frames": 0, "peak_rss_mb": None,
            "max_rss_delta_mb": None,
            # Carried through so the summary can be grouped or coloured by what
            # renders each screen, which is the hybrid comparison worth making.
            "kind": v.get("kind", "unknown"),
            "kind_label": v.get("kind_label", "Unknown"),
            "parent": v.get("parent"), "step": v.get("step"),
            # Every visit kept, in order, so the dashboard can draw one bar per
            # visit and say whether any single one deviates from the rest. A
            # total alone cannot: twelve even visits and eleven cheap ones plus
            # a pathological twelfth sum to the same number.
            "visit_list": []})
        s["visit_list"].append({
            "index": len(s["visit_list"]) + 1,
            "start_ms": v.get("start_ms"),
            "duration_ms": v["duration_ms"],
            "cpu_ms": v.get("cpu_ms"),
            "cpu_pct_of_wall": v.get("cpu_pct_of_wall"),
            "peak_rss_mb": (v.get("rss") or {}).get("peak_mb"),
            "rss_delta_mb": (v.get("rss") or {}).get("delta_mb"),
            "slow_frame_pct": v.get("slow_frame_pct"),
            "open_ended": v.get("open_ended", False),
            # The same screen can be visited at different depths, and that is
            # exactly when its cost changes, so depth belongs on the visit
            # rather than only on the route.
            "depth": v.get("depth", 1),
            "stack": v.get("stack") or [],
            "beneath": v.get("beneath") or [],
        })
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
        s["stats"] = _visit_stats(s["visit_list"])
        # A route is not always visited at one depth. Report the range rather
        # than an average, because "sometimes root, sometimes three deep" is the
        # interesting case and a mean of 2 would hide it.
        depths = sorted({v.get("depth", 1) for v in s["visit_list"]})
        s["depths"] = depths
        s["depth_label"] = (str(depths[0]) if len(depths) == 1
                            else f"{depths[0]}\u2013{depths[-1]}") if depths else None
    return sorted(by.values(), key=lambda s: -s["total_cpu_ms"])


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _stdev(xs, mean):
    """Population standard deviation; None when a spread is meaningless.

    A single visit has no spread, and reporting 0 would read as "perfectly
    consistent" rather than "nothing to compare against".
    """
    if mean is None or len(xs) < 2:
        return None
    return (sum((x - mean) ** 2 for x in xs) / len(xs)) ** 0.5


def _visit_stats(visits):
    """Per-metric mean and spread across a screen's visits, plus outlier flags.

    The point of keeping visits separate is to answer "is this screen
    consistently expensive, or was one visit pathological?". That needs a centre
    to compare against and a sense of how tightly the visits cluster, so each
    visit is marked as an outlier when it sits more than two standard deviations
    from the mean. Two is the conventional threshold and is deliberately
    unsubtle: this flags a visit worth opening, it does not claim significance.
    """
    out = {}
    for key in ("duration_ms", "cpu_ms", "cpu_pct_of_wall", "peak_rss_mb",
                "rss_delta_mb"):
        xs = [v[key] for v in visits if v.get(key) is not None]
        mean = _mean(xs)
        sd = _stdev(xs, mean)
        out[key] = {
            "mean": round(mean, 2) if mean is not None else None,
            "stdev": round(sd, 2) if sd is not None else None,
            "min": round(min(xs), 2) if xs else None,
            "max": round(max(xs), 2) if xs else None,
        }
        # Mark the visits themselves so the client does not repeat this maths.
        for v in visits:
            val = v.get(key)
            v.setdefault("outlier", {})[key] = bool(
                val is not None and sd and sd > 0 and abs(val - mean) > 2 * sd)
    return out


INSTANT_NS = 100_000  # 0.1ms


def actions(tp):
    """User actions, aggregated by name.

    Instant markers have no duration, so count is the signal for those; spans
    additionally carry timing. Both shapes are reported through one table so a
    caller does not need to know which the app emitted.
    """
    # On Android an instant is emitted as an async begin/end pair a few
    # microseconds apart, so it arrives with a tiny non-zero duration. Anything
    # under INSTANT_NS is treated as an instant: reporting it as "0.01 ms mean"
    # presented a marker's bookkeeping as the action's cost.
    rows = _rows(tp, f"""
        select name as nm, count(*) as n,
               sum(case when dur > {INSTANT_NS} then dur else 0 end) as total_dur,
               max(case when dur > {INSTANT_NS} then dur else 0 end) as max_dur
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


def screen_stack(tp):
    """Reconstruct the navigation stack over time, one entry per screen visit.

    A screen visit tells you what was on top. It does not tell you what was
    still *underneath* -- and a screen pushed on top of two others has not
    replaced them: the ones below are still alive, still holding their views and
    bitmaps, and sometimes still doing work. That is frequently the answer to
    "why is RAM high on this screen when the screen itself is cheap".

    The stack cannot be read from slice nesting, because `ScreenTrace` keeps a
    single slot: screen slices are strictly sequential and never overlap. It is
    instead replayed from the navigation markers the coordinator emits, which
    are exactly the stack operations:

        nav:open-<Route>   push     (AppCoordinator.open)
        nav:back-<Route>   pop      (AppCoordinator.onBack)
        nav:tab-<Route>    reset    (AppCoordinator.selectTab)

    Replaying those in timestamp order rebuilds the same back stack the app
    itself held, which is why this is a reconstruction rather than a guess.
    """
    rows = _rows(tp, f"""
        select name as nm, ts as ts
        from slice
        where name like '{SCREEN_PREFIX}%' or name like '{NAV_PREFIX}open-%'
           or name like '{NAV_PREFIX}back-%' or name like '{NAV_PREFIX}tab-%'
        order by ts
    """)
    if not rows:
        return []

    OPEN, BACK, TAB = (NAV_PREFIX + "open-", NAV_PREFIX + "back-",
                       NAV_PREFIX + "tab-")
    stack, out = [], []
    for r in rows:
        nm = r["nm"]
        if nm.startswith(SCREEN_PREFIX):
            route = parse_route(nm[len(SCREEN_PREFIX):])["route"]
            # A screen opening is the top of the stack becoming that screen.
            # The push itself was recorded by the nav marker just before, so
            # this replaces the top rather than adding to it -- otherwise every
            # navigation would count twice.
            if stack:
                stack[-1] = route
            else:
                stack = [route]
            out.append({
                "route": route,
                "ts": r["ts"],
                "stack": list(stack),
                "depth": len(stack),
                # What is held open underneath, which is the part a per-screen
                # number cannot show.
                "beneath": list(stack[:-1]),
            })
        elif nm.startswith(OPEN):
            stack.append(nm[len(OPEN):])
        elif nm.startswith(BACK):
            # Never pop the last entry: something is always on screen, and a
            # trace that begins mid-session can show a back with no matching
            # push recorded before it.
            if len(stack) > 1:
                stack.pop()
        elif nm.startswith(TAB):
            # Selecting a tab clears the stack rather than deepening it.
            stack = [nm[len(TAB):]]
    return out


def attach_stacks(visits, stack_events):
    """Annotate each visit with the navigation stack at the moment it opened.

    Matched by start timestamp: both lists come from the same ordered pass over
    the same slices, so the nth visit to a route lines up with the nth stack
    entry for it. Matching on route alone would collapse repeat visits, which is
    precisely where depth differs -- the same screen is cheap at the root of the
    stack and expensive three deep.
    """
    by_route = {}
    for ev in stack_events:
        by_route.setdefault(ev["route"], []).append(ev)
    seen = {}
    for v in visits:
        route = v["route"]
        i = seen.get(route, 0)
        seen[route] = i + 1
        evs = by_route.get(route) or []
        ev = evs[i] if i < len(evs) else None
        v["stack"] = ev["stack"] if ev else [route]
        v["depth"] = ev["depth"] if ev else 1
        v["beneath"] = ev["beneath"] if ev else []
    return visits


def stack_summary(visits):
    """Cost grouped by how deep the screen sat, plus what was held beneath it.

    This is the view that answers the question the per-screen table raises: if a
    screen is expensive only when it is three deep, the cost belongs to
    everything kept alive below it, not to the screen itself.
    """
    by = {}
    for v in visits:
        depth = v.get("depth", 1)
        d = by.setdefault(depth, {
            "depth": depth, "visits": 0, "total_ms": 0.0, "total_cpu_ms": 0.0,
            "peak_rss_mb": None, "routes": {}, "beneath": {}})
        d["visits"] += 1
        d["total_ms"] += v["duration_ms"]
        d["total_cpu_ms"] += v["cpu_ms"] or 0.0
        if v.get("rss"):
            d["peak_rss_mb"] = max(d["peak_rss_mb"] or 0, v["rss"]["peak_mb"])
        d["routes"][v["route"]] = d["routes"].get(v["route"], 0) + 1
        for b in v.get("beneath") or []:
            d["beneath"][b] = d["beneath"].get(b, 0) + 1
    out = []
    for d in by.values():
        d["total_ms"] = round(d["total_ms"], 2)
        d["total_cpu_ms"] = round(d["total_cpu_ms"], 2)
        d["mean_cpu_pct"] = (round(d["total_cpu_ms"] / d["total_ms"] * 100, 1)
                             if d["total_ms"] else None)
        d["routes"] = sorted(d["routes"].items(), key=lambda kv: -kv[1])
        d["beneath"] = sorted(d["beneath"].items(), key=lambda kv: -kv[1])
        out.append(d)
    return sorted(out, key=lambda d: d["depth"])


def navigations(tp, upids=None):
    """Screen-to-screen transitions, each costed as the user experiences it.

    Three marker shapes share the `nav:` prefix, and reading them all as
    transitions listed every navigation two or three times: `nav:open-Send`
    and friends are *stack operations* (consumed by `screen_stack`), while
    `nav:Home->Send` and its kind-tagged twin `nav:Home#native_view->Send#compose`
    are the same transition emitted twice at the same instant. Only `From->To`
    markers are read here, kind tags are stripped, and twins are collapsed.

    The marker's own duration is not the cost. It closes in the same call that
    opened it -- before the destination has drawn anything -- so every
    transition read 0.0-0.2ms. What a user waits for is the gap from the
    navigation to the end of the first frame the app renders after it, and the
    trace has both, so that is what is reported.
    """
    import bisect
    events = _rows(tp, f"""
        select name as nm, ts from slice
        where name like '{NAV_PREFIX}%->%' order by ts
    """)
    scope = ""
    if upids:
        ids = ",".join(str(int(u)) for u in upids)
        scope = f""" and s.track_id in (select tt.id from thread_track tt
                     join thread th using(utid) where th.upid in ({ids}))"""
    frames = _rows(tp, f"""
        select s.ts as ts, s.ts + s.dur as e from slice s
        where s.name like 'Choreographer#doFrame%' and s.dur > 0{scope}
        order by s.ts
    """)
    starts = [f["ts"] for f in frames]

    seen, by = {}, {}
    for ev in events:
        label = ev["nm"][len(NAV_PREFIX):]
        frm, _, to = label.partition("->")
        frm = frm.split(KIND_SEPARATOR)[0] or None
        to = to.split(KIND_SEPARATOR)[0] or None
        # Twins land within microseconds of each other; 50ms buckets them.
        key = (frm, to, ev["ts"] // 50_000_000)
        if key in seen:
            continue
        seen[key] = True
        cost = None
        i = bisect.bisect_left(starts, ev["ts"])
        if i < len(frames):
            cost = (frames[i]["e"] - ev["ts"]) / 1e6
        d = by.setdefault((frm, to), {"costs": [], "n": 0})
        d["n"] += 1
        if cost is not None:
            d["costs"].append(cost)

    out = []
    for (frm, to), d in by.items():
        cs = sorted(d["costs"])
        out.append({
            "transition": f"{frm}->{to}",
            "from": frm, "to": to,
            "count": d["n"],
            # Median and worst, not mean: one cold first visit would drag a mean.
            "median_ms": round(cs[len(cs) // 2], 1) if cs else None,
            "max_ms": round(cs[-1], 1) if cs else None,
            "total_ms": round(sum(cs), 1) if cs else None,
        })
    return sorted(out, key=lambda r: -(r["max_ms"] or 0))


# Bump whenever the shape or maths of extract_screens changes, so a cached
# result computed by older code is never served as if it were current.
SCREENS_CACHE_VERSION = 4


def _cache_path(trace_path):
    """Where a trace's extracted screen data is cached, or None if uncachable.

    Keyed on the trace's absolute path, size and mtime: a trace file is written
    once and never edited, so those three identify its content without hashing
    hundreds of megabytes on every request.
    """
    import hashlib, os
    try:
        st = os.stat(trace_path)
    except OSError:
        return None
    key = f"{os.path.abspath(trace_path)}|{st.st_size}|{st.st_mtime_ns}|{SCREENS_CACHE_VERSION}"
    d = os.path.join(os.path.dirname(os.path.abspath(trace_path)), ".screens-cache")
    return os.path.join(d, hashlib.sha1(key.encode()).hexdigest() + ".json")


def extract_screens(trace_path, use_cache=True):
    """Screen, action and navigation metrics for one trace.

    Cached per trace file. Extraction re-parses the whole trace and runs a CPU,
    RAM and frame query per visit, which took 2.5-3.7s on a real 165-280MB
    manual session -- paid again every time the Screens tab opened or the run
    picker changed, for a result that cannot change because the trace cannot.
    """
    import json, os
    cp = _cache_path(trace_path) if use_cache else None
    if cp and os.path.exists(cp):
        try:
            with open(cp) as f:
                return json.load(f)
        except (OSError, ValueError):
            pass  # a torn or stale cache file is just a miss
    out = _extract_screens(trace_path)
    if cp:
        try:
            os.makedirs(os.path.dirname(cp), exist_ok=True)
            tmp = cp + ".tmp"
            with open(tmp, "w") as f:
                json.dump(out, f)
            os.replace(tmp, cp)  # atomic, so a concurrent reader never sees half a file
        except OSError:
            pass  # caching is an optimisation; failing to write it is not an error
    return out


def _screen_upids(tp):
    """The process(es) that emitted screen markers -- the app, by definition."""
    return [r["upid"] for r in _rows(tp, f"""
        select distinct coalesce(pt.upid, th.upid) as upid
        from slice s
        left join process_track pt on s.track_id = pt.id
        left join thread_track tt on s.track_id = tt.id
        left join thread th on tt.utid = th.utid
        where s.name like '{SCREEN_PREFIX}%'
    """) if r.get("upid") is not None]


TIMELINE_BUCKET_MS = 500


def session_timeline(tp, upids):
    """The app's RAM and CPU across the whole session, on the visits' clock.

    Per-visit numbers say how much a screen cost; they cannot say *when* memory
    arrived. On a real session the app grew 256MB, and the only way to see which
    screen it arrived on is to draw RAM over time with each visit behind it.
    Timestamps are milliseconds on the same absolute clock as `start_ms` in
    each visit, so the dashboard can overlay the two without re-basing.
    """
    if not upids:
        return {"rss": [], "cpu": [], "bucket_ms": TIMELINE_BUCKET_MS}
    ids = ",".join(str(int(u)) for u in upids)
    mb = 1024 * 1024
    rss = [[round(r["ts"] / 1e6, 1), round(r["v"] / mb, 1)] for r in _rows(tp, f"""
        select c.ts as ts, c.value as v
        from counter c join process_counter_track t on c.track_id = t.id
        where t.name = 'mem.rss' and t.upid in ({ids})
        order by c.ts
    """)]
    bucket_ns = TIMELINE_BUCKET_MS * 1_000_000
    # A slice is credited to the bucket it starts in. Scheduler slices are
    # micro- to milliseconds long against a 500ms bucket, so the error from not
    # splitting the rare one that straddles a boundary is well under a percent.
    cpu = [[round(r["b"] * TIMELINE_BUCKET_MS, 1), round(r["ns"] / bucket_ns * 100, 1)]
           for r in _rows(tp, f"""
        select ss.ts / {bucket_ns} as b, sum(ss.dur) as ns
        from sched_slice ss
        where ss.utid in (select utid from thread where upid in ({ids}))
        group by b order by b
    """)]
    return {"rss": rss, "cpu": cpu, "bucket_ms": TIMELINE_BUCKET_MS}


# Android's own FrameTimeline verdict on each late frame. "App Deadline
# Missed" is the app's fault; the SurfaceFlinger / Display HAL / prediction
# types are the system's; "Buffer Stuffing" means frames queued faster than
# they could be shown (app-side, usually not a visible hitch on its own).
JANK_GROUPS = (
    ("app", ("App Deadline Missed",)),
    ("system", ("SurfaceFlinger", "Display HAL", "Prediction Error")),
    ("dropped", ("Dropped Frame",)),
    ("buffer_stuffing", ("Buffer Stuffing",)),
)


def _jank_group(jank_type):
    for group, needles in JANK_GROUPS:
        if any(n in jank_type for n in needles):
            return group
    return "other"


def jank_by_screen(tp, upids, visits):
    """Late frames per screen, split by whose fault Android says they were.

    Slow-frame percentages say a screen stuttered, not why. FrameTimeline
    classifies each late frame at the source, which separates "our code missed
    the deadline" from "the compositor or display did" -- two problems with
    nothing in common in how they are fixed.
    """
    if not upids or not visits:
        return {}
    ids = ",".join(str(int(u)) for u in upids)
    try:
        frames = _rows(tp, f"""
            select ts, jank_type as jt from actual_frame_timeline_slice
            where upid in ({ids}) order by ts""")
    except Exception:
        return {}  # older traces have no FrameTimeline table
    if not frames:
        return {}
    spans = sorted(((v["start_ms"] * 1e6, (v["start_ms"] + v["duration_ms"]) * 1e6, v["route"])
                    for v in visits))
    out, i = {}, 0
    for f in frames:
        while i < len(spans) and spans[i][1] < f["ts"]:
            i += 1
        if i >= len(spans):
            break
        start, end, route = spans[i]
        if f["ts"] < start:
            continue  # between visits: not attributable to a screen
        d = out.setdefault(route, {"frames": 0, "late": 0, "app": 0, "system": 0,
                                   "dropped": 0, "buffer_stuffing": 0, "other": 0})
        d["frames"] += 1
        jt = f.get("jt") or "None"
        if jt not in ("None", ""):
            d["late"] += 1
            d[_jank_group(jt)] += 1
    for d in out.values():
        d["app_jank_pct"] = round(d["app"] / d["frames"] * 100, 2) if d["frames"] else None
        d["late_pct"] = round(d["late"] / d["frames"] * 100, 2) if d["frames"] else None
    return out


def _extract_screens(trace_path):
    from perfetto.trace_processor import TraceProcessor
    tp = TraceProcessor(trace=trace_path)
    try:
        if not has_markers(tp):
            return {"instrumented": False, "screens": [], "screen_summary": [],
                    "stack_summary": [], "max_depth": 0,
                    "actions": [], "navigations": [],
                    "note": "This trace carries no SwagTrace screen/action markers. "
                            "Screen attribution needs the app to emit them; see "
                            "SwagTrace in the swag-pay repo."}
        visits = screen_visits(tp)
        # Stacks are attached before summarising so each visit carries the depth
        # it ran at, and the summary can group by it.
        visits = attach_stacks(visits, screen_stack(tp))
        upids = _screen_upids(tp)
        summary = screen_summary(visits)
        jank = jank_by_screen(tp, upids, visits)
        for row in summary:
            row["jank"] = jank.get(row["route"])
        return {"instrumented": True,
                "screens": visits,
                "screen_summary": summary,
                "timeline": session_timeline(tp, upids),
                "stack_summary": stack_summary(visits),
                "max_depth": max((v.get("depth", 1) for v in visits), default=0),
                "actions": actions(tp),
                "navigations": navigations(tp, upids)}
    finally:
        tp.close()


# --------------------------------------------------------------- live markers

STEP_PREFIX = "step:"

# The live view is polled while a session records, so it must stay cheap. It
# reads marker slices only -- no sched_slice join, no per-visit CPU or RAM
# attribution -- because those are what make full extraction take seconds on a
# multi-hundred-megabyte trace. The dashboard wants to know *what happened and
# when*, not what it cost; cost is the job of the analysis after the stop.
_LIVE_PREFIXES = ((SCREEN_PREFIX, "screen"), (ACTION_PREFIX, "action"),
                  (NAV_PREFIX, "nav"), (STEP_PREFIX, "step"))


def live_markers(trace_path, *, limit=500):
    """Markers seen so far in a partial trace, newest last.

    Returns a flat timeline plus per-kind counts. `open_ended` marks a screen
    slice that has not closed yet, which for the live view is the normal state
    of the screen currently on display rather than an anomaly.
    """
    from perfetto.trace_processor import TraceProcessor
    tp = TraceProcessor(trace=trace_path)
    try:
        where = " or ".join(f"s.name like '{p}%'" for p, _ in _LIVE_PREFIXES)
        rows = _rows(tp, f"""
            select s.name as nm, s.ts as ts, s.dur as dur
            from slice s where {where}
            order by s.ts
        """)
        # Timestamps are boot-relative, which means nothing on their own. The
        # first marker is the natural zero for a session view: it makes the
        # numbers read as "N seconds into this session".
        base = rows[0]["ts"] if rows else 0

        events, counts = [], {}
        for r in rows:
            nm = r["nm"]
            kind = label = None
            for prefix, k in _LIVE_PREFIXES:
                if nm.startswith(prefix):
                    kind, label = k, nm[len(prefix):]
                    break
            if kind is None:
                continue
            dur = r["dur"] or 0
            counts[kind] = counts.get(kind, 0) + 1
            ev = {
                "kind": kind,
                "name": label,
                "at_ms": round((r["ts"] - base) / 1e6, 1),
                "duration_ms": round(dur / 1e6, 2) if dur > 0 else None,
                "open_ended": dur < 0,
            }
            if kind == "screen":
                # Strip the `#kind` tag out of the displayed name and report it
                # as its own field, so the feed reads as a screen name rather
                # than a wire format.
                meta = parse_route(label)
                ev["name"] = meta["route"]
                ev["screen_kind"] = meta["kind"]
                ev["screen_kind_label"] = meta["kind_label"]
                ev["parent"] = meta["parent"]
                ev["step"] = meta["step"]
            events.append(ev)

        # Several screen slices can be open at once now: a parent route and the
        # sub-screen inside it. The innermost one is what the user is looking
        # at, so prefer a sub-screen over the parent that contains it.
        open_screens = [e for e in events
                        if e["kind"] == "screen" and e["open_ended"]]
        current_ev = next((e for e in reversed(open_screens) if e.get("step")),
                          open_screens[-1] if open_screens else None)
        current = current_ev["name"] if current_ev else None
        return {
            "events": events[-limit:],
            "truncated": len(events) > limit,
            "total": len(events),
            "counts": counts,
            "current_screen": current,
            "current_screen_kind": (current_ev or {}).get("screen_kind_label"),
        }
    finally:
        tp.close()
