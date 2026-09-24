"""Tests for the iOS lane: reading Instruments exports, converting them into a
Perfetto trace, and keeping iOS and simulator runs apart from Android history.

Real exports (trimmed with xctrace.trim_export from a Swag Pay recording on
an iPhone 17 simulator, Xcode 27) are in tests/fixtures/ios/; synthetic
recordings with known answers come from swagperf/synth_ios.py. Nothing here
needs Xcode or a simulator.
"""
import json, os, plistlib, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from perfetto.trace_processor import TraceProcessor

from swagperf import (analyst, backends, capture, capture_ios, catalogue, convert_ios,
                      extract as ex, store, xctrace as xt)
from swagperf.synth_ios import Recording, gen_ios_trace

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "ios")
REAL_APP = "com.cambench.compose.ios"   # Swag Pay iOS in apps.json (instrumented)


def _fix(name):
    """A fixture's contents (bytes); parse_table and parse_toc take either."""
    with open(os.path.join(FIX, name), "rb") as f:
        return f.read()


def _write(tmp, name, data):
    p = os.path.join(tmp, name)
    with open(p, "wb") as f:
        f.write(data)
    return p


def _rows(path, q):
    tp = TraceProcessor(trace=path)
    try:
        return [dict(r.__dict__) for r in tp.query(q)]
    finally:
        tp.close()


def _real_trace(tmp):
    """The fixture recording, converted, with a few RAM samples."""
    toc = xt.parse_toc(_fix("toc.xml"))
    tables = {s: xt.parse_table(_fix(f"{s}.xml"))
              for s in ("os-signpost", "dyld-activity-interval", "potential-hangs")}
    data, rep = convert_ios.convert(
        tables, bundle_id=REAL_APP, pid=toc["process"]["pid"],
        source={"platform": "ios", "simulator": 1, "device": "iPhone 17", "os": "27.0"},
        memory=[(2_000_000_000, 70e6), (4_000_000_000, 90e6)],
        end_ns=int(toc["duration_s"] * 1e9))
    return _write(tmp, "real.pftrace", data), rep, toc


class TestXctraceParsing(unittest.TestCase):

    def test_toc(self):
        toc = xt.parse_toc(_fix("toc.xml"))
        self.assertEqual(toc["device"]["platform"], "iOS Simulator")
        self.assertEqual(toc["device"]["name"], "iPhone 17")
        self.assertEqual(toc["process"]["name"], "Swag Pay")
        self.assertIsInstance(toc["process"]["pid"], int)
        self.assertEqual(toc["end_reason"], "Time limit reached")
        self.assertIn("os-signpost", toc["schemas"])
        self.assertIn("potential-hangs", toc["schemas"])

    def test_refs_resolve_to_the_first_occurrence(self):
        """Repeated values are `<tag ref="N"/>` after the first; every row must
        still read its thread's tid and its process's pid."""
        rows = xt.parse_table(_fix("os-signpost.xml"))
        self.assertTrue(rows)
        pids = {xt.num(xt.kid(xt.kid(r["thread"], "process"), "pid")) for r in rows}
        self.assertEqual(len(pids), 1)
        self.assertNotIn(None, pids)
        mine = [r for r in rows if xt.fmt(r["subsystem"]) == convert_ios.APP_SUBSYSTEM]
        self.assertEqual({xt.fmt(r["message"]) for r in mine},
                         {"step:returning_bootstrap", "screen:Home#native_view"})

    def test_empty_cells_are_none(self):
        rows = xt.parse_table(_fix("os-signpost.xml"))
        # Blanked by trim_export, and absent from a real End row's message.
        self.assertTrue(all(r.get("backtrace") is None for r in rows))

    def test_trim_keeps_the_rows_it_keeps_intact(self):
        text = _fix("dyld-activity-interval.xml").decode()
        full = xt.parse_table(text)
        kept = xt.parse_table(xt.trim_export(text, lambda r: xt.fmt(r["level"]) == "3"))
        want = [r for r in full if xt.fmt(r["level"]) == "3"]
        self.assertEqual(len(kept), len(want))
        for a, b in zip(kept, want):
            self.assertEqual((xt.num(a["start"]), xt.fmt(a["type"]), xt.fmt(a["process"])),
                             (xt.num(b["start"]), xt.fmt(b["type"]), xt.fmt(b["process"])))

    def test_record_command(self):
        cmd = xt.record_cmd(device="UDID", app="/x/Swag Pay.app", out="o.trace",
                            time_limit_s=12, options_path="opts.json")
        self.assertEqual(cmd[:3], ["xcrun", "xctrace", "record"])
        self.assertEqual(cmd[-3:], ["--launch", "--", "/x/Swag Pay.app"])
        self.assertIn("12000ms", cmd)
        for name in xt.INSTRUMENTS:
            self.assertIn(name, cmd)
        self.assertEqual(cmd[cmd.index("--recording-options") + 1], "opts.json")


