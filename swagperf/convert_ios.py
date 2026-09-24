"""Convert an xctrace recording into a Perfetto trace.

Everything this tool measures is Perfetto SQL (extract.py, screens.py,
derive.py), so an iOS run is normalised into the slice and counter shapes the
Android markers produce instead of being read by a second extractor:

  app markers (os_signpost, subsystem com.swag.pay.trace)
      span            -> slice on the emitting thread's track
      screen/sub/nav  -> async slice on a process-scoped track
      event           -> instant on the emitting thread
      counter         -> process counter, from its "name=value" message
  RAM usage           -> process counter `mem.rss` (physical footprint)
  launch              -> `swagperf.launch:*` slices on a Launch track, from
                         dyld's intervals and Apple's launch-measurement signposts
  hangs               -> `swagperf.hang:<type>` slices on a Hangs track
  error records       -> one instant per record, `swagperf.error_record:<id>`,
                         its JSON in the `record` arg, reassembled from the
                         app's `os_log` lines (SwagErrors in the app)
  provenance          -> one instant, `swagperf.source:platform=ios;...`

The process is named with the bundle id, which is how extract.py finds an
app. The original `.trace` stays beside the output for Instruments.
"""
from perfetto.protos.perfetto.trace.perfetto_trace_pb2 import Trace, TracePacket, TrackEvent

from . import xctrace as xt

APP_SUBSYSTEM = "com.swag.pay.trace"
LAUNCH_SUBSYSTEM = "com.apple.app_launch_measurement"
SOURCE_PREFIX = "swagperf.source:"
LAUNCH_PREFIX = "swagperf.launch:"
HANG_PREFIX = "swagperf.hang:"
END_MARKER = "swagperf.recording_end"
ERROR_RECORD_PREFIX = "swagperf.error_record:"
ERROR_CATEGORY = "errors"

# The async families and their single-slot ids (swagsignpost.def), which the
# app reuses like the Android cookies. Pairing is by (family, marker).
ASYNC_FAMILIES = ("screen", "sub", "nav")

SEQ = 1


class _Builder:
    """TrackEvent packets on one sequence, emitted in timestamp order."""

    def __init__(self):
        self.trace = Trace()
        self.events = []  # (ts, order, fill)
        self._uuid = 1000
        self._n = 0

    def uuid(self):
        self._uuid += 1
        return self._uuid

    def descriptor(self, fill):
        p = self.trace.packet.add()
        p.trusted_packet_sequence_id = SEQ
        fill(p.track_descriptor)
        return p

    def event(self, ts, fill):
        self._n += 1
        self.events.append((ts, self._n, fill))

    def serialize(self):
        for ts, _, fill in sorted(self.events, key=lambda e: (e[0], e[1])):
            p = self.trace.packet.add()
            p.timestamp = max(int(ts), 0)
            p.trusted_packet_sequence_id = SEQ
            fill(p.track_event)
        return self.trace.SerializeToString()


def _begin(track, name):
    def f(te):
        te.type = TrackEvent.TYPE_SLICE_BEGIN
        te.track_uuid = track
        te.name = name
    return f


def _end(track):
    def f(te):
        te.type = TrackEvent.TYPE_SLICE_END
        te.track_uuid = track
    return f


def _instant(track, name, args=None):
    def f(te):
        te.type = TrackEvent.TYPE_INSTANT
        te.track_uuid = track
        te.name = name
        for k, v in (args or {}).items():
            a = te.debug_annotations.add()
            a.name = k
            a.string_value = str(v)
    return f


def _count(track, value):
    def f(te):
        te.type = TrackEvent.TYPE_COUNTER
        te.track_uuid = track
        te.double_counter_value = float(value)
    return f


def _thread_name(cell):
    """`Main Thread (0x2665b1) (Swag Pay, pid: 99692)` -> `Main Thread`."""
    f = xt.fmt(cell) or ""
    return f.split(" (0x", 1)[0].strip() or None


def _pid_of(row):
    return xt.num(xt.kid(xt.kid(row.get("thread"), "process"), "pid")) \
        or xt.num(xt.kid(row.get("process"), "pid"))


def _tid_of(row):
    return xt.num(xt.kid(row.get("thread"), "tid"))


