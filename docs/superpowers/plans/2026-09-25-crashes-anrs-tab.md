# Crashes & ANRs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record ANRs and every crash (with its crash log) from Android traces, and show JS exceptions, ANRs and crashes together on one dashboard tab, "Crashes & ANRs", with hangs moved to Frame pacing.

**Architecture:** Measurement stays in `swagperf/stability.py` (Perfetto SQL in, a dict out): ANRs come from the trace processor's `android.anrs` module, crashes from the `AndroidRuntime`, `libc` and `DEBUG` log lines the Android configs already record. The run row gains `anr_count` and `crash_count`; the analyst and triage raise both. The React dashboard renames the Stability screen to Crashes & ANRs (one time-ordered event list built by a pure domain function) and moves the hangs block into Frame pacing.

**Tech Stack:** Python 3 (unittest, `perfetto` trace processor v49 prebuilt, protos from `perfetto.protos`), React + TypeScript (Vite, vitest, oxlint), the in-repo design system `frontend/src/design`.

**Spec:** `docs/superpowers/specs/2026-09-25-crashes-anrs-tab-design.md` (F-028 in `docs/TRACKER.md`).

## Global Constraints

- Say "RAM usage" and "RAM growth", never "RSS", in anything a reader sees (AGENTS.md → Wording). Say "North Star target", never "budget", in anything a reader sees (F-027); code names and keys stay.
- Dashboard pages use only `frontend/src/design` components: no raw controls, no inline styles (T-003's oxlint rule).
- Unmeasured is never zero: a count the run didn't measure is `None`/`null` and reads "not measured".
- Never judge or label another app with Swag Pay's names: every crash and ANR is matched to the run's own package.
- **Commit each task, staging only its own hunks** (the user asked for commits on 2026-09-25). Other sessions edit the same files (`server.py`, `analyst.py`, `routes.ts`, `TRACKER.md`, the run skill) at the same time. For a file that also carries another session's changes, build the staged blob from `HEAD` plus this task's hunks (`git update-index --cacheinfo`), and check `git diff --cached` before every commit. Never revert a change you didn't make, never switch branches, and never run `swagperf.cli seed`, `capture` or `analyse` from the repo root (they write the user's `history.db` and `traces/`).
- Python tests: `./.venv/bin/python -m unittest tests.test_stability -v` per task; the whole suite (`./.venv/bin/python -m unittest discover -s tests`, ~3 min) once, in Task 10. Frontend: `cd frontend && npm test`, `npm run lint`, `npm run typecheck`.

## Review Focus

