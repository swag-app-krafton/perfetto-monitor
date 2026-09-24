"""Hangs, JS errors and crashes (stability.py), on both platforms.

iOS recordings come from synth_ios (the Hangs instrument's rows, the app's
error markers and os_log lines); the Android trace is built here with
Perfetto's own trace builder, because it needs logcat packets the synthetic
Android generator does not write.
"""
import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from perfetto.protos.perfetto.trace.perfetto_trace_pb2 import Trace, TrackEvent

from swagperf import analyst, extract as ex, sourcemaps, stability, store, triage
from swagperf.synth_ios import Recording

MS = 1_000_000


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
        self.assertTrue(m["stability"]["crash"]["crashed"])
        self.assertEqual(m["stability"]["crash"]["reason"], "SIGABRT")
        m, _ = _ios(lambda r: None)
        self.assertFalse(m["stability"]["crash"]["crashed"])

    def test_how_xctrace_saw_the_process_end(self):
        from swagperf.capture_ios import crash_of
        ok = {"end_reason": "Time limit reached", "process": {"termination_reason": "exit(0)", "exit_status": 0}}
        self.assertEqual(crash_of(ok), (False, "exit(0)"))
        died = {"end_reason": "Target exited", "process": {"termination_reason": "SIGABRT", "exit_status": 6}}
        self.assertTrue(crash_of(died)[0])


def _android_trace():
    """An Android app: a first frame, then main-thread stalls, a JS error's
    marker and record in logcat, and a crash."""
    t = Trace()
    pid = 4000

    def pkt():
        p = t.packet.add()
        p.trusted_packet_sequence_id = 1
        return p
    # Log timestamps are on the realtime clock; a snapshot maps it onto the
    # trace's boot clock, as every real device trace has.
    p = pkt()
    for clock_id in (6, 1):      # BUILTIN_CLOCK_BOOTTIME, BUILTIN_CLOCK_REALTIME
        c = p.clock_snapshot.clocks.add()
        c.clock_id, c.timestamp = clock_id, 0
    p = pkt()
    p.track_descriptor.uuid = 1
    p.track_descriptor.process.pid = pid
    p.track_descriptor.process.process_name = "com.swag.pay"
    p = pkt()
    p.track_descriptor.uuid = 2
    p.track_descriptor.thread.pid = pid
    p.track_descriptor.thread.tid = pid
    p.track_descriptor.thread.thread_name = "com.swag.pay"

    def sl(ts_ms, dur_ms, name):
        for ts, kind in ((ts_ms, TrackEvent.TYPE_SLICE_BEGIN), (ts_ms + dur_ms, TrackEvent.TYPE_SLICE_END)):
            p = pkt()
            p.timestamp = int(ts * MS)
            p.track_event.type = kind
            p.track_event.track_uuid = 2
            if kind == TrackEvent.TYPE_SLICE_BEGIN:
                p.track_event.name = name
    sl(100, 300, "bindApplication")                # startup
    sl(500, 20, "Choreographer#doFrame 1")         # the first frame ends at 520 ms
    sl(1000, 320, "Choreographer#doFrame 2")       # a hang
    sl(2000, 180, "binder transaction")            # a microhang
    p = pkt()
    p.timestamp = 3000 * MS
    p.track_event.type = TrackEvent.TYPE_INSTANT
    p.track_event.track_uuid = 2
    p.track_event.name = "error:js:global:TypeError#fatal@k1"
    rec = json.dumps({"id": "k1", "name": "TypeError", "message": "x", "stack": "TypeError: x\n    at a (address at index.android.bundle:1:9)"})
    p = pkt()
    lp = p.android_log
    for i, (tag, msg) in enumerate([("SwagPerfError", f"swagerr|k1|1/1|{rec}"),
                                    ("AndroidRuntime", "FATAL EXCEPTION: main")]):
        ev = lp.events.add()
        ev.pid, ev.tid, ev.timestamp, ev.tag, ev.message = pid, pid, (3000 + i) * MS, tag, msg
        ev.prio = 4 if tag == "SwagPerfError" else 6   # INFO, ERROR
    return t.SerializeToString()


class TestAndroidStability(unittest.TestCase):

    def test_main_thread_stalls_logcat_records_and_crash(self):
        path = _write(_android_trace())
        from perfetto.trace_processor import TraceProcessor
        tp = TraceProcessor(trace=path)
        try:
            st = stability.extract_stability(tp, "com.swag.pay", "android")
        finally:
            tp.close()
        h = st["hangs"]
        self.assertEqual((h["count"], h["microhangs"], h["startup"]["count"]), (1, 1, 1))
        self.assertEqual(h["source"], "the app's main-thread slices")
        e = st["errors"]
        self.assertEqual((e["js"], e["js_fatal"]), (1, 1))
        self.assertIn("index.android.bundle", e["events"][0]["stack"])
        self.assertTrue(st["crash"]["crashed"])


class TestStabilityDownstream(unittest.TestCase):

    def test_stored_findings_and_signals(self):
        m, _ = _ios(lambda r: (r.js_error(2000, fatal=True), r.hang(3000, 400)),
                    crashed="SIGSEGV")
        db = os.path.join(tempfile.mkdtemp(), "h.db")
        rid = store.record(m, device="iPhone 17", db=db)
        row = store.run_row(rid, db=db)
        self.assertEqual((row["hang_count"], row["js_errors"], row["crashed"]), (1, 1, 1))
        kinds = {f["kind"] for f in analyst.heuristic(m, [])["findings"]}
        self.assertTrue({"crash", "js_error", "hang"} <= kinds)
        run = {"id": rid, "app_pkg": "com.example.ios", "path_kind": "cold", "platform": "ios",
               "stability": json.loads(row["stability_json"]), "breaches": [], "violations": []}
        keys = {s["key"] for s in triage.signals_of(run, [])}
        self.assertIn("js_error:TypeError:ios:com.example.ios:cold", keys)
        self.assertIn("crash:app:ios:com.example.ios:cold", keys)

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


if __name__ == "__main__":
    unittest.main()
