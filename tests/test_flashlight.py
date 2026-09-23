"""Flashlight audits and the guard that keeps Flashlight and Perfetto apart.

No device and no Node: adb is stubbed, and the audit summary is a fixture that
flashlight/summary.js produced from three real Flashlight-sampled cold starts
(flashlight/summary.test.js checks that side).
"""
import json, os, subprocess, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from swagperf import capture, extract, flashlight, jobs, reset, store

HERE = os.path.dirname(os.path.abspath(__file__))
SUMMARY = json.load(open(os.path.join(HERE, "fixtures", "flashlight_summary.json")))
S = 1_000_000_000


class TestTracingCoverage(unittest.TestCase):
    """What Flashlight does to a Perfetto trace, measured in the Phase 0
    experiment: either no scheduler events at all, or events that stop
    partway while the trace carries on."""

    def test_no_scheduler_events_is_refused(self):
        self.assertIn("no scheduler events", extract.tracing_problem(0, 30 * S, 0, None))

    def test_scheduler_events_stopping_early_is_refused(self):
        p = extract.tracing_problem(0, 40 * S, 500_000, 18 * S)
        self.assertIn("22.0s before the trace ended", p)

    def test_a_full_trace_passes(self):
        self.assertIsNone(extract.tracing_problem(0, 40 * S, 500_000, int(39.5 * S)))


class TestOtherProfilers(unittest.TestCase):
    def _run(self, stdout):
        return mock.patch.object(capture.subprocess, "run",
                                 return_value=subprocess.CompletedProcess([], 0, stdout, ""))

    def test_names_what_is_running(self):
        with mock.patch.object(capture, "devices", return_value=["X"]), self._run("flashlight\natrace\n"):
            self.assertEqual(capture.other_profilers(), ["Flashlight's profiler", "an atrace session"])

    def test_a_capture_refuses_while_flashlight_runs(self):
        with mock.patch.object(capture, "devices", return_value=["X"]), self._run("flashlight\n"):
            with self.assertRaisesRegex(RuntimeError, "Flashlight's profiler is running"):
                capture.require_no_other_profiler("X")

    def test_nothing_running_is_fine(self):
        with mock.patch.object(capture, "devices", return_value=["X"]), self._run(""):
            capture.require_no_other_profiler("X")


class TestAuditStore(unittest.TestCase):
    def setUp(self):
        self.db = tempfile.mktemp(suffix=".db")

    def tearDown(self):
        if os.path.exists(self.db):
            os.remove(self.db)

    def test_an_audit_keeps_flashlights_numbers(self):
        aid = store.audit_create(app_pkg="com.swag.pay", device="V2514", iterations=3,
                                 duration_ms=10000, meta={"device": {"model": "V2514"}}, db=self.db)
        store.audit_finish(aid, results_path="traces/flashlight/audit1.json", summary=SUMMARY, db=self.db)

        a = store.audit_get(aid, db=self.db)
        self.assertEqual(a["state"], "done")
        self.assertEqual(a["score"], SUMMARY["score"])
        self.assertEqual(a["cpu_pct"], SUMMARY["metrics"]["cpu_pct"])
        self.assertEqual(len(a["summary"]["series"]), len(SUMMARY["series"]))
        self.assertEqual(a["meta"]["device"]["model"], "V2514")

        [row] = store.audit_list(db=self.db)
        self.assertNotIn("series", row["summary"])  # lists stay small
        self.assertEqual(row["summary"]["key_threads"]["ui"]["name"], "UI Thread")
        self.assertEqual(store.audit_list(app_pkg="com.other", db=self.db), [])

    def test_audits_left_running_are_closed_at_startup(self):
        aid = store.audit_create(app_pkg="com.swag.pay", iterations=3, duration_ms=10000, db=self.db)
        self.assertEqual(store.audit_mark_interrupted(db=self.db), 1)
        self.assertEqual(store.audit_get(aid, db=self.db)["state"], "interrupted")

    def test_reset_deletes_audits_and_their_results(self):
        traces = tempfile.mkdtemp()
        os.makedirs(os.path.join(traces, "flashlight"))
        with open(os.path.join(traces, "flashlight", "audit1.json"), "w") as f:
            f.write("{}")
        store.audit_create(app_pkg="com.swag.pay", iterations=3, duration_ms=10000, db=self.db)

        done = reset.reset(db=self.db, traces_dir=traces)
        self.assertEqual(done["rows"]["flashlight_audits"], 1)
        self.assertEqual(store.audit_list(db=self.db), [])
        self.assertFalse(os.path.exists(os.path.join(traces, "flashlight")))
        # Ids start again at 1, as they do for runs.
        self.assertEqual(store.audit_create(app_pkg="com.swag.pay", iterations=2,
                                            duration_ms=5000, db=self.db), 1)


class TestRunner(unittest.TestCase):
    def test_flashlight_log_lines_lose_their_clock_and_emoji(self):
        self.assertEqual(flashlight.clean_line("[17:18:14] \x1b[34mℹ️  Running iteration 1/5\x1b[39m"),
                         "Running iteration 1/5")
        self.assertEqual(flashlight.clean_line("[17:18:24] ✅  Finished iteration 1/5 in 10123ms"),
                         "Finished iteration 1/5 in 10123ms")

    def test_summary_sits_beside_the_results_file(self):
        self.assertEqual(flashlight.summary_path("/t/audit3_com.swag.pay.json"),
                         "/t/audit3_com.swag.pay.summary.json")

    def test_a_missing_install_says_how_to_fix_it(self):
        with mock.patch.object(flashlight, "RUNNER", tempfile.mkdtemp()):
            st = flashlight.runner_status()
        self.assertFalse(st["ready"])
        self.assertIn("npm ci --prefix flashlight", st["reason"])


class TestStartAudit(unittest.TestCase):
    def test_rejects_a_bad_package_name(self):
        with self.assertRaises(ValueError):
            jobs.start_audit("not a package")

    def test_says_why_when_flashlight_cannot_run(self):
        with mock.patch.object(flashlight, "runner_status",
                               return_value={"ready": False, "reason": "Flashlight is not installed yet."}):
            with self.assertRaisesRegex(ValueError, "not installed"):
                jobs.start_audit("com.swag.pay")


if __name__ == "__main__":
    unittest.main()