1. **A run recorded before this change** (its `stability_json` has no `anrs`, and `crash` is only `{crashed, reason}`) must render: ANRs "not measured", crashes 1 or 0 from `crashed`, and one crash row from `reason`. Pinned by `incidents.test.ts` "reads a run recorded before…" (Task 6) and `test_old_stability_still_signals` (Task 5).
2. **The app crashes, restarts and crashes again** in one flow run: two processes with the same package. Both crashes count and both are listed. Pinned by `test_a_restarted_app_crashes_twice` (Task 3).
3. **Another app crashes or ANRs during the run**: device logs and ANR counters are system-wide. Its crash, tombstone and ANR are never the app's. Pinned by `test_another_apps_crash_is_ignored` (Task 3) and `test_another_apps_anr_is_not_the_apps` (Task 2).
4. **A trace recorded without the log source or the `am` category** (run #1): crashes or ANRs read "not measured", never 0. Pinned by `test_a_trace_without_the_log_source_measures_no_crashes` (Task 3), `test_a_trace_without_the_am_category_measures_no_anrs` (Task 2) and `incidents.test.ts` (Task 6).
5. **A long flow run with more than 100 events**: counts stay complete while the lists cap at `MAX_EVENTS`. Pinned by `test_counts_stay_whole_past_the_event_cap` (Task 3).

---

### Task 0: Phone check (a real ANR, a Kotlin/Java crash and a native crash in one trace)

The project's rule: verify instrumentation in a real trace before changing extraction. This task changes no repo code. It decides whether Task 4 (the event-log fallback) is needed, and its lines become the reference for the synthetic fixtures.

**Files:**
- Create (scratchpad only): `$SCRATCH/phone_check.py`, `$SCRATCH/phone_check.pftrace`, where `$SCRATCH` is the session scratchpad directory.
- Modify: `docs/superpowers/specs/2026-09-25-crashes-anrs-tab-design.md` (append a "Phone check, 2026-09-25" section with the findings).

- [ ] **Step 1: Check the phone is attached and free**

```bash
adb devices -l                                    # expect the V2514 as "device"
./.venv/bin/python -m swagperf.cli manual status   # expect nothing recording
adb shell ps -A | grep -E "perfetto|BAMPerfProfiler|atrace" || true   # expect no other profiler
```

If anything is recording, stop and ask the user: another session owns the phone.

- [ ] **Step 2: Check the installed Swag Pay is debuggable**

```bash
adb shell run-as com.swag.pay id
```

Expected: `uid=… (u0_a…)`. If it prints `run-as: package not debuggable`, stop and ask the user before installing anything. Freezing and signalling the app needs `run-as`.

- [ ] **Step 3: Write the session script**

It starts a manual session with the event-log ANR line added to the log source, so one session answers both questions. It triggers the three events and writes the trace to the scratchpad. It never records a run in `history.db`.

```python
# $SCRATCH/phone_check.py -- run from the repo root
import subprocess, sys, time
sys.path.insert(0, ".")
from swagperf import capture

PKG = "com.swag.pay"
OUT = sys.argv[1]
# The trial source: today's LOG_SOURCE plus the events buffer's am_anr line.
capture.LOG_SOURCE = capture.LOG_SOURCE.replace(
    "log_ids: LID_DEFAULT log_ids: LID_CRASH",
    "log_ids: LID_DEFAULT log_ids: LID_CRASH log_ids: LID_EVENTS").replace(
    'filter_tags: "libc"', 'filter_tags: "libc" filter_tags: "am_anr"')

def sh(*a):
    return subprocess.run(["adb", "shell", *a], capture_output=True, text=True).stdout.strip()

def launch():
    sh("monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")
    time.sleep(6)

capture.manual_start(pkg=PKG, cold=True)
time.sleep(8)
# 1. ANR: freeze the main thread, then touch the screen twice.
pid = sh("pidof", PKG)
sh("run-as", PKG, "kill", "-STOP", pid)
for _ in range(2):
    sh("input", "tap", "540", "1200")
    time.sleep(1)
time.sleep(12)
sh("run-as", PKG, "kill", "-CONT", pid)
time.sleep(2)
sh("input", "keyevent", "KEYCODE_BACK")          # leave the ANR dialog
sh("am", "force-stop", PKG)
launch()
# 2. Kotlin/Java crash.
sh("am", "crash", PKG)
time.sleep(4)
launch()
# 3. Native crash.
pid = sh("pidof", PKG)
sh("run-as", PKG, "kill", "-SEGV", pid)
time.sleep(6)
print(capture.manual_stop(OUT))
```

- [ ] **Step 4: Run it**

```bash
./.venv/bin/python "$SCRATCH/phone_check.py" "$SCRATCH/phone_check.pftrace"
```

Expected: the trace path printed. If the ANR dialog didn't appear (watch the phone), freeze for longer and repeat.

- [ ] **Step 5: Read what the trace holds**

```bash
./.venv/bin/python - "$SCRATCH/phone_check.pftrace" <<'EOF'
import sys
from perfetto.trace_processor import TraceProcessor
tp = TraceProcessor(trace=sys.argv[1])
q = lambda s: [dict(r.__dict__) for r in tp.query(s)]
print("ANRS", q("include perfetto module android.anrs; select process_name, pid, error_id, ts, anr_type, subject, anr_dur_ms, default_anr_dur_ms from android_anrs"))
print("COUNTERS", q("select distinct t.name from process_counter_track t where t.name glob 'ErrorId:*' or t.name glob 'Subject(for ErrorId*'"))
for r in q("""select l.ts, l.tag, p.pid, p.name, l.msg from android_logs l
              left join thread t using (utid) left join process p using (upid)
              where l.tag in ('AndroidRuntime','libc','DEBUG','am_anr') order by l.ts"""):
    print(r)
tp.close()
EOF
```

- [ ] **Step 6: Record the findings in the spec**

Append this to the spec, filled with what Step 5 printed:
- whether `android_anrs` had the ANR, with its type, subject and durations;
- the exact `AndroidRuntime` lines, including the `Process:` line and the exception line from `am crash`;
- the `libc` line, the `DEBUG` header line and the pid of the process that wrote the `DEBUG` lines;
- the `am_anr` line, if any.

**Decision:** if `android_anrs` is empty but the ANR happened, do Task 4. Otherwise skip Task 4.

If a real line's format differs from what Task 1's `Session` writes (e.g. the tombstone header), change `Session` to write the real format before Task 2.

---

### Task 1: A synthetic Android session builder

One builder for every Android stability fixture: the tests (Tasks 2, 3, 5) and the run skill's demo session (Task 9).

**Files:**
- Create: `swagperf/synth_stability.py`
- Modify: `tests/test_stability.py` (`_android_trace()` rebuilt on `Session`; new `_stability()` helper)

**Interfaces:**
- Produces: `synth_stability.Session(pkg="com.swag.pay", pid=4000, *, others=())` with methods `config(*, sources, atrace=())`, `slice(ts_ms, dur_ms, name, pid=None)`, `screen(ts_ms, dur_ms, route)`, `log(ts_ms, tag, msg, *, pid=None, prio=ERROR)`, `js_error(ts_ms, rid, *, name="TypeError", fatal=False, source="global", message="x", stack=…)`, `anr(ts_ms, error_id, subject, *, pid=None, process=None)`, `java_crash(ts_ms, *, exc=…, message="boom", frames=…, pid=None, process=None)`, `native_crash(ts_ms, *, signal=11, name="SIGSEGV", pid=None, process=None, backtrace=…, libc=True, tombstone=True, writer=DUMP_PID)`, `bytes() -> bytes`. Constants `SYS_PID = 1500`, `DUMP_PID = 5000`, `MS`, `INFO`, `ERROR`, `FATAL`.
- Produces (tests): `_stability(data: bytes, pkg="com.swag.pay") -> dict`, the result of `stability.extract_stability` on that trace.

- [ ] **Step 1: Write `swagperf/synth_stability.py`**

```python
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
```

- [ ] **Step 2: Rebuild the test's Android trace on `Session`**

In `tests/test_stability.py`, replace the import line and the whole `_android_trace()` function:

```python
from swagperf import analyst, extract as ex, sourcemaps, stability, store, triage
from swagperf.synth_ios import Recording
from swagperf.synth_stability import Session
```

```python
def _android_trace():
    """An Android app: a first frame, then main-thread stalls, a JS error's
    marker and record in logcat, and a crash."""
    s = Session()
    s.slice(100, 300, "bindApplication")               # startup
    s.slice(500, 20, "Choreographer#doFrame 1")        # the first frame ends at 520 ms
    s.slice(1000, 320, "Choreographer#doFrame 2")      # a hang
    s.slice(2000, 180, "binder transaction")           # a microhang
    s.js_error(3000, "k1", fatal=True)
    s.java_crash(3001)
    return s.bytes()


def _stability(data, pkg="com.swag.pay"):
    from perfetto.trace_processor import TraceProcessor
    tp = TraceProcessor(trace=_write(data))
    try:
        return stability.extract_stability(tp, pkg, "android")
    finally:
        tp.close()
```

Then simplify `TestAndroidStability.test_main_thread_stalls_logcat_records_and_crash` to use the helper (same assertions):

```python
    def test_main_thread_stalls_logcat_records_and_crash(self):
        st = _stability(_android_trace())
        h = st["hangs"]
        self.assertEqual((h["count"], h["microhangs"], h["startup"]["count"]), (1, 1, 1))
        self.assertEqual(h["source"], "the app's main-thread slices")
        e = st["errors"]
        self.assertEqual((e["js"], e["js_fatal"]), (1, 1))
        self.assertIn("index.android.bundle", e["events"][0]["stack"])
        self.assertTrue(st["crash"]["crashed"])
```

Also drop `Trace, TrackEvent` from the protos import at the top if nothing else in the file uses them (`grep -n "TrackEvent\|Trace()" tests/test_stability.py`).

- [ ] **Step 3: Run the stability tests**

Run: `./.venv/bin/python -m unittest tests.test_stability -v`
Expected: all PASS. The builder change keeps every existing assertion.

---

### Task 2: ANRs in `stability.py`

**Files:**
- Modify: `swagperf/stability.py` (module docstring; new `ANR_TYPES`, `ANR_WINDOW_MS`, `_q`, `_ids`, `_config`, `_main_thread_work`, `anrs`; `extract_stability`)
- Test: `tests/test_stability.py` (new `TestAnrs`)

**Interfaces:**
- Consumes: `Session`, `_stability` (Task 1).
- Produces: `stability.anrs(tp, pkg, upids, platform, wins=None) -> {"measured": bool, "count": int|None, "by_type": {type: n}, "per_screen": {screen: n}, "events": [{"id", "start_ms", "type", "type_label", "subject", "dur_ms", "screen", "main_thread": {"name", "dur_ms"}|None}]}`; `extract_stability(...)["anrs"]`; `stability._config(tp) -> str|None`, `stability._ids(upids) -> str`, `stability._q(s) -> str` (used by Task 3).

- [ ] **Step 1: Write the failing tests**

Add after `TestAndroidStability` in `tests/test_stability.py`:

```python
ANR_SUBJECT = ("Input dispatching timed out (1f2 com.swag.pay/com.swag.pay.MainActivity "
               "is not responding. Waited 5001ms for MotionEvent)")


def _session(build, pkg="com.swag.pay", **kw):
    """A session with a first frame and a Home visit, then `build(s)`."""
    s = Session(pkg, **kw)
    s.slice(500, 20, "Choreographer#doFrame 1")
    s.screen(600, 20_000, "Home#compose")
    build(s)
    return _stability(s.bytes(), pkg)


class TestAnrs(unittest.TestCase):

    def test_an_anr_names_its_type_screen_and_main_thread_work(self):
        def build(s):
            s.slice(3000, 5600, "binder transaction")    # the stall behind the ANR
            s.anr(8500, "e1", ANR_SUBJECT)
        a = _session(build)["anrs"]
        self.assertEqual((a["measured"], a["count"]), (True, 1))
        ev = a["events"][0]
        self.assertEqual((ev["id"], ev["start_ms"]), ("e1", 8500.0))
        self.assertEqual(ev["type"], "INPUT_DISPATCHING_TIMEOUT")
        self.assertEqual(ev["type_label"], "A touch or key went unanswered")
        self.assertEqual(ev["subject"], ANR_SUBJECT)
        self.assertEqual(ev["dur_ms"], 5000)
        self.assertEqual(ev["screen"], "Home")
        self.assertEqual(ev["main_thread"], {"name": "binder transaction", "dur_ms": 5600.0})
        self.assertEqual(a["by_type"], {"INPUT_DISPATCHING_TIMEOUT": 1})
        self.assertEqual(a["per_screen"], {"Home": 1})

    def test_an_anr_with_nothing_traced_on_the_main_thread(self):
        a = _session(lambda s: s.anr(9000, "e1", ANR_SUBJECT))["anrs"]
        self.assertIsNone(a["events"][0]["main_thread"])

    def test_another_apps_anr_is_not_the_apps(self):
        a = _session(lambda s: s.anr(8000, "e2", ANR_SUBJECT, pid=6000, process="com.other.app"),
                     others=[(6000, "com.other.app")])["anrs"]
        self.assertEqual((a["measured"], a["count"], a["events"]), (True, 0, []))

    def test_a_trace_without_the_am_category_measures_no_anrs(self):
        def build(s):
            s.config(sources=["linux.ftrace", "android.log"], atrace=["view"])
            s.anr(8000, "e3", ANR_SUBJECT)
        a = _session(build)["anrs"]
        self.assertEqual((a["measured"], a["count"]), (False, None))

    def test_ios_has_no_anrs(self):
        m, _ = _ios(lambda r: None)
        a = m["stability"]["anrs"]
        self.assertEqual((a["measured"], a["count"]), (False, None))
```

- [ ] **Step 2: Run them to see them fail**

Run: `./.venv/bin/python -m unittest tests.test_stability.TestAnrs -v`
Expected: FAIL with `KeyError: 'anrs'`.

- [ ] **Step 3: Implement**

In `swagperf/stability.py`, add to the module docstring after the **JS errors** block:

```
**ANRs** (Android only) are declared by the system, not the app: when
ActivityManager declares one it writes two atrace counters from
system_server under the `am` category, `ErrorId:<process> <pid>#<id>` and
`Subject(for ErrorId <id>):<subject>`. The trace processor's android.anrs
module joins them into `android_anrs`. Each ANR names the screen on display
and the longest main-thread slice in the window before it.
```

Add helpers after `_loads`:

```python
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
```

Add a section after the hangs section:

```python
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
```

Update `extract_stability`:

```python
def extract_stability(tp, pkg, platform=None):
    """Hangs, JS errors, ANRs and crashes for the app in one trace."""
    src = trace_source(tp)
    platform = platform or src["platform"]
    upids = _app_upids(tp, pkg, platform) if pkg else []
    wins = _screen_windows(tp)
    return {"hangs": hangs(tp, upids, platform, wins),
            "errors": errors(tp, upids, platform, wins),
            "anrs": anrs(tp, pkg, upids, platform, wins),
            "crash": crash(tp, upids, platform, src)}
```

- [ ] **Step 4: Run the tests**

Run: `./.venv/bin/python -m unittest tests.test_stability -v`
Expected: all PASS.

---

### Task 3: Every crash, with its crash log

**Files:**
- Modify: `swagperf/stability.py` (crashes section: `_ANDROID_CRASH` removed; `_FATAL_SIGNAL`, `_PROCESS_LINE`, `_TOMBSTONE_HEAD`, `_crash_lines`, `_java_crashes`, `_native_crashes`, new `crash`; `extract_stability` passes `pkg` and `wins`)
- Test: `tests/test_stability.py` (new `TestCrashes`; `TestCrash.test_ios_crash_comes_from_the_provenance` extended)

**Interfaces:**
- Consumes: `_config`, `_ids` (Task 2); `Session` (Task 1).
- Produces: `stability.crash(tp, upids, platform, src, pkg=None, wins=None) -> {"measured": bool, "crashed": bool, "reason": str|None, "count": int|None, "events": [{"start_ms": float|None, "kind": "java"|"native"|"ios", "signature": str, "message": str|None, "log": str|None, "screen": str|None, "pid": int|None}]}`.

- [ ] **Step 1: Write the failing tests**

```python
class TestCrashes(unittest.TestCase):

    def test_a_java_crash_is_reassembled_from_its_log_lines(self):
        c = _session(lambda s: s.java_crash(4000, frames=("a.B.c(B.kt:1)", "a.B.d(B.kt:2)")))["crash"]
        self.assertEqual((c["measured"], c["crashed"], c["count"]), (True, True, 1))
        ev = c["events"][0]
        self.assertEqual((ev["kind"], ev["signature"]), ("java", "java.lang.IllegalStateException"))
        self.assertEqual(ev["message"], "java.lang.IllegalStateException: boom")
        self.assertEqual(ev["log"].splitlines(), ["FATAL EXCEPTION: main", "Process: com.swag.pay, PID: 4000",
                                                  "java.lang.IllegalStateException: boom",
                                                  "\tat a.B.c(B.kt:1)", "\tat a.B.d(B.kt:2)"])
        self.assertEqual((ev["screen"], ev["pid"], ev["start_ms"]), ("Home", 4000, 4000.0))
        self.assertEqual(c["reason"], "java.lang.IllegalStateException: boom")

    def test_a_native_crash_carries_crash_dumps_tombstone(self):
        c = _session(lambda s: s.native_crash(5000))["crash"]
        self.assertEqual(c["count"], 1)
        ev = c["events"][0]
        self.assertEqual((ev["kind"], ev["signature"], ev["pid"]), ("native", "SIGSEGV", 4000))
        self.assertTrue(ev["message"].startswith("Fatal signal 11 (SIGSEGV)"))
        self.assertIn(">>> com.swag.pay <<<", ev["log"])
        self.assertIn("backtrace:", ev["log"])

    def test_a_tombstone_without_its_libc_line_is_still_a_crash(self):
        c = _session(lambda s: s.native_crash(5000, libc=False))["crash"]
        self.assertEqual((c["count"], c["events"][0]["signature"]), (1, "SIGSEGV"))

    def test_another_apps_crash_is_ignored(self):
        def build(s):
            s.java_crash(3000, pid=6000, process="com.other.app")
            s.native_crash(4000, pid=6000, process="com.other.app", writer=5001)
        c = _session(build, others=[(6000, "com.other.app")])["crash"]
        self.assertEqual((c["measured"], c["crashed"], c["count"]), (True, False, 0))

    def test_a_restarted_app_crashes_twice(self):
        def build(s):
            s.java_crash(3000)
            s.native_crash(9000, pid=4100, writer=5001)
        c = _session(build, others=[(4100, "com.swag.pay")])["crash"]
        self.assertEqual(c["count"], 2)
        self.assertEqual([e["kind"] for e in c["events"]], ["java", "native"])
        self.assertEqual([e["pid"] for e in c["events"]], [4000, 4100])

    def test_a_trace_without_the_log_source_measures_no_crashes(self):
        def build(s):
            s.config(sources=["linux.ftrace"], atrace=["am"])
            s.java_crash(3000)
        c = _session(build)["crash"]
        self.assertEqual((c["measured"], c["crashed"], c["count"]), (False, False, None))

    def test_counts_stay_whole_past_the_event_cap(self):
        def build(s):
            for i in range(stability.MAX_EVENTS + 5):
                s.java_crash(1000 + i * 20)
        c = _session(build)["crash"]
        self.assertEqual(c["count"], stability.MAX_EVENTS + 5)
        self.assertEqual(len(c["events"]), stability.MAX_EVENTS)
```

Extend `TestCrash.test_ios_crash_comes_from_the_provenance`:

```python
    def test_ios_crash_comes_from_the_provenance(self):
        m, _ = _ios(lambda r: r.js_error(3000, fatal=True), crashed="SIGABRT")
        c = m["stability"]["crash"]
        self.assertTrue(c["crashed"])
        self.assertEqual(c["reason"], "SIGABRT")
        self.assertEqual((c["count"], c["events"][0]["kind"], c["events"][0]["signature"]), (1, "ios", "SIGABRT"))
        m, _ = _ios(lambda r: None)
        self.assertFalse(m["stability"]["crash"]["crashed"])
        self.assertEqual(m["stability"]["crash"]["count"], 0)
```

- [ ] **Step 2: Run them to see them fail**

Run: `./.venv/bin/python -m unittest tests.test_stability.TestCrashes tests.test_stability.TestCrash -v`
Expected: FAIL (`KeyError: 'measured'` / `'count'`).

- [ ] **Step 3: Implement**

Replace the `**Crashes:**` block of the module docstring with:

```
**Crashes:**
  - iOS: how xctrace saw the process end, carried in the trace's provenance.
  - Android, every one in the run, with its crash log:
    - Kotlin/Java: AndroidRuntime's report (`FATAL EXCEPTION`, `Process:
      <pkg>, PID: <pid>`, the exception, a line per frame), reassembled;
    - native: libc's `Fatal signal` line from the app, joined to the
      tombstone crash_dump writes from its own process, whose header names
      the app (`pid: N, … >>> <pkg> <<<`).
  A trace recorded without the android.log source measured none.
```

Replace everything from `_ANDROID_CRASH = …` through the end of the old `crash()` with:

```python
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


def crash(tp, upids, platform, src, pkg=None, wins=None):
    """Every time the app died on its own during the recording."""
    if platform == "ios":
        died = src.get("crashed") in ("1", True)
        reason = (src.get("termination") or None) if died else None
        events = [{"start_ms": None, "kind": "ios", "signature": reason or "crash", "message": reason,
                   "log": None, "screen": None, "pid": None}] if died else []
        return {"measured": True, "crashed": died, "reason": reason, "count": len(events), "events": events}
    cfg = _config(tp)
    if cfg is not None and 'name: "android.log"' not in cfg:
        return {"measured": False, "crashed": False, "reason": None, "count": None, "events": []}
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
    return {"measured": True, "crashed": bool(events), "reason": reason,
            "count": len(events), "events": events[:MAX_EVENTS]}
```

In `extract_stability`, pass the package and screens:

```python
            "crash": crash(tp, upids, platform, src, pkg, wins)}
```

- [ ] **Step 4: Run the tests**

Run: `./.venv/bin/python -m unittest tests.test_stability -v`
Expected: all PASS. The old Android test still sees `crashed` True.

---

### Task 4 (only if Task 0 found `android_anrs` empty): ANRs from the event log

**Files:**
- Modify: `swagperf/capture.py` (`LOG_SOURCE`)
- Modify: `swagperf/stability.py` (`anrs` also reads `am_anr` lines)
- Test: `tests/test_stability.py`

- [ ] **Step 1: Add the events buffer to `LOG_SOURCE`**

```python
# The app's error records (SwagErrors, tag SwagPerfError), crash reports
# (AndroidRuntime's FATAL EXCEPTION, libc's fatal signal, crash_dump's
# tombstone under DEBUG) and the system's ANR line (am_anr, events buffer).
# Filtered to those tags, so the log adds kilobytes, not the whole logcat.
LOG_SOURCE = """data_sources: { config { name: "android.log" android_log_config {
  log_ids: LID_DEFAULT log_ids: LID_CRASH log_ids: LID_EVENTS
  filter_tags: "SwagPerfError" filter_tags: "AndroidRuntime" filter_tags: "DEBUG" filter_tags: "libc"
  filter_tags: "am_anr"
} } }"""
```

- [ ] **Step 2: Write the failing test**

Use the `am_anr` line exactly as Task 0 recorded it, as `AM_ANR_LINE`:

```python
    def test_an_anr_from_the_event_log(self):
        a = _session(lambda s: s.log(8500, "am_anr", AM_ANR_LINE, pid=1500, prio=4))["anrs"]
        self.assertEqual(a["count"], 1)
        self.assertIn("Input dispatching timed out", a["events"][0]["subject"])
```

- [ ] **Step 3: Implement**

In `anrs()`, after the `android_anrs` rows, read `am_anr` lines that name the package and aren't already there (same second):

```python
    seen = {round(r["ts"] / 1e9) for r in rows}
    for ln in _rows(tp, "select ts, msg from android_logs where tag = 'am_anr' order by ts"):
        msg = ln["msg"] or ""
        if pkg and pkg in msg and round(ln["ts"] / 1e9) not in seen:
            subject = msg.rsplit(",", 1)[-1].strip(" ]") or None
            rows.append({"error_id": f"am_anr@{ln['ts']}", "ts": ln["ts"], "anr_type": None,
                         "subject": subject, "anr_dur_ms": None, "default_anr_dur_ms": None})
    rows.sort(key=lambda r: r["ts"])
```

If Task 0's line puts the reason somewhere else than its last comma-separated field, parse it from where the recorded line has it.

- [ ] **Step 4: Run the tests**

Run: `./.venv/bin/python -m unittest tests.test_stability -v`
Expected: all PASS.

---

### Task 5: Run data, analyst and triage

**Files:**
- Modify: `swagperf/store.py` (`MIGRATIONS`, `_stability_cols`, new `_write_stability`, `record`, `reextract`, `METRIC_DIRECTION`)
- Modify: `swagperf/analyst.py` (`_stability_summary`, `stability_findings`)
- Modify: `swagperf/triage.py` (`signals_of` stability part, new `_slug`, `_context`)
- Test: `tests/test_stability.py` (`TestStabilityDownstream`)

**Interfaces:**
- Consumes: the stability dict of Tasks 2 and 3.
- Produces: run columns `anr_count int`, `crash_count int`; `store.METRIC_DIRECTION["anr_count"|"crash_count"] = "lower"`; finding kinds `crash`, `anr`; signal keys `anr:<type>:<app>:<path>` and `crash:<signature>:<app>:<path>`.

- [ ] **Step 1: Write the failing tests**

Replace `TestStabilityDownstream.test_stored_findings_and_signals` and add three tests:

```python
    def test_stored_findings_and_signals(self):
        m, _ = _ios(lambda r: (r.js_error(2000, fatal=True), r.hang(3000, 400)),
                    crashed="SIGSEGV")
        db = os.path.join(tempfile.mkdtemp(), "h.db")
        rid = store.record(m, device="iPhone 17", db=db)
        row = store.run_row(rid, db=db)
        self.assertEqual((row["hang_count"], row["js_errors"], row["crashed"]), (1, 1, 1))
        self.assertEqual((row["crash_count"], row["anr_count"]), (1, None))   # iOS: no ANRs
        kinds = {f["kind"] for f in analyst.heuristic(m, [])["findings"]}
        self.assertTrue({"crash", "js_error", "hang"} <= kinds)
        run = {"id": rid, "app_pkg": "com.example.ios", "path_kind": "cold", "platform": "ios",
               "stability": json.loads(row["stability_json"]), "breaches": [], "violations": []}
        keys = {s["key"] for s in triage.signals_of(run, [])}
        self.assertIn("js_error:TypeError:ios:com.example.ios:cold", keys)
        self.assertIn("crash:SIGSEGV:ios:com.example.ios:cold", keys)

    def test_android_anrs_and_crashes_are_stored_found_and_signalled(self):
        def build(s):
            s.anr(8500, "e1", ANR_SUBJECT)
            s.java_crash(9000)
            s.java_crash(15000)
        st = _session(build)
        m, _ = _ios(lambda r: None)
        m["stability"] = st
        db = os.path.join(tempfile.mkdtemp(), "h.db")
        rid = store.record(m, device="V2514", db=db)
        row = store.run_row(rid, db=db)
        self.assertEqual((row["anr_count"], row["crash_count"], row["crashed"]), (1, 2, 1))
        findings = {f["kind"]: f for f in analyst.stability_findings({"stability": st})}
        self.assertEqual(findings["anr"]["severity"], "high")
        self.assertIn("2 times", findings["crash"]["title"])
        self.assertIn("Crashes & ANRs", findings["crash"]["recommendation"])
        run = {"id": rid, "app_pkg": "com.swag.pay", "path_kind": "cold", "platform": "android",
               "stability": st, "breaches": [], "violations": []}
        sig = {s["key"]: s for s in triage.signals_of(run, [])}
        self.assertEqual(sig["anr:INPUT_DISPATCHING_TIMEOUT:com.swag.pay:cold"]["value"], 1)
        self.assertEqual(sig["crash:java.lang.IllegalStateException:com.swag.pay:cold"]["value"], 2)
        self.assertEqual(triage._key_scope("anr:INPUT_DISPATCHING_TIMEOUT:com.swag.pay:cold"),
                         ("com.swag.pay", "cold"))
        ctx = triage._context(sig["anr:INPUT_DISPATCHING_TIMEOUT:com.swag.pay:cold"], run, [], None)
        self.assertIn("/crashes", json.dumps(ctx["links"]))
        self.assertNotIn("risk", ctx)   # not the ordering-violation advice (S-02)

    def test_old_stability_still_signals(self):
        """stability_json written before ANRs and crash lists (F-028)."""
        st = {"hangs": {}, "errors": {"events": []}, "crash": {"crashed": True, "reason": "FATAL EXCEPTION: main"}}
        run = {"id": 1, "app_pkg": "com.swag.pay", "path_kind": "cold", "platform": "android",
               "stability": st, "breaches": [], "violations": []}
        keys = {s["key"] for s in triage.signals_of(run, [])}
        self.assertIn("crash:app:com.swag.pay:cold", keys)
        self.assertEqual([f["kind"] for f in analyst.stability_findings({"stability": st})], ["crash"])

    def test_compare_diffs_anrs_and_crashes(self):
        self.assertEqual(store.METRIC_DIRECTION["anr_count"], "lower")
        self.assertEqual(store.METRIC_DIRECTION["crash_count"], "lower")
```

- [ ] **Step 2: Run them to see them fail**

Run: `./.venv/bin/python -m unittest tests.test_stability.TestStabilityDownstream -v`
Expected: FAIL (`KeyError: 'crash_count'`, missing keys).

- [ ] **Step 3: Implement the store**

In `MIGRATIONS`, after `("runs", "stability_json", "text"),`:

```python
    # F-028: ANRs and every crash, counted for sorting and Compare. Null for
    # runs recorded before, and where the trace didn't measure them.
    ("runs", "anr_count", "int"),
    ("runs", "crash_count", "int"),
```

Replace `_stability_cols` and add `_write_stability` below it:

```python
def _stability_cols(metrics):
    st = metrics.get("stability") or {}
    h, e, cr, a = (st.get(k) or {} for k in ("hangs", "errors", "crash", "anrs"))
    crashes = cr.get("count") if "count" in cr else (int(bool(cr.get("crashed"))) if cr else None)
    return (h.get("count"), h.get("longest_ms"), e.get("js"), int(bool(cr.get("crashed"))),
            a.get("count"), crashes, json.dumps(st) if st else None)


def _write_stability(c, rid, metrics):
    c.execute("""update runs set hang_count=?, longest_hang_ms=?, js_errors=?, crashed=?,
                 anr_count=?, crash_count=?, stability_json=? where id=?""",
              (*_stability_cols(metrics), rid))
```

In `record()` and in `reextract()`, replace each of the two `c.execute("""update runs set hang_count=?, …""", (*_stability_cols(…), …))` statements with:

```python
    _write_stability(c, rid, metrics)          # in record()
```

```python
        _write_stability(c, r["id"], m)        # in reextract()
```

In `METRIC_DIRECTION`, extend the stability line:

```python
    "hang_count": "lower", "longest_hang_ms": "lower", "js_errors": "lower",
    "anr_count": "lower", "crash_count": "lower",
```

- [ ] **Step 4: Implement the analyst**

Replace `_stability_summary`:

```python
def _stability_summary(st):
    if not st:
        return None
    h, e, cr, a = (st.get(k) or {} for k in ("hangs", "errors", "crash", "anrs"))
    return {"hangs": {k: h.get(k) for k in ("count", "microhangs", "longest_ms", "total_ms",
                                            "rate_s_per_hr", "startup", "per_screen")},
            "js_errors": {k: e.get(k) for k in ("js", "js_fatal", "by_name", "by_source", "per_screen")},
            "anrs": {k: a.get(k) for k in ("measured", "count", "by_type", "per_screen")} if a else None,
            "crashed": bool(cr.get("crashed")),
            "crashes": {"count": cr.get("count"),
                        "signatures": [c.get("signature") for c in (cr.get("events") or [])][:5]}}
```

Replace the crash block at the top of `stability_findings`, and add the ANR block after the JS errors block. Point the hang recommendation at Frame pacing:

```python
    cr = st.get("crash") or {}
    if cr.get("crashed"):
        n = cr.get("count") or 1
        sigs = ", ".join(dict.fromkeys(c.get("signature") for c in (cr.get("events") or []) if c.get("signature")))
        out.append({"title": "The app crashed during the run" if n == 1 else f"The app crashed {n} times during the run",
                    "runtime": "unknown", "severity": "high", "kind": "crash",
                    "evidence": sigs or cr.get("reason") or "the process ended on its own",
                    "architectural_risk": None,
                    "recommendation": "Open Crashes & ANRs for the crash log. A fatal JS error just "
                                      "before a crash points at React Native; none points at native code."})
```

```python
    a = st.get("anrs") or {}
    if a.get("count"):
        types = ", ".join(f"{k} ×{v}" for k, v in sorted((a.get("by_type") or {}).items(), key=lambda kv: -kv[1]))
        screens = ", ".join(sorted(a.get("per_screen") or {}))
        out.append({"title": f"{a['count']} ANR(s): Android declared the app not responding",
                    "runtime": "unknown", "severity": "high", "kind": "anr",
                    "evidence": f"{types} on {screens}" if screens else types,
                    "architectural_risk": None,
                    "recommendation": "Open Crashes & ANRs: each ANR names the screen and what the "
                                      "main thread was doing."})
```

In the JS errors finding, change the recommendation to `"Open Crashes & ANRs for the resolved stack and the screen each error happened on."`, and in the hang finding to `"Open Frame pacing: each hang names the screen it happened on."`.

- [ ] **Step 5: Implement triage**

Add near `_where`:

```python
def _slug(s):
    """A signal key's subject: no whitespace, at most 80 characters."""
    return re.sub(r"[^A-Za-z0-9_.$-]+", "_", s or "")[:80] or "app"
```

(add `import re` at the top of `triage.py` if it isn't imported).

Replace the crash block in `signals_of` with one signal per crash signature and one per ANR type:

```python
    st = run.get("stability") or {}
    cr = st.get("crash") or {}
    crashes = cr.get("events")
    if crashes is None and cr.get("crashed"):     # recorded before crash lists (F-028)
        crashes = [{"signature": "app", "message": cr.get("reason")}]
    groups = {}
    for c in crashes or []:
        g = groups.setdefault(_slug(c.get("signature")), {"n": 0, "detail": c.get("message")})
        g["n"] += 1
    for sig, g in sorted(groups.items()):
        out.append({"key": f"crash:{sig}:{app}:{path}", "kind": "crash", "subject": sig,
                    "title": "The app crashed during the run" if sig == "app" else f"The app crashed: {sig}",
                    "unit": "", "value": g["n"], "reference": None, "reference_kind": None,
                    "over_pct": None, "severity": "high", "detail": g["detail"]})
    anr_groups = {}
    for a in (st.get("anrs") or {}).get("events") or []:
        g = anr_groups.setdefault(_slug(a.get("type")), {"n": 0, "label": a.get("type_label"), "detail": a.get("subject")})
        g["n"] += 1
    for typ, g in sorted(anr_groups.items()):
        out.append({"key": f"anr:{typ}:{app}:{path}", "kind": "anr", "subject": typ,
                    "title": f"ANR: {g['label'] or typ}", "unit": "", "value": g["n"],
                    "reference": None, "reference_kind": None, "over_pct": None,
                    "severity": "high", "detail": g["detail"]})
```

In `_context`, add a branch before the final `else:` so these kinds stop getting the ordering-violation advice (TESTING-PLAN S-02):

```python
    elif kind in ("crash", "anr", "js_error"):
        ctx["next_check"] = {
            "crash": "Open Crashes & ANRs and read the crash log; a fatal JS error just before it points at React Native.",
            "anr": "Open Crashes & ANRs: the ANR names the screen and what the main thread was doing.",
            "js_error": "Open Crashes & ANRs for the resolved stack and the screen it happened on.",
        }[kind]
        links.append(_link("Crashes & ANRs", f"/crashes?run={rid}"))
```

Check `_link`'s signature (`grep -n "def _link" swagperf/triage.py`) and call it with the arguments it takes. The existing calls pass `(label, path)` or `(label, path, focus)`.

- [ ] **Step 6: Run the tests**

Run: `./.venv/bin/python -m unittest tests.test_stability tests.test_triage -v`
Expected: all PASS. If a `test_triage` test pinned the old `crash:app:` key or context, update it to the new key and context. Update only tests about crash signals.

---

### Task 6: Frontend types and the incidents domain function

**Files:**
- Modify: `frontend/src/api/types.ts` (`Run`, `Stability`, new `AnrEvent`, `CrashEvent`)
- Create: `frontend/src/domain/incidents.ts`
- Test: `frontend/src/domain/incidents.test.ts`

**Interfaces:**
- Produces: `type IncidentKind = 'js' | 'anr' | 'crash'`, `type IncidentFilter = IncidentKind | 'all'`, `type Incident`; `incidentsOf(st: Stability): Incident[]`, `filterIncidents(list: Incident[], f: IncidentFilter): Incident[]`, `incidentCounts(st: Stability): { js: number | null; anr: number | null; crash: number | null }`.

- [ ] **Step 1: Add the types**

In `frontend/src/api/types.ts`, in `Run` after `crashed: number | null`:

```ts
  /** ANRs and crashes in the run (F-028). Null before F-028, and where the trace didn't measure them. */
  anr_count?: number | null
  crash_count?: number | null
```

After `JsErrorEvent`:

```ts
export interface AnrEvent {
  id: string
  start_ms: number
  /** The trace processor's type, e.g. INPUT_DISPATCHING_TIMEOUT. */
  type: string
  /** The type in plain words. */
  type_label: string
  /** The system's reason line. */
  subject: string | null
  /** The timeout behind it, in ms, when known. */
  dur_ms: number | null
  screen: string | null
  /** The longest main-thread slice in the window before the ANR. */
  main_thread: { name: string; dur_ms: number } | null
}

export interface CrashEvent {
  /** Null on iOS, where the recording says only that the process crashed. */
  start_ms: number | null
  kind: 'java' | 'native' | 'ios' | 'unknown'
  /** The exception class or signal name. */
  signature: string
  message: string | null
  /** The whole crash log: stack or tombstone. */
  log: string | null
  screen: string | null
  pid: number | null
}
```

In `Stability`, add `anrs` and replace `crash`:

```ts
  /** Absent for runs recorded before F-028. */
  anrs?: {
    measured: boolean
    count: number | null
    by_type: Record<string, number>
    per_screen: Record<string, number>
    events: AnrEvent[]
  }
  crash: { crashed: boolean; reason: string | null; measured?: boolean; count?: number | null; events?: CrashEvent[] }
```

- [ ] **Step 2: Write the failing test**

```ts
// frontend/src/domain/incidents.test.ts
import { describe, expect, it } from 'vitest'
import type { Stability } from '@/api/types'
import { filterIncidents, incidentCounts, incidentsOf } from './incidents'

const st = (over: Partial<Stability> = {}): Stability => ({
  hangs: { count: 0, microhangs: 0, longest_ms: null, total_ms: 0, rate_s_per_hr: null, session_s: 10, startup: { count: 0, microhangs: 0, longest_ms: null }, per_screen: {}, events: [], source: 'the app\'s main-thread slices' },
  errors: {
    js: 1, js_fatal: 1, by_name: {}, by_source: {}, per_screen: {},
    events: [{ id: 'k1', start_ms: 3000, name: 'TypeError', source: 'global', fatal: true, screen: 'Home', message: 'x', stack: null, component_stack: null, has_record: true }],
  },
  anrs: {
    measured: true, count: 1, by_type: {}, per_screen: {},
    events: [{ id: 'e1', start_ms: 1000, type: 'INPUT_DISPATCHING_TIMEOUT', type_label: 'A touch or key went unanswered', subject: null, dur_ms: 5000, screen: 'Home', main_thread: null }],
  },
  crash: {
    measured: true, crashed: true, reason: 'boom', count: 1,
    events: [{ start_ms: 3001, kind: 'java', signature: 'java.lang.IllegalStateException', message: 'boom', log: 'FATAL EXCEPTION: main', screen: 'Home', pid: 4000 }],
  },
  ...over,
})

describe('incidents', () => {
  it('puts every kind in one list, in time order', () => {
    const list = incidentsOf(st())
    expect(list.map((i) => i.kind)).toEqual(['anr', 'js', 'crash'])
    expect(list.map((i) => i.name)).toEqual(['A touch or key went unanswered', 'TypeError', 'java.lang.IllegalStateException'])
    expect(list.map((i) => i.fatal)).toEqual([false, true, true])
  })

  it('filters by kind', () => {
    const list = incidentsOf(st())
    expect(filterIncidents(list, 'crash').map((i) => i.kind)).toEqual(['crash'])
    expect(filterIncidents(list, 'all')).toHaveLength(3)
  })

  it('keeps a crash with no time at the end', () => {
    const ios = st({ anrs: { measured: false, count: null, by_type: {}, per_screen: {}, events: [] }, crash: { measured: true, crashed: true, reason: 'SIGABRT', count: 1, events: [{ start_ms: null, kind: 'ios', signature: 'SIGABRT', message: 'SIGABRT', log: null, screen: null, pid: null }] } })
    expect(incidentsOf(ios).map((i) => i.kind)).toEqual(['js', 'crash'])
    expect(incidentCounts(ios)).toEqual({ js: 1, anr: null, crash: 1 })
  })

  it('reads a run recorded before ANRs and crash lists as not measured, not zero', () => {
    const old = st({ anrs: undefined, crash: { crashed: true, reason: 'FATAL EXCEPTION: main' } })
    expect(incidentCounts(old)).toEqual({ js: 1, anr: null, crash: 1 })
    const crashes = incidentsOf(old).filter((i) => i.kind === 'crash')
    expect(crashes).toHaveLength(1)
    expect(crashes[0]!.name).toBe('Crash')
  })

  it('says a trace without the crash log did not measure crashes', () => {
    const none = st({ crash: { measured: false, crashed: false, reason: null, count: null, events: [] } })
    expect(incidentCounts(none).crash).toBeNull()
  })
})
```

- [ ] **Step 3: Run it to see it fail**

Run: `cd frontend && npx vitest run src/domain/incidents.test.ts`
Expected: FAIL, "Failed to resolve import './incidents'".

- [ ] **Step 4: Implement**

```ts
// frontend/src/domain/incidents.ts
import type { AnrEvent, CrashEvent, JsErrorEvent, Stability } from '@/api/types'

/** JS exceptions, ANRs and crashes of one run, as one list (stability.py). */
export type IncidentKind = 'js' | 'anr' | 'crash'
export type IncidentFilter = IncidentKind | 'all'

interface Base {
  key: string
  start_ms: number | null
  name: string
  screen: string | null
  fatal: boolean
}
export type Incident = (Base & { kind: 'js'; js: JsErrorEvent }) | (Base & { kind: 'anr'; anr: AnrEvent }) | (Base & { kind: 'crash'; crash: CrashEvent })

/** A run recorded before crash lists (F-028) says only whether it crashed. */
const crashesOf = (st: Stability): CrashEvent[] =>
  st.crash.events ?? (st.crash.crashed ? [{ start_ms: null, kind: 'unknown', signature: 'Crash', message: st.crash.reason, log: null, screen: null, pid: null }] : [])

/** Every JS exception, ANR and crash, in time order, so a fatal JS error just
 *  before a crash reads as its cause. A crash with no time (iOS) goes last:
 *  the app ended there. */
export function incidentsOf(st: Stability): Incident[] {
  const list: Incident[] = [
    ...st.errors.events.map((e): Incident => ({ kind: 'js', key: `js:${e.id}`, start_ms: e.start_ms, name: e.name, screen: e.screen, fatal: e.fatal, js: e })),
    ...(st.anrs?.events ?? []).map((a): Incident => ({ kind: 'anr', key: `anr:${a.id}`, start_ms: a.start_ms, name: a.type_label, screen: a.screen, fatal: false, anr: a })),
    ...crashesOf(st).map((c, i): Incident => ({ kind: 'crash', key: `crash:${i}`, start_ms: c.start_ms, name: c.signature, screen: c.screen, fatal: true, crash: c })),
  ]
  const at = (x: Incident) => x.start_ms ?? Number.POSITIVE_INFINITY
  return list.sort((a, b) => (at(a) === at(b) ? 0 : at(a) < at(b) ? -1 : 1))
}

export const filterIncidents = (list: Incident[], f: IncidentFilter) => (f === 'all' ? list : list.filter((x) => x.kind === f))

/** The tiles' counts. Null where the run didn't measure it: an iOS run's
 *  ANRs, a trace recorded without the crash log, a run from before F-028. */
export function incidentCounts(st: Stability) {
  return {
    js: st.errors.js,
    anr: st.anrs?.measured ? st.anrs.count : null,
    crash: st.crash.measured === false ? null : (st.crash.count ?? (st.crash.crashed ? 1 : 0)),
  }
}
```

- [ ] **Step 5: Run the tests**

Run: `cd frontend && npx vitest run src/domain/incidents.test.ts && npm run typecheck`
Expected: PASS, no type errors. `StabilityPage.tsx` still compiles, because `crash.crashed` and `crash.reason` remain.

---

### Task 7: The Crashes & ANRs page, its route and the redirects

**Files:**
- Create: `frontend/src/features/shared/DeltaTile.tsx`
- Create: `frontend/src/features/crashes/CrashesPage.tsx`
- Delete: `frontend/src/features/stability/StabilityPage.tsx` (its hangs part moves in Task 8, which lands in the same change)
- Modify: `frontend/src/app/routes.ts`, `frontend/src/app/router.tsx`, `frontend/src/app/routes.test.ts`

**Interfaces:**
- Consumes: `incidentsOf`, `filterIncidents`, `incidentCounts`, types (Task 6); `useStability` (`api/hooks.ts`, unchanged).
- Produces: `DeltaTile({ label, help, value, base, unit?, note? })` (Task 8 uses it); screen id `crashes` at `/crashes` and `/ios/crashes`; `MOVED_PATHS` in `routes.ts`.

- [ ] **Step 1: Write the failing route test**

Add to `frontend/src/app/routes.test.ts`:

```ts
import { MOVED_PATHS, SCREENS } from './routes'

describe('crashes & ANRs', () => {
  it('replaces Stability in both trace lanes', () => {
    expect(screenByPath('/crashes')).toMatchObject({ id: 'crashes', label: 'Crashes & ANRs', profiler: 'perfetto' })
    expect(screenByPath('/ios/crashes')).toMatchObject({ page: 'crashes', profiler: 'ios' })
    expect(SCREENS.some((x) => x.path.endsWith('/stability'))).toBe(false)
  })

  it('sends old Stability links to a screen that exists', () => {
    expect(MOVED_PATHS).toEqual({ '/stability': '/crashes', '/ios/stability': '/ios/crashes' })
    for (const to of Object.values(MOVED_PATHS)) expect(SCREENS.some((x) => x.path === to)).toBe(true)
  })
})
```

(merge the `import` into the file's existing import from `./routes`).

- [ ] **Step 2: Run it to see it fail**

Run: `cd frontend && npx vitest run src/app/routes.test.ts`
Expected: FAIL, "MOVED_PATHS is not exported" / no `crashes` screen.

- [ ] **Step 3: Routes and redirects**

In `routes.ts`, replace the `stability` entry:

```ts
  { id: 'crashes', path: '/crashes', label: 'Crashes & ANRs', code: 'CR', group: 'ANALYSE', hint: 'JS exceptions, ANRs and crashes: when, on which screen, with the stack or crash log.', profiler: 'perfetto' },
```

and add below `SCREENS`:

```ts
/** Old addresses of moved screens. Copilot answers, analyst findings and
 *  issue files keep linking to them. */
export const MOVED_PATHS: Record<string, string> = { '/stability': '/crashes', '/ios/stability': '/ios/crashes' }
```

In `router.tsx`, import `useLocation` from `react-router` and `MOVED_PATHS` from `./routes`. Change the `stability` page entry to:

```tsx
  crashes: page(() => import('@/features/crashes/CrashesPage'), 'CrashesPage'),
```

add above `export const router`:

```tsx
/** A moved screen's old address, keeping the run and focus in the query. */
function Moved({ to }: { to: string }) {
  const { search, hash } = useLocation()
  return <Navigate to={`${to}${search}${hash}`} replace />
}
```

and in the shell's `children`, before the `'*'` catch-all:

```tsx
      ...Object.entries(MOVED_PATHS).map(([from, to]) => ({ path: from.slice(1), element: <Moved to={to} /> })),
```

- [ ] **Step 4: `DeltaTile`**

```tsx
// frontend/src/features/shared/DeltaTile.tsx
import { KpiTile } from '@/design'
import { fmt, signed } from '@/domain/format'

/** A count or duration tile with its change against the previous run. */
export function DeltaTile({ label, help, value, base, unit, note }: { label: string; help: string; value: number | null; base: number | null | undefined; unit?: string; note?: string }) {
  return (
    <KpiTile
      label={label}
      help={help}
      value={value == null ? null : fmt(value)}
      unit={unit}
      delta={value != null && base != null ? { value: value - base, text: signed(value - base, 0, unit ? ` ${unit}` : ''), against: `vs ${fmt(base)} in the previous run` } : null}
      note={note}
    />
  )
}
```

- [ ] **Step 5: The page**

```tsx
// frontend/src/features/crashes/CrashesPage.tsx
import { useState } from 'react'
import { useStability } from '@/api/hooks'
import type { AnrEvent, CrashEvent, JsErrorEvent, ResolvedFrame, Run, Stability } from '@/api/types'
import { Card, CodeBlock, EmptyState, ExpandableTable, Grid, LineChart, Segmented, Stack, StatusPill, Text, type SegmentOption, type Tone } from '@/design'
import { fmt } from '@/domain/format'
import { filterIncidents, incidentCounts, incidentsOf, type Incident, type IncidentFilter } from '@/domain/incidents'
import { useScope } from '@/domain/scope'
import { DeltaTile } from '@/features/shared/DeltaTile'

/** JS exceptions, ANRs and crashes for the run in view (stability.py), in one
 *  list in time order. Hangs are on Frame pacing. */
export function CrashesPage() {
  const { scope, isLoading } = useScope()
  const run = scope?.run ?? null
  const q = useStability(run?.id ?? null)
  const [filter, setFilter] = useState<IncidentFilter>('all')
  if (isLoading || !scope) return <EmptyState>Loading runs…</EmptyState>
  if (!run) return <EmptyState title="No runs yet">Capture a trace to see JS exceptions, ANRs and crashes.</EmptyState>
  // The detail, with stacks resolved, once the server has answered; the history's copy until then.
  const st = q.data?.stability ?? run.stability
  if (!st)
    return (
      <EmptyState title="Not measured for this run">
        This run was recorded before JS exceptions, ANRs and crashes were measured. Run <code>swagperf reextract</code> to measure it from its trace.
      </EmptyState>
    )
  const base = scope.allRuns.filter((r) => r.id < run.id).pop() ?? null
  const counts = incidentCounts(st)
  const all = incidentsOf(st)
  const ios = run.platform === 'ios'
  const firstCrash = all.find((i) => i.kind === 'crash')?.name

  return (
    <Stack as="section" gap={20}>
      <Grid min={200} gap={12}>
        <DeltaTile label="JS exceptions" help="Uncaught JavaScript errors, unhandled promise rejections and errors a screen's error boundary caught." value={counts.js} base={base?.js_errors} note={`${st.errors.js_fatal} fatal`} />
        <DeltaTile
          label="ANRs"
          help="Times Android declared the app not responding: a touch or key went unanswered for about 5 s, or a receiver or service ran too long."
          value={counts.anr}
          base={base?.anr_count}
          note={ios ? 'Android only' : counts.anr == null ? 'not measured in this trace' : undefined}
        />
        <DeltaTile
          label="Crashes"
          help="Times the app's process died on its own: an exception nothing caught, or a native signal."
          value={counts.crash}
          base={base?.crash_count}
          note={counts.crash == null ? 'the crash log was not recorded' : firstCrash}
        />
      </Grid>

      {scope.runs.length > 1 && (
        <Card title="JS exceptions, ANRs and crashes per run" hint="Each kind counted for every run in range.">
          <LineChart
            label="JS exceptions, ANRs and crashes per run"
            labels={scope.runs.map((r) => `#${r.id}`)}
            series={[
              { name: 'JS exceptions', color: 'var(--c3)', values: scope.runs.map((r) => r.js_errors) },
              { name: 'ANRs', color: 'var(--c2)', values: scope.runs.map((r) => r.anr_count ?? null) },
              { name: 'Crashes', color: 'var(--c1)', values: scope.runs.map((r) => r.crash_count ?? r.crashed) },
            ]}
            unit=""
            decimals={0}
          />
        </Card>
      )}

      <Card title="What went wrong" hint="Every JS exception, ANR and crash in the run, in time order. Open a row for its stack, reason or crash log.">
        <Stack gap={12}>
          <Segmented label="Show" options={FILTERS} value={filter} onChange={setFilter} />
          <IncidentTable rows={filterIncidents(all, filter)} empty={all.length ? 'None of this kind in this run.' : 'No JS exception, ANR or crash in this run.'} />
          {st.errors.js > 0 && <SourceMapNote st={st} run={run} />}
        </Stack>
      </Card>
    </Stack>
  )
}

