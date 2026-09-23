"""Tests for the deterministic half of the pipeline.

The LLM analyst is deliberately not tested here: its output is not
deterministic. What must be reliable is measurement and regression detection,
and that is what these cover.
"""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from swagperf.synth import gen_trace
from swagperf.extract import extract, extract_any
from swagperf import store, analyst, catalogue


def _trace(tmp, seed, **kw):
    b, meta = gen_trace(seed, **kw)
    p = os.path.join(tmp, f"t{seed}.pftrace")
    with open(p, "wb") as fh:
        fh.write(b)
    return p, meta


class TestExtract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.p, cls.meta = _trace(cls.tmp, 42)
        cls.m = extract(cls.p)

    def test_steps_found(self):
        names = [s["step"] for s in self.m["steps"]]
        self.assertIn("step:bootstrap", names)
        self.assertIn("step:camera_open", names)
        self.assertTrue(all(s["dur_ms"] > 0 for s in self.m["steps"]))

    def test_child_attribution(self):
        cam = next(s for s in self.m["steps"] if s["step"] == "step:camera_open")
        kids = [c["name"] for c in cam["children"]]
        self.assertIn("CameraX.bindToLifecycle", kids)

    def test_ttff_matches_generator(self):
        self.assertAlmostEqual(
            self.m["startup"]["time_to_first_camera_frame_ms"],
            self.meta["first_frame_ns"] / 1e6, delta=1.0)

    def test_clean_run_has_no_ordering_violation(self):
        """Deferred work starting at the frame boundary must not be flagged."""
        self.assertEqual(self.m["ordering_violations"], [])

    def test_frames_and_memory_present(self):
        self.assertGreater(self.m["frames"]["total"], 100)
        self.assertIn("rss", self.m["memory"])
        self.assertGreater(self.m["memory"]["rss"]["peak_mb"], 0)

    def test_first_run_path_uses_its_own_critical_path(self):
        p, _ = _trace(self.tmp, 43, path="first_run")
        m = extract(p, path_kind="first_run")
        self.assertIn("step:hermes_boot", m["startup"]["critical_path"])
        # Hermes on the critical path is correct for first-run, not a violation.
        self.assertEqual(m["ordering_violations"], [])


class TestRegression(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "h.db")
        for i in range(10):
            p, _ = _trace(self.tmp, 200 + i)
            store.record(extract(p), label=f"b{i}", device="pixel7", db=self.db)

    def test_detects_injected_regression(self):
        p, _ = _trace(self.tmp, 900, regress={"step:camera_open": 1.9})
        rid = store.record(extract(p), label="bad", device="pixel7", db=self.db)
        regs = store.regressions(rid, db=self.db)
        self.assertTrue(any(r["step"] == "step:camera_open" for r in regs))
        self.assertGreater(next(r for r in regs if r["step"] == "step:camera_open")["delta_pct"], 40)

    def test_clean_run_is_quiet(self):
        p, _ = _trace(self.tmp, 901)
        rid = store.record(extract(p), label="ok", device="pixel7", db=self.db)
        self.assertEqual(store.regressions(rid, db=self.db), [])

    def test_no_regressions_below_minimum_baseline(self):
        db2 = os.path.join(self.tmp, "thin.db")
        p, _ = _trace(self.tmp, 300)
        store.record(extract(p), db=db2)
        p2, _ = _trace(self.tmp, 301, regress={"step:camera_open": 3.0})
        rid = store.record(extract(p2), db=db2)
        # Two samples is not a baseline; must not fire.
        self.assertEqual(store.regressions(rid, db=db2), [])


class TestRegressionFloor(unittest.TestCase):
    def test_tiny_absolute_move_is_not_a_regression(self):
        """process_start 2.61ms -> 6.17ms is +136% and many sigma, and still not
        something a user can perceive. It used to fail a real device run."""
        db = os.path.join(tempfile.mkdtemp(), "h.db")
        c = store.connect(db)
        ids = []
        for i, d in enumerate([2.6, 2.5, 2.7, 2.6, 2.55, 2.65, 6.17]):
            cur = c.execute("insert into runs (ts, path_kind, device) values (?, 'cold', 'x')",
                            (f"2026-01-0{i+1}",))
            c.execute("insert into step_metrics (run_id, step, dur_ms) values (?, 'step:process_start', ?)",
                      (cur.lastrowid, d))
            ids.append(cur.lastrowid)
        c.commit(); c.close()
        self.assertEqual(store.regressions(ids[-1], db=db, use_benchmark=False), [])
        # The same relative move on a step large enough to matter still fires.
        self.assertTrue(store.regressions(ids[-1], db=db, use_benchmark=False, min_delta_ms=1.0))


class TestOrderingViolation(unittest.TestCase):
    def test_deferred_work_on_critical_path_is_caught(self):
        """A first_run trace judged as returning_user must flag Hermes."""
        tmp = tempfile.mkdtemp()
        p, _ = _trace(tmp, 55, path="first_run")
        m = extract(p, path_kind="returning_user")
        steps = [v["step"] for v in m["ordering_violations"]]
        self.assertIn("step:hermes_boot", steps)


class TestChildBreakdown(unittest.TestCase):
    def test_children_sum_to_step_duration(self):
        """Direct children plus self-time must account for the whole step."""
        tmp = tempfile.mkdtemp()
        p, _ = _trace(tmp, 61)
        m = extract(p)
        for st in m["steps"]:
            if not st["children"]:
                continue
            total = sum(c["dur_ms"] for c in st["children"])
            self.assertAlmostEqual(total, st["dur_ms"], delta=0.05,
                                   msg=f"{st['step']} breakdown does not sum")

    def test_pct_of_step_present_and_sane(self):
        tmp = tempfile.mkdtemp()
        p, _ = _trace(tmp, 62)
        m = extract(p)
        for st in m["steps"]:
            for c in st["children"]:
                self.assertIsNotNone(c["pct_of_step"])
                self.assertGreater(c["pct_of_step"], 0)
                self.assertLessEqual(c["pct_of_step"], 100.5)

    def test_reextract_rewrites_history(self):
        tmp = tempfile.mkdtemp()
        db = os.path.join(tmp, "r.db")
        p, _ = _trace(tmp, 63)
        rid = store.record(extract(p), trace_path=p, db=db)
        c = store.connect(db)
        c.execute("update step_metrics set children_json='[]' where run_id=?", (rid,))
        c.commit(); c.close()
        res = store.reextract(db=db)
        self.assertEqual(res["reextracted"], 1)
        c = store.connect(db)
        import json as _j
        kids = _j.loads(list(c.execute(
            "select children_json from step_metrics where run_id=? and step='step:camera_open'",
            (rid,)))[0]["children_json"])
        c.close()
        self.assertTrue(any(k["name"] == "CameraX.bindToLifecycle" for k in kids))


