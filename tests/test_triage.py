"""The PM agent's run review: the deterministic triage it reasons from, and
the background runner that decides when to start it.

No device, database or model is involved: history is built in the shape the
dashboard's /api/history returns, and the agent is a fake `claude` script
that records how it was called.
"""
import json, os, stat, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from swagperf import pm, triage

TRACKER = """# Tracker

- Runs reviewed through: #{n}

## Performance issues from runs
"""


def run(i, *, peak=300.0, app="com.swag.pay", role="own", path="cold", regress=False, violation=False):
    breaches = [{"metric": "peak_rss_mb", "value": peak, "budget": 320, "over_by_pct": round((peak / 320 - 1) * 100, 1)}] if peak > 320 else []
    return {"id": i, "ts": f"2026-09-2{i % 10}T10:00:00+00:00", "app_pkg": app, "app_name": "Swag Pay" if role == "own" else app,
            "app_role": role, "path_kind": path, "device": "V2514", "label": f"run-{i}", "trace_path": None,
            "breaches": breaches,
            "violations": [{"step": "step:hermes_init", "started_at_ms": 80.0, "first_frame_ms": 200.0,
                            "detail": "step:hermes_init began 120.0ms before first usable camera frame"}] if violation else [],
            "steps": [{"step": "step:activity_create", "dur_ms": 30.0 if regress else 20.0,
                       "children": [{"name": "inflate", "dur_ms": 18.0 if regress else 9.0}, {"name": "theme", "dur_ms": 2.0}]}],
            "analysis": {"verdict": "fail" if breaches or regress else "pass", "headline": f"run {i}"}}


def regs(runs):
    """store.regressions, from the fixture: a regressed run's step against 20 ms."""
    by = {r["id"]: r for r in runs}
    return lambda rid: ([{"step": "step:activity_create", "dur_ms": 30.0, "baseline_ms": 20.0, "delta_pct": 50.0,
                          "reference": "trailing_baseline"}] if by[rid]["steps"][0]["dur_ms"] == 30.0 else [])


def review(runs, after, issues=()):
    return triage.review({"runs": runs}, after=after, regressions=regs(runs), issues=list(issues))


class TestTriage(unittest.TestCase):
    def test_repeated_breach_is_one_signal_across_runs(self):
        """Four failing runs of one problem must land on one issue, not four."""
        runs = [run(i) for i in range(1, 6)] + [run(i, peak=480 + i) for i in range(6, 10)]
        t = review(runs, after=5)
        self.assertEqual([s["key"] for s in t["signals"]], ["budget:peak_rss_mb:com.swag.pay:cold"])
        s = t["signals"][0]
        self.assertEqual((s["first_seen"], s["last_seen"], s["count"], s["of_runs"]), (6, 9, 4, 4))
        self.assertEqual(s["trend"], "flat")
        self.assertEqual(s["fired_before_window"], [], "it did not fire before #6, so it is new")
        self.assertEqual(s["severity"], "high")
        self.assertEqual(s["context"]["risk"], "Peak RAM usage — three runtimes resident")

    def test_ongoing_signal_knows_it_fired_before_the_window(self):
        runs = [run(i, peak=400) for i in range(1, 6)]
        self.assertEqual(review(runs, after=3)["signals"][0]["fired_before_window"], [1, 2, 3])

    def test_a_signal_that_stopped_says_how_many_runs_since(self):
        runs = [run(1, peak=400), run(2, peak=400), run(3), run(4)]
        self.assertEqual(review(runs, after=0)["signals"][0]["runs_since_last_seen"], 2)

    def test_regression_names_the_child_slice_that_moved(self):
        runs = [run(i) for i in range(1, 6)] + [run(6, regress=True)]
        s = review(runs, after=5)["signals"][0]
        self.assertEqual(s["key"], "regression:step:activity_create:com.swag.pay:cold")
        self.assertEqual(s["context"]["child_moves"][0], {"child": "inflate", "ms": 18.0, "baseline_ms": 9.0, "delta_ms": 9.0})

    def test_ordering_violation_is_a_high_signal(self):
        s = review([run(1, violation=True)], after=0)["signals"][0]
        self.assertEqual((s["kind"], s["severity"]), ("ordering_violation", "high"))

    def test_competitor_runs_are_skipped_not_reviewed(self):
        t = review([run(1, peak=500, app="com.phonepe.app", role="competitor"), run(2)], after=0)
        self.assertEqual([x["id"] for x in t["skipped"]], [1])
        self.assertEqual(t["signals"], [])
        self.assertEqual(t["through"], 2)

    def test_existing_issue_is_found_by_its_signal_line(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "P-004.md"), "w") as fh:
            fh.write("# P-004 · Peak RAM\n\n- **Status:** confirmed\n- **Signal:** `budget:peak_rss_mb:com.swag.pay:cold`\n")
        issues = triage.read_issues(d)
        t = review([run(1, peak=450)], after=0, issues=issues)
        self.assertEqual(t["signals"][0]["existing"]["id"], "P-004")
        self.assertEqual(t["signals"][0]["existing"]["status"], "confirmed")
        self.assertEqual(t["next_issue_id"], "P-005")

    def test_open_issue_that_did_not_fire_is_quiet(self):
        issue = {"id": "P-001", "signal": "budget:peak_rss_mb:com.swag.pay:cold", "status": "needs-review", "file": "x"}
        closed = {**issue, "id": "P-002", "status": "dismissed"}
        other_scope = {**issue, "id": "P-003", "signal": "budget:peak_rss_mb:com.swag.pay:warm"}
        t = review([run(1), run(2)], after=0, issues=[issue, closed, other_scope])
        self.assertEqual([(q["id"], q["runs_checked"]) for q in t["quiet"]], [("P-001", [1, 2])])
        self.assertTrue(t["actionable"])

    def test_clean_runs_are_not_actionable(self):
        t = review([run(1), run(2)], after=0)
        self.assertEqual((t["actionable"], t["clean_runs"]), (False, [1, 2]))

    def test_a_reset_history_is_reviewed_from_run_one(self):
        """`swagperf reset` restarts ids at #1; a marker at #81 must not wait for #82."""
        t = review([run(1, peak=400), run(2)], after=81)
        self.assertTrue(t["history_reset"])
        self.assertEqual((t["after"], t["marker"], t["through"]), (0, 81, 2))
        self.assertEqual(len(t["signals"]), 1)

    def test_a_reset_with_open_issues_needs_the_agent_even_with_no_runs(self):
        issue = {"id": "P-001", "signal": "budget:peak_rss_mb:com.swag.pay:cold", "status": "needs-review", "file": "x"}
        t = review([], after=81, issues=[issue])
        self.assertEqual((t["history_reset"], t["through"], t["actionable"]), (True, 0, True))
        self.assertFalse(review([], after=81)["actionable"], "no open issues, nothing to note")

    def test_marker_moves_forward_only_unless_forced(self):
        f = os.path.join(tempfile.mkdtemp(), "TRACKER.md")
        with open(f, "w") as fh:
            fh.write(TRACKER.format(n=10))
        self.assertEqual(triage.read_marker(f), 10)
        self.assertEqual(triage.write_marker(12, f), 12)
        self.assertEqual(triage.write_marker(11, f), 12, "a slow review must not un-review runs")
        self.assertEqual(triage.write_marker(0, f, force=True), 0)
        self.assertIsNone(triage.read_marker(os.path.join(os.path.dirname(f), "missing.md")))