const FILTERS: SegmentOption<IncidentFilter>[] = [
  { value: 'all', label: 'All' },
  { value: 'js', label: 'JS exceptions' },
  { value: 'anr', label: 'ANRs' },
  { value: 'crash', label: 'Crashes' },
]

const KIND: Record<Incident['kind'], { label: string; tone: Tone }> = {
  js: { label: 'JS EXCEPTION', tone: 'warn' },
  anr: { label: 'ANR', tone: 'warn' },
  crash: { label: 'CRASH', tone: 'fail' },
}

const COLS = [
  { key: 'at', label: 'At', width: '90px' },
  { key: 'what', label: 'What', width: '150px' },
  { key: 'name', label: 'Name', width: 'minmax(200px, 2fr)' },
  { key: 'screen', label: 'Screen', width: 'minmax(140px, 1fr)' },
  { key: 'fatal', label: 'Fatal', width: '96px' },
]

const at = (ms: number | null) => (ms == null ? '–' : `${fmt(ms / 1000, 2)} s`)

function IncidentTable({ rows, empty }: { rows: Incident[]; empty: string }) {
  const [open, setOpen] = useState<string | null>(null)
  if (rows.length === 0) return <Text variant="body">{empty}</Text>
  return (
    <ExpandableTable
      label="JS exceptions, ANRs and crashes"
      minWidth={720}
      columns={COLS}
      rows={rows}
      rowKey={(i) => i.key}
      toggleLabel={(i) => `${i.name} at ${at(i.start_ms)}`}
      openKey={open}
      onToggle={(k) => setOpen(open === k ? null : k)}
      cells={(i) => [
        at(i.start_ms),
        <StatusPill key="k" tone={KIND[i.kind].tone}>
          {KIND[i.kind].label}
        </StatusPill>,
        <Text key="n" as="span" variant="body" tone="primary" weight={600}>
          {i.name}
        </Text>,
        i.screen ?? '–',
        <StatusPill key="f" tone={i.fatal ? 'fail' : 'neutral'}>
          {i.fatal ? 'FATAL' : 'NO'}
        </StatusPill>,
      ]}
      detail={(i) => (i.kind === 'js' ? <JsErrorDetail e={i.js} /> : i.kind === 'anr' ? <AnrDetail a={i.anr} /> : <CrashDetail c={i.crash} />)}
    />
  )
}

