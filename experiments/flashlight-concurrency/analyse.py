"""Say whether Flashlight damaged the Perfetto traces in a run.py results directory.

    ./.venv/bin/python experiments/flashlight-concurrency/analyse.py <results-dir>
    ./.venv/bin/python experiments/flashlight-concurrency/analyse.py --trace t.pftrace --pkg com.swag.pay

Every trace number is per window and is read against the perfetto_only control
for the same window, so what the workload and the phone contribute cancels out
and what remains is what the other tool did. Three kinds of evidence:

  ftrace-fed    sched_switch events, the app's atrace slices (doFrame), and the
                app's own screen:/nav: markers -- all of which arrive through
                the kernel trace buffer Flashlight also reads
  not ftrace    frame timeline and RAM samples, which reach Perfetto by other
                routes; they show the app kept running normally, so a drop in
                the first group cannot be blamed on the app doing less
  Flashlight    the atrace lines and frames its own sampler received, against
                the flashlight_only control

`--trace` reads one existing trace split into three equal windows, with no
expected marker counts. It exists to check the queries against real traces.
"""
import argparse, glob, json, os, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
from perfetto.trace_processor import TraceProcessor  # noqa: E402
from swagperf.extract import _app_upids  # noqa: E402

WINDOWS = ["W1", "W2", "W3"]
# Window edges are read on the device just before the first tap and just after
# the last pause, so no trimming is needed. Trimming would cut the first tap's
# marker, which the app emits before the tap loop gets to log the tap.
EDGE_S = 0.0

# A window is damaged when it falls this far below the control for the same
# window. The margins are wide on purpose: they must not fire on run-to-run
# noise, and the failures being tested for are not subtle.
MIN_SCHED_RATIO = 0.8
MIN_DOFRAME_RATIO = 0.8
MAX_MARKER_YIELD_DROP = 0.1


def _one(tp, sql):
    rows = list(tp.query(sql))
    return rows[0] if rows else None


def _in(ids):
    return ",".join(str(int(i)) for i in ids) or "-1"


def window_metrics(tp, upids, a_ns, b_ns):
    secs = (b_ns - a_ns) / 1e9
    w = f"ts >= {a_ns} and ts < {b_ns}"
    sched = _one(tp, f"select count(*) n, count(distinct cast((ts - {a_ns}) / 1e9 as int)) live "
                     f"from sched_slice where {w}")
    # sched_slice includes idle time, so each CPU's slices normally tile it
    # with no gaps. A gap is a stretch in which no sched_switch was recorded.
    gap = _one(tp, f"""select max(gap) g from (
        select ts - lag(ts + dur) over (partition by cpu order by ts) as gap
        from sched_slice where {w})""")
    app_thread = (f"from slice s join thread_track tt on s.track_id = tt.id "
                  f"join thread t using(utid) where t.upid in ({_in(upids)}) and s.{w}")
    doframe = _one(tp, f"select count(*) n {app_thread} and s.name like 'Choreographer#doFrame%'")
    app_slices = _one(tp, f"select count(*) n {app_thread}")
    screen = _one(tp, f"select count(*) n from slice where name like 'screen:%' and {w}")
    nav = _one(tp, f"select count(*) n from slice where name like 'nav:%' and {w}")
    frames = _one(tp, f"select count(*) n from actual_frame_timeline_slice "
                      f"where upid in ({_in(upids)}) and {w}")
    ram = _one(tp, f"""select count(*) n from counter c
        join process_counter_track t on c.track_id = t.id
        where t.upid in ({_in(upids)}) and t.name = 'mem.rss' and c.{w}""")
    return {
        "secs": round(secs, 2),
        "sched_per_s": round(sched.n / secs, 1),
        "silent_s": max(0, int(secs) - sched.live),
        "sched_max_gap_ms": round((gap.g or 0) / 1e6, 1),
        "doframe_per_s": round(doframe.n / secs, 2),
        "app_slices_per_s": round(app_slices.n / secs, 1),
        "screen_markers": screen.n,
        "nav_markers": nav.n,
        "frametimeline_per_s": round(frames.n / secs, 2),
        "ram_samples_per_s": round(ram.n / secs, 2),
    }


def trace_stats(tp):
    """Problems Perfetto recorded about its own capture."""
    return {f"{r.name}[{r.idx}]" if r.idx is not None else r.name: r.value for r in tp.query(
        "select name, idx, value from stats where value > 0 and severity in ('error', 'data_loss')")}


def analyse_trace(path, pkg, windows):
    """windows: [(name, start_ns, end_ns, expected_markers or None)]."""
    tp = TraceProcessor(trace=path)
    try:
        upids = _app_upids(tp, pkg)
        bounds = _one(tp, "select start_ts, end_ts from trace_bounds")
        out = {"app_found": bool(upids), "stats": trace_stats(tp), "windows": {}}
        for name, a, b, expected in windows:
            # A trace ends at its last event, and a damaged one can go quiet a
            # poll interval before it is stopped, so allow a second of slack.
            if a < bounds.start_ts - 1e9 or b > bounds.end_ts + 1e9:
                out.setdefault("warnings", []).append(
                    f"{name} lies outside the trace ({a}..{b} vs {bounds.start_ts}..{bounds.end_ts}): "
                    "the boot clock and the trace clock disagree")
            m = window_metrics(tp, upids, a, b)
            m["expected_markers"] = expected
            m["marker_yield"] = round(m["screen_markers"] / expected, 2) if expected else None
            out["windows"][name] = m
        return out
    finally:
        tp.close()


