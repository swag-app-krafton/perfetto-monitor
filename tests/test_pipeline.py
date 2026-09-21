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
        m = extract_any(p, app_pkg="com.swagpay")
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
        self.assertTrue(catalogue.is_instrumented("com.swagpay"))

    def test_add_and_remove_round_trip(self):
        catalogue.add("com.test.app", name="Test App", role="competitor")
        self.assertIsNotNone(catalogue.get("com.test.app"))
        catalogue.remove("com.test.app")
        self.assertIsNone(catalogue.get("com.test.app"))

    def test_remove_can_hide_a_builtin_entry(self):
        self.assertIsNotNone(catalogue.get("com.swagpay"))
        catalogue.remove("com.swagpay")
        self.assertIsNone(catalogue.get("com.swagpay"))

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