function SourceMapNote({ st, run }: { st: Stability; run: Run }) {
  const map = st.errors.source_map
  return (
    <Text variant="small">
      {map
        ? `JS stacks are resolved against this build's source map (${map}).`
        : `No source map is registered for this build, so JS stacks show Hermes bytecode offsets. Register it with: swagperf maps add <map> --app ${run.app_pkg ?? '<app>'} --platform ${run.platform ?? 'android'} --bundle <bundle>`}
    </Text>
  )
}

const frameLine = (f: ResolvedFrame) => (f.resolved ? `${f.in_app ? '' : '  '}${f.fn ?? '<anonymous>'}  ${f.file ?? '?'}:${f.line ?? '?'}:${f.col ?? '?'}` : `  ${f.raw}`)

function JsErrorDetail({ e }: { e: JsErrorEvent }) {
  if (!e.has_record) return <Text variant="body">Only the marker arrived: the error's record (message and stack) is missing from the trace.</Text>
  return (
    <Stack gap={12}>
      {e.message ? <Text variant="body">{e.message}</Text> : null}
      {e.frames ? <CodeBlock lang="Stack, resolved (library frames indented)" code={e.frames.map(frameLine).join('\n')} /> : e.stack && <CodeBlock lang="Stack, as Hermes reported it" code={e.stack} />}
      {e.component_stack && <CodeBlock lang="Component stack" code={e.component_stack.trim()} defaultOpen={false} />}
    </Stack>
  )
}