class TestBenchmarkAndCompare(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "b.db")
        self.ids = []
        for i in range(8):
            p, _ = _trace(self.tmp, 400 + i)
            self.ids.append(store.record(extract(p), label=f"b{i}", device="pixel7",
                                         trace_path=p, db=self.db))

    def test_set_get_clear_benchmark(self):
        store.set_benchmark(self.ids[0], note="golden", db=self.db)
        b = store.get_benchmark(path_kind="returning_user", device="pixel7", db=self.db)
        self.assertEqual(b["run_id"], self.ids[0])
        self.assertEqual(b["note"], "golden")
        store.clear_benchmark(run_id=self.ids[0], db=self.db)
        self.assertIsNone(store.get_benchmark(path_kind="returning_user",
                                              device="pixel7", db=self.db))

    def test_benchmark_is_scoped_by_path_kind(self):
        """A returning_user benchmark must not be used for a first_run trace."""
        store.set_benchmark(self.ids[0], db=self.db)
        self.assertIsNone(store.get_benchmark(path_kind="first_run",
                                              device="pixel7", db=self.db))

    def test_benchmark_changes_regression_reference(self):
        p, _ = _trace(self.tmp, 500, regress={"step:camera_open": 2.0})
        rid = store.record(extract(p), label="bad", device="pixel7", db=self.db)
        store.set_benchmark(self.ids[0], db=self.db)
        regs = store.regressions(rid, db=self.db)
        self.assertTrue(regs)
        self.assertEqual(regs[0]["reference"], "benchmark")
        self.assertEqual(regs[0]["benchmark_run_id"], self.ids[0])

    def test_run_is_never_a_regression_against_itself(self):
        store.set_benchmark(self.ids[3], db=self.db)
        self.assertEqual(store.regressions(self.ids[3], db=self.db), [])

    def test_clean_run_quiet_against_benchmark(self):
        store.set_benchmark(self.ids[0], db=self.db)
        self.assertEqual(store.regressions(self.ids[5], db=self.db), [])

    def test_compare_is_symmetric_in_sign(self):
        a, b = self.ids[1], self.ids[2]
        d1 = store.compare(a, b, db=self.db)
        d2 = store.compare(b, a, db=self.db)
        m1 = {m["metric"]: m["delta"] for m in d1["metrics"]}
        m2 = {m["metric"]: m["delta"] for m in d2["metrics"]}
        for k in m1:
            self.assertAlmostEqual(m1[k], -m2[k], places=2)

    def test_compare_flags_incomparable_paths(self):
        p, _ = _trace(self.tmp, 510, path="first_run")
        fid = store.record(extract(p, path_kind="first_run"), label="fr",
                           device="pixel7", db=self.db)
        d = store.compare(fid, self.ids[0], db=self.db)
        self.assertFalse(d["comparable"])

    def test_signed_metric_has_no_percentage(self):
        """Thermal drift crosses zero, so a ratio would be nonsense."""
        d = store.compare(self.ids[1], self.ids[2], db=self.db)
        drift = next(m for m in d["metrics"] if m["metric"] == "thermal_drift_pct")
        self.assertTrue(drift["signed"])
        self.assertIsNone(drift["delta_pct"])

    def test_compare_attributes_to_child_slices(self):
        p, _ = _trace(self.tmp, 520, regress={"CameraX.bindToLifecycle": 2.5})
        rid = store.record(extract(p), label="kid", device="pixel7", db=self.db)
        d = store.compare(rid, self.ids[0], db=self.db)
        cam = next(s for s in d["steps"] if s["step"] == "step:camera_open")
        worst = max((k for k in cam["children"] if k["delta_ms"] is not None),
                    key=lambda k: k["delta_ms"])
        self.assertEqual(worst["name"], "CameraX.bindToLifecycle")


class TestGenericAppDerivation(unittest.TestCase):
    """Coverage for the uninstrumented-app path (competitor binaries)."""

    def test_cold_start_derives_process_start_phase(self):
        from swagperf.synth_android import gen_android_trace
        tmp = tempfile.mkdtemp()
        b, _ = gen_android_trace(1, pkg="com.example.app", cold=True)
        p = os.path.join(tmp, "cold.pftrace")
        with open(p, "wb") as fh:
            fh.write(b)
        m = extract_any(p, app_pkg="com.example.app")
        self.assertTrue(m["derived"])
        names = [s["step"] for s in m["steps"]]
        self.assertIn("step:process_start", names)
        self.assertIn("step:bind_application", names)
        self.assertGreater(m["startup"]["time_to_first_camera_frame_ms"], 0)

    def test_warm_start_has_no_process_start_phase(self):
        from swagperf.synth_android import gen_android_trace
        tmp = tempfile.mkdtemp()
        b, _ = gen_android_trace(2, pkg="com.example.app", cold=False)
        p = os.path.join(tmp, "warm.pftrace")
        with open(p, "wb") as fh:
            fh.write(b)
        m = extract_any(p, app_pkg="com.example.app")
        names = [s["step"] for s in m["steps"]]
        self.assertNotIn("step:process_start", names)

    def test_derived_run_has_no_invented_budgets(self):
        """A competitor's app must never get a made-up performance budget."""
        from swagperf.synth_android import gen_android_trace
        tmp = tempfile.mkdtemp()
        b, _ = gen_android_trace(3, pkg="com.some.competitor")
        p = os.path.join(tmp, "c.pftrace")
        with open(p, "wb") as fh:
            fh.write(b)
        m = extract_any(p, app_pkg="com.some.competitor")
        self.assertIsNone(m["startup"]["budget_ms"])
        for s in m["steps"]:
            self.assertIsNone(s["budget_ms"])

    def test_instrumented_app_with_own_budget_is_read_directly(self):
        """An app the catalogue marks instrumented bypasses derivation entirely."""
        tmp = tempfile.mkdtemp()
        p, _ = _trace(tmp, 700)
        m = extract_any(p, app_pkg="com.swag.pay")
        self.assertFalse(m["derived"])
        self.assertEqual(m["startup"]["budget_ms"], 420)


