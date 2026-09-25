"""Hangs, JS errors, ANRs and crashes (stability.py), on both platforms.

iOS recordings come from synth_ios (the Hangs instrument's rows, the app's
error markers and os_log lines); Android traces come from synth_stability,
which writes the logcat lines, ANR counters and trace config the byte-level
Android generator does not.
"""
import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from swagperf import analyst, extract as ex, sourcemaps, stability, store, triage
from swagperf.synth_ios import Recording
from swagperf.synth_stability import Session


def _write(data, name="t.pftrace"):
    p = os.path.join(tempfile.mkdtemp(), name)
    with open(p, "wb") as f:
        f.write(data)
    return p


def _ios(build, **convert):
    r = Recording()
    r.launch()                                   # first frame at 1200 ms
    r.async_slice("screen", "screen:Home#compose", 1300, 5000)
    r.async_slice("screen", "screen:Pay#compose", 5000)
    build(r)
    data, rep = r.convert(end_ms=70_000, **convert)
    return ex.extract_any(_write(data), app_pkg="com.example.ios"), rep


class TestHangs(unittest.TestCase):

    def test_ios_hangs_are_classified_and_attributed(self):
        def build(r):
            r.hang(800, 400)       # before the first frame: startup
            r.hang(2000, 300)      # Home, a hang
            r.hang(3000, 150)      # Home, a microhang
            r.hang(6000, 1200)     # Pay, a long hang
        m, _ = _ios(build)
        h = m["stability"]["hangs"]
        self.assertEqual((h["count"], h["microhangs"]), (2, 1))
        self.assertEqual(h["startup"]["count"], 1)
        self.assertEqual(h["longest_ms"], 1200.0)
        self.assertEqual(h["total_ms"], 1500.0)
        self.assertEqual(set(h["per_screen"]), {"Home", "Pay"})
        self.assertEqual(h["per_screen"]["Home"]["count"], 2)
        # 70 s recording: long enough for a rate, in seconds of hang per hour.
        self.assertAlmostEqual(h["rate_s_per_hr"], 1.5 / (h["session_s"] / 3600), delta=0.1)
        self.assertEqual(h["source"], "the Hangs instrument")

    def test_short_sessions_have_no_rate(self):
        r = Recording()
        r.launch()
        r.hang(2000, 300)
        data, _ = r.convert(end_ms=10_000)
        h = ex.extract_any(_write(data), app_pkg="com.example.ios")["stability"]["hangs"]
        self.assertEqual(h["count"], 1)
        self.assertIsNone(h["rate_s_per_hr"])


class TestJsErrors(unittest.TestCase):

    def test_markers_join_their_records_and_screens(self):
        long_stack = "Error: x\n" + "\n".join(f"    at f{i} (address at main.jsbundle:1:{i})" for i in range(200))
        ids = {}

        def build(r):
            ids["a"] = r.js_error(2000, name="TypeError", message="redacted", chunk=300)
            ids["b"] = r.js_error(6000, name="RangeError", source="promise", fatal=True,
                                  stack=long_stack, chunk=300)
            ids["c"] = r.js_error(6500, name="Error", source="boundary", chunk=40, drop_chunk=1)
        m, rep = _ios(build)
        e = m["stability"]["errors"]
        self.assertEqual((e["js"], e["js_fatal"]), (3, 1))
        self.assertEqual(e["by_source"], {"global": 1, "promise": 1, "boundary": 1})
        self.assertEqual(e["per_screen"], {"Home": 1, "Pay": 2})
        ev = {x["id"]: x for x in e["events"]}
        self.assertEqual(ev[ids["a"]]["message"], "redacted")
        # A record cut into many log lines comes back whole.
        self.assertEqual(ev[ids["b"]]["stack"], long_stack)
        # A record missing a line is dropped, never parsed half-read.
        self.assertFalse(ev[ids["c"]]["has_record"])
        self.assertEqual(rep["error_records_incomplete"], 1)

    def test_assembly_needs_every_chunk(self):
        recs, bad = stability.assemble_records([
            (1, "swagerr|a|2/2|world"), (0, "swagerr|a|1/2|hello "),
            (2, "swagerr|b|1/2|half"), (3, "not a record")])
        self.assertEqual(recs, {"a": (1, "hello world")})
        self.assertEqual(bad, 1)