function AnrDetail({ a }: { a: AnrEvent }) {
  return (
    <Stack gap={12}>
      <Text variant="body">
        {a.type_label}.{a.dur_ms ? ` Android waits ${fmt(a.dur_ms)} ms for this before declaring an ANR.` : ''}
      </Text>
      {a.subject && <CodeBlock lang="The system's reason" code={a.subject} />}
      <Text variant="body">
        {a.main_thread
          ? `The main thread was in ${a.main_thread.name} for ${fmt(a.main_thread.dur_ms)} ms.`
          : "The trace doesn't show what the main thread was doing: nothing was traced on it in the window before the ANR."}
      </Text>
    </Stack>
  )
}

function CrashDetail({ c }: { c: CrashEvent }) {
  if (!c.log) return <Text variant="body">{c.message ?? 'The process ended on its own; this run recorded no crash log.'}</Text>
  return <CodeBlock lang={c.kind === 'native' ? 'Crash log: signal and backtrace' : 'Crash log: exception and stack'} code={c.log} />
}
```

Check before compiling: `grep -n "'small'" frontend/src/design/primitives/Text.tsx` (the variant exists: `caption | meta | small | …`). Also check `CodeBlock` accepts `defaultOpen` as the old page used it (`grep -n "defaultOpen" frontend/src/design/components/CodeBlock.tsx`).

Delete `frontend/src/features/stability/StabilityPage.tsx` (its hangs parts are recreated in Task 8's `HangsSection.tsx`).

- [ ] **Step 6: Run the checks**

Run: `cd frontend && npx vitest run src/app/routes.test.ts src/domain/incidents.test.ts && npm run typecheck && npm run lint`
Expected: PASS, no type or lint errors. The existing lanes test still passes: the iOS lane mirrors the new entry.

---

### Task 8: Hangs on Frame pacing, and Compare's rows

**Files:**
- Create: `frontend/src/features/frames/HangsSection.tsx`
- Modify: `frontend/src/features/frames/FramesPage.tsx`
- Modify: `frontend/src/features/shared/ComparisonTables.tsx` (`STABILITY_LABELS`)

**Interfaces:**
- Consumes: `DeltaTile` (Task 7); `Run.stability`, `hang_count`, `longest_hang_ms`.
- Produces: `HangsSection({ run, runs, prev }: { run: Run; runs: Run[]; prev: Run | null })`.

- [ ] **Step 1: `HangsSection`**

```tsx
// frontend/src/features/frames/HangsSection.tsx
import type { Run, Stability } from '@/api/types'
import { Card, Grid, KpiTile, LineChart, Stack, StatusPill, TableCard, Text, numCell } from '@/design'
import { fmt } from '@/domain/format'
import { DeltaTile } from '@/features/shared/DeltaTile'