def convert(tables, *, bundle_id, pid, source, memory=None, end_ns=None):
    """Build the Perfetto trace. Returns (trace bytes, report).

    tables: parsed rows by schema name ('os-signpost', 'dyld-activity-interval',
            'potential-hangs'); any may be missing.
    source: provenance written into the trace, e.g. {"platform": "ios",
            "simulator": 1, "device": "iPhone 17", "os": "27.0", "xctrace": "27.0"}.
    memory: [(trace_ns, bytes)] RAM usage samples, when captured.
    end_ns: when the recording stopped. Marked with an instant so the trace
            spans the whole recording: screens.py clamps a screen still open at
            the end to the last event, which would otherwise be whatever the app
            last emitted.
    """
    b = _Builder()
    rep = {"app_signposts": 0, "spans": 0, "async_slices": 0, "instants": 0,
           "counters": 0, "open_at_end": 0, "unmatched_ends": 0, "overflow_tracks": 0,
           "launch": {}, "hangs": 0, "memory_samples": 0,
           "error_records": 0, "error_records_incomplete": 0}

    proc = b.uuid()
    b.descriptor(lambda td: (setattr(td, "uuid", proc),
                             setattr(td.process, "pid", pid),
                             setattr(td.process, "process_name", bundle_id)))

    threads = {}

    def thread_track(tid, name):
        if tid not in threads:
            u = b.uuid()
            threads[tid] = u
            b.descriptor(lambda td: (setattr(td, "uuid", u),
                                     setattr(td.thread, "pid", pid),
                                     setattr(td.thread, "tid", tid),
                                     setattr(td.thread, "thread_name", name or f"thread {tid}")))
        return threads[tid]

    def child_track(name):
        u = b.uuid()
        b.descriptor(lambda td: (setattr(td, "uuid", u), setattr(td, "parent_uuid", proc),
                                 setattr(td, "name", name)))
        return u

    counters = {}

    def counter_track(name):
        if name not in counters:
            u = b.uuid()
            counters[name] = u

            def fill(td):
                td.uuid = u
                td.parent_uuid = proc
                td.name = name
                td.counter.SetInParent()
            b.descriptor(fill)
        return counters[name]

    signposts = [r for r in tables.get("os-signpost") or [] if _pid_of(r) in (pid, None)]

    # Provenance at the recording's start, so every reader can tell the
    # platform from the trace alone; and the recording's end, so the trace
    # covers all of it.
    tag = ";".join(f"{k}={v}" for k, v in source.items() if v not in (None, ""))
    b.event(0, _instant(proc, SOURCE_PREFIX + tag))
    if end_ns:
        b.event(end_ns, _instant(proc, END_MARKER))

    _app_markers(b, signposts, thread_track, child_track, counter_track, proc, rep)
    _launch(b, signposts, tables.get("dyld-activity-interval") or [], pid,
            child_track, rep)
    _hangs(b, tables.get("potential-hangs") or [], pid, child_track, rep)
    _error_records(b, tables.get("os-log") or [], pid, proc, rep)

    if memory:
        t = counter_track("mem.rss")
        for ts, value in memory:
            b.event(ts, _count(t, value))
        rep["memory_samples"] = len(memory)

    return b.serialize(), rep


def _app_markers(b, rows, thread_track, child_track, counter_track, proc, rep):
    open_spans = {}          # signpost id -> track
    async_open = {}          # (family, marker) -> track
    pools = {f: [] for f in ASYNC_FAMILIES}   # family -> [[track, busy]]

    def pool_track(family):
        for slot in pools[family]:
            if not slot[1]:
                slot[1] = True
                return slot[0]
        if pools[family]:
            rep["overflow_tracks"] += 1
        u = child_track(family)
        pools[family].append([u, True])
        return u

    def release(family, track):
        for slot in pools[family]:
            if slot[0] == track:
                slot[1] = False

    for r in sorted(rows, key=lambda r: xt.num(r.get("time")) or 0):
        if xt.fmt(r.get("subsystem")) != APP_SUBSYSTEM:
            continue
        rep["app_signposts"] += 1
        ts = xt.num(r["time"])
        kind = xt.fmt(r.get("event-type"))
        family = xt.fmt(r.get("name"))
        marker = xt.fmt(r.get("message")) or ""
        sid = xt.raw(r.get("identifier"))
        tid = _tid_of(r)

        if family == "span":
            if kind == "Begin":
                t = thread_track(tid, _thread_name(r.get("thread")))
                open_spans[sid] = t
                b.event(ts, _begin(t, marker))
                rep["spans"] += 1
            elif kind == "End":
                t = open_spans.pop(sid, None)
                if t is None:
                    rep["unmatched_ends"] += 1
                else:
                    b.event(ts, _end(t))
        elif family in ASYNC_FAMILIES:
            key = (family, marker)
            if kind == "Begin":
                if key in async_open:
                    # Reopened without a close: end the stale one here.
                    old = async_open.pop(key)
                    b.event(ts, _end(old))
                    release(family, old)
                t = pool_track(family)
                async_open[key] = t
                b.event(ts, _begin(t, marker))
                rep["async_slices"] += 1
            elif kind == "End":
                t = async_open.pop(key, None)
                if t is None:
                    rep["unmatched_ends"] += 1
                else:
                    b.event(ts, _end(t))
                    release(family, t)
        elif family == "event":
            b.event(ts, _instant(thread_track(tid, _thread_name(r.get("thread"))), marker))
            rep["instants"] += 1
        elif family == "counter":
            name, _, value = marker.rpartition("=")
            try:
                b.event(ts, _count(counter_track(name), float(value)))
                rep["counters"] += 1
            except ValueError:
                pass

    # Left open: Perfetto records these as unfinished (dur = -1), which
    # screens.py clamps to the end of the trace, as it does on Android.
    rep["open_at_end"] = len(open_spans) + len(async_open)