class TestCatalogue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig_user = catalogue.USER
        catalogue.USER = os.path.join(self.tmp, "apps.local.json")

    def tearDown(self):
        catalogue.USER = self._orig_user

    def test_own_app_is_instrumented_by_default(self):
        self.assertTrue(catalogue.is_instrumented("com.swag.pay"))

    def test_add_and_remove_round_trip(self):
        catalogue.add("com.test.app", name="Test App", role="competitor")
        self.assertIsNotNone(catalogue.get("com.test.app"))
        catalogue.remove("com.test.app")
        self.assertIsNone(catalogue.get("com.test.app"))

    def test_remove_can_hide_a_builtin_entry(self):
        self.assertIsNotNone(catalogue.get("com.swag.pay"))
        catalogue.remove("com.swag.pay")
        self.assertIsNone(catalogue.get("com.swag.pay"))

    def test_competitor_has_no_budgets_unless_explicitly_given(self):
        catalogue.add("com.rival.app", name="Rival", role="competitor")
        self.assertEqual(catalogue.budgets_for("com.rival.app"), {})

    def test_invalid_role_rejected(self):
        with self.assertRaises(ValueError):
            catalogue.add("com.bad.app", role="not_a_real_role")


class TestCLIPathKindDefaulting(unittest.TestCase):
    """Regression coverage for a real bug: the CLI's --path-kind flag defaulted
    to "returning_user" (Swag Pay's own default) and was passed through even
    for a derived competitor app, silently mislabeling its cold/warm
    classification and mixing it into Swag Pay's own path_kind bucket."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "cli.db")
        self._orig_db = store.DB
        store.DB = self.db
        self._orig_user = catalogue.USER
        catalogue.USER = os.path.join(self.tmp, "apps.local.json")
        catalogue.add("com.rival.app", name="Rival", role="competitor")

    def tearDown(self):
        store.DB = self._orig_db
        catalogue.USER = self._orig_user

    def test_analysing_a_derived_app_without_path_kind_flag_infers_cold_or_warm(self):
        from swagperf import cli
        from swagperf.synth_android import gen_android_trace
        b, _ = gen_android_trace(9, pkg="com.rival.app", cold=True)
        p = os.path.join(self.tmp, "rival.pftrace")
        with open(p, "wb") as fh:
            fh.write(b)
        rc = cli.main(["analyse", p, "--app", "com.rival.app", "--no-llm"])
        self.assertEqual(rc, 0)
        c = store.connect(self.db)
        row = c.execute("select path_kind, app_pkg from runs order by id desc limit 1").fetchone()
        c.close()
        self.assertEqual(row["app_pkg"], "com.rival.app")
        self.assertIn(row["path_kind"], ("cold", "warm"))
        self.assertNotEqual(row["path_kind"], "returning_user")


class TestStressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "s.db")

    def _seed(self, values, requested=None):
        sid = store.stress_create(app_pkg="com.rival.app", device="pixel7",
                                  sessions=requested or len(values), db=self.db)
        for i, v in enumerate(values, start=1):
            if v is None:
                store.stress_session_done(sid, i, state="error",
                                          error="did not observe app", db=self.db)
            else:
                store.stress_session_done(sid, i, ttid_ms=v, db=self.db)
        store.stress_finish(sid, db=self.db)
        return sid

    def test_stats_report_spread_not_just_mean(self):
        sid = self._seed([100.0, 120.0, 110.0, 180.0, 105.0])
        t = store.stress_get(sid, db=self.db)
        st = t["stats"]["ttid_ms"]
        self.assertEqual(st["n"], 5)
        self.assertEqual(st["min"], 100.0)
        self.assertEqual(st["max"], 180.0)
        self.assertEqual(st["median"], 110.0)
        # The spread is the headline: 80ms of range on a 110ms median.
        self.assertAlmostEqual(st["spread_pct"], 72.7, places=1)
        self.assertGreater(st["stdev"], 0)

    def test_failed_sessions_do_not_sink_the_test(self):
        """A stress test with some failures is still informative."""
        sid = self._seed([100.0, None, 120.0, None, 110.0])
        t = store.stress_get(sid, db=self.db)
        self.assertEqual(t["completed"], 3)
        self.assertEqual(t["failed"], 2)
        self.assertEqual(t["stats"]["ttid_ms"]["n"], 3)

    def test_all_sessions_failed_yields_no_stats(self):
        sid = self._seed([None, None])
        t = store.stress_get(sid, db=self.db)
        self.assertEqual(t["completed"], 0)
        self.assertIsNone(t["stats"]["ttid_ms"])

    def test_single_session_has_zero_stdev_not_a_crash(self):
        sid = self._seed([150.0])
        st = store.stress_get(sid, db=self.db)["stats"]["ttid_ms"]
        self.assertEqual(st["n"], 1)
        self.assertEqual(st["stdev"], 0.0)
        self.assertEqual(st["median"], 150.0)

    def test_sessions_are_ordered_and_listed(self):
        sid = self._seed([100.0, 200.0, 150.0])
        t = store.stress_get(sid, db=self.db)
        self.assertEqual([x["seq"] for x in t["sessions"]], [1, 2, 3])
        self.assertIn(sid, [x["id"] for x in store.stress_list(db=self.db)])

    def test_pending_sessions_counted_before_completion(self):
        sid = store.stress_create(app_pkg="com.rival.app", sessions=4, db=self.db)
        t = store.stress_get(sid, db=self.db)
        self.assertEqual(t["state"], "running")
        self.assertEqual(t["completed"], 0)
        self.assertEqual(len(t["sessions"]), 4)


class TestScreenMetrics(unittest.TestCase):
    """Per-screen attribution from SwagTrace markers."""

    @classmethod
    def setUpClass(cls):
        from swagperf.synth_android import gen_swagpay_trace
        from swagperf.screens import extract_screens
        cls.tmp = tempfile.mkdtemp()
        cls.flow = [("Home", 2000), ("Store", 1200), ("Pay", 2400), ("Home", 800)]
        b, _ = gen_swagpay_trace(11, flow=cls.flow)
        cls.path = os.path.join(cls.tmp, "s.pftrace")
        with open(cls.path, "wb") as fh:
            fh.write(b)
        cls.d = extract_screens(cls.path)

    def test_detects_markers(self):
        self.assertTrue(self.d["instrumented"])

    def test_one_visit_per_flow_entry(self):
        self.assertEqual(len(self.d["screens"]), len(self.flow))
        self.assertEqual([v["route"] for v in self.d["screens"]],
                         [r for r, _ in self.flow])

    def test_visit_durations_match_the_flow(self):
        """A nav slice opening before the screen slice would swap these."""
        for visit, (_, dwell) in zip(self.d["screens"], self.flow):
            self.assertAlmostEqual(visit["duration_ms"], dwell, delta=5.0)

    def test_repeat_visits_are_summed_not_averaged(self):
        home = next(s for s in self.d["screen_summary"] if s["route"] == "Home")
        self.assertEqual(home["visits"], 2)
        self.assertAlmostEqual(home["total_ms"], 2000 + 800, delta=10.0)

    def test_ram_growth_attributed_per_screen(self):
        pay = next(s for s in self.d["screen_summary"] if s["route"] == "Pay")
        home = next(s for s in self.d["screen_summary"] if s["route"] == "Home")
        # Pay hosts an RN surface and grows fastest in the generator; the point
        # of per-screen RAM is that this difference is visible at all.
        self.assertGreater(pay["max_rss_delta_mb"], home["max_rss_delta_mb"])

    def test_actions_are_counted(self):
        names = {a["action"] for a in self.d["actions"]}
        self.assertIn("qr_validate_valid_upi", names)
        self.assertTrue(any(a.startswith("pay_") for a in names))

    def test_navigations_report_the_transition_not_the_dwell(self):
        """A transition costs tens of ms; a dwell costs hundreds."""
        self.assertTrue(self.d["navigations"])
        for n in self.d["navigations"]:
            self.assertIsNotNone(n["from"])
            self.assertIsNotNone(n["to"])
            self.assertLess(n["max_ms"], 200.0)

    def test_unclosed_screen_slice_is_still_a_visit(self):
        """The last screen of a manual session never closes.

        Perfetto stores dur = -1 for a slice whose end event never arrived,
        which is the normal shape of whichever screen was on display when
        tracing stopped. Discarding those reported "0 visits" for a session
        that plainly had one, so the visit must survive, be clamped to the end
        of the trace, and be flagged as open-ended rather than silently
        presented as a completed span.
        """
        from swagperf.screens import screen_visits

        class FakeTP:
            """Minimal stand-in: screens.py only ever calls _rows(tp, sql)."""

        import swagperf.screens as sc
        real_rows = sc._rows
        calls = []

        def fake_rows(tp, sql):
            calls.append(sql)
            if "max(ts + max(dur, 0))" in sql:
                return [{"e": 5_000_000_000}]
            if "like 'screen:%'" in sql:
                return [{"sid": 1, "nm": "screen:Onboarding",
                         "ts": 1_000_000_000, "dur": -1, "upid": 7}]
            if "sched_slice" in sql:
                return [{"cpu_ns": 400_000_000}]
            if "mem.rss" in sql:
                return [{"lo": 100 * 1024 * 1024, "hi": 150 * 1024 * 1024}]
            return [{"n": 0, "slow": 0}]

        sc._rows = fake_rows
        try:
            visits = screen_visits(FakeTP())
        finally:
            sc._rows = real_rows

        self.assertEqual(len(visits), 1)
        v = visits[0]
        self.assertEqual(v["route"], "Onboarding")
        self.assertTrue(v["open_ended"])
        # Clamped to trace end: 5s - 1s = 4s, not left at -1.
        self.assertAlmostEqual(v["duration_ms"], 4000.0, delta=1.0)
        self.assertEqual(v["cpu_ms"], 400.0)
        self.assertEqual(v["rss"]["delta_mb"], 50.0)

    def test_live_markers_timeline_and_current_screen(self):
        """The live feed reports each kind and which screen is still open."""
        from swagperf.screens import live_markers
        d = live_markers(self.path)
        self.assertEqual(d["counts"].get("screen"), len(self.flow))
        self.assertTrue(d["counts"].get("action"))
        kinds = {e["kind"] for e in d["events"]}
        self.assertTrue(kinds <= {"screen", "action", "nav", "step"})
        # The synthetic flow closes every screen, so nothing is left open.
        self.assertIsNone(d["current_screen"])
        # Timeline is ordered and zeroed on the first marker.
        ats = [e["at_ms"] for e in d["events"]]
        self.assertEqual(ats, sorted(ats))
        self.assertEqual(ats[0], 0.0)

    def test_screen_kind_is_parsed_from_the_marker(self):
        """A hybrid app must say what rendered each screen.

        The kind rides as a `#suffix` on the slice name so the extractor's
        prefix matching is unchanged. An untagged name must still parse, or a
        trace from an older build would lose every visit rather than just the
        tag.
        """
        from swagperf.screens import parse_route
        rn = parse_route("Onboarding.otp#rn")
        self.assertEqual(rn["route"], "Onboarding.otp")
        self.assertEqual(rn["parent"], "Onboarding")
        self.assertEqual(rn["step"], "otp")
        self.assertEqual(rn["kind_label"], "React Native")

        compose = parse_route("Home#compose")
        self.assertEqual(compose["route"], "Home")
        self.assertIsNone(compose["step"])
        self.assertEqual(compose["kind_label"], "Compose")

        legacy = parse_route("Home")
        self.assertEqual(legacy["route"], "Home")
        self.assertEqual(legacy["kind"], "unknown")

    def test_substeps_are_not_added_into_their_parent(self):
        """A sub-screen runs *inside* its parent, so summing both double-counts.

        An onboarding flow whose steps were added to the route containing them
        would report roughly twice its real wall time, which is worse than not
        reporting the steps at all.
        """
        from swagperf.screens import screen_summary, parse_route

        def visit(raw, ms, cpu):
            return {**parse_route(raw), "duration_ms": ms, "cpu_ms": cpu,
                    "frames": 0, "slow_frames": 0, "rss": None}

        visits = [
            visit("Onboarding#rn", 5000.0, 900.0),
            visit("Onboarding.mobile#rn", 2000.0, 300.0),
            visit("Onboarding.otp#rn", 3000.0, 600.0),
            visit("Home#native_view", 4000.0, 1200.0),
        ]

        full = screen_summary(visits)
        self.assertEqual({r["route"] for r in full},
                         {"Onboarding", "Onboarding.mobile", "Onboarding.otp",
                          "Home"})
        otp = next(r for r in full if r["route"] == "Onboarding.otp")
        self.assertEqual(otp["step"], "otp")
        self.assertEqual(otp["kind_label"], "React Native")

        top = screen_summary(visits, include_substeps=False)
        self.assertEqual({r["route"] for r in top}, {"Onboarding", "Home"})
        self.assertEqual(sum(r["total_ms"] for r in top), 9000.0)

    def test_visits_are_kept_individually_with_spread_and_outliers(self):
        """A total cannot distinguish steady visits from one pathological one.

        Twelve even visits and eleven cheap ones plus a runaway twelfth sum to
        the same number, and it is nearly always the twelfth that is the bug.
        Each visit is therefore kept, with a mean to compare against and a flag
        on anything more than two standard deviations away.
        """
        from swagperf.screens import screen_summary, parse_route

        def visit(ms, cpu):
            return {**parse_route("Home#compose"), "duration_ms": ms,
                    "cpu_ms": cpu, "cpu_pct_of_wall": round(cpu / ms * 100, 1),
                    "frames": 0, "slow_frames": 0, "rss": None}

        # Eleven steady visits and one that costs an order of magnitude more.
        visits = [visit(1000.0, 200.0) for _ in range(11)] + [visit(1000.0, 5000.0)]
        home = screen_summary(visits)[0]

        self.assertEqual(home["visits"], 12)
        self.assertEqual(len(home["visit_list"]), 12)
        # Order is preserved, so a trend across visits stays visible.
        self.assertEqual([v["index"] for v in home["visit_list"]], list(range(1, 13)))

        cpu = home["stats"]["cpu_ms"]
        self.assertEqual(cpu["min"], 200.0)
        self.assertEqual(cpu["max"], 5000.0)
        self.assertGreater(cpu["stdev"], 0)

        flagged = [v["index"] for v in home["visit_list"] if v["outlier"]["cpu_ms"]]
        self.assertEqual(flagged, [12])

    def test_a_single_visit_has_no_spread_rather_than_zero_spread(self):
        """One visit cannot deviate from itself.

        Reporting a standard deviation of 0 would read as "perfectly
        consistent" instead of "nothing to compare against", and would make
        every later comparison against it meaningless.
        """
        from swagperf.screens import screen_summary, parse_route
        only = [{**parse_route("Pay#compose"), "duration_ms": 500.0,
                 "cpu_ms": 120.0, "cpu_pct_of_wall": 24.0,
                 "frames": 0, "slow_frames": 0, "rss": None}]
        row = screen_summary(only)[0]
        self.assertIsNone(row["stats"]["cpu_ms"]["stdev"])
        self.assertFalse(row["visit_list"][0]["outlier"]["cpu_ms"])

    def test_navigation_stack_is_replayed_from_push_pop_and_reset(self):
        """The stack cannot be read from slice nesting, so it is replayed.

        `ScreenTrace` keeps a single slot, so screen slices are strictly
        sequential and never overlap -- there is no nesting to read a depth
        from. The coordinator's nav markers are the stack operations, so
        replaying them in order rebuilds the same back stack the app held.
        """
        from swagperf.screens import screen_stack
        import swagperf.screens as sc

        events = [
            ("screen:Home#native_view", 0),
            ("nav:open-Send", 100), ("screen:Send#compose", 101),
            ("nav:open-Pay", 200), ("screen:Pay#compose", 201),
            ("nav:back-Send", 300), ("screen:Send#compose", 301),
            ("nav:tab-Store", 400), ("screen:Store#compose", 401),
        ]
        real = sc._rows
        sc._rows = lambda tp, sql: [{"nm": n, "ts": t} for n, t in events]
        try:
            out = screen_stack(object())
        finally:
            sc._rows = real

        self.assertEqual([(e["route"], e["depth"]) for e in out],
                         [("Home", 1), ("Send", 2), ("Pay", 3), ("Send", 2),
                          ("Store", 1)])
        pay = out[2]
        self.assertEqual(pay["stack"], ["Home", "Send", "Pay"])
        # What is still alive underneath is the part a per-screen number cannot
        # show, and is usually the reason RAM is high on a cheap screen.
        self.assertEqual(pay["beneath"], ["Home", "Send"])
        # A tab reset clears the stack rather than deepening it.
        self.assertEqual(out[4]["stack"], ["Store"])

    def test_back_never_pops_the_last_screen(self):
        """A trace can begin mid-session, with a back and no recorded push.

        Popping the root would leave an empty stack and a depth of zero, which
        is not a state the app can be in -- something is always on screen.
        """
        from swagperf.screens import screen_stack
        import swagperf.screens as sc
        events = [("nav:back-Home", 0), ("screen:Home#native_view", 1),
                  ("nav:back-Home", 2), ("screen:Home#native_view", 3)]
        real = sc._rows
        sc._rows = lambda tp, sql: [{"nm": n, "ts": t} for n, t in events]
        try:
            out = screen_stack(object())
        finally:
            sc._rows = real
        self.assertTrue(all(e["depth"] >= 1 for e in out))

    def test_stack_summary_groups_cost_by_depth(self):
        """Depth is the grouping that explains a cheap screen holding RAM."""
        from swagperf.screens import stack_summary, parse_route

        def visit(raw, ms, cpu, stack):
            return {**parse_route(raw), "duration_ms": ms, "cpu_ms": cpu,
                    "frames": 0, "slow_frames": 0,
                    "rss": {"min_mb": 400.0, "peak_mb": 480.0, "delta_mb": 80.0},
                    "depth": len(stack), "stack": stack, "beneath": stack[:-1]}

        rows = stack_summary([
            visit("Home#native_view", 1000.0, 500.0, ["Home"]),
            visit("Pay#compose", 1000.0, 100.0, ["Home", "Send", "Pay"]),
            visit("Pay#compose", 1000.0, 120.0, ["Home", "Send", "Pay"]),
        ])
        self.assertEqual([r["depth"] for r in rows], [1, 3])
        deep = rows[1]
        self.assertEqual(deep["visits"], 2)
        self.assertEqual(dict(deep["beneath"]), {"Home": 2, "Send": 2})
        # Low CPU with high resident memory is the signature worth surfacing.
        self.assertEqual(deep["mean_cpu_pct"], 11.0)
        self.assertEqual(deep["peak_rss_mb"], 480.0)

    def test_uninstrumented_trace_says_so_rather_than_reporting_zeros(self):
        from swagperf.synth_android import gen_android_trace
        from swagperf.screens import extract_screens
        b, _ = gen_android_trace(12, pkg="com.plain.app")
        p2 = os.path.join(self.tmp, "plain.pftrace")
        with open(p2, "wb") as fh:
            fh.write(b)
        d = extract_screens(p2)
        self.assertFalse(d["instrumented"])
        self.assertEqual(d["screens"], [])
        self.assertIn("SwagTrace", d["note"])


class TestManualModeConfig(unittest.TestCase):
    def test_manual_config_has_no_duration(self):
        """A manual session is open-ended; a duration would truncate it."""
        from swagperf import capture
        self.assertNotIn("duration_ms", capture.MANUAL_CONFIG)
        self.assertIn("duration_ms", capture.CONFIG)

    def test_manual_config_formats_with_pkg(self):
        from swagperf import capture
        cfg = capture.MANUAL_CONFIG.format(pkg="com.example.app")
        self.assertIn('atrace_apps: "com.example.app"', cfg)
        # Braces survive as real perfetto config syntax; what must NOT survive
        # is a doubled brace, which would mean a placeholder was left unescaped.
        self.assertNotIn("{{", cfg)
        self.assertNotIn("}}", cfg)

    def test_manual_status_without_device_is_not_an_error(self):
        from swagperf import capture
        orig = capture.devices
        capture.devices = lambda: []
        try:
            st = capture.manual_status()
            self.assertFalse(st["device"])
            self.assertFalse(st["recording"])
        finally:
            capture.devices = orig


class TestHeuristic(unittest.TestCase):
    def test_heuristic_runs_without_network(self):
        tmp = tempfile.mkdtemp()
        p, _ = _trace(tmp, 77)
        m = extract(p)
        res = analyst.heuristic(m, [])
        self.assertIn(res["verdict"], ("pass", "warn", "fail"))
        self.assertIn("findings", res)

    def test_payload_excludes_raw_trace(self):
        """The model must only ever see extracted metrics."""
        tmp = tempfile.mkdtemp()
        p, _ = _trace(tmp, 78)
        payload = analyst.build_payload(extract(p), [], {})
        blob = repr(payload)
        self.assertNotIn("pftrace", blob)
        self.assertIn("steps", payload)
        self.assertIn("global_budgets", payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestDeviceTraceAccuracy(unittest.TestCase):
    """Faults found against a real Android 16 device, each of which produced a
    plausible-looking wrong number rather than an error."""

    def _fake_rows(self, answers):
        """Stand in for _rows: return the first answer whose key is in the SQL."""
        def fake(tp, sql):
            for key, rows in answers:
                if key in sql:
                    return rows
            return []
        return fake

    def test_no_frames_is_unmeasured_not_perfect(self):
        """Zero frames used to report 0% slow -- which read as a clean pass and
        hid the doFrame naming bug on every device run."""
        import swagperf.extract as ex
        real = ex._rows
        ex._rows = self._fake_rows([("count(*) total", [{"total": 0}])])
        try:
            f = ex._frames(object())
        finally:
            ex._rows = real
        self.assertIsNone(f["slow_pct"])
        self.assertIsNone(f["janky_pct"])
        self.assertIsNone(f["thermal_drift_pct"])

    def test_frames_match_the_android12_vsync_suffix(self):
        """Android 12+ names the slice `Choreographer#doFrame <vsync>`."""
        import swagperf.extract as ex
        self.assertTrue(ex.DOFRAME.endswith("%"))
        self.assertTrue("Choreographer#doFrame 5887310".startswith(ex.DOFRAME[:-1]))

    def test_frames_and_memory_are_scoped_to_the_app(self):
        """Unscoped, peak RAM was system_server's 803MB and growth subtracted one
        process's minimum from another process's maximum."""
        import swagperf.extract as ex
        seen = []
        real = ex._rows
        def fake(tp, sql):
            seen.append(sql)
            return [{"total": 0}] if "count(*) total" in sql else [{"mx": 1, "mn": 1}]
        ex._rows = fake
        try:
            ex._frames(object(), upids=[1223])
            ex._memory(object(), upids=[1223])
        finally:
            ex._rows = real
        self.assertTrue(any("th.upid in (1223)" in q for q in seen))
        self.assertTrue(any("t.upid in (1223)" in q for q in seen))

    def test_short_trace_has_no_drift(self):
        """Too few sustained frames is too short a window to see throttling."""
        import swagperf.extract as ex
        real = ex._rows
        ex._rows = self._fake_rows([
            ("count(*) total", [{"total": 50, "slow": 0, "janky": 0,
                                 "avg_dur": 5_000_000, "max_dur": 9_000_000}]),
            ("first_half", [{"first_half": 30e6, "second_half": 5e6, "n": 40}]),
        ])
        try:
            f = ex._frames(object())
        finally:
            ex._rows = real
        self.assertIsNone(f["thermal_drift_pct"])


class TestCataloguePlaceholders(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig = catalogue.USER
        catalogue.USER = os.path.join(self.tmp, "apps.local.json")

    def tearDown(self):
        catalogue.USER = self._orig

    def test_auto_added_placeholder_never_overrides_a_builtin(self):
        """How Swag Pay itself came to be listed as a nameless competitor."""
        catalogue.add("com.swag.pay", name="com.swag.pay", role="competitor", auto=True)
        a = catalogue.get("com.swag.pay")
        self.assertEqual(a["role"], "own")
        self.assertEqual(a["name"], "Swag Pay")
        self.assertTrue(a["instrumented"])

    def test_legacy_placeholder_without_flag_is_also_ignored(self):
        """Placeholders written before `auto` existed have name == pkg."""
        catalogue.save_user([{"pkg": "com.swag.pay", "name": "com.swag.pay",
                              "role": "competitor"}])
        self.assertEqual(catalogue.get("com.swag.pay")["role"], "own")

    def test_a_deliberate_local_override_still_wins(self):
        catalogue.add("com.swag.pay", name="Swag Pay (dogfood)", role="own",
                      budgets={"ttid_ms": 380})
        self.assertEqual(catalogue.get("com.swag.pay")["budgets"]["ttid_ms"], 380)


class TestBreachSeverity(unittest.TestCase):
    def _m(self, breaches):
        return {"ordering_violations": [], "breaches": breaches}

    def test_far_over_budget_fails(self):
        """A 4x RAM-growth breach used to read WARN: every breach was 'medium'."""
        res = analyst.heuristic(self._m([
            {"metric": "rss_growth_mb", "value": 256.0, "budget": 60, "over_by_pct": 326.7},
            {"metric": "janky_frame_pct", "value": 0.52, "budget": 0.5, "over_by_pct": 4.0},
        ]), [])
        self.assertEqual(res["verdict"], "fail")
        self.assertTrue(res["headline"].startswith("RAM growth over budget"))
        self.assertIn("+1 more", res["headline"])

    def test_marginal_breach_only_warns(self):
        res = analyst.heuristic(self._m([
            {"metric": "janky_frame_pct", "value": 0.52, "budget": 0.5, "over_by_pct": 4.0},
        ]), [])
        self.assertEqual(res["verdict"], "warn")

    def test_clean_run_headline_says_so(self):
        res = analyst.heuristic(self._m([]), [])
        self.assertEqual(res["verdict"], "pass")
        self.assertIn("within budget", res["headline"])


class TestAppProcessResolution(unittest.TestCase):
    """The app's process must be found, and if it cannot be, nothing may be
    silently measured across the whole device instead."""

    def test_falls_back_to_the_process_that_emitted_markers(self):
        import swagperf.extract as ex
        real = ex._rows
        ex._rows = lambda tp, sql: [] if "from process where name" in sql else [{"upid": 42}]
        try:
            self.assertEqual(ex._app_upids(object(), "com.swag.pay"), [42])
        finally:
            ex._rows = real

    def test_named_process_wins(self):
        import swagperf.extract as ex
        real = ex._rows
        ex._rows = lambda tp, sql: [{"upid": 7}] if "from process where name" in sql else [{"upid": 42}]
        try:
            self.assertEqual(ex._app_upids(object(), "com.swag.pay"), [7])
        finally:
            ex._rows = real

    def test_unfound_app_is_unmeasured_not_device_wide(self):
        import swagperf.extract as ex
        f = ex._unmeasured_frames()
        self.assertIsNone(f["slow_pct"])
        self.assertIsNone(f["thermal_drift_pct"])


class TestLeanManualConfig(unittest.TestCase):
    def test_no_unread_high_volume_sources(self):
        """cpu_idle / cpu_frequency / camera / binder filled 975MB in 4 minutes."""
        from swagperf.capture import MANUAL_CONFIG
        for noisy in ("power/cpu_idle", "power/cpu_frequency", '"camera"', '"binder_driver"', '"freq"'):
            self.assertNotIn(noisy, MANUAL_CONFIG)

    def test_keeps_what_extraction_reads(self):
        from swagperf.capture import MANUAL_CONFIG
        for needed in ("sched/sched_switch", "task/task_newtask", "task/task_rename",
                       '"view"', '"am"', "atrace_apps", "frametimeline", "process_stats"):
            self.assertIn(needed, MANUAL_CONFIG)


class TestDeviceShapedSession(unittest.TestCase):
    """End-to-end on a trace shaped like a real device capture: every process
    on the phone, Android 12+ frame names, FrameTimeline, per-process RSS and
    scheduler data. The generator returns the answers it built in, so these
    check numbers, not just that something came out."""

    @classmethod
    def setUpClass(cls):
        from swagperf.synth_android import gen_device_session
        from swagperf.screens import extract_screens
        cls.bytes, cls.exp = gen_device_session(3)
        cls.path = os.path.join(tempfile.mkdtemp(), "device.pftrace")
        with open(cls.path, "wb") as fh:
            fh.write(cls.bytes)
        cls.m = extract_any(cls.path, app_pkg="com.swag.pay")
        cls.d = extract_screens(cls.path, use_cache=False)

    def test_frames_are_the_apps_own(self):
        """system_server renders slow frames all session; none may count."""
        self.assertEqual(self.m["frames"]["total"], self.exp["frames"])
        self.assertEqual(self.m["frames"]["slow"], self.exp["slow"])

    def test_ram_is_the_apps_not_system_servers(self):
        self.assertEqual(self.m["memory"]["rss"]["peak_mb"], self.exp["app_rss_peak_mb"])
        self.assertLess(self.m["memory"]["rss"]["peak_mb"], self.exp["sys_rss_mb"])

    def test_drift_is_unmeasured_when_screens_change(self):
        self.assertIsNone(self.m["frames"]["thermal_drift_pct"])

    def test_app_jank_is_split_from_buffer_stuffing(self):
        j = {r["route"]: r["jank"] for r in self.d["screen_summary"]}
        self.assertEqual(j["Send"]["app"], self.exp["app_jank"]["Send"])
        self.assertEqual(j["History"]["buffer_stuffing"], self.exp["stuffing"]["History"])
        self.assertEqual(j["History"]["app"], 0)
        self.assertEqual(j["Home"]["app"], 0)

    def test_transitions_listed_once_and_costed_to_first_frame(self):
        """Each is emitted twice (plain and kind-tagged) at the same instant."""
        got = {(n["from"], n["to"]): n for n in self.d["navigations"]}
        self.assertEqual(set(got), set(self.exp["transitions"]))
        for key, ms in self.exp["transitions"].items():
            self.assertEqual(got[key]["count"], 1)
            self.assertAlmostEqual(got[key]["median_ms"], ms, delta=1.0)

    def test_timeline_follows_the_app(self):
        tl = self.d["timeline"]
        self.assertEqual(max(r[1] for r in tl["rss"]), self.exp["app_rss_peak_mb"])
        self.assertAlmostEqual(max(c[1] for c in tl["cpu"]), 60.0, delta=5.0)
        # Same clock as the visits, so the dashboard can overlay them directly.
        first_visit = self.d["screens"][0]["start_ms"]
        self.assertLess(abs(tl["rss"][0][0] - first_visit), 1000)

    def test_per_screen_cpu_follows_the_work(self):
        cpu = {}
        for v in self.d["screens"]:
            cpu.setdefault(v["route"], v["cpu_pct_of_wall"])
        self.assertGreater(cpu["Home"], cpu["Send"])
        self.assertGreater(cpu["Send"], cpu["Store"])

    def test_stack_depth_from_push_and_pop(self):
        self.assertEqual([v["depth"] for v in self.d["screens"]], [1, 2, 1, 1, 1])

    def test_unknown_package_is_unmeasured_not_device_wide(self):
        """An app the trace does not contain must not borrow system_server's numbers."""
        m = extract_any(self.path, app_pkg="com.not.installed")
        self.assertNotEqual(m["memory"].get("rss", {}).get("peak_mb"), self.exp["sys_rss_mb"])
        self.assertIsNone(m["frames"]["slow_pct"])


