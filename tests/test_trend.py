"""The trend view's data (F-026): each metric across app versions, per device.

What must hold: versions in release order, one point per version and device
(the median of its runs), a gap where nothing was measured, never a mix of
apps, start paths, platforms or startup kinds, and each device's own pinned
benchmark.
"""
import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from swagperf import server, store, trend
from swagperf.budgets import GLOBAL_BUDGETS

STEPS = ("step:process_start", "step:bind_application", "step:activity_create")


def metrics(ttff, *, janky=0.4, peak=300.0, steps=(10.0, 20.0, 30.0), derived=True,
            simulator=False, platform="android", path="cold"):
    return {
        "path_kind": path, "derived": derived, "platform": platform, "simulator": simulator,
        "startup": {"time_to_first_camera_frame_ms": ttff, "budget_ms": None, "critical_path": []},
        "frames": {"slow_pct": 1.0, "janky_pct": janky, "thermal_drift_pct": None},
        "memory": {"rss": {"peak_mb": peak, "growth_mb": 40.0}},
        "breaches": [], "ordering_violations": [],
        "steps": [{"step": n, "dur_ms": d, "start_ms": float(i * 100), "budget_ms": None,
                   "over_budget": False, "children": [], "track": "derived"}
                  for i, (n, d) in enumerate(zip(STEPS, steps)) if d is not None],
    }


class _History(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(), "h.db")

    def add(self, m, *, device="V2514", version=None, build=None, app="com.swag.pay"):
        meta = {"app": {"version_name": version, "version_code": build}} if (version or build) else None
        return store.record(m, device=device, app_pkg=app, meta=meta, db=self.db)

    def trend(self, app="com.swag.pay", path="cold", platform="android"):
        return trend.trend(app, path, platform, db=self.db)

    def series(self, t, device, metric, kind=None):
        return next(s for s in t["series"] if s["device"] == device and s["metric"] == metric
                    and s["kind"] == kind)


class TestVersions(_History):
    def test_build_numbers_order_versions_when_every_version_has_one(self):
        self.add(metrics(500), version="2.10.0", build=210)
        self.add(metrics(500), version="2.9.1", build=291)   # a later build, an odd name
        self.add(metrics(500), version="2.3.0", build=23)
        self.assertEqual([v["build"] for v in self.trend()["versions"]], [23, 210, 291])

    def test_names_order_as_numbers_without_build_numbers(self):
        for v in ("2.10.0", "2.9.1", "2.9.0", "10.0"):
            self.add(metrics(500), version=v)
        self.assertEqual([v["name"] for v in self.trend()["versions"]], ["2.9.0", "2.9.1", "2.10.0", "10.0"])

    def test_unversioned_runs_are_counted_not_plotted(self):
        self.add(metrics(500))
        self.add(metrics(500), version="2.3.0", build=230)
        t = self.trend()
        self.assertEqual(t["unversioned"], 1)
        self.assertEqual(len(t["versions"]), 1)
        self.assertEqual(self.series(t, "V2514", "ttff_ms")["points"][0]["n"], 1)

    def test_version_key_matches_the_dashboard(self):
        self.add(metrics(500), version="2.3.1", build=231)
        self.assertEqual(self.trend()["versions"][0]["key"], "2.3.1|231")
        self.assertEqual(self.trend()["versions"][0]["label"], "2.3.1 (build 231)")


class TestPoints(_History):
    def test_a_point_is_the_median_of_that_versions_runs_on_that_device(self):
        for v in (400.0, 500.0, 900.0):
            self.add(metrics(v), version="2.3.0", build=230)
        p = self.series(self.trend(), "V2514", "ttff_ms")["points"][0]
        self.assertEqual((p["value"], p["n"]), (500.0, 3))
        self.assertEqual(len(p["run_ids"]), 3)

    def test_an_unmeasured_value_is_a_gap_never_zero(self):
        self.add(metrics(500, steps=(10.0, 20.0, 30.0)), version="2.3.0", build=230)
        self.add(metrics(0.0, steps=(10.0, None, 30.0)), version="2.4.0", build=240)
        t = self.trend()
        ttff = self.series(t, "V2514", "ttff_ms")["points"]
        self.assertIsNone(ttff[1]["value"])
        bind = self.series(t, "V2514", "step:bind_application")["points"]
        self.assertEqual([p["value"] for p in bind], [20.0, None])

    def test_steps_are_listed_in_the_order_they_happen(self):
        self.add(metrics(500), version="2.3.0", build=230)
        self.assertEqual(self.trend()["steps"], list(STEPS))

    def test_each_device_is_its_own_line(self):
        self.add(metrics(500), device="V2514", version="2.3.0", build=230)
        self.add(metrics(800), device="Pixel 7", version="2.3.0", build=230)
        t = self.trend()
        self.assertEqual({d["name"] for d in t["devices"]}, {"V2514", "Pixel 7"})
        self.assertEqual(self.series(t, "Pixel 7", "ttff_ms")["points"][0]["value"], 800.0)