class TestCrash(unittest.TestCase):

    def test_ios_crash_comes_from_the_provenance(self):
        m, _ = _ios(lambda r: r.js_error(3000, fatal=True), crashed="SIGABRT")
        c = m["stability"]["crash"]
        self.assertTrue(c["crashed"])
        self.assertEqual(c["reason"], "SIGABRT")
        self.assertEqual((c["count"], c["events"][0]["kind"], c["events"][0]["signature"]), (1, "ios", "SIGABRT"))
        m, _ = _ios(lambda r: None)
        self.assertFalse(m["stability"]["crash"]["crashed"])
        self.assertEqual(m["stability"]["crash"]["count"], 0)

    def test_how_xctrace_saw_the_process_end(self):
        from swagperf.capture_ios import crash_of
        ok = {"end_reason": "Time limit reached", "process": {"termination_reason": "exit(0)", "exit_status": 0}}
        self.assertEqual(crash_of(ok), (False, "exit(0)"))
        died = {"end_reason": "Target exited", "process": {"termination_reason": "SIGABRT", "exit_status": 6}}
        self.assertTrue(crash_of(died)[0])


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


class TestAndroidStability(unittest.TestCase):

    def test_main_thread_stalls_logcat_records_and_crash(self):
        st = _stability(_android_trace())
        h = st["hangs"]
        self.assertEqual((h["count"], h["microhangs"], h["startup"]["count"]), (1, 1, 1))
        self.assertEqual(h["source"], "the app's main-thread slices")
        e = st["errors"]
        self.assertEqual((e["js"], e["js_fatal"]), (1, 1))
        self.assertIn("index.android.bundle", e["events"][0]["stack"])
        self.assertTrue(st["crash"]["crashed"])


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