class TestLiveTrace(unittest.TestCase):
    """Reading a trace that is still being written, a chunk per poll."""

    def test_holds_back_a_partial_packet(self):
        from swagperf.live import packet_starts
        from swagperf.synth import packet, slice_begin
        whole = slice_begin(10, 1, "screen:Home") + slice_begin(20, 1, "screen:Send")
        starts, cut = packet_starts(whole + whole[:5])
        self.assertEqual(cut, len(whole))
        self.assertEqual(len(starts), 2)

    def _replay(self, data, step, lead):
        from swagperf.live import LiveTrace
        from swagperf.screens import marker_rows
        lt = LiveTrace(lambda off: data[off:off + step], marker_rows, lead_bytes=lead)
        rows = []
        for _ in range(len(data) // step + 3):
            rows = lt.poll()
        return lt, rows

    def test_chunked_replay_matches_a_full_parse(self):
        """Replayed in small polls, every marker arrives exactly once."""
        from swagperf.synth_android import gen_device_session
        from swagperf.screens import marker_rows
        data, _ = gen_device_session(4)
        p = os.path.join(tempfile.mkdtemp(), "d.pftrace")
        with open(p, "wb") as fh:
            fh.write(data)
        full = sorted((n, t) for n, t, _ in marker_rows(p))
        # Each poll spawns the trace reader (~1s), so the steps are sized to
        # cross many packet boundaries without running a hundred polls.
        for step in (8 * 1024, 32 * 1024):
            _, rows = self._replay(data, step, lead=4 * 1024)
            self.assertEqual(sorted((n, t) for n, t, _ in rows), full)

    def test_reset_starts_a_new_session(self):
        from swagperf.synth_android import gen_device_session
        data, _ = gen_device_session(5)
        lt, rows = self._replay(data, 64 * 1024, lead=8 * 1024)
        self.assertTrue(rows)
        lt.reset()
        self.assertEqual((lt.offset, lt.rows), (0, {}))

    def test_screen_durations_derived_across_chunks(self):
        """A screen that opened in an earlier chunk never shows its close."""
        from swagperf.screens import summarise_markers
        rows = [("screen:Home#native_view", 0, -1),
                ("screen:Send#compose", 2_000_000_000, -1),
                ("screen:Home#native_view", 3_500_000_000, -1)]
        s = summarise_markers(rows)
        durs = [e["duration_ms"] for e in s["events"]]
        self.assertEqual(durs, [2000.0, 1500.0, None])
        self.assertEqual(s["current_screen"], "Home")
        self.assertEqual(s["current_screen_kind"], "Native view")


class TestZygoteNamedApp(unittest.TestCase):
    """A capture that missed the app's rename leaves it named `zygote64`."""

    @classmethod
    def setUpClass(cls):
        from swagperf.synth_android import gen_device_session
        cls.bytes, cls.exp = gen_device_session(6, process_name="zygote64")
        cls.path = os.path.join(tempfile.mkdtemp(), "zygote.pftrace")
        with open(cls.path, "wb") as fh:
            fh.write(cls.bytes)

    def test_instrumented_app_is_found_by_its_markers(self):
        m = extract_any(self.path, app_pkg="com.swag.pay")
        self.assertEqual(m["memory"]["rss"]["peak_mb"], self.exp["app_rss_peak_mb"])
        self.assertEqual(m["frames"]["total"], self.exp["frames"])

    def test_other_package_does_not_borrow_those_markers(self):
        m = extract_any(self.path, app_pkg="com.not.installed")
        self.assertIsNone(m["memory"].get("rss"))
        self.assertIsNone(m["frames"]["slow_pct"])


class TestLiveServerFallback(unittest.TestCase):
    """If the phone cannot serve partial reads, the feed must still work."""

    def test_misaligned_read_falls_back_to_full_copy(self):
        import shutil
        import swagperf.capture as cap
        import swagperf.server as srv
        from swagperf.synth_android import gen_device_session
        data, _ = gen_device_session(7)
        p = os.path.join(tempfile.mkdtemp(), "live.pftrace")
        with open(p, "wb") as fh:
            fh.write(data)
        saved = (cap.manual_status, cap.manual_remote_size, cap.manual_read_from,
                 cap.manual_snapshot, srv._live, srv._LIVE_TTL_S)
        try:
            cap.manual_status = lambda serial=None: {"device": True, "recording": True}
            cap.manual_remote_size = lambda serial=None: len(data)
            # A tail that ignores the offset: bytes from mid-packet.
            cap.manual_read_from = lambda off, serial=None, max_bytes=0: data[7:4096]
            cap.manual_snapshot = lambda out, serial=None: shutil.copy(p, out)
            srv._live, srv._LIVE_TTL_S = None, 0
            srv._live_reset()
            out = srv._live_markers()
            self.assertEqual(out.get("mode"), "full-copy fallback")
            self.assertTrue(out["counts"].get("screen"))
            srv._live_reset()
            self.assertTrue(srv._live_mode["incremental"])
        finally:
            (cap.manual_status, cap.manual_remote_size, cap.manual_read_from,
             cap.manual_snapshot, srv._live, srv._LIVE_TTL_S) = saved
            srv._live_reset()


class TestStressInterrupted(unittest.TestCase):
    def test_running_tests_are_closed_at_startup(self):
        """A server restart kills its job threads; their tests must not read RUNNING forever."""
        db = os.path.join(tempfile.mkdtemp(), "h.db")
        sid = store.stress_create(app_pkg="com.swag.pay", sessions=5, db=db)
        done = store.stress_create(app_pkg="com.swag.pay", sessions=5, db=db)
        store.stress_finish(done, state="done", db=db)
        self.assertEqual(store.stress_mark_interrupted(db=db), 1)
        self.assertEqual(store.stress_get(sid, db=db)["state"], "interrupted")
        self.assertEqual(store.stress_get(done, db=db)["state"], "done")