def sampler_metrics(path, clock, windows):
    """Flashlight's view of each window, from the sampler's own log."""
    if not path or not os.path.exists(path):
        return None
    events = []
    for l in open(path):
        try:
            events.append(json.loads(l))
        except json.JSONDecodeError:
            pass
    # The sampler logs host time; the run's clock pairs convert it to boot time.
    offset = statistics.median(c["boot_s"] - c["host_s"] for c in clock)
    measures = [e for e in events if e.get("event") == "measure"]
    out = {"measures": len(measures), "windows": {}}
    for name, a, b, _ in windows:
        ms = [e for e in measures if a / 1e9 <= e["host_ms"] / 1000 + offset < b / 1e9]
        if not ms:
            continue
        with_lines = [e for e in ms if "atrace_lines" in e]
        out["windows"][name] = {
            "measures": len(ms),
            "atrace_lines_per_measure": round(statistics.mean(e["atrace_lines"] for e in with_lines), 1)
            if with_lines else None,
            "frames_per_measure": round(statistics.mean(e["frames"] for e in with_lines), 2)
            if with_lines else None,
            "fps": round(statistics.mean(e["fps"] for e in ms if e.get("fps") is not None), 1)
            if any(e.get("fps") is not None for e in ms) else None,
        }
    return out


def _windows_from_log(log):
    out = []
    for w in log["windows"]:
        a = int((w["start_boot_s"] + EDGE_S) * 1e9)
        b = int((w["end_boot_s"] - EDGE_S) * 1e9)
        out.append((w["name"], a, b, len(w["taps_boot_s"])))
    return out


def _median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _ratio(x, base):
    return None if x is None or not base else round(x / base, 2)


def judge(runs):
    """Mark each window of each run clean or damaged, against the control."""
    control = {}
    for w in WINDOWS:
        ws = [r["trace"]["windows"].get(w) for r in runs
              if r["mode"] == "perfetto_only" and r.get("trace")]
        ws = [x for x in ws if x]
        control[w] = {k: _median([x[k] for x in ws]) for k in
                      ("sched_per_s", "doframe_per_s", "marker_yield", "frametimeline_per_s",
                       "ram_samples_per_s", "silent_s")} if ws else None
    ctrl_stats = set()
    for r in runs:
        if r["mode"] == "perfetto_only" and r.get("trace"):
            ctrl_stats |= set(r["trace"]["stats"])

    for r in runs:
        if not r.get("trace"):
            continue
        r["trace"]["new_stats"] = {k: v for k, v in r["trace"]["stats"].items() if k not in ctrl_stats}
        for w, m in r["trace"]["windows"].items():
            c = control.get(w)
            if not c:
                m["verdict"] = "no control"
                continue
            m["sched_ratio"] = _ratio(m["sched_per_s"], c["sched_per_s"])
            m["doframe_ratio"] = _ratio(m["doframe_per_s"], c["doframe_per_s"])
            m["frametimeline_ratio"] = _ratio(m["frametimeline_per_s"], c["frametimeline_per_s"])
            reasons = []
            if m["silent_s"] > (c["silent_s"] or 0):
                reasons.append(f"{m['silent_s']}s with no scheduler events")
            if m["sched_ratio"] is not None and m["sched_ratio"] < MIN_SCHED_RATIO:
                reasons.append(f"scheduler events at {m['sched_ratio']:.0%} of control")
            if m["doframe_ratio"] is not None and m["doframe_ratio"] < MIN_DOFRAME_RATIO:
                reasons.append(f"app doFrame slices at {m['doframe_ratio']:.0%} of control")
            if (m["marker_yield"] is not None and c["marker_yield"] is not None
                    and m["marker_yield"] < c["marker_yield"] - MAX_MARKER_YIELD_DROP):
                reasons.append(f"{m['screen_markers']} of {m['expected_markers']} screen markers "
                               f"(control yields {c['marker_yield']:.0%})")
            m["reasons"] = reasons
            m["verdict"] = "damaged" if reasons else "clean"
    return control


def load_dir(d):
    session = json.load(open(os.path.join(d, "session.json")))
    pkg = session["args"]["pkg"]
    runs = []
    for p in sorted(glob.glob(os.path.join(d, "*.run.json"))):
        log = json.load(open(p))
        wins = _windows_from_log(log)
        run = {"mode": log["mode"], "rep": log["rep"], "error": log.get("error"),
               "notes": log.get("notes", []), "states": log.get("states", [])}
        if log.get("trace") and os.path.exists(os.path.join(d, log["trace"])):
            print(f"  reading {log['trace']}…", file=sys.stderr)
            run["trace"] = analyse_trace(os.path.join(d, log["trace"]), pkg, wins)
        run["flashlight"] = sampler_metrics(
            os.path.join(d, log["sampler_log"]) if log.get("sampler_log") else None,
            log.get("clock", []), wins)
        runs.append(run)
    return session, runs