class TestConvertRealRecording(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.path, cls.rep, cls.toc = _real_trace(cls.tmp)

    def test_process_is_the_bundle_id(self):
        names = {r["name"] for r in _rows(self.path, "select name from process where pid > 0")}
        self.assertEqual(names, {REAL_APP})

    def test_provenance_and_recording_end(self):
        src = _rows(self.path, "select ts, name from slice where name like 'swagperf.source:%'")
        self.assertEqual(len(src), 1)
        self.assertEqual(src[0]["ts"], 0)
        self.assertIn("platform=ios", src[0]["name"])
        end = _rows(self.path, f"select ts from slice where name = '{convert_ios.END_MARKER}'")
        self.assertAlmostEqual(end[0]["ts"] / 1e9, self.toc["duration_s"], places=3)

    def test_launch_phases_follow_dyld_and_apples_signposts(self):
        l = self.rep["launch"]
        rows = {r["name"]: r for r in _rows(self.path, """
            select name, ts, dur from slice where name like 'swagperf.launch:%'""")}
        pm = rows["swagperf.launch:pre_main"]
        self.assertEqual(pm["ts"], l["process_start"])
        self.assertEqual(pm["ts"] + pm["dur"], l["pre_main_end"])
        mf = rows["swagperf.launch:main_to_first_frame"]
        self.assertEqual(mf["ts"] + mf["dur"], l["first_frame"])
        self.assertIn("swagperf.launch:first_frame_to_responsive", rows)

    def test_pre_main_children_nest_inside_it(self):
        kids = _rows(self.path, """
            select c.name from slice c join slice p on c.parent_id = p.id
            where p.name = 'swagperf.launch:pre_main'""")
        self.assertTrue(any(k["name"].startswith("static init: ") for k in kids))

    def test_markers(self):
        rows = {r["name"]: r for r in _rows(self.path, """
            select name, dur from slice where name like 'screen:%' or name like 'step:%'""")}
        self.assertEqual(rows["step:returning_bootstrap"]["dur"], 0)
        # Still on screen when the recording stopped: unfinished, as on Android.
        self.assertEqual(rows["screen:Home#native_view"]["dur"], -1)

    def test_ram_is_a_process_counter(self):
        rows = _rows(self.path, """
            select t.name, t.upid from process_counter_track t
            join process p using (upid) where p.name = '%s'""" % REAL_APP)
        self.assertEqual([r["name"] for r in rows], ["mem.rss"])


class TestExtractIos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        data, cls.want = gen_ios_trace()
        cls.path = _write(cls.tmp, "synth.pftrace", data)
        cls.m = ex.extract_any(cls.path, app_pkg="com.example.ios")

    def test_platform_is_read_from_the_trace(self):
        self.assertEqual(ex.trace_source_of(self.path)["platform"], "ios")
        self.assertEqual(self.m["platform"], "ios")
        self.assertTrue(self.m["simulator"])

    def test_startup_is_process_start_to_first_frame(self):
        self.assertTrue(self.m["derived"])
        self.assertEqual(self.m["path_kind"], "cold")
        self.assertAlmostEqual(self.m["startup"]["time_to_first_camera_frame_ms"],
                               self.want["ttid_ms"], delta=0.01)
        names = [s["step"] for s in self.m["steps"]]
        self.assertEqual(names, ["step:pre_main", "step:main_to_first_frame",
                                 "step:first_frame_to_responsive"])
        pm = self.m["steps"][0]
        self.assertEqual({c["name"] for c in pm["children"]},
                         {"static init: libSystem.B.dylib", "static init: React"})

    def test_simulator_frames_are_unmeasured_not_perfect(self):
        f = self.m["frames"]
        self.assertEqual(f["total"], 0)
        self.assertIsNone(f["slow_pct"])
        self.assertIsNone(f["avg_ms"])
        self.assertIn("Simulator", f["note"])
        self.assertNotIn("no frame slices were recorded",
                         " ".join(ex.capture_problems(self.m, requested_pkg="com.example.ios")))

    def test_simulator_runs_carry_no_budgets(self):
        self.assertFalse(self.m["budgets_asserted"])
        self.assertEqual(self.m["breaches"], [])
        self.assertIsNone(self.m["startup"]["budget_ms"])
        self.assertIn("Simulator", self.m["note"])

    def test_ram(self):
        rss = self.m["memory"]["rss"]
        self.assertAlmostEqual(rss["peak_mb"], self.want["peak_mb"], delta=0.1)
        self.assertAlmostEqual(rss["min_mb"], self.want["min_mb"], delta=0.1)

    def test_a_device_run_keeps_its_budgets(self):
        data, _ = gen_ios_trace(simulator=False)
        m = ex.extract_any(_write(self.tmp, "device.pftrace", data), app_pkg="com.example.ios")
        self.assertFalse(m["simulator"])
        self.assertTrue(m["budgets_asserted"])

    def test_trace_metadata_names_the_device(self):
        md = ex.trace_metadata(self.path, "com.example.ios")
        self.assertEqual(md["device"]["platform"], "ios")
        self.assertEqual(md["device"]["model"], "iPhone 17")

    def test_screens(self):
        from swagperf.screens import extract_screens
        d = extract_screens(self.path, use_cache=False)
        self.assertTrue(d["instrumented"])
        visits = {v["route"]: v for v in d["screens"]}
        self.assertAlmostEqual(visits["Home"]["duration_ms"], 2700, delta=1)
        # Pay was still open: clamped to the recording's end, not the last marker.
        self.assertTrue(visits["Pay"]["open_ended"])
        self.assertAlmostEqual(visits["Pay"]["duration_ms"], 2500, delta=1)
        # No scheduler data in an iOS trace: CPU is unmeasured, never 0 (B-005).
        self.assertTrue(all(v["cpu_ms"] is None for v in d["screens"]))
        self.assertTrue(all(s["total_cpu_ms"] is None for s in d["screen_summary"]))
        self.assertFalse(d["timeline"]["cpu_measured"])
        self.assertIsNotNone(visits["Home"]["rss"])


class TestSignpostPairing(unittest.TestCase):

    def _convert(self, r):
        tmp = tempfile.mkdtemp()
        data, rep = r.convert(end_ms=5000)
        return _write(tmp, "p.pftrace", data), rep

    def test_nested_spans_become_nested_slices(self):
        r = Recording()
        r.span("step:bootstrap", 100, 300)
        r.span("session.read", 150, 50)
        p, rep = self._convert(r)
        rows = {x["name"]: x for x in _rows(p, "select name, depth, dur from slice where name not like 'swagperf.%'")}
        self.assertEqual(rows["step:bootstrap"]["depth"], 0)
        self.assertEqual(rows["session.read"]["depth"], 1)
        self.assertEqual(rows["session.read"]["dur"], 50_000_000)
        self.assertEqual(rep["spans"], 2)

    def test_open_and_unmatched(self):
        r = Recording()
        r.open_span("step:hermes_boot", 200)
        r.unmatched_end(300)
        p, rep = self._convert(r)
        self.assertEqual(rep["open_at_end"], 1)
        self.assertEqual(rep["unmatched_ends"], 1)
        rows = _rows(p, "select dur from slice where name = 'step:hermes_boot'")
        self.assertEqual(rows[0]["dur"], -1)

    def test_overlapping_async_slices_do_not_share_a_track(self):
        """Transitions and async actions share the nav slot; overlapping ones
        on one track would mis-nest, so the second gets its own."""
        r = Recording()
        r.async_slice("nav", "nav:Home->Pay", 100, 400)
        r.async_slice("nav", "action:fetch_balance", 200, 600)
        p, rep = self._convert(r)
        self.assertEqual(rep["overflow_tracks"], 1)
        rows = _rows(p, "select name, depth, dur from slice where name in ('nav:Home->Pay', 'action:fetch_balance')")
        self.assertEqual({x["depth"] for x in rows}, {0})
        self.assertEqual(sorted(x["dur"] for x in rows), [300_000_000, 400_000_000])

    def test_sub_screen_is_a_sibling_of_its_screen(self):
        r = Recording()
        r.async_slice("screen", "screen:Onboarding#rn", 100, 900)
        r.async_slice("sub", "screen:Onboarding.otp#rn", 200, 500)
        p, _ = self._convert(r)
        rows = _rows(p, "select name, depth from slice where name like 'screen:%'")
        self.assertEqual({x["depth"] for x in rows}, {0})

    def test_counters_and_hangs(self):
        r = Recording()
        r.counter("mem.hermes_heap", 12_582_912, 300)
        r.hang(1000, 300)
        r.hang(2000, 150)
        p, rep = self._convert(r)
        self.assertEqual(rep["counters"], 1)
        self.assertEqual(rep["hangs"], 2)
        heap = _rows(p, """select c.value from counter c join process_counter_track t
                           on c.track_id = t.id where t.name = 'mem.hermes_heap'""")
        self.assertEqual(heap[0]["value"], 12_582_912)
        hangs = sorted(x["name"] for x in _rows(p, "select name from slice where name like 'swagperf.hang:%'"))
        self.assertEqual(hangs, ["swagperf.hang:Hang", "swagperf.hang:Microhang"])


class TestCriticalPathGuard(unittest.TestCase):

    def test_a_partial_critical_path_is_not_a_fast_one(self):
        """Timed Swag Pay steps without the camera ones (the simulator has no
        camera): the latest end among the rest is not time to first camera frame."""
        r = Recording()
        r.launch()
        r.span("step:bootstrap", 1250, 40)
        r.span("step:session_read", 1290, 20)
        r.span("step:compose_shell", 1310, 90)
        data, _ = r.convert(bundle_id=REAL_APP)
        p = _write(tempfile.mkdtemp(), "g.pftrace", data)
        m = ex.extract(p, path_kind="returning_user", app_pkg=REAL_APP)
        self.assertIsNone(m["startup"]["time_to_first_camera_frame_ms"])
        self.assertIn("camera_open", m["note"])
        # No deferred step ran before the recorded path ended: no violation.
        self.assertEqual(m["ordering_violations"], [])
        # extract_any falls back to the launch phases, and says why.
        a = ex.extract_any(p, app_pkg=REAL_APP)
        self.assertTrue(a["derived"])
        self.assertIn("critical path incomplete", a["note"])
        self.assertGreater(a["startup"]["time_to_first_camera_frame_ms"], 0)


class TestStorePlatforms(unittest.TestCase):

    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(), "h.db")

    def _record(self, platform, simulator, dur, app="com.swag.pay", device="dev"):
        m = {"path_kind": "cold", "platform": platform, "simulator": simulator,
             "app_pkg": app, "derived": True,
             "startup": {"time_to_first_camera_frame_ms": dur},
             "frames": {"slow_pct": None, "janky_pct": None, "thermal_drift_pct": None},
             "memory": {}, "breaches": [], "ordering_violations": [],
             "steps": [{"step": "step:x", "dur_ms": dur, "start_ms": 0, "budget_ms": None,
                        "over_budget": False, "children": []}]}
        return store.record(m, device=device, db=self.db)

    def test_migration_upgrades_an_old_history(self):
        c = sqlite3.connect(self.db)
        c.executescript("""create table runs (id integer primary key autoincrement, ts text not null,
            label text, git_sha text, app_version text, device text, path_kind text,
            trace_path text, ttff_ms real, slow_pct real, janky_pct real, thermal_drift_pct real,
            peak_rss_mb real, rss_growth_mb real, breaches_json text, violations_json text,
            frames_json text, memory_json text);
            insert into runs (ts, path_kind) values ('2026-01-01', 'cold');""")
        c.commit(); c.close()
        c = store.connect(self.db)
        row = c.execute("select platform, simulator from runs").fetchone()
        c.close()
        self.assertEqual((row["platform"], row["simulator"]), ("android", 0))

    def test_android_scope_keys_are_unchanged(self):
        self.assertEqual(store._scope("cold", "V2514", "com.swag.pay"), "com.swag.pay|cold|V2514")
        self.assertEqual(store._scope("cold", "iPhone 17", "com.swag.pay", "ios"),
                         "ios:com.swag.pay|cold|iPhone 17")

    def test_baselines_never_mix_platforms_or_simulators(self):
        for _ in range(6):
            self._record("android", False, 100.0)
            self._record("ios", True, 800.0)
            self._record("ios", False, 300.0)
        b = store.baseline("step:x", app_pkg="com.swag.pay", platform="ios", simulator=True, db=self.db)
        self.assertEqual(b["median_ms"], 800.0)
        self.assertEqual(b["stdev_ms"], 0.0)
        b = store.baseline("step:x", app_pkg="com.swag.pay", platform="android", simulator=False, db=self.db)
        self.assertEqual(b["median_ms"], 100.0)
        # A slower iOS simulator run is not a regression against Android history.
        rid = self._record("ios", True, 810.0)
        self.assertEqual(store.regressions(rid, db=self.db), [])

    def test_a_simulator_run_cannot_be_a_benchmark(self):
        rid = self._record("ios", True, 800.0)
        with self.assertRaises(ValueError):
            store.set_benchmark(rid, db=self.db)
        dev = self._record("ios", False, 300.0, device="iPhone 17")
        self.assertTrue(store.set_benchmark(dev, db=self.db)["scope"].startswith("ios:"))

    def test_compare_across_platforms_is_not_comparable(self):
        a = self._record("android", False, 100.0)
        b = self._record("ios", True, 800.0)
        d = store.compare(a, b, db=self.db)
        self.assertFalse(d["comparable"])
        self.assertFalse(d["same_platform"])


