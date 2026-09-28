"""Crash logs from adb logcat, for traces whose log source delivered nothing.

On some phones Perfetto's `android.log` data source records no line at all
(B-011: the V2514, vivo on Android 16, records none even with no filters),
while `adb logcat` on the same phone has every line. Then crashes and JS
error records never reach the trace, and a run would read "0 crashes" as if
measured. So after every Android session swagperf reads the session's window
of logcat and appends it to the trace as log packets. The trace stays
self-contained, `reextract` keeps the lines, and stability.py reads them as
if Perfetto had recorded them.

A probe line, written at the start of every session under PROBE_TAG, tells
"no crash" from "no log": a trace whose config asks for the log but that has
no line at all, not even the probe, measured no crashes (stability.crash).
"""
import re, subprocess

from perfetto.protos.perfetto.trace.perfetto_trace_pb2 import Trace

PROBE_TAG = "SwagPerfProbe"
# The tags capture.LOG_SOURCE keeps: the app's error records, crash reports
# (Kotlin/Java, libc's fatal signal, crash_dump's tombstone) and the probe.
TAGS = ("SwagPerfError", "AndroidRuntime", "DEBUG", "libc", PROBE_TAG)
_PRIORITY = {"V": 2, "D": 3, "I": 4, "W": 5, "E": 6, "F": 7, "A": 7}
# `logcat -v epoch,usec`:  "  1759049162.296123 28036 28036 E AndroidRuntime: FATAL EXCEPTION: main"
_LINE = re.compile(r"^\s*(\d+)\.(\d+)\s+(\d+)\s+(\d+)\s+([VDIWEFA])\s+(.*?)\s*: (.*)$")
# Appended packets get their own sequence, apart from traced's.
_SEQUENCE = 0xB011


def parse(text):
    """logcat lines -> [(realtime ns, pid, tid, priority, tag, message)].
    Buffer banners and anything else that isn't a log line are skipped."""
    out = []
    for line in (text or "").splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        sec, frac, pid, tid, prio, tag, msg = m.groups()
        ns = int(sec) * 1_000_000_000 + int(frac.ljust(9, "0")[:9])
        out.append((ns, int(pid), int(tid), _PRIORITY[prio], tag.strip(), msg))
    return out


def probe(serial):
    """The session's probe line, written once tracing is live."""
    try:
        subprocess.run(["adb", "-s", serial, "shell", "log", "-t", PROBE_TAG, "swagperf session"],
                       capture_output=True, timeout=15)
    except (subprocess.SubprocessError, OSError):
        pass


def _read(serial):
    """The phone's retained logcat lines for TAGS, main and crash buffers."""
    cmd = ["adb", "-s", serial, "logcat", "-d", "-v", "epoch,usec", "-b", "main,crash",
           "-s", *[f"{t}:V" for t in TAGS]]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
    except (subprocess.SubprocessError, OSError):
        return ""


def _session(trace_path):
    """The trace's time span in realtime ns, and whether it has log lines;
    None when the trace can't place wall-clock times (no realtime clock)."""
    from perfetto.trace_processor import TraceProcessor
    from .extract import _rows
    tp = TraceProcessor(trace=trace_path)
    try:
        has_logs = bool(_rows(tp, "select 1 as x from android_logs limit 1"))
        b = _rows(tp, "select start_ts as s, end_ts as e from trace_bounds")[0]
        snap = _rows(tp, """select ts, clock_value as v from clock_snapshot
                            where clock_name = 'REALTIME' order by ts limit 1""")
    finally:
        tp.close()
    if not snap or b.get("s") is None:
        return None
    offset = snap[0]["v"] - snap[0]["ts"]
    return {"has_logs": has_logs, "start": b["s"] + offset, "end": b["e"] + offset}


def import_into(trace_path, serial=None, *, read=None):
    """Append the session's window of logcat to a trace that has no log line.
    A trace whose log source worked is left alone, so nothing is doubled.
    Returns how many lines were added."""
    s = _session(trace_path)
    if not s or s["has_logs"]:
        return 0
    text = read() if read else (_read(serial) if serial else "")
    lines = [ln for ln in parse(text) if s["start"] <= ln[0] <= s["end"]]
    if not lines:
        return 0
    t = Trace()
    p = t.packet.add()
    p.trusted_packet_sequence_id = _SEQUENCE
    for ns, pid, tid, prio, tag, msg in lines:
        ev = p.android_log.events.add()
        ev.timestamp, ev.pid, ev.tid, ev.prio, ev.tag, ev.message = ns, pid, tid, prio, tag, msg
    with open(trace_path, "ab") as f:
        f.write(t.SerializeToString())
    return len(lines)