class TestPmRunner(unittest.TestCase):
    """When the agent is started, how, and that reviews never overlap."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.tracker = os.path.join(self.dir, "TRACKER.md")
        self.state = os.path.join(self.dir, "state")
        with open(self.tracker, "w") as fh:
            fh.write(TRACKER.format(n=0))
        # A fake `claude` that records its arguments and the prompt it was given.
        self.calls = os.path.join(self.dir, "calls.jsonl")
        self.claude = os.path.join(self.dir, "claude")
        with open(self.claude, "w") as fh:
            fh.write(f"#!{sys.executable}\nimport json, sys\n"
                     f"open({self.calls!r}, 'a').write(json.dumps({{'argv': sys.argv[1:], 'stdin': sys.stdin.read()}}) + '\\n')\n")
        os.chmod(self.claude, os.stat(self.claude).st_mode | stat.S_IEXEC)
        self.env = {k: os.environ.get(k) for k in ("SWAGPERF_CLAUDE_BIN", "SWAGPERF_PM_AUTOTRIAGE")}
        os.environ["SWAGPERF_CLAUDE_BIN"] = self.claude
        os.environ.pop("SWAGPERF_PM_AUTOTRIAGE", None)

    def tearDown(self):
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _calls(self):
        if not os.path.exists(self.calls):
            return []
        with open(self.calls) as fh:
            return [json.loads(l) for l in fh]

    def _request(self, runs):
        spawned = []
        line = pm.request_review(tracker=self.tracker, state=self.state,
                                 triage_fn=lambda after: review(runs, after),
                                 spawn=lambda tr, st: spawned.append((tr, st)))
        return line, spawned

    def _run(self, runs):
        return pm.run(self.tracker, self.state, triage_fn=lambda after: review(runs, after), claude=self.claude)

    def test_clean_run_moves_the_marker_without_a_model(self):
        runs = [run(1), run(2)]
        line, spawned = self._request(runs)
        self.assertIn("nothing for the tracker", line)
        self.assertEqual(len(spawned), 1)
        self.assertEqual(self._run(runs), 1)
        self.assertEqual(triage.read_marker(self.tracker), 2)
        self.assertEqual(self._calls(), [], "a clean run must not start the agent")

    def test_failing_run_starts_the_agent_once_with_its_limits(self):
        runs = [run(1, peak=480)]
        line, _ = self._request(runs)
        self.assertIn("PM agent reviewing in the background", line)
        self.assertIn("Peak RAM usage over its North Star target", line)
        self.assertEqual(self._run(runs), 1)
        calls = self._calls()
        self.assertEqual(len(calls), 1)
        argv = calls[0]["argv"]
        self.assertEqual(argv[argv.index("--agent") + 1], "product-manager")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "acceptEdits")
        self.assertIn(f"Bash({pm.TRIAGE_CMD}:*)", argv)
        self.assertNotIn("Bash", argv, "no unrestricted shell")
        self.assertIn("run #1", calls[0]["stdin"])
        self.assertEqual(triage.read_marker(self.tracker), 1, "a review that succeeded moves the marker")
        logs = os.listdir(os.path.join(self.state, "logs"))
        self.assertEqual(len(logs), 1)

    def test_a_run_recorded_mid_review_gets_one_more_pass(self):
        runs = [run(1, peak=480)]
        self._request(runs)

        def triage_fn(after):
            # A second run is recorded while the first review is in progress.
            if not os.path.exists(os.path.join(self.state, "second")):
                open(os.path.join(self.state, "second"), "w").close()
                runs.append(run(2, peak=490))
                self.assertIn("reviewing", pm.request_review(tracker=self.tracker, state=self.state,
                                                             triage_fn=lambda a: review(runs, a), spawn=lambda *a: None))
            return review(runs, after)

        passes = pm.run(self.tracker, self.state, triage_fn=triage_fn, claude=self.claude)
        self.assertEqual(passes, 2)
        self.assertEqual(triage.read_marker(self.tracker), 2)

    def test_a_second_runner_leaves_the_review_to_the_one_holding_the_lock(self):
        self.assertTrue(pm._lock(self.state))
        try:
            pm._flag(self.state, "pending")
            self.assertEqual(self._run([run(1, peak=480)]), 0)
            self.assertTrue(os.path.exists(os.path.join(self.state, "pending")), "the holder still has to see it")
        finally:
            pm._unlock(self.state)

    def test_a_dead_runners_lock_is_taken_over(self):
        os.makedirs(self.state, exist_ok=True)
        with open(os.path.join(self.state, "lock"), "w") as fh:
            fh.write("999999")  # no such process
        self.assertTrue(pm._lock(self.state))
        pm._unlock(self.state)

    def test_after_a_reset_the_marker_moves_back_only_once_the_agent_has_run(self):
        with open(self.tracker, "w") as fh:
            fh.write(TRACKER.format(n=81))
        seen = []

        def triage_fn(after):
            seen.append(triage.read_marker(self.tracker))
            return review([run(1, peak=480)], after)

        pm._flag(self.state, "pending")
        pm.run(self.tracker, self.state, triage_fn=triage_fn, claude=self.claude)
        self.assertEqual(seen, [81], "the reset was visible when the review started")
        self.assertIn("after the run history was reset", self._calls()[0]["stdin"])
        self.assertEqual(triage.read_marker(self.tracker), 1)

    def test_failed_agent_leaves_the_marker_for_the_next_review(self):
        with open(self.claude, "w") as fh:
            fh.write(f"#!{sys.executable}\nimport sys\nsys.exit(3)\n")
        runs = [run(1, peak=480)]
        self._request(runs)
        self._run(runs)
        self.assertEqual(triage.read_marker(self.tracker), 0)

    def test_switched_off_does_nothing(self):
        os.environ["SWAGPERF_PM_AUTOTRIAGE"] = "0"
        line, spawned = self._request([run(1, peak=480)])
        self.assertIn("off", line)
        self.assertEqual(spawned, [])

    def test_no_new_runs_does_nothing(self):
        with open(self.tracker, "w") as fh:
            fh.write(TRACKER.format(n=2))
        line, spawned = self._request([run(1), run(2)])
        self.assertIn("no runs since", line)
        self.assertEqual(spawned, [])

    def test_runs_in_another_database_never_reach_the_tracker(self):
        """A test that records into a temporary database once started a real
        review of the real history, which then misread the marker."""
        from swagperf import store
        orig = store.DB
        store.DB = os.path.join(self.dir, "other.db")
        try:
            line, spawned = self._request([run(1, peak=480)])
        finally:
            store.DB = orig
        self.assertIn("not the project's history.db", line)
        self.assertEqual(spawned, [])

    def test_a_tracker_problem_never_fails_the_capture(self):
        line = pm.request_review(tracker=self.tracker, state=self.state,
                                 triage_fn=lambda after: 1 / 0, spawn=lambda *a: None)
        self.assertTrue(line.startswith("PM review not started"))


if __name__ == "__main__":
    unittest.main()