class TestCatalogueAndBackends(unittest.TestCase):

    def test_the_same_id_on_both_platforms(self):
        tmp = tempfile.mkdtemp()
        orig = catalogue.USER
        catalogue.USER = os.path.join(tmp, "apps.local.json")
        try:
            catalogue.add("com.swag.pay", name="Swag Pay iOS", role="own", instrumented=True,
                          platform="ios")
            self.assertEqual(catalogue.get("com.swag.pay", "ios")["name"], "Swag Pay iOS")
            self.assertEqual(catalogue.get("com.swag.pay")["platform"], "android")
            self.assertNotEqual(catalogue.get("com.swag.pay")["name"], "Swag Pay iOS")
            catalogue.remove("com.swag.pay", "ios")
            self.assertIsNone(catalogue.get("com.swag.pay", "ios"))
            self.assertIsNotNone(catalogue.get("com.swag.pay"))
        finally:
            catalogue.USER = orig

    def test_bundle_ids(self):
        self.assertEqual(backends.validate_id("ios", "com.acme.my-app"), "com.acme.my-app")
        with self.assertRaises(ValueError):
            backends.validate_id("android", "com.acme.my-app")
        for bad in ("", "noDots", "com.acme;rm -rf", "../x.y"):
            with self.assertRaises(ValueError):
                backends.validate_id("ios", bad)

    def test_both_backends_expose_the_same_surface(self):
        for mod in (capture, capture_ios):
            missing = [f for f in backends.SURFACE if not callable(getattr(mod, f, None))]
            self.assertEqual(missing, [], mod.__name__)
        self.assertIs(backends.get("ios"), capture_ios)
        self.assertIs(backends.get("android"), capture)

    def test_simulator_verdicts_are_capped(self):
        res = analyst.cap_for_simulator({"verdict": "fail", "headline": "Startup over budget"},
                                        {"simulator": True})
        self.assertEqual(res["verdict"], "warn")
        self.assertTrue(res["headline"].startswith(analyst.SIMULATOR_PREFIX))
        same = analyst.cap_for_simulator({"verdict": "fail", "headline": "x"}, {"simulator": False})
        self.assertEqual(same["verdict"], "fail")