class TestNeverMixed(_History):
    def test_other_apps_paths_and_platforms_stay_out(self):
        self.add(metrics(500), version="2.3.0", build=230)
        self.add(metrics(999), version="2.3.0", build=230, app="com.rival.app")
        self.add(metrics(999, path="warm"), version="2.3.0", build=230)
        self.add(metrics(999, platform="ios"), version="2.3.0", build=230)
        p = self.series(self.trend(), "V2514", "ttff_ms")["points"][0]
        self.assertEqual((p["value"], p["n"]), (500.0, 1))

    def test_startup_splits_when_a_device_has_both_kinds(self):
        self.add(metrics(500, derived=True), version="2.3.0", build=230)
        self.add(metrics(300, derived=False), version="2.3.0", build=230)
        t = self.trend()
        derived = self.series(t, "V2514", "ttff_ms", "derived")
        inst = self.series(t, "V2514", "ttff_ms", "instrumented")
        self.assertEqual(derived["points"][0]["value"], 500.0)
        self.assertEqual(derived["startup_metric"], "time to initial display")
        self.assertEqual(inst["points"][0]["value"], 300.0)

    def test_an_unknown_app_is_its_own_scope_and_never_an_error(self):
        self.add(metrics(500), version="2.3.0", build=230, app=None)
        self.assertEqual(len(self.trend(app="unknown")["versions"]), 1)
        self.assertEqual(self.trend(app="com.nothing.here")["series"], [])
        self.assertEqual(self.trend(path="")["series"], [])


class TestReferences(_History):
    def test_each_device_gets_its_own_pin_else_none(self):
        a = self.add(metrics(450), device="V2514", version="2.3.0", build=230)
        self.add(metrics(800), device="Pixel 7", version="2.3.0", build=230)
        self.add(metrics(500), device="V2514", version="2.4.0", build=240)
        store.set_benchmark(a, db=self.db)
        b = self.trend()["benchmarks"]
        self.assertEqual(list(b), ["V2514"])
        self.assertEqual(b["V2514"]["run_id"], a)
        self.assertEqual(b["V2514"]["values"]["ttff_ms"], 450.0)
        self.assertEqual(b["V2514"]["version"], "2.3.0 (build 230)")

    def test_a_simulator_device_has_no_benchmark_and_no_targets(self):
        self.add(metrics(500, simulator=True, platform="ios"), device="iPhone 17", version="1.0", build=1,
                 app="com.cambench.compose.ios")
        t = self.trend(app="com.cambench.compose.ios", platform="ios")
        self.assertEqual(t["benchmarks"], {})
        self.assertTrue(all(s["target"] is None for s in t["series"]))
        self.assertTrue(t["devices"][0]["simulator"])

    def test_a_derived_swag_pay_startup_has_no_target_but_frames_and_ram_do(self):
        self.add(metrics(500), version="2.3.0", build=230)
        t = self.trend()
        self.assertIsNone(self.series(t, "V2514", "ttff_ms")["target"])
        self.assertIsNotNone(t["startup_target_reason"])
        self.assertEqual(self.series(t, "V2514", "janky_pct")["target"], GLOBAL_BUDGETS["janky_frame_pct"])
        self.assertEqual(self.series(t, "V2514", "peak_rss_mb")["target"], GLOBAL_BUDGETS["peak_rss_mb"])

    def test_ram_targets_are_never_asserted_on_another_app(self):
        self.add(metrics(500), version="1.0", build=1, app="com.rival.app")
        t = self.trend(app="com.rival.app")
        self.assertIsNone(self.series(t, "V2514", "peak_rss_mb")["target"])
        self.assertEqual(self.series(t, "V2514", "janky_pct")["target"], GLOBAL_BUDGETS["janky_frame_pct"])


class TestEndpoint(_History):
    def test_the_server_serves_it(self):
        self.add(metrics(500), version="2.3.0", build=230)
        orig = store.DB
        store.DB = self.db
        try:
            out = trend.trend("com.swag.pay", "cold", "android")
            self.assertEqual(json.loads(json.dumps(out)), out)   # JSON-safe as served
        finally:
            store.DB = orig
        self.assertTrue(hasattr(server, "H"))


if __name__ == "__main__":
    unittest.main()
