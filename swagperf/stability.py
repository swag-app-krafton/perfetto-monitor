"""Stability: hangs, JS errors and crashes, from a trace of either platform.

Measurement only, like extract.py: Perfetto SQL in, a dict out.

**Hangs** are the main thread not responding. Apple's definitions are used on
both platforms, so the two lanes report the same thing:
  - a microhang is a stall of 100-250 ms,
  - a hang is 250 ms or more.
The sources differ:
  - iOS: the Hangs instrument, written as `swagperf.hang:*` slices by
    convert_ios.py.
  - Android: top-level slices on the app's main thread of 100 ms or more. A
    top-level slice is one Looper message the thread could not interrupt.
    Untraced main-thread work is invisible here, so Android undercounts.
Stalls before the first frame are counted apart: startup has its own metric.
A hang rate (seconds of hang per hour, Apple's unit) is given only for
sessions of a minute or more. One 300 ms hang in a 10 s capture would read as
108 s/hr, which says nothing about the app.

**JS errors** come from React Native's error reporting in the app
(react-native/src/errorReporting.ts). Each error has two parts:
  - a marker, `error:js:<source>:<Name>#fatal|nonfatal@<id>`, which gives the
    time and the screen;
  - a record with the redacted message and the raw stack, joined to the
    marker by id.
Records arrive as log lines, `swagerr|<id>|<seq>/<total>|<chunk>`: logcat on
Android (Perfetto's `android.log` source), os_log on iOS (reassembled by
convert_ios.py). Stacks are resolved against the build's source map later,
when the run is read (sourcemaps.py), so a map registered after the run
still applies.

**ANRs** (Android only) are declared by the system, not the app: when
ActivityManager declares one it writes two atrace counters from
system_server under the `am` category, `ErrorId:<process> <pid>#<id>` and
`Subject(for ErrorId <id>):<subject>`. The trace processor's android.anrs
module joins them into `android_anrs`. Each ANR names the screen on display
and the longest main-thread slice in the window before it.

**Crashes:**
  - iOS: how xctrace saw the process end, carried in the trace's provenance.
  - Android, every one in the run, with its crash log:
    - Kotlin/Java: AndroidRuntime's report (`FATAL EXCEPTION`, `Process:
      <pkg>, PID: <pid>`, the exception, a line per frame), reassembled;
    - native: libc's `Fatal signal` line from the app, joined to the
      tombstone crash_dump writes from its own process, whose header names
      the app (`pid: N, … >>> <pkg> <<<`).
  A trace recorded without the android.log source measured none.
"""
import json, re

from .extract import _app_upids, _rows, frame_like, trace_source

MICROHANG_MS = 100
HANG_MS = 250
RATE_MIN_SESSION_S = 60
MAX_EVENTS = 100

ERROR_PREFIX = "error:js:"
LOG_TAG = "SwagPerfError"
_MARKER = re.compile(r"^error:js:(?P<source>[a-z]+):(?P<name>[A-Za-z0-9_]+)#(?P<fatal>fatal|nonfatal)@(?P<id>[A-Za-z0-9]+)$")
_LINE = re.compile(r"^swagerr\|(?P<id>[A-Za-z0-9]+)\|(?P<seq>\d+)/(?P<total>\d+)\|(?P<chunk>.*)$", re.S)


# ------------------------------------------------------------- error records

def assemble_records(lines):
    """[(ts, line)] -> ({id: (first ts, record text)}, incomplete count).

    A record with a chunk missing is dropped and counted, never parsed
    half-read."""
    parts, first = {}, {}
    for ts, line in lines:
        m = _LINE.match(line or "")
        if not m:
            continue
        rid, seq, total = m["id"], int(m["seq"]), int(m["total"])
        parts.setdefault(rid, {"total": total, "chunks": {}})["chunks"][seq] = m["chunk"]
        first.setdefault(rid, ts)
    records, incomplete = {}, 0
    for rid, p in parts.items():
        if len(p["chunks"]) != p["total"]:
            incomplete += 1
            continue
        records[rid] = (first[rid], "".join(p["chunks"][i] for i in range(1, p["total"] + 1)))
    return records, incomplete


def parse_marker(name):
    m = _MARKER.match(name or "")
    return m.groupdict() if m else None