class TestTriageIos(unittest.TestCase):
    """The PM review never opens an issue from a simulator run, and an iOS
    signal never lands on the Android issue for the same app id."""

    def _run(self, i, *, platform, simulator):
        return {"id": i, "ts": "2026-09-24T10:00:00+00:00", "app_pkg": "com.swag.pay",
                "app_name": "Swag Pay", "app_role": "own", "path_kind": "cold",
                "device": "iPhone 17", "label": f"r{i}", "trace_path": None,
                "platform": platform, "simulator": simulator,
                "breaches": [{"metric": "peak_rss_mb", "value": 480, "budget": 320, "over_by_pct": 50.0}],
                "violations": [], "steps": [], "analysis": {"verdict": "fail", "headline": ""}}

    def test_simulator_runs_are_skipped_and_ios_keys_are_prefixed(self):
        from swagperf import triage
        runs = [self._run(1, platform="ios", simulator=True),
                self._run(2, platform="ios", simulator=False),
                self._run(3, platform="android", simulator=False)]
        t = triage.review({"runs": runs}, after=0, regressions=lambda rid: [], issues=[])
        self.assertEqual([x["id"] for x in t["skipped"]], [1])
        self.assertIn("simulator", t["skipped"][0]["reason"])
        keys = sorted(x["key"] for x in t["signals"])
        self.assertEqual(keys, ["budget:peak_rss_mb:com.swag.pay:cold",
                                "budget:peak_rss_mb:ios:com.swag.pay:cold"])
        ios = next(x for x in t["signals"] if x["key"].endswith("ios:com.swag.pay:cold"))
        self.assertEqual((ios["count"], ios["of_runs"]), (1, 1))


