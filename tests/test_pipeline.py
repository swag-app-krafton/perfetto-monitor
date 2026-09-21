"""Tests for the deterministic half of the pipeline.

The LLM analyst is deliberately not tested here: its output is not
deterministic. What must be reliable is measurement and regression detection,
and that is what these cover.
"""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from swagperf.synth import gen_trace
from swagperf.extract import extract
from swagperf import store, analyst


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
