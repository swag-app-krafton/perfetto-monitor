"""A synthetic Android session with everything stability.py reads.

Built with Perfetto's own protos, because it needs packets the byte-level
generators in synth.py don't write: logcat lines, atrace counters and a
recorded trace config. It writes app main-thread slices, screen slices on
their own track, the app's JS error markers and SwagErrors records, the ANR
counters system_server writes, and crash logs (AndroidRuntime from the app,
libc's fatal-signal line, and crash_dump's tombstone from its own process).
The tests build their traces with it, and so does the run skill's demo
session (synth_android.gen_device_session(stability=True)).
"""
import json

from perfetto.protos.perfetto.trace.perfetto_trace_pb2 import Trace, TrackEvent

MS = 1_000_000
SYS_PID, DUMP_PID = 1500, 5000
INFO, ERROR, FATAL = 4, 6, 7          # Android log priorities


class Session:
    """An app process with a main thread and a screen track, plus
    system_server and crash_dump. `others` adds (pid, process name) pairs: a
    restarted app, or another app on the phone."""

    def __init__(self, pkg="com.swag.pay", pid=4000, *, others=()):
        self.pkg, self.pid = pkg, pid
        self.t = Trace()
        self._uuid = 10
        self._logs = []
        self._main = {}
        p = self._pkt()
        # Log timestamps are on the realtime clock; a snapshot maps it onto
        # the boot clock, as every real device trace has.
        for clock_id in (6, 1):           # BUILTIN_CLOCK_BOOTTIME, BUILTIN_CLOCK_REALTIME
            c = p.clock_snapshot.clocks.add()
            c.clock_id, c.timestamp = clock_id, 0
        p = self._pkt()
        for ppid, name in [(pid, pkg), (SYS_PID, "system_server"),
                           (DUMP_PID, "/system/bin/crash_dump64"), *others]:
            pr = p.process_tree.processes.add()
            pr.pid, pr.ppid = ppid, 1
            pr.cmdline.append(name)
            th = p.process_tree.threads.add()
            th.tid, th.tgid, th.name = ppid, ppid, name.rsplit("/", 1)[-1][:15]
        for ppid, _ in [(pid, pkg), *others]:
            self.main_thread(ppid)
        u, d = self._desc()
        d.process.pid = pid
        proc = u
        u, d = self._desc()
        d.parent_uuid, d.name = proc, "screens"
        self._screens = u

    # -------------------------------------------------------------- plumbing

    def _pkt(self):
        p = self.t.packet.add()
        p.trusted_packet_sequence_id = 1
        return p

    def _desc(self):
        self._uuid += 1
        p = self._pkt()
        p.track_descriptor.uuid = self._uuid
        return self._uuid, p.track_descriptor

    def _event(self, track, ts_ms, kind, name=None):
        p = self._pkt()
        p.timestamp = int(ts_ms * MS)
        p.track_event.type = kind
        p.track_event.track_uuid = track
        if name is not None:
            p.track_event.name = name

    def main_thread(self, pid):
        """The track of process `pid`'s main thread (tid == pid)."""
        if pid not in self._main:
            u, d = self._desc()
            d.thread.pid, d.thread.tid = pid, pid
            self._main[pid] = u
        return self._main[pid]

    # ---------------------------------------------------------------- events

    def config(self, *, sources, atrace=()):
        """The trace's recorded config: data source names, and the atrace
        categories of its linux.ftrace source."""
        p = self._pkt()
        for name in sources:
            ds = p.trace_config.data_sources.add()
            ds.config.name = name
            if name == "linux.ftrace":
                ds.config.ftrace_config.atrace_categories.extend(atrace)

    def slice(self, ts_ms, dur_ms, name, pid=None):
        """A slice on a main thread: the app's unless `pid` says otherwise."""
        tr = self.main_thread(pid or self.pid)
        self._event(tr, ts_ms, TrackEvent.TYPE_SLICE_BEGIN, name)
        self._event(tr, ts_ms + dur_ms, TrackEvent.TYPE_SLICE_END)

    def screen(self, ts_ms, dur_ms, route):
        """A screen visit, `route` as the app writes it (`Home#compose`)."""
        self._event(self._screens, ts_ms, TrackEvent.TYPE_SLICE_BEGIN, f"screen:{route}")
        self._event(self._screens, ts_ms + dur_ms, TrackEvent.TYPE_SLICE_END)

    def log(self, ts_ms, tag, msg, *, pid=None, prio=ERROR):
        pid = pid or self.pid
        self._logs.append((pid, pid, ts_ms, prio, tag, msg))

    def js_error(self, ts_ms, rid, *, name="TypeError", fatal=False, source="global", message="x",
                 stack="TypeError: x\n    at a (address at index.android.bundle:1:9)"):
        """The app's `error:js:` marker on its main thread, and its record in logcat."""
        self._event(self.main_thread(self.pid), ts_ms, TrackEvent.TYPE_INSTANT,
                    f"error:js:{source}:{name}#{'fatal' if fatal else 'nonfatal'}@{rid}")
        rec = json.dumps({"id": rid, "name": name, "message": message, "stack": stack})
        self.log(ts_ms, "SwagPerfError", f"swagerr|{rid}|1/1|{rec}", prio=INFO)

    def anr(self, ts_ms, error_id, subject, *, pid=None, process=None):
        """The two atrace counters ActivityManager writes from system_server
        when it declares an ANR."""
        pid, process = pid or self.pid, process or self.pkg
        p = self._pkt()
        b = p.ftrace_events
        b.cpu = 0
        for buf in (f"C|{SYS_PID}|ErrorId:{process} {pid}#{error_id}|1\n",
                    f"C|{SYS_PID}|Subject(for ErrorId {error_id}):{subject}|1\n"):
            ev = b.event.add()
            ev.timestamp, ev.pid = int(ts_ms * MS), SYS_PID
            ev.print.buf = buf

    def java_crash(self, ts_ms, *, exc="java.lang.IllegalStateException", message="boom",
                   frames=("com.swag.pay.Home.render(Home.kt:10)",), pid=None, process=None):
        """AndroidRuntime's report from the crashing process, a log entry per line."""
        pid, process = pid or self.pid, process or self.pkg
        lines = ["FATAL EXCEPTION: main", f"Process: {process}, PID: {pid}", f"{exc}: {message}",
                 *(f"\tat {f}" for f in frames)]
        for i, line in enumerate(lines):
            self.log(ts_ms + i * 0.1, "AndroidRuntime", line, pid=pid)

    def native_crash(self, ts_ms, *, signal=11, name="SIGSEGV", pid=None, process=None,
                     backtrace=("#00 pc 000000000008a1c4  /apex/com.android.runtime/lib64/bionic/libc.so (syscall+4)",),
                     libc=True, tombstone=True, writer=DUMP_PID):
        """libc's line from the crashing app, then crash_dump's tombstone,
        written from crash_dump's own process (`writer`)."""
        pid, process = pid or self.pid, process or self.pkg
        short = process[:15]
        if libc:
            self.log(ts_ms, "libc", f"Fatal signal {signal} ({name}), code 0 (SI_USER from pid 1, uid 0) "
                                    f"in tid {pid} ({short}), pid {pid} ({short})", pid=pid, prio=FATAL)
        if not tombstone:
            return
        lines = ["*** *** *** *** *** *** *** *** *** *** *** *** *** *** *** ***",
                 f"pid: {pid}, tid: {pid}, name: {short}  >>> {process} <<<",
                 f"signal {signal} ({name}), code 0 (SI_USER), fault addr --------",
                 "backtrace:", *(f"      {b}" for b in backtrace)]
        for i, line in enumerate(lines):
            self.log(ts_ms + 100 + i * 0.1, "DEBUG", line, pid=writer, prio=FATAL)

    def bytes(self):
        """The trace. Call once: it writes the log lines."""
        p = self._pkt()
        for pid, tid, ts_ms, prio, tag, msg in sorted(self._logs, key=lambda x: x[2]):
            ev = p.android_log.events.add()
            ev.pid, ev.tid, ev.timestamp = pid, tid, int(ts_ms * MS)
            ev.prio, ev.tag, ev.message = prio, tag, msg
        return self.t.SerializeToString()