class TestTriageQuiet(unittest.TestCase):
    """An open issue whose signal did not fire in a run of its scope is
    reported quiet, whatever its key's subject holds (B-008)."""

    def test_step_keys_and_ios_keys_are_checked(self):
        from swagperf import triage
        self.assertEqual(triage._key_scope("regression:step:activity_create:com.swag.pay:cold"),
                         ("com.swag.pay", "cold"))
        self.assertEqual(triage._key_scope("ordering:step:hermes_boot:ios:com.swag.pay:cold"),
                         ("ios:com.swag.pay", "cold"))
        self.assertEqual(triage._key_scope("budget:peak_rss_mb:com.swag.pay:cold"),
                         ("com.swag.pay", "cold"))
        run = {"id": 1, "ts": "2026-09-24T10:00:00+00:00", "app_pkg": "com.swag.pay",
               "app_name": "Swag Pay", "app_role": "own", "path_kind": "cold", "device": "V2514",
               "label": "r1", "trace_path": None, "breaches": [], "violations": [], "steps": [],
               "analysis": {"verdict": "pass", "headline": ""}}
        issues = [{"id": "P-004", "signal": "regression:step:activity_create:com.swag.pay:cold",
                   "status": "needs-review", "file": "docs/issues/P-004.md"},
                  {"id": "P-009", "signal": "regression:step:pre_main:ios:com.swag.pay:cold",
                   "status": "needs-review", "file": "docs/issues/P-009.md"}]
        t = triage.review({"runs": [run]}, after=0, regressions=lambda rid: [], issues=issues)
        self.assertEqual([q["id"] for q in t["quiet"]], ["P-004"])