def flashlight_summary(runs):
    """Flashlight's frames per measure in each mode, against flashlight_only."""
    by = {}
    for r in runs:
        for w, m in ((r.get("flashlight") or {}).get("windows") or {}).items():
            by.setdefault(r["mode"], []).append(m["frames_per_measure"])
    return {mode: _median(v) for mode, v in by.items()}


def report(session, runs):
    control = judge(runs)
    print(f"\n  device {session['serial']}  Flashlight profiler {session['flashlight']}  "
          f"{len(runs)} run(s)\n")
    print(f"  {'mode':<26}{'rep':>4}  {'win':<4}{'sched/s':>9}{'ratio':>7}{'silent':>7}"
          f"{'gap ms':>8}{'doFrame':>9}{'ratio':>7}{'markers':>9}{'frames':>8}{'ratio':>7}  verdict")
    for r in sorted(runs, key=lambda r: (r["mode"], r["rep"])):
        if r.get("error"):
            print(f"  {r['mode']:<26}{r['rep']:>4}  error: {r['error']}")
        for n in r["notes"]:
            print(f"  {r['mode']:<26}{r['rep']:>4}  note: {n}")
        if not r.get("trace"):
            continue
        for w in WINDOWS:
            m = r["trace"]["windows"].get(w)
            if not m:
                continue
            mk = f"{m['screen_markers']}/{m['expected_markers']}"
            print(f"  {r['mode']:<26}{r['rep']:>4}  {w:<4}{m['sched_per_s']:>9.0f}"
                  f"{(m.get('sched_ratio') or 0):>7.2f}{m['silent_s']:>7}{m['sched_max_gap_ms']:>8.0f}"
                  f"{m['doframe_per_s']:>9.1f}{(m.get('doframe_ratio') or 0):>7.2f}{mk:>9}"
                  f"{m['frametimeline_per_s']:>8.1f}{(m.get('frametimeline_ratio') or 0):>7.2f}  "
                  f"{m.get('verdict', '')}" + (f"  ({'; '.join(m['reasons'])})" if m.get("reasons") else ""))
        if r["trace"].get("new_stats"):
            print(f"  {'':<30}Perfetto recorded problems the control did not: {r['trace']['new_stats']}")
        for warn in r["trace"].get("warnings", []):
            print(f"  {'':<30}warning: {warn}")

    fl = flashlight_summary(runs)
    if fl:
        print("\n  Flashlight's own frames per 500 ms measure (median across windows)")
        for mode, v in sorted(fl.items()):
            base = fl.get("flashlight_only")
            print(f"  {mode:<26}{v if v is not None else '-':>8}"
                  + (f"   {v / base:.0%} of flashlight_only" if base and v is not None else ""))

    print("\n  tracing state at each boundary (first repetition of each mode)")
    seen = set()
    for r in sorted(runs, key=lambda r: (r["mode"], r["rep"])):
        if r["mode"] in seen:
            continue
        seen.add(r["mode"])
        print(f"  {r['mode']}")
        for s in r["states"]:
            print(f"    {s.get('label', ''):<18} tracing_on={s.get('tracing_on', '?'):<2} "
                  f"sched_switch={s.get('sched_switch_enabled', '?'):<2} "
                  f"atrace_tags={s.get('atrace_tags', '?'):<12} apps={s.get('atrace_app_number', '?'):<2} "
                  f"perfetto={s.get('perfetto_session', '?'):<4} profiler={s.get('profiler_procs', '?')} "
                  f"atrace={s.get('atrace_procs', '?')}")
    return {"control": control, "runs": runs, "flashlight": fl}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("results", nargs="?", help="a run.py results directory")
    ap.add_argument("--trace", help="analyse one existing trace instead")
    ap.add_argument("--pkg", default="com.swag.pay")
    a = ap.parse_args(argv)

    if a.trace:
        tp = TraceProcessor(trace=a.trace)
        b = _one(tp, "select start_ts, end_ts from trace_bounds")
        tp.close()
        third = (b.end_ts - b.start_ts) // 3
        wins = [(w, b.start_ts + i * third, b.start_ts + (i + 1) * third, None)
                for i, w in enumerate(WINDOWS)]
        print(json.dumps(analyse_trace(a.trace, a.pkg, wins), indent=1))
        return
    if not a.results:
        ap.error("give a results directory, or --trace")
    session, runs = load_dir(a.results)
    out = report(session, runs)
    with open(os.path.join(a.results, "report.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(f"\n  full numbers -> {os.path.join(a.results, 'report.json')}")


if __name__ == "__main__":
    main()
