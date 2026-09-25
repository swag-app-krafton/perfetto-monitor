"""One rule for a run's startup North Star target (budgets.startup_target).

B-010: Swag Pay's catalogue target (420 ms) is the camera-frame target. When
its build emits only instant step: markers, extraction falls back to Android's
launch slices, whose startup ends at Android's first frame, before the camera
delivers one. Judging that number by the camera-frame target showed a pass that
was never measured. Until B-010 is fixed, such a run has no startup target, and
the reader is told why.
"""
import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from swagperf import budgets, catalogue, server, store
from swagperf.budgets import STARTUP_TARGET_REASONS, startup_target
from swagperf.extract import extract_any
from swagperf.synth import gen_trace
from swagperf.synth_android import gen_android_trace

SWAG = {"pkg": "com.swag.pay", "role": "own", "instrumented": True, "budgets": {"ttid_ms": 420}}
RIVAL = {"pkg": "com.rival.app", "role": "competitor", "budgets": {"ttid_ms": 900}}


class TestTheRule(unittest.TestCase):
    def test_an_instrumented_android_run_gets_the_camera_frame_target(self):
        self.assertEqual(startup_target(SWAG, "android", derived=False, simulator=False),
                         (budgets.GLOBAL_BUDGETS["time_to_first_camera_frame_ms"], None))
        # A synthetic trace with no app is judged the same way, as before.
        self.assertEqual(startup_target(None, "android", derived=False, simulator=False)[0], 420)

    def test_a_derived_run_of_our_own_app_gets_none_and_says_why(self):
        self.assertEqual(startup_target(SWAG, "android", derived=True, simulator=False),
                         (None, STARTUP_TARGET_REASONS["derived_own"]))

    def test_another_app_gets_only_what_its_catalogue_entry_states(self):
        self.assertEqual(startup_target(RIVAL, "android", derived=True, simulator=False), (900, None))
        self.assertEqual(startup_target({"pkg": "x", "role": "competitor"}, "android",
                                        derived=True, simulator=False),
                         (None, STARTUP_TARGET_REASONS["none"]))

    def test_ios_takes_only_the_catalogue_value(self):
        ios_swag = {"pkg": "com.cambench.compose.ios", "role": "own", "instrumented": True}
        self.assertEqual(startup_target(ios_swag, "ios", derived=False, simulator=False),
                         (None, STARTUP_TARGET_REASONS["none"]))
        self.assertEqual(startup_target({**ios_swag, "budgets": {"ttid_ms": 500}}, "ios",
                                        derived=False, simulator=False), (500, None))

    def test_a_simulator_run_gets_none(self):
        self.assertEqual(startup_target(SWAG, "ios", derived=False, simulator=True),
                         (None, STARTUP_TARGET_REASONS["simulator"]))

    def test_every_reason_reads_as_a_sentence_in_the_new_wording(self):
        for key, text in STARTUP_TARGET_REASONS.items():
            self.assertTrue(text.endswith("."), key)
            self.assertNotIn("budget", text.lower(), key)


class TestSwagPayDerivedStartup(unittest.TestCase):
    """A Swag Pay trace with no timed step: spans, as in run #1."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        b, _ = gen_android_trace(4, pkg="com.swag.pay",
                                 regress={"bindApplication": 4.0, "inflate": 4.0, "first_frame": 4.0})
        cls.path = os.path.join(cls.tmp, "swag.pftrace")
        with open(cls.path, "wb") as fh:
            fh.write(b)
        cls.m = extract_any(cls.path, app_pkg="com.swag.pay")

    def test_it_is_derived_and_slower_than_the_camera_frame_target(self):
        self.assertTrue(self.m["derived"])
        self.assertGreater(self.m["startup"]["time_to_first_camera_frame_ms"], 420)

    def test_it_is_not_checked_against_the_camera_frame_target(self):
        self.assertIsNone(self.m["startup"]["budget_ms"])
        self.assertEqual(self.m["startup"]["target_reason"], STARTUP_TARGET_REASONS["derived_own"])
        self.assertNotIn("time_to_first_camera_frame_ms", [b["metric"] for b in self.m["breaches"]])

    def test_the_dashboard_gets_no_target_and_the_reason(self):
        db = os.path.join(self.tmp, "h.db")
        rid = store.record(self.m, device="V2514", app_pkg="com.swag.pay", db=db)
        # A run recorded before the rule changed still carries the old breach.
        c = store.connect(db)
        old = self.m["breaches"] + [{"metric": "time_to_first_camera_frame_ms", "value": 900.0,
                                     "budget": 420, "over_by_pct": 114.3}]
        c.execute("update runs set breaches_json=? where id=?", (json.dumps(old), rid))
        c.commit(); c.close()
        orig = store.DB
        store.DB = db
        try:
            run = next(r for r in server._payload()["runs"] if r["id"] == rid)
        finally:
            store.DB = orig
        self.assertIsNone(run["ttid_budget_ms"])
        self.assertEqual(run["ttid_target_reason"], STARTUP_TARGET_REASONS["derived_own"])
        self.assertNotIn("time_to_first_camera_frame_ms", [b["metric"] for b in run["breaches"]])


class TestOthersKeepTheirTargets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig_user = catalogue.USER
        catalogue.USER = os.path.join(self.tmp, "apps.local.json")

    def tearDown(self):
        catalogue.USER = self._orig_user

    def test_an_instrumented_swag_pay_trace_keeps_420(self):
        data, _ = gen_trace(seed=2)
        p = os.path.join(self.tmp, "t.pftrace")
        with open(p, "wb") as fh:
            fh.write(data)
        m = extract_any(p, app_pkg="com.swag.pay")
        self.assertFalse(m["derived"])
        self.assertEqual(m["startup"]["budget_ms"], 420)
        self.assertIsNone(m["startup"]["target_reason"])

    def test_a_competitor_with_a_catalogue_target_keeps_it(self):
        catalogue.add("com.rival.app", name="Rival", role="competitor", budgets={"ttid_ms": 50})
        b, _ = gen_android_trace(5, pkg="com.rival.app")
        p = os.path.join(self.tmp, "r.pftrace")
        with open(p, "wb") as fh:
            fh.write(b)
        m = extract_any(p, app_pkg="com.rival.app")
        self.assertTrue(m["derived"])
        self.assertEqual(m["startup"]["budget_ms"], 50)
        self.assertIn("time_to_first_camera_frame_ms", [b["metric"] for b in m["breaches"]])


if __name__ == "__main__":
    unittest.main()