class TestCaptureIosParsers(unittest.TestCase):

    def test_simctl_devices(self):
        text = json.dumps({"devices": {
            "com.apple.CoreSimulator.SimRuntime.iOS-27-0": [
                {"udid": "A", "name": "iPhone 17", "state": "Booted", "isAvailable": True,
                 "deviceTypeIdentifier": "com.apple.CoreSimulator.SimDeviceType.iPhone-17"},
                {"udid": "B", "name": "Gone", "state": "Shutdown", "isAvailable": False}],
            "com.apple.CoreSimulator.SimRuntime.watchOS-12-0": [
                {"udid": "C", "name": "Watch", "state": "Shutdown", "isAvailable": True}]}})
        devs = capture_ios.parse_simctl_devices(text)
        self.assertEqual([(d["udid"], d["os_version"], d["state"]) for d in devs],
                         [("A", "27.0", "Booted")])

    def test_listapps(self):
        apps = capture_ios.parse_listapps(json.dumps({
            "com.cambench.compose.ios": {"ApplicationType": "User"},
            "com.apple.Maps": {"ApplicationType": "System"}}))
        self.assertEqual(list(apps), ["com.cambench.compose.ios"])

    def test_app_bundle_release_and_debug(self):
        app = os.path.join(tempfile.mkdtemp(), "Swag Pay.app")
        os.makedirs(app)
        with open(os.path.join(app, "Info.plist"), "wb") as f:
            plistlib.dump({"CFBundleShortVersionString": "1.0.0", "CFBundleVersion": "7",
                           "CFBundleExecutable": "Swag Pay"}, f)
        self.assertEqual(capture_ios.parse_app_bundle(app)["build_type"], "debug")
        with open(os.path.join(app, "main.jsbundle"), "wb") as f:
            f.write(capture_ios.HBC_MAGIC + (98).to_bytes(4, "little") + bytes(range(20)))
        info = capture_ios.parse_app_bundle(app)
        self.assertEqual((info["build_type"], info["js_bundle"], info["hbc_version"]),
                         ("release", "hermes", 98))
        self.assertEqual(info["hbc_source_hash"], bytes(range(20)).hex())
        self.assertEqual((info["version_name"], info["version_code"]), ("1.0.0", "7"))

    def test_mac_state(self):
        self.assertEqual(capture_ios.parse_pmset_batt(
            "Now drawing from 'Battery Power'\n -InternalBattery-0 (id=1)\t99%; discharging; 16:38"),
            {"host_power": "battery", "host_battery_pct": 99, "host_battery_state": "discharging"})
        self.assertFalse(capture_ios.parse_pmset_therm(
            "Note: No thermal warning level has been recorded")["host_thermal_warning"])
        self.assertEqual(capture_ios.parse_loadavg("{ 1.13 1.80 2.19 }"), {"host_load_1m": 1.13})

    def test_ram_samples_go_on_the_recordings_clock(self):
        start = capture_ios._epoch_ns("2026-09-24T12:49:58.019+05:30")
        got = capture_ios.align_samples([(start - 5, 1), (start + 1_500_000, 2)],
                                        wall_start_ns=start, trace_start_ns=0)
        self.assertEqual(got, [(1_500_000, 2)])

    def test_verify(self):
        tmp = tempfile.mkdtemp()
        out = os.path.join(tmp, "r.pftrace")

        def report(**kw):
            rep = {"toc": {"process": {"pid": 7}}, "convert": {"app_signposts": 2,
                   "launch": {"first_frame": 1}}, "record_issues": []}
            for k, v in kw.items():
                rep[k] = {**rep.get(k, {}), **v} if isinstance(v, dict) else v
            with open(capture_ios.report_path(out), "w") as f:
                json.dump(rep, f)
        report()
        self.assertIsNone(capture_ios.verify(out, instrumented=True))
        report(toc={"process": {}})
        self.assertIn("never launched", capture_ios.verify(out))
        report(convert={"app_signposts": 0})
        self.assertIn("instrumented", capture_ios.verify(out, instrumented=True))
        report(record_issues=["[Error] Hitches is not supported on this platform."])
        self.assertIn("Hitches", capture_ios.verify(out))


if __name__ == "__main__":
    unittest.main()
