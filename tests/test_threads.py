"""Plain-language thread descriptions (swagperf/threads.py) and their delivery
with a Flashlight audit's CPU-by-thread list."""
import copy, json, os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from swagperf.threads import THREAD_DESCRIPTIONS, describe_summary, describe_thread

HERE = os.path.dirname(os.path.abspath(__file__))


class TestDescribeThread(unittest.TestCase):

    # Every name in a real audit's CPU-by-thread list, as Flashlight wrote it.
    AUDITED = ["UI Thread", "mqt_v_js", "RenderThread", "Thread-22", "Jit thread pool",
               "glide-disk-cach", "Thread-21", "HeapTaskDaemon", "mqt_v_native",
               "DefaultDispatch (3)", "DefaultDispatch (6)", "glide-animation (2)"]

    def test_every_thread_in_a_real_audit_is_described(self):
        for name in self.AUDITED:
            self.assertTrue(describe_thread(name), name)

    def test_the_known_families(self):
        cases = {
            "mqt_js": "JavaScript thread",
            "mqt_native_modu": "native-modules",
            "mqt_native_modules": "native-modules",
            "hades": "garbage collector",
            "FinalizerDaemon": "finalize()",
            "FinalizerWatchd": "FinalizerDaemon",
            "FinalizerWatchdogDaemon": "FinalizerDaemon",
            "ReferenceQueueD": "references",
            "Signal Catcher": "signals",
            "Profile Saver": "compile them",
            "Binder #4": "binder thread",
            "binder:4242_3": "binder thread",
            "binder:31940_A": "binder thread",
            "HwBinder:1234_1": "binder thread",
            "hwuiTask0": "hwui",
            "DefaultDispatcher-worker-12": "coroutines",
            "OkHttp Dispatch": "OkHttp",
            "OkHttp TaskRunn": "OkHttp",
            "glide-source-th": "fetches images",
            "glide-active-re": "Glide",
            "CameraX-core_ca": "CameraX",
            "CameraX-core_ca (2)": "CameraX",
            "CXCP-Camera-H": "camera-pipe",
            "mali-event-hand": "Mali",
            "Chrome_ChildIOT": "Chromium",
            "FrescoIoBoundEx": "Fresco",
            "pool-3-thread-1": "thread pool",
            "AsyncTask #2": "AsyncTask",
            "queued-work-loo": "SharedPreferences",
            "arch_disk_io_0": "Room",
        }
        for name, needle in cases.items():
            d = describe_thread(name)
            self.assertIsNotNone(d, name)
            self.assertIn(needle, d, name)

    def test_an_unnamed_thread_says_so_and_how_to_fix_it(self):
        d = describe_thread("Thread-22")
        self.assertIn("no clue", d)
        self.assertIn("naming the thread", d)

    def test_a_repeat_suffix_does_not_change_the_answer(self):
        self.assertEqual(describe_thread("DefaultDispatch (3)"), describe_thread("DefaultDispatch"))
        self.assertEqual(describe_thread("glide-animation (2)"), describe_thread("glide-animation"))

    def test_unknown_or_ambiguous_names_get_nothing(self):
        for name in ["money.super.pay", "Empty name", "RenderThreadX", "mqt_jsx", "Thread-x",
                     "MyWorker", "glide", "binder", "main", "", None, "Choreographer",
                     "CameraX", "pool-thread"]:
            self.assertIsNone(describe_thread(name), name)

    def test_descriptions_stay_short_and_use_the_ram_wording(self):
        for pattern, d in THREAD_DESCRIPTIONS:
            self.assertLessEqual(len(d.split()), 35, pattern.pattern)
            self.assertNotIn("RSS", d, pattern.pattern)


class TestDescribeSummary(unittest.TestCase):
    """What /api/audits delivers: the stored summary with descriptions added."""

    def setUp(self):
        with open(os.path.join(HERE, "fixtures", "flashlight_summary.json")) as fh:
            self.summary = json.load(fh)

    def test_threads_key_threads_and_iterations_are_described(self):
        before = copy.deepcopy(self.summary)
        out = describe_summary(self.summary)
        self.assertEqual(self.summary, before, "the stored summary is not modified")
        for t in out["threads"]:
            self.assertEqual(t.get("description"), describe_thread(t["name"]), t["name"])
        self.assertIn("main thread", out["key_threads"]["ui"]["description"])
        self.assertIn("JavaScript", out["key_threads"]["js"]["description"])
        self.assertIsNone(out["key_threads"]["native_modules"])
        for it in out["iterations"]:
            self.assertIn("description", it["key_threads"]["render"])

    def test_a_list_entry_and_a_missing_summary(self):
        # A list carries only headline parts; no threads list at all.
        out = describe_summary({"successful": 3, "failed": 0, "metrics": {}, "key_threads": None})
        self.assertIsNone(out["key_threads"])
        self.assertNotIn("threads", out)
        self.assertIsNone(describe_summary(None))

    def test_an_undescribed_thread_has_no_description_key(self):
        out = describe_summary({"threads": [{"name": "SomeWorker", "cpu_pct": 1.0}]})
        self.assertEqual(out["threads"], [{"name": "SomeWorker", "cpu_pct": 1.0}])


if __name__ == "__main__":
    unittest.main()