/** Hangs after the first frame (stability.py), by Apple's definitions on both
 *  platforms: a microhang is a 100-250 ms stall of the main thread, a hang
 *  250 ms or more. */
export function HangsSection({ run, runs, prev }: { run: Run; runs: Run[]; prev: Run | null }) {
  const st = run.stability
  if (!st)
    return (
      <Card title="Hangs" hint="Main-thread stalls of 100 ms or more after the first frame.">
        <Text variant="body">
          Not measured for this run. Run <code>swagperf reextract</code> to measure it from its trace.
        </Text>
      </Card>
    )
  const h = st.hangs
  return (
    <Stack gap={20}>
      <Grid min={180} gap={12}>
        <DeltaTile label="Hangs" help="Main-thread stalls of 250 ms or more after the first frame: the app did not respond to touch." value={h.count} base={prev?.hang_count} note={h.startup.count ? `${h.startup.count} more during startup` : 'none during startup'} />
        <KpiTile label="Microhangs" help="Main-thread stalls of 100 to 250 ms after the first frame: noticeable, short of a hang." value={fmt(h.microhangs)} />
        <DeltaTile label="Longest hang" help="The longest main-thread stall after the first frame." value={h.longest_ms} base={prev?.longest_hang_ms} unit="ms" />
        <KpiTile
          label="Hang rate"
          help="Seconds of hang per hour of use, Apple's measure. Only for sessions of a minute or more: one hang in a short capture would read as a huge rate."
          value={h.rate_s_per_hr == null ? null : fmt(h.rate_s_per_hr, 1)}
          unit="s/hr"
          note={h.rate_s_per_hr == null ? `session ${fmt(h.session_s)} s: under a minute` : undefined}
        />
      </Grid>
      {runs.length > 1 && (
        <Card title="Hangs per run" hint="Hangs after the first frame, for each run in range.">
          <LineChart label="Hangs per run" labels={runs.map((r) => `#${r.id}`)} series={[{ name: 'Hangs', color: 'var(--c2)', values: runs.map((r) => r.hang_count) }]} unit="" decimals={0} />
        </Card>
      )}
      <HangTable st={st} />
    </Stack>
  )
}