def _record_lines(tp, platform, upids):
    """Every error record in the trace, as {id: parsed record}."""
    from .convert_ios import ERROR_RECORD_PREFIX
    out = {}
    if platform == "ios":
        for r in _rows(tp, f"""
                select s.name as nm, a.string_value as v from slice s
                join args a using (arg_set_id)
                where s.name like '{ERROR_RECORD_PREFIX}%' and a.key = 'debug.record'"""):
            out[r["nm"][len(ERROR_RECORD_PREFIX):]] = r["v"]
        return {k: _loads(v) for k, v in out.items()}
    try:
        scope = ""
        if upids:
            ids = ",".join(str(int(u)) for u in upids)
            scope = f" and utid in (select utid from thread where upid in ({ids}))"
        lines = [(r["ts"], r["msg"]) for r in _rows(tp, f"""
            select ts, msg from android_logs where tag = '{LOG_TAG}'{scope} order by ts""")]
    except Exception:
        return {}  # a trace without the android.log data source
    records, _ = assemble_records(lines)
    return {k: _loads(v) for k, (_, v) in records.items()}


def _loads(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _q(s):
    return (s or "").replace("'", "''")


def _ids(upids):
    return ",".join(str(int(u)) for u in upids)


def _config(tp):
    """The trace's own recorded config, or None: synthetic and converted
    traces carry none."""
    try:
        r = _rows(tp, "select str_value as v from metadata where name = 'trace_config_pbtxt'")
    except Exception:
        return None
    return (r[0].get("v") or None) if r else None


# ------------------------------------------------------------------ helpers

def _screen_windows(tp):
    """(start, end, route) for every screen and sub-screen visit, innermost
    last, for attributing a moment to the screen on display."""
    from .screens import SCREEN_PREFIX, parse_route
    end = (_rows(tp, "select max(ts + max(dur, 0)) as e from slice")[0].get("e") or 0)
    wins = []
    for r in _rows(tp, f"select ts, dur, name from slice where name like '{SCREEN_PREFIX}%' and dur != 0"):
        e = end if (r["dur"] or 0) < 0 else r["ts"] + r["dur"]
        meta = parse_route(r["name"][len(SCREEN_PREFIX):])
        wins.append((r["ts"], e, meta["route"], bool(meta.get("step"))))
    return wins


def _screen_at(wins, ts):
    """The screen on display at `ts`: a sub-screen over its parent."""
    hit = [w for w in wins if w[0] <= ts <= w[1]]
    if not hit:
        return None
    hit.sort(key=lambda w: (not w[3], -w[0]))
    return hit[0][2]


def first_frame_ns(tp, upids, platform):
    """When the app first drew: the end of iOS's first-frame launch phase, or
    of the app's first frame slice on Android. None without a launch."""
    if platform == "ios":
        r = _rows(tp, """select max(ts + dur) as e from slice
                         where name in ('swagperf.launch:main_to_first_frame',
                                        'swagperf.launch:to_first_frame')""")
        return r[0].get("e") if r else None
    scope = ""
    if upids:
        ids = ",".join(str(int(u)) for u in upids)
        scope = f""" and s.track_id in (select tt.id from thread_track tt
                     join thread th using (utid) where th.upid in ({ids}))"""
    r = _rows(tp, f"select min(s.ts + s.dur) as e from slice s where {frame_like()} and s.dur > 0{scope}")
    return r[0].get("e") if r else None


# ------------------------------------------------------------------- hangs

def _hang_intervals(tp, upids, platform):
    """[(ts, dur)] of main-thread stalls of MICROHANG_MS or more."""
    floor = MICROHANG_MS * 1_000_000
    if platform == "ios":
        from .convert_ios import HANG_PREFIX
        return [(r["ts"], r["dur"]) for r in _rows(tp, f"""
            select ts, dur from slice where name like '{HANG_PREFIX}%' and dur >= {floor}
            order by ts""")]
    if not upids:
        return []
    ids = ",".join(str(int(u)) for u in upids)
    return [(r["ts"], r["dur"]) for r in _rows(tp, f"""
        select s.ts as ts, s.dur as dur from slice s
        join thread_track tt on s.track_id = tt.id
        join thread t using (utid)
        join process p on p.upid = t.upid
        where t.upid in ({ids}) and t.tid = p.pid and s.depth = 0 and s.dur >= {floor}
        order by s.ts""")]


def hangs(tp, upids, platform, wins=None):
    wins = _screen_windows(tp) if wins is None else wins
    ff = first_frame_ns(tp, upids, platform) or 0
    bounds = _rows(tp, "select start_ts as s, end_ts as e from trace_bounds")[0]
    session_s = max(0.0, ((bounds["e"] or 0) - max(ff, bounds["s"] or 0)) / 1e9)
    events, startup = [], []
    for ts, dur in _hang_intervals(tp, upids, platform):
        ms = round(dur / 1e6, 1)
        kind = "hang" if ms >= HANG_MS else "microhang"
        ev = {"start_ms": round(ts / 1e6, 2), "dur_ms": ms, "kind": kind,
              "screen": _screen_at(wins, ts)}
        (startup if ff and ts < ff else events).append(ev)
    hang_ms = [e["dur_ms"] for e in events if e["kind"] == "hang"]
    return {
        "count": len(hang_ms),
        "microhangs": sum(1 for e in events if e["kind"] == "microhang"),
        "longest_ms": max((e["dur_ms"] for e in events), default=None),
        "total_ms": round(sum(hang_ms), 1),
        "rate_s_per_hr": (round(sum(hang_ms) / 1000 / (session_s / 3600), 1)
                          if session_s >= RATE_MIN_SESSION_S else None),
        "session_s": round(session_s, 1),
        "startup": {"count": sum(1 for e in startup if e["kind"] == "hang"),
                    "microhangs": sum(1 for e in startup if e["kind"] == "microhang"),
                    "longest_ms": max((e["dur_ms"] for e in startup), default=None)},
        "per_screen": _by_screen(events, "dur_ms"),
        "events": (startup + events)[:MAX_EVENTS],
        "thresholds_ms": {"microhang": MICROHANG_MS, "hang": HANG_MS},
        "source": "the Hangs instrument" if platform == "ios" else "the app's main-thread slices",
    }


# -------------------------------------------------------------------- ANRs

# The trace processor's ANR types, for a reader. Timeouts are AOSP's
# defaults; vendors may change them.
ANR_TYPES = {
    "INPUT_DISPATCHING_TIMEOUT": "A touch or key went unanswered",
    "INPUT_DISPATCHING_TIMEOUT_NO_FOCUSED_WINDOW": "A touch or key arrived with no window to take it",
    "BROADCAST_OF_INTENT": "A broadcast receiver ran too long",
    "EXECUTING_SERVICE": "A service callback ran too long",
    "START_FOREGROUND_SERVICE": "A foreground service didn't start in time",
    "BIND_APPLICATION": "The app took too long to start",
    "CONTENT_PROVIDER_NOT_RESPONDING": "A content provider didn't respond",
    "APP_TRIGGERED": "The app reported an ANR itself",
}
# The window before an ANR searched for main-thread work when the module gives
# no duration: the input-dispatch timeout.
ANR_WINDOW_MS = 5000
_NO_ANRS = {"measured": False, "count": None, "by_type": {}, "per_screen": {}, "events": []}


def _main_thread_work(tp, upids, start, end):
    """The longest top-level slice on the app's main thread overlapping
    [start, end], or None when nothing was traced there."""
    if not upids:
        return None
    r = _rows(tp, f"""
        select s.name as name, s.dur as dur from slice s
        join thread_track tt on s.track_id = tt.id
        join thread t using (utid)
        join process p on p.upid = t.upid
        where t.upid in ({_ids(upids)}) and t.tid = p.pid and s.depth = 0 and s.dur > 0
          and s.ts < {int(end)} and s.ts + s.dur > {int(start)}
        order by s.dur desc limit 1""")
    return {"name": r[0]["name"], "dur_ms": round(r[0]["dur"] / 1e6, 1)} if r else None


def anrs(tp, pkg, upids, platform, wins=None):
    """ANRs the system declared for the app. iOS has none; a trace recorded
    without the `am` category measured none."""
    if platform == "ios":
        return dict(_NO_ANRS)
    cfg = _config(tp)
    if cfg is not None and 'atrace_categories: "am"' not in cfg:
        return dict(_NO_ANRS)
    wins = _screen_windows(tp) if wins is None else wins
    where = f"process_name = '{_q(pkg)}'" if pkg else "0"
    if upids:
        where += f" or upid in ({_ids(upids)})"
    try:
        rows = _rows(tp, f"""include perfetto module android.anrs;
            select error_id, ts, anr_type, subject, anr_dur_ms, default_anr_dur_ms
            from android_anrs where {where} order by ts""")
    except Exception:
        rows = []   # a trace processor without the module
    events = []
    for r in rows:
        dur = r.get("anr_dur_ms") or r.get("default_anr_dur_ms")
        typ = r.get("anr_type") or "UNKNOWN_ANR_TYPE"
        window = (dur or ANR_WINDOW_MS) * 1_000_000
        events.append({
            "id": r["error_id"], "start_ms": round(r["ts"] / 1e6, 2),
            "type": typ, "type_label": ANR_TYPES.get(typ, typ.replace("_", " ").capitalize()),
            "subject": r.get("subject"), "dur_ms": dur,
            "screen": _screen_at(wins, r["ts"]),
            "main_thread": _main_thread_work(tp, upids, r["ts"] - window, r["ts"]),
        })
    by_type, per_screen = {}, {}
    for e in events:
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1
        screen = e["screen"] or "(no screen)"
        per_screen[screen] = per_screen.get(screen, 0) + 1
    return {"measured": True, "count": len(events), "by_type": by_type,
            "per_screen": per_screen, "events": events[:MAX_EVENTS]}


def _by_screen(events, key):
    out = {}
    for e in events:
        s = out.setdefault(e.get("screen") or "(no screen)", {"count": 0, "longest_ms": 0.0})
        s["count"] += 1
        s["longest_ms"] = max(s["longest_ms"], e[key])
    return out


# ------------------------------------------------------------------ errors

def errors(tp, upids, platform, wins=None):
    wins = _screen_windows(tp) if wins is None else wins
    records = _record_lines(tp, platform, upids)
    events = []
    for r in _rows(tp, f"select ts, name from slice where name like '{ERROR_PREFIX}%' order by ts"):
        m = parse_marker(r["name"])
        if not m:
            continue
        rec = records.get(m["id"]) or {}
        events.append({
            "id": m["id"], "start_ms": round(r["ts"] / 1e6, 2),
            "name": m["name"], "source": m["source"], "fatal": m["fatal"] == "fatal",
            "screen": _screen_at(wins, r["ts"]),
            "message": rec.get("message"), "stack": rec.get("stack"),
            "component_stack": rec.get("component_stack"),
            "has_record": bool(rec),
        })
    by_name, by_source, per_screen = {}, {}, {}
    for e in events:
        by_name[e["name"]] = by_name.get(e["name"], 0) + 1
        by_source[e["source"]] = by_source.get(e["source"], 0) + 1
        screen = e["screen"] or "(no screen)"
        per_screen[screen] = per_screen.get(screen, 0) + 1
    return {"js": len(events), "js_fatal": sum(1 for e in events if e["fatal"]),
            "by_name": by_name, "by_source": by_source, "per_screen": per_screen,
            "events": events[:MAX_EVENTS]}


# ------------------------------------------------------------------ crashes

_FATAL_SIGNAL = re.compile(r"^Fatal signal (?P<num>\d+) \((?P<sig>SIG[A-Z0-9]+)\).* pid (?P<pid>\d+) \(")
_PROCESS_LINE = re.compile(r"^Process: (?P<pkg>[^,\s]+), PID: (?P<pid>\d+)")
_TOMBSTONE_HEAD = re.compile(r"^pid: (?P<pid>\d+), tid: \d+, name: .*>>> (?P<pkg>\S+) <<<")
_TOMBSTONE_START = "*** *** ***"
_SIGNAL_NAME = re.compile(r"\((SIG[A-Z0-9]+)\)")
# A report's lines arrive together; a longer gap ends it.
_REPORT_GAP_NS = 1_000_000_000


def _crash_lines(tp):
    """Every crash-log line in the trace, with the pid of the process that
    wrote it. Unscoped on purpose: crash_dump, not the app, writes a native
    crash's tombstone, and every report names the app itself."""
    try:
        return _rows(tp, """
            select l.ts as ts, l.utid as utid, p.pid as pid, l.tag as tag, l.msg as msg
            from android_logs l
            left join thread t using (utid) left join process p using (upid)
            where l.tag in ('AndroidRuntime', 'libc', 'DEBUG') order by l.ts""")
    except Exception:
        return []


def _java_crashes(lines, pkg, pids):
    blocks, cur = [], None
    for ln in lines:
        if ln["tag"] != "AndroidRuntime":
            continue
        msg = ln["msg"] or ""
        if msg.startswith("FATAL EXCEPTION"):
            cur = {"ts": ln["ts"], "last": ln["ts"], "utid": ln["utid"], "pid": ln["pid"],
                   "pkg": None, "lines": [msg]}
            blocks.append(cur)
        elif cur and ln["utid"] == cur["utid"] and ln["ts"] - cur["last"] <= _REPORT_GAP_NS:
            cur["lines"].append(msg)
            cur["last"] = ln["ts"]
            m = _PROCESS_LINE.match(msg)
            if m:
                cur["pkg"], cur["pid"] = m["pkg"], int(m["pid"])
    out = []
    for b in blocks:
        if b["pkg"] != pkg and not (b["pkg"] is None and b["pid"] in pids):
            continue
        exc = next((x for x in b["lines"][1:]
                    if not x.startswith("Process:") and not x.lstrip().startswith("at ")), "")
        out.append({"ts": b["ts"], "kind": "java",
                    "signature": exc.partition(": ")[0].strip() or "FATAL EXCEPTION",
                    "message": exc or b["lines"][0], "log": "\n".join(b["lines"]), "pid": b["pid"]})
    return out


def _native_crashes(lines, pkg, pids):
    tombs, writing = [], {}
    for ln in lines:
        if ln["tag"] != "DEBUG":
            continue
        msg = ln["msg"] or ""
        if msg.startswith(_TOMBSTONE_START):
            writing[ln["utid"]] = t = {"ts": ln["ts"], "lines": [msg], "pid": None, "pkg": None, "used": False}
            tombs.append(t)
            continue
        t = writing.get(ln["utid"])
        if t is None:
            continue
        t["lines"].append(msg)
        m = _TOMBSTONE_HEAD.match(msg)
        if m:
            t["pid"], t["pkg"] = int(m["pid"]), m["pkg"]
    mine = [t for t in tombs if t["pkg"] == pkg]
    out = []
    for ln in lines:
        m = _FATAL_SIGNAL.match(ln["msg"] or "") if ln["tag"] == "libc" else None
        if not m or int(m["pid"]) not in pids:
            continue
        pid = int(m["pid"])
        t = next((t for t in mine if t["pid"] == pid and not t["used"] and t["ts"] >= ln["ts"]), None)
        if t:
            t["used"] = True
        out.append({"ts": ln["ts"], "kind": "native", "signature": m["sig"], "message": ln["msg"],
                    "log": "\n".join([ln["msg"]] + (t["lines"] if t else [])), "pid": pid})
    # A tombstone whose libc line never reached the trace is still a crash.
    for t in mine:
        if t["used"]:
            continue
        sig = next((s.group(1) for s in map(_SIGNAL_NAME.search, t["lines"]) if s), "native crash")
        out.append({"ts": t["ts"], "kind": "native", "signature": sig,
                    "message": next((x for x in t["lines"] if x.startswith("signal ")), None),
                    "log": "\n".join(t["lines"]), "pid": t["pid"]})
    return out


def _by_signature(crashes):
    """{signature: {count, message}} over every crash, not only the listed
    ones: triage opens one issue per signature, and a crash loop longer than
    the list must not hide another kind."""
    out = {}
    for c in crashes:
        g = out.setdefault(c["signature"], {"count": 0, "message": c["message"]})
        g["count"] += 1
    return out


def crash(tp, upids, platform, src, pkg=None, wins=None):
    """Every time the app died on its own during the recording."""
    if platform == "ios":
        died = src.get("crashed") in ("1", True)
        reason = (src.get("termination") or None) if died else None
        events = [{"start_ms": None, "kind": "ios", "signature": reason or "crash", "message": reason,
                   "log": None, "screen": None, "pid": None}] if died else []
        return {"measured": True, "crashed": died, "reason": reason, "count": len(events),
                "by_signature": _by_signature(events), "events": events}
    cfg = _config(tp)
    if cfg is not None and 'name: "android.log"' not in cfg:
        return {"measured": False, "crashed": False, "reason": None, "count": None,
                "by_signature": {}, "events": []}
    wins = _screen_windows(tp) if wins is None else wins
    pids = ({r["pid"] for r in _rows(tp, f"select pid from process where upid in ({_ids(upids)})")}
            if upids else set())
    lines = _crash_lines(tp)
    found = sorted(_java_crashes(lines, pkg, pids) + _native_crashes(lines, pkg, pids),
                   key=lambda c: c["ts"])
    events = [{"start_ms": round(c["ts"] / 1e6, 2), "kind": c["kind"], "signature": c["signature"],
               "message": c["message"], "log": c["log"], "screen": _screen_at(wins, c["ts"]),
               "pid": c["pid"]} for c in found]
    reason = (events[0]["message"] or events[0]["signature"])[:200] if events else None
    return {"measured": True, "crashed": bool(events), "reason": reason, "count": len(events),
            "by_signature": _by_signature(events), "events": events[:MAX_EVENTS]}


def extract_stability(tp, pkg, platform=None):
    """Hangs, JS errors, ANRs and crashes for the app in one trace."""
    src = trace_source(tp)
    platform = platform or src["platform"]
    upids = _app_upids(tp, pkg, platform) if pkg else []
    wins = _screen_windows(tp)
    return {"hangs": hangs(tp, upids, platform, wins),
            "errors": errors(tp, upids, platform, wins),
            "anrs": anrs(tp, pkg, upids, platform, wins),
            "crash": crash(tp, upids, platform, src, pkg, wins)}
