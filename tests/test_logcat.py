"""Crash logs that Perfetto's log source didn't deliver (B-011): on the V2514
it records no line at all, so swagperf reads the session's window of adb
logcat and appends it to the trace, and a probe line tells "no crash" from
"no log"."""
import os, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from perfetto.trace_processor import TraceProcessor

from swagperf import capture, logcat, stability
from swagperf.synth_stability import Session

# The lines the V2514's logcat printed for the phone check (spec, "Phone
# check, 2026-09-28"), with `-v epoch,usec` times inside a synthetic session.
LOGCAT = """--------- beginning of main
     2.000000  4000  4000 I SwagPerfProbe: swagperf session
--------- beginning of crash
     4.000000  4000  4000 E AndroidRuntime: FATAL EXCEPTION: main
     4.000100  4000  4000 E AndroidRuntime: Process: com.swag.pay, PID: 4000
     4.000200  4000  4000 E AndroidRuntime: java.lang.IllegalStateException: boom
     4.000300  4000  4000 E AndroidRuntime: \tat com.swag.pay.Home.render(Home.kt:10)
     9.000000  4000  4000 F libc    : Fatal signal 11 (SIGSEGV), code 0 (SI_USER from pid 1, uid 0) in tid 4000 (com.swag.pay), pid 4000 (com.swag.pay)
     9.500000  5000  5000 F DEBUG   : *** *** *** *** *** *** *** *** *** *** *** *** *** *** *** ***
     9.500100  5000  5000 F DEBUG   : pid: 4000, tid: 4000, name: com.swag.pay  >>> com.swag.pay <<<
     9.500200  5000  5000 F DEBUG   : backtrace:
    99.000000  4000  4000 E AndroidRuntime: FATAL EXCEPTION: after the session
"""


def _trace(build=lambda s: None, *, log_source=True):
    s = Session()
    s.config(sources=["linux.ftrace", "android.log"] if log_source else ["linux.ftrace"], atrace=["am"])
    s.slice(500, 20, "Choreographer#doFrame 1")
    s.screen(600, 20_000, "Home#compose")
    build(s)
    p = os.path.join(tempfile.mkdtemp(), "t.pftrace")
    with open(p, "wb") as f:
        f.write(s.bytes())
    return p


def _stability(path):
    tp = TraceProcessor(trace=path)
    try:
        return stability.extract_stability(tp, "com.swag.pay", "android")
    finally:
        tp.close()


class TestParse(unittest.TestCase):

    def test_reads_time_pid_priority_tag_and_message(self):
        lines = logcat.parse(LOGCAT)
        self.assertEqual(len(lines), 10)
        self.assertEqual(lines[1], (4_000_000_000, 4000, 4000, 6, "AndroidRuntime", "FATAL EXCEPTION: main"))
        self.assertEqual(lines[5][3:5], (7, "libc"))
        self.assertEqual(lines[4][5], "\tat com.swag.pay.Home.render(Home.kt:10)")
        self.assertEqual(lines[7][5], "pid: 4000, tid: 4000, name: com.swag.pay  >>> com.swag.pay <<<")


class TestImport(unittest.TestCase):

    def test_a_trace_without_log_lines_gets_the_sessions_logcat(self):
        path = _trace()
        self.assertFalse(_stability(path)["crash"]["measured"])     # no log arrived: not 0
        n = logcat.import_into(path, read=lambda: LOGCAT)
        self.assertEqual(n, 9)                                       # the line after the session stays out
        c = _stability(path)["crash"]
        self.assertEqual((c["measured"], c["count"]), (True, 2))
        self.assertEqual([e["kind"] for e in c["events"]], ["java", "native"])
        self.assertEqual(c["events"][0]["screen"], "Home")
        self.assertIn(">>> com.swag.pay <<<", c["events"][1]["log"])
        # Importing again adds nothing: the trace has its log now.
        self.assertEqual(logcat.import_into(path, read=lambda: LOGCAT), 0)

    def test_a_phone_whose_log_source_works_is_never_doubled(self):
        path = _trace(lambda s: (s.log(2000, logcat.PROBE_TAG, "swagperf session", prio=4), s.java_crash(4000)))
        self.assertEqual(logcat.import_into(path, read=lambda: LOGCAT), 0)
        self.assertEqual(_stability(path)["crash"]["count"], 1)

    def test_a_probe_line_alone_means_measured_with_no_crash(self):
        path = _trace()
        logcat.import_into(path, read=lambda: "     2.000000  4000  4000 I SwagPerfProbe: swagperf session\n")
        c = _stability(path)["crash"]
        self.assertEqual((c["measured"], c["count"]), (True, 0))

    def test_no_logcat_leaves_the_trace_alone(self):
        path = _trace()
        size = os.path.getsize(path)
        self.assertEqual(logcat.import_into(path, read=lambda: ""), 0)
        self.assertEqual(os.path.getsize(path), size)


class TestSessions(unittest.TestCase):
    """Every Android session writes the probe line and imports its logcat."""

    def setUp(self):
        self.calls = []

        def run(cmd, *a, **kw):
            self.calls.append(cmd if isinstance(cmd, list) else [cmd])
            return mock.Mock(returncode=0, stdout="ok\n", stderr="")
        for p in (mock.patch.object(capture.subprocess, "run", side_effect=run),
                  mock.patch.object(capture, "devices", return_value=["S1"]),
                  mock.patch.object(capture, "require_no_other_profiler", return_value=None),
                  mock.patch.object(capture.time, "sleep", return_value=None)):
            p.start()
            self.addCleanup(p.stop)

    def probes(self):
        return [c for c in self.calls if logcat.PROBE_TAG in " ".join(map(str, c))]

    def test_the_log_source_keeps_the_probe_tag(self):
        self.assertIn(f'filter_tags: "{logcat.PROBE_TAG}"', capture.LOG_SOURCE)

    def test_a_manual_session_probes_at_start_and_imports_at_stop(self):
        with mock.patch.object(capture, "manual_status", return_value={"recording": False}):
            capture.manual_start(pkg="com.swag.pay")
        self.assertEqual(len(self.probes()), 1)
        with mock.patch.object(logcat, "import_into", return_value=3) as imp, \
                mock.patch.object(capture, "manual_status", return_value={"recording": True}):
            out = os.path.join(tempfile.mkdtemp(), "m.pftrace")
            capture.manual_stop(out)
        imp.assert_called_once_with(out, serial="S1")

    def test_a_timed_capture_probes_and_imports(self):
        with mock.patch.object(logcat, "import_into", return_value=0) as imp:
            out = os.path.join(tempfile.mkdtemp(), "c.pftrace")
            capture.capture(out, pkg="com.swag.pay", duration_ms=10)
        self.assertEqual(len(self.probes()), 1)
        imp.assert_called_once_with(out, serial="S1")


if __name__ == "__main__":
    unittest.main()