const seconds = (ms: number) => `${fmt(ms / 1000, 2)} s`

function HangTable({ st }: { st: Stability }) {
  const events = st.hangs.events
  return (
    <TableCard title="Hangs" hint={`Every stall of 100 ms or more, from ${st.hangs.source}. Startup stalls happen before the first frame.`} minWidth={560}>
      <thead>
        <tr>
          <th>At</th>
          <th className={numCell}>Duration</th>
          <th>Kind</th>
          <th>Screen</th>
        </tr>
      </thead>
      <tbody>
        {events.length === 0 && (
          <tr>
            <td colSpan={4}>
              <Text variant="body">No stall of 100 ms or more in this run.</Text>
            </td>
          </tr>
        )}
        {events.map((h) => (
          <tr key={`${h.start_ms}`}>
            <td>{seconds(h.start_ms)}</td>
            <td className={numCell}>{fmt(h.dur_ms)} ms</td>
            <td>
              <StatusPill tone={h.kind === 'hang' ? 'warn' : 'neutral'}>{h.kind === 'hang' ? 'HANG' : 'MICROHANG'}</StatusPill>
            </td>
            <td>
              <Text variant="body">{h.screen ?? 'startup'}</Text>
            </td>
          </tr>
        ))}
      </tbody>
    </TableCard>
  )
}
```

- [ ] **Step 2: Frame pacing renders hangs even when frames aren't measured**

In `FramesPage.tsx`, import `HangsSection` and compute the previous run once:

```tsx
import { HangsSection } from './HangsSection'
```

Replace the simulator early return with a card that sits above the hangs:

```tsx
  const prev = allRuns.filter((r) => r.id < run.id).pop() ?? null
  // Unmeasured is not perfect: a simulator run has no frames to show, and
  // empty charts would read as a clean run. Its hangs are measured (the
  // Hangs instrument), so they still show.
  if (run.simulator)
    return (
      <Stack as="section" gap={20}>
        <Card title="Frames not measured on the iOS Simulator">
          <Text variant="body">
            The simulator supports none of Instruments' frame instruments (Hitches, Frame Lifetimes, Core Animation FPS). Slow and janky frames are measured on a physical iPhone.
          </Text>
        </Card>
        <HangsSection run={run} runs={runs} prev={prev} />
      </Stack>
    )