class TestStabilityDownstream(unittest.TestCase):

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

    def test_signals_count_every_crash_and_anr_past_the_event_cap(self):
        """A crash loop longer than the event list must not hide another
        crash kind, nor undercount the loop (review focus 5)."""
        def build(s):
            for i in range(stability.MAX_EVENTS + 5):
                s.java_crash(1000 + i * 20)
                s.anr(1005 + i * 20, f"a{i}", ANR_SUBJECT)
            s.java_crash(9000, exc="java.lang.OutOfMemoryError", message="Failed to allocate")
        st = _session(build)
        self.assertEqual(len(st["crash"]["events"]), stability.MAX_EVENTS)
        run = {"id": 1, "app_pkg": "com.swag.pay", "path_kind": "cold", "platform": "android",
               "stability": st, "breaches": [], "violations": []}
        sig = {s["key"]: s for s in triage.signals_of(run, [])}
        self.assertEqual(sig["crash:java.lang.IllegalStateException:com.swag.pay:cold"]["value"], stability.MAX_EVENTS + 5)
        self.assertEqual(sig["crash:java.lang.OutOfMemoryError:com.swag.pay:cold"]["value"], 1)
        self.assertEqual(sig["crash:java.lang.OutOfMemoryError:com.swag.pay:cold"]["detail"],
                         "java.lang.OutOfMemoryError: Failed to allocate")
        self.assertEqual(sig["anr:INPUT_DISPATCHING_TIMEOUT:com.swag.pay:cold"]["value"], stability.MAX_EVENTS + 5)
        crash = next(f for f in analyst.stability_findings({"stability": st}) if f["kind"] == "crash")
        self.assertIn("java.lang.OutOfMemoryError", crash["evidence"])

    def test_compare_diffs_anrs_and_crashes(self):
        self.assertEqual(store.METRIC_DIRECTION["anr_count"], "lower")
        self.assertEqual(store.METRIC_DIRECTION["crash_count"], "lower")

    def test_unresolved_errors_fall_back_to_their_class(self):
        st = {"errors": {"events": [{"name": "TypeError", "stack": "TypeError: x\n    at a (address at main.jsbundle:1:9)"}]}}
        out = sourcemaps.resolve(st, None)["errors"]["events"][0]
        self.assertFalse(out["symbolicated"])
        self.assertEqual(out["fingerprint"], "TypeError")

    def test_real_hermes_stacks_resolve_only_against_their_own_map(self):
        """A real Swag Pay iOS stack (fixtures from the resolver's own tests):
        its own map resolves it to source and a stable fingerprint; the
        Android build's map is refused rather than trusted."""
        fix = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "sourcemaps", "swagpay")
        with open(os.path.join(fix, "ios.stacks.json")) as f:
            stacks = {s["id"]: s["text"] for s in json.load(f)}
        st = {"errors": {"events": [{"name": "TypeError", "stack": stacks["format_rupees"]},
                                    {"name": "Error", "stack": stacks["uncaught"]}]}}
        good = sourcemaps.resolve(st, os.path.join(fix, "ios.map"))["errors"]
        app, lib = good["events"]
        self.assertTrue(app["symbolicated"])
        self.assertIn("src/money.ts", [fr.get("path") for fr in app["frames"] if fr["in_app"]])
        self.assertNotIn(app["fingerprint"], ("TypeError", None))
        # Thrown inside React Native: no app frame, so the first library frame.
        self.assertTrue(lib["fingerprint"].startswith("lib-"))
        self.assertEqual(good["source_map"], "ios.map")
        wrong = sourcemaps.resolve(st, os.path.join(fix, "android.map"))["errors"]["events"][0]
        self.assertFalse(wrong["symbolicated"])
        self.assertEqual(wrong["fingerprint"], "TypeError")

    def test_map_registry_keys_by_bundle_hash(self):
        root = tempfile.mkdtemp()
        bundle = os.path.join(root, "main.jsbundle")
        with open(bundle, "wb") as f:
            f.write(bytes.fromhex("c61fbc03c103191f") + (98).to_bytes(4, "little") + bytes(range(20)))
        src = os.path.join(root, "x.map")
        with open(src, "w") as f:
            f.write("{}")
        dest = sourcemaps.add("ios", "com.example.ios", src, bundle=bundle, root=root)
        self.assertTrue(dest.endswith(f"hbc-{bytes(range(20)).hex()}.map"))
        self.assertEqual(sourcemaps.find("ios", "com.example.ios", source_hash=bytes(range(20)).hex(), root=root), dest)
        self.assertIsNone(sourcemaps.find("android", "com.example.ios", source_hash=bytes(range(20)).hex(), root=root))
        with self.assertRaises(ValueError):
            sourcemaps.add("ios", "com.example.ios", src, root=root)


class TestDemoSession(unittest.TestCase):

    def test_the_demo_session_carries_every_kind(self):
        from swagperf.synth_android import gen_device_session
        data, _ = gen_device_session(3, pkg="com.example.app", stability=True)
        st = _stability(data, "com.example.app")
        self.assertEqual((st["errors"]["js"], st["anrs"]["count"], st["crash"]["count"]), (2, 1, 2))
        self.assertEqual({e["kind"] for e in st["crash"]["events"]}, {"java", "native"})
        anr = st["anrs"]["events"][0]
        self.assertEqual((anr["screen"], anr["main_thread"]["name"]), ("Store", "binder transaction"))