def _first(rows, name):
    ts = [xt.num(r["time"]) for r in rows
          if xt.fmt(r.get("subsystem")) == LAUNCH_SUBSYSTEM and xt.fmt(r.get("name")) == name
          and xt.fmt(r.get("event-type")) == "End"]
    return min(ts) if ts else None


def _child_name(row):
    """A pre-main interval's name, grouped so repeated work sums per library."""
    kind = xt.fmt(row.get("type")) or "dyld"
    desc = xt.fmt(row.get("description")) or ""
    lib = desc.rsplit(" ", 1)[-1].rsplit("/", 1)[-1] if " " in desc else ""
    if kind == "Static Initializer":
        return f"static init: {lib}" if lib else "static init"
    if kind == "Objc Image Init":
        return f"objc init: {lib}" if lib else "objc init"
    if kind == "dlopen":
        return f"dlopen: {lib}" if lib else "dlopen"
    return kind.lower()


def _launch(b, signposts, dyld, pid, child_track, rep):
    """Launch phases, from process start to the app becoming responsive.

    Start is dyld's outermost "Launch Executable" (the process exec); pre-main
    ends with its inner one. The first frame and the responsive point are
    Apple's own launch-measurement signposts, the ones XCTest's launch metric
    and Xcode Organizer read. The App Launch template's life-cycle table is
    empty on the simulator, so it is not relied on.
    """
    mine = [r for r in dyld if _pid_of(r) in (pid, None)]
    outer = [r for r in mine if xt.fmt(r.get("type")) == "Launch Executable"
             and xt.fmt(r.get("level")) == "1"]
    inner = [r for r in mine if xt.fmt(r.get("type")) == "Launch Executable"
             and xt.fmt(r.get("level")) == "2"]
    start = xt.num(outer[0]["start"]) if outer else None
    pre_main_end = (xt.num(inner[0]["start"]) + xt.num(inner[0]["duration"])) if inner else None
    first_frame = _first(signposts, "ApplicationFirstFramePresentation")
    responsive = _first(signposts, "ApplicationFirstFramePresentationResponsive") \
        or _first(signposts, "ApplicationLaunchExtendedResponsive")
    rep["launch"] = {"process_start": start, "pre_main_end": pre_main_end,
                     "first_frame": first_frame, "responsive": responsive}
    if start is None or first_frame is None or first_frame <= start:
        return

    track = child_track("Launch")
    phases = []
    if pre_main_end and start < pre_main_end < first_frame:
        phases += [("pre_main", start, pre_main_end), ("main_to_first_frame", pre_main_end, first_frame)]
    else:
        phases += [("to_first_frame", start, first_frame)]
    if responsive and responsive > first_frame:
        phases.append(("first_frame_to_responsive", first_frame, responsive))

    for name, s, e in phases:
        b.event(s, _begin(track, LAUNCH_PREFIX + name))
        if name == "pre_main":
            # Its direct dyld children, sequential and wholly inside it; the
            # extractor reads them as the step's breakdown.
            kids = sorted((r for r in mine if xt.fmt(r.get("level")) == "3"),
                          key=lambda r: xt.num(r["start"]))
            last_end = s
            for r in kids:
                ks, kd = xt.num(r["start"]), xt.num(r["duration"])
                if ks is None or kd is None or ks < last_end or ks + kd > e:
                    continue
                b.event(ks, _begin(track, _child_name(r)))
                b.event(ks + kd, _end(track))
                last_end = ks + kd
        b.event(e, _end(track))


def _hangs(b, rows, pid, child_track, rep):
    mine = sorted((r for r in rows if _pid_of(r) in (pid, None)),
                  key=lambda r: xt.num(r.get("start")) or 0)
    if not mine:
        return
    track = child_track("Hangs")
    last_end = None
    for r in mine:
        s, d = xt.num(r.get("start")), xt.num(r.get("duration"))
        if s is None or d is None or (last_end is not None and s < last_end):
            continue
        kind = (xt.fmt(r.get("hang-type")) or "Hang").strip()
        b.event(s, _begin(track, HANG_PREFIX + kind))
        b.event(s + d, _end(track))
        last_end = s + d
        rep["hangs"] += 1


def _error_records(b, rows, pid, proc, rep):
    """The app's error records, rebuilt from their log lines.

    SwagErrors writes each record as `swagerr|<id>|<seq>/<total>|<chunk>`
    lines, because a record is longer than one log line may be. A record
    missing a chunk is counted and dropped rather than parsed half-read.
    """
    from .stability import assemble_records
    lines = []
    for r in sorted(rows, key=lambda r: xt.num(r.get("time")) or 0):
        if xt.fmt(r.get("subsystem")) != APP_SUBSYSTEM or xt.fmt(r.get("category")) != ERROR_CATEGORY:
            continue
        if _pid_of(r) not in (pid, None):
            continue
        lines.append((xt.num(r["time"]), xt.fmt(r.get("message")) or ""))
    records, incomplete = assemble_records(lines)
    for rec_id, (ts, text) in records.items():
        b.event(ts, _instant(proc, ERROR_RECORD_PREFIX + rec_id, {"record": text}))
    rep["error_records"] = len(records)
    rep["error_records_incomplete"] = incomplete