```

and add the section as the last child of the page's main `<Stack>`, after the Thermal drift card:

```tsx
      <HangsSection run={run} runs={runs} prev={prev} />
```

Add `Text` to the `@/design` import. Hangs compare with the previous run, as they did on Stability. The frame tiles keep comparing with the benchmark.

- [ ] **Step 3: Compare's labels**

In `frontend/src/features/shared/ComparisonTables.tsx`:

```ts
const STABILITY_LABELS: Record<string, string> = { hang_count: 'Hangs', longest_hang_ms: 'Longest hang', js_errors: 'JS exceptions', anr_count: 'ANRs', crash_count: 'Crashes' }
```

- [ ] **Step 4: Run the checks**

Run: `cd frontend && npm test && npm run typecheck && npm run lint`
Expected: all PASS.

---

### Task 9: Demo data and screenshots

**Files:**
- Modify: `swagperf/synth_android.py` (`gen_device_session(…, stability=False)`)
- Modify: `.claude/skills/run-perfetto-monitor/driver.py` (`seed()`), `.claude/skills/run-perfetto-monitor/SKILL.md` (seed table)
- Test: `tests/test_stability.py`

Another session is editing the run skill's two files. Read both files just before editing, and change only the lines named here.

- [ ] **Step 1: Write the failing test**

```python
class TestDemoSession(unittest.TestCase):

    def test_the_demo_session_carries_every_kind(self):
        from swagperf.synth_android import gen_device_session
        data, _ = gen_device_session(3, pkg="com.example.app", stability=True)
        st = _stability(data, "com.example.app")
        self.assertEqual((st["errors"]["js"], st["anrs"]["count"], st["crash"]["count"]), (2, 1, 2))
        self.assertEqual({e["kind"] for e in st["crash"]["events"]}, {"java", "native"})
        anr = st["anrs"]["events"][0]
        self.assertEqual((anr["screen"], anr["main_thread"]["name"]), ("Store", "binder transaction"))
```

- [ ] **Step 2: Run it to see it fail**

Run: `./.venv/bin/python -m unittest tests.test_stability.TestDemoSession -v`
Expected: FAIL, `TypeError: gen_device_session() got an unexpected keyword argument 'stability'`.

- [ ] **Step 3: Implement**

In `gen_device_session`, add the keyword and append a `Session`'s packets. Two serialized `Trace` messages concatenate into one trace. The session reuses the app's pid (`APP`) and system_server's pid (1500, `synth_stability.SYS_PID`), and its times fall inside the flow (Home 0–3 s, Send 3–5 s, Home 5–6.5 s, Store 6.5–8 s, History 8–9.2 s):

```python
def gen_device_session(seed=0, *, pkg="com.swag.pay", process_name=None, stability=False):
```

Document it in the docstring:

```
    * with stability=True (synth_stability.Session): a non-fatal JS error
      on Send; a 5 s main-thread stall from 2.9 s that Android declares an
      ANR at its end, on Store; then on History a fatal JS error, the
      Kotlin crash it causes, and a native crash
```

Before `expect.update(...)`. The stall is 5 s long, so it is the longest main-thread slice in the ANR's 5 s window: the screen slices this generator draws on the main thread are 3 s at most.

```python
    if stability:
        from .synth_stability import Session
        s = Session(pkg, APP)
        s.js_error(3500, "d1", name="TypeError", message="Cannot read property 'amount' of undefined")
        s.slice(2900, 5000, "binder transaction")
        s.anr(7900, "demo-anr", "Input dispatching timed out (demo "
              f"{pkg}/.MainActivity is not responding. Waited 5001ms for MotionEvent)")
        s.js_error(8600, "d2", name="RangeError", fatal=True, source="promise")
        s.java_crash(8700, exc="com.facebook.react.common.JavascriptException",
                     message="RangeError: amount out of range")
        s.native_crash(9150)
        out += s.bytes()
```

In `driver.py`'s `seed()`, pass the keyword to the demo session:

```python
    pyrun("from swagperf.synth_android import gen_device_session\n"
          "b, _ = gen_device_session(3, pkg='com.example.app', stability=True)\n"
          "open('traces/example_session.pftrace', 'wb').write(b)")
```

In `SKILL.md`'s seed table, change row #1's "where it shows" to `Screens, Crashes & ANRs, Frame pacing's hangs (\`--run 1\`)`, and its "what" to add "JS exceptions, an ANR and two crashes".

- [ ] **Step 4: Run the test**

Run: `./.venv/bin/python -m unittest tests.test_stability.TestDemoSession -v`
Expected: PASS.

- [ ] **Step 5: Screenshots in the live dashboard**

Use the run-perfetto-monitor skill's driver. It runs in its own scratch workspace and never touches `history.db`:

```bash
./.venv/bin/python .claude/skills/run-perfetto-monitor/driver.py up --fresh --dev
./.venv/bin/python .claude/skills/run-perfetto-monitor/driver.py shot /crashes --run 1 --full
./.venv/bin/python .claude/skills/run-perfetto-monitor/driver.py shot /frames --run 1 --full
./.venv/bin/python .claude/skills/run-perfetto-monitor/driver.py shot /stability --run 1
./.venv/bin/python .claude/skills/run-perfetto-monitor/driver.py shot /compare --full
./.venv/bin/python .claude/skills/run-perfetto-monitor/driver.py tour
./.venv/bin/python .claude/skills/run-perfetto-monitor/driver.py down
```

Check the flags against the skill's command table first (`sed -n 60,90p .claude/skills/run-perfetto-monitor/SKILL.md`). Read each screenshot, and expect:
- `/crashes`: three tiles (2 JS exceptions with "1 fatal", 1 ANR, 2 crashes) and five rows in time order.
- Opening a row shows, per kind: the JS stack, the ANR's reason and main-thread line, and the crash log.
- `/frames`: the Hangs section at the bottom.
- `/stability?run=1` lands on `/crashes?run=1`.
- The tour reports every page clean.

---

### Task 10: Docs, tracker, full verification, and the phone trace end to end

**Files:**
- Modify: `docs/FEATURES.md` (section 15 and the `/stability` rows), `docs/TESTING-PLAN.md` (new rows, S-02 and STB-14 notes, RS-04), `docs/TRACKER.md` (F-028 notes), `docs/superpowers/specs/2026-09-25-crashes-anrs-tab-design.md` (status line).

- [ ] **Step 1: Run the phone trace from Task 0 through the new extraction**

```bash
./.venv/bin/python - "$SCRATCH/phone_check.pftrace" <<'EOF'
import json, sys
from perfetto.trace_processor import TraceProcessor
from swagperf import stability
tp = TraceProcessor(trace=sys.argv[1])
st = stability.extract_stability(tp, "com.swag.pay", "android")
tp.close()
print(json.dumps({"anrs": {k: st["anrs"][k] for k in ("measured", "count", "by_type")},
                  "crash": {"count": st["crash"]["count"],
                            "kinds": [(e["kind"], e["signature"]) for e in st["crash"]["events"]]}}, indent=1))
EOF
```

Expected: one ANR (`INPUT_DISPATCHING_TIMEOUT`), and two crashes: `java` with `…CrashedByAdbException` (or what `am crash` threw on the V2514), and `native` `SIGSEGV` whose log holds the tombstone. If any is missing, the fixtures in Task 1 don't match the device. Fix `Session` to write the real format, re-run Tasks 2 and 3, then this step.

- [ ] **Step 2: Full test runs**

```bash
./.venv/bin/python -m unittest discover -s tests          # ~3 min
(cd frontend && npm test && npm run typecheck && npm run lint)
```

Expected: all pass. A failure in a file this plan didn't touch may be another session's work in progress: check `git diff --stat` for that file. Report it; don't fix it.

- [ ] **Step 3: Docs**

- `docs/FEATURES.md`:
  - section 15 becomes "Crashes & ANRs, and hangs on Frame pacing (F-014, F-028)";
  - describe the ANR source, the crash list with its logs, the "not measured" rule, the `anr_count`/`crash_count` columns and the new triage keys;
  - replace the `/stability` row with `/crashes`, noting that `/stability` redirects.
- `docs/TESTING-PLAN.md`:
  - add rows CR-01 to CR-06 for Task 9's screenshots and the old-run and redirect behaviour;
  - add CR-07 for Task 0's phone check, with its result;
  - mark S-02 fixed for crash, ANR and JS-error signals;
  - note under STB-14 that tombstones are now read by header;
  - note under RS-04 that the demo session seeds stability data.
- The spec's status line: "Implemented 2026-09-25; see the plan."
- Commit these docs (own hunks only).

- [ ] **Step 4: Tracker**

Following the product-manager skill:
- move F-028 to Done with the hash of the commit that delivers the dashboard tab (Task 8's);
- mark TESTING-PLAN S-02 fixed for crash, ANR and JS-error signals;
- if Task 0 found anything new, log it.

Commit the tracker's own hunks.

- [ ] **Step 5: Report**

List the commits, the test results with counts, the phone check's result, and anything skipped, including whether Task 4 ran.