class TestReleaseArchive(unittest.TestCase):
    """Maps from release builds archived by Swag Pay's release_build.py: a
    manifest, and each platform's bundle and composed map."""
    SYN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "sourcemaps", "synthetic")

    def setUp(self):
        import shutil
        self.root = tempfile.mkdtemp()
        self.folder = tempfile.mkdtemp()
        self.bundle = os.path.join(self.folder, "android-index.android.bundle")
        self.map = os.path.join(self.folder, "android-index.android.bundle.map")
        shutil.copyfile(os.path.join(self.SYN, "v1", "index.android.bundle"), self.bundle)
        shutil.copyfile(os.path.join(self.SYN, "v1", "index.android.bundle.map"), self.map)
        from swagperf import symbolicate
        self.hash = symbolicate.hbc_info(self.bundle)["source_hash"]
        self.write_manifest()

    def write_manifest(self, tag="v1.2.0-42", code=42, dry_run=False, **build):
        entry = lambda p: {"file": os.path.basename(p), "sha256": sourcemaps._sha256(p),
                           "bytes": os.path.getsize(p)}
        b = {"platform": "android", "appId": "com.swag.pay", "versionName": "1.2.0",
             "versionCode": code, "hbc": {"version": 98, "sourceHash": self.hash},
             "bundle": entry(self.bundle), "map": entry(self.map), "packagerMap": None}
        b.update(build)
        with open(os.path.join(self.folder, "manifest.json"), "w") as f:
            json.dump({"schema": 1, "tag": tag, "versionName": "1.2.0", "versionCode": code,
                       "dryRun": dry_run, "commit": "a" * 40, "builtAt": "2026-09-25T12:00:00Z",
                       "builds": [b]}, f)

    def test_registers_by_hash_and_build_with_a_sidecar(self):
        [(platform, pkg, paths)] = sourcemaps.import_release(self.folder, root=self.root)
        self.assertEqual((platform, pkg), ("android", "com.swag.pay"))
        self.assertEqual([os.path.basename(p) for p in paths], [f"hbc-{self.hash}.map", "build-42.map"])
        self.assertEqual(sourcemaps.find("android", "com.swag.pay", source_hash=self.hash, root=self.root),
                         paths[0])
        self.assertEqual(sourcemaps.find("android", "com.swag.pay", build=42, root=self.root), paths[1])
        # Sidecars sit beside the maps; listing still sees only maps.
        self.assertEqual([r[2] for r in sourcemaps.listed(self.root)], ["build-42", f"hbc-{self.hash}"])
        info = sourcemaps.release_info(paths[0])
        self.assertEqual((info["tag"], info["versionCode"], info["hbcSourceHash"]),
                         ("v1.2.0-42", 42, self.hash))
        self.assertEqual(sourcemaps.imported_tags(self.root), {"v1.2.0-42"})

    def test_dry_run_is_registered_by_hash_only(self):
        self.write_manifest(tag=None, code=1, dry_run=True, versionName="1.2.0-dryrun")
        [(_, _, paths)] = sourcemaps.import_release(self.folder, root=self.root)
        self.assertEqual([os.path.basename(p) for p in paths], [f"hbc-{self.hash}.map"])
        self.assertEqual(sourcemaps.imported_tags(self.root), set())

    def test_refuses_a_file_that_isnt_the_manifests(self):
        with open(self.map, "a") as f:
            f.write(" ")
        with self.assertRaisesRegex(ValueError, "sha256"):
            sourcemaps.import_release(self.folder, root=self.root)
        self.assertEqual(sourcemaps.listed(self.root), [])

    def test_refuses_a_map_from_another_build(self):
        import shutil
        # v2 of the same program: 94 functions against the bundle's 90.
        shutil.copyfile(os.path.join(self.SYN, "v2", "main.jsbundle.map"), self.map)
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "doesn't belong"):
            sourcemaps.import_release(self.folder, root=self.root)
        self.assertEqual(sourcemaps.listed(self.root), [])

    def test_refuses_a_bundle_with_another_hash(self):
        self.write_manifest(hbc={"version": 98, "sourceHash": "0" * 40})
        with self.assertRaisesRegex(ValueError, "source hash"):
            sourcemaps.import_release(self.folder, root=self.root)

    def test_fetch_downloads_then_imports(self):
        import shutil
        calls = []

        def download(tag, repo, dest):
            calls.append((tag, repo))
            for f in os.listdir(self.folder):
                shutil.copyfile(os.path.join(self.folder, f), os.path.join(dest, f))

        rows = sourcemaps.fetch_release("v1.2.0-42", repo="o/r", root=self.root, download=download)
        self.assertEqual(calls, [("v1.2.0-42", "o/r")])
        self.assertEqual(rows[0][0], "android")

    def test_a_run_with_a_hash_never_falls_back_to_the_build_number(self):
        sourcemaps.import_release(self.folder, root=self.root)
        run = {"platform": "android", "app_pkg": "com.swag.pay"}
        # A local build with the same number but other JS: no map, not build-42's.
        self.assertIsNone(sourcemaps.map_for_run(
            run, {"app": {"hbc_source_hash": "f" * 40, "version_code": 42}}, root=self.root))
        self.assertTrue(sourcemaps.map_for_run(
            run, {"app": {"version_code": 42}}, root=self.root).endswith("build-42.map"))
        self.assertTrue(sourcemaps.map_for_run(
            run, {"app": {"hbc_source_hash": self.hash, "version_code": 7}}, root=self.root)
            .endswith(f"hbc-{self.hash}.map"))

    def stack(self):
        with open(os.path.join(self.SYN, "v1", "stacks.json")) as f:
            return next(s["text"] for s in json.load(f) if s["id"] == "nested_function")

    def records(self, stack, size=800):
        """The SwagErrors lines the app writes for one error: its JSON record
        in chunks (800 characters in the app), as `swagerr|<id>|<seq>/<total>|<chunk>`."""
        rec = json.dumps({"id": "e1", "name": "RangeError", "message": "divide by zero",
                          "stack": stack, "fatal": False, "source": "boundary"})
        chunks = [rec[i:i + size] for i in range(0, len(rec), size)]
        return [f"swagerr|e1|{n}/{len(chunks)}|{c}" for n, c in enumerate(chunks, 1)]

    def test_resolves_a_pasted_stack(self):
        from swagperf import symbolicate
        [e], incomplete = sourcemaps.resolve_text(self.stack(), self.map)
        self.assertEqual((e["name"], e["message"], incomplete), ("RangeError", "divide by zero", 0))
        self.assertEqual(e["frames"], symbolicate.symbolicate(self.stack(), self.map))
        self.assertTrue(e["frames"][0]["resolved"])

    def test_resolves_logcat_records(self):
        from swagperf import symbolicate
        logcat = "\n".join(["--------- beginning of main"] + self.records(self.stack()))
        [e], incomplete = sourcemaps.resolve_text(logcat, self.map)
        self.assertEqual((e["name"], e["fatal"], e["source"], incomplete), ("RangeError", False, "boundary", 0))
        self.assertEqual(e["frames"], symbolicate.symbolicate(self.stack(), self.map))

    def test_resolves_the_simulators_os_log(self):
        """`log show` prefixes each line and prints backslashes as \\134."""
        from swagperf import symbolicate
        lines = [f"2026-09-25 18:04:32.247 Df Swag Pay[24662:16cf3a] [com.swag.pay.trace:errors] "
                 + r.replace("\\", "\\134") for r in self.records(self.stack())]
        [e], _ = sourcemaps.resolve_text("\n".join(lines), self.map)
        self.assertEqual(e["frames"], symbolicate.symbolicate(self.stack(), self.map))

    def test_a_record_missing_a_chunk_is_counted_not_guessed(self):
        lines = self.records(self.stack(), size=100)
        self.assertGreater(len(lines), 2)
        errors, incomplete = sourcemaps.resolve_text("\n".join(lines[:1] + lines[2:]), self.map)
        self.assertEqual((errors, incomplete), ([], 1))

    def test_finds_a_releases_map_by_tag(self):
        sourcemaps.import_release(self.folder, root=self.root)
        found = sourcemaps.find_by_tag("v1.2.0-42", "android", root=self.root)
        self.assertTrue(found.endswith(f"hbc-{self.hash}.map"))
        self.assertIsNone(sourcemaps.find_by_tag("v1.2.0-42", "ios", root=self.root))
        self.assertIsNone(sourcemaps.find_by_tag("v9.9.9-99", "android", root=self.root))


if __name__ == "__main__":
    unittest.main()
