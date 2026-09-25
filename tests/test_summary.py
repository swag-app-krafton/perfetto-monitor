"""AI summaries of recorded runs (F-023) and their benchmark comparison (F-024).

The model itself isn't tested (its output isn't deterministic). What must hold
is the plumbing around it: a summary never becomes the run's verdict, it can be
written for any recorded run without its trace, the model is sent nothing it
could act with, the benchmark it compares against is the pinned one, numbers
it writes that the run doesn't contain are flagged, and a summary job never
competes with a capture for the device.
"""
import http.client, json, os, stat, sys, tempfile, threading, time, unittest
from http.server import ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from swagperf import analyst, jobs, server, store, summary
from swagperf.extract import extract, extract_any
from swagperf.synth import gen_trace
from swagperf.synth_android import gen_android_trace

REPLY = {"verdict": "fail", "headline": "Peak RAM usage over its North Star target",
         "findings": [{"title": "Peak RAM usage over its North Star target", "runtime": "unknown",
                       "severity": "high", "kind": "budget_breach",
                       "evidence": "777.7 MB vs 320 MB", "architectural_risk": None,
                       "recommendation": "Open Screens."}],
         "dismissed": ["thermal drift: within noise"],
         "summary": "A cold start of Swag Pay. RAM usage peaked well over its target.",
         "benchmark_comparison": None}


def _write(tmp, name, data):
    p = os.path.join(tmp, name)
    with open(p, "wb") as fh:
        fh.write(data)
    return p


class _Scratch(unittest.TestCase):
    """A scratch history and a fake `claude` that records its argv and cwd."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "h.db")
        self._orig_db = store.DB
        store.DB = self.db
        self.calls = os.path.join(self.tmp, "calls.jsonl")
        self.claude = os.path.join(self.tmp, "claude")
        self.reply = dict(REPLY)
        self._write_fake()
        self.env = {k: os.environ.get(k) for k in ("SWAGPERF_CLAUDE_BIN",)}
        os.environ["SWAGPERF_CLAUDE_BIN"] = self.claude

    def _write_fake(self, reply=None, exit_code=0):
        envelope = json.dumps({"type": "result", "result": json.dumps(reply or self.reply)})
        with open(self.claude, "w") as fh:
            fh.write(f"#!{sys.executable}\nimport json, os, sys\n"
                     f"open({self.calls!r}, 'a').write(json.dumps({{'argv': sys.argv[1:], 'cwd': os.getcwd()}}) + '\\n')\n"
                     f"print({envelope!r})\nsys.exit({exit_code})\n")
        os.chmod(self.claude, os.stat(self.claude).st_mode | stat.S_IEXEC)

    def tearDown(self):
        store.DB = self._orig_db
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def calls_made(self):
        if not os.path.exists(self.calls):
            return []
        with open(self.calls) as fh:
            return [json.loads(l) for l in fh]

    def record_swag(self, seed=1, **kw):
        data, _ = gen_trace(seed=seed)
        p = _write(self.tmp, f"t{seed}.pftrace", data)
        m = extract(p)
        rid = store.record(m, device=kw.get("device", "V2514"), trace_path=p, db=self.db,
                           app_version=kw.get("app_version"))
        store.add_analysis(rid, analyst.heuristic(m, []), db=self.db)
        return rid, m


class TestVerdictAndSummaryStayApart(_Scratch):
    def test_existing_rows_are_verdicts_and_the_step_track_column_exists(self):
        c = store.connect(self.db)
        cols = {r["name"] for r in c.execute("pragma table_info(analyses)")}
        steps = {r["name"] for r in c.execute("pragma table_info(step_metrics)")}
        c.close()
        self.assertIn("kind", cols)
        self.assertIn("track", steps)

    def test_a_newer_summary_row_never_steals_the_verdict(self):
        rid, _ = self.record_swag()
        store.add_analysis(rid, {**REPLY, "_model": "m (claude cli)"}, kind="summary", db=self.db)
        verdict = store.latest_analyses("verdict", db=self.db)[rid]
        self.assertEqual(verdict["model"], "heuristic")
        run = next(r for r in server._payload()["runs"] if r["id"] == rid)
        self.assertTrue(run["analysis"]["_heuristic"])
        self.assertEqual(run["analysis_meta"]["model"], "heuristic")
        self.assertEqual(run["summary"]["model"], "m (claude cli)")
        self.assertFalse(run["summary"]["stale"])
        # Only metadata travels in the history; the body is its own endpoint.
        self.assertNotIn("findings", run["summary"])
        self.assertEqual(store.summary_of(rid, db=self.db)["summary"], REPLY["summary"])

    def test_a_new_verdict_marks_the_summary_stale(self):
        rid, m = self.record_swag()
        store.add_analysis(rid, REPLY, kind="summary", db=self.db)
        store.add_analysis(rid, analyst.heuristic(m, []), db=self.db)   # what reextract does
        self.assertTrue(store.summary_of(rid, db=self.db)["_stale"])

    def test_reextract_recomputes_the_verdict_and_leaves_the_summary(self):
        from swagperf import cli
        rid, _ = self.record_swag()
        sid = store.add_analysis(rid, REPLY, kind="summary", db=self.db)
        self.assertEqual(cli.main(["reextract"]), 0)
        self.assertGreater(store.latest_analyses("verdict", db=self.db)[rid]["id"], sid)
        s = store.summary_of(rid, db=self.db)
        self.assertEqual(s["_id"], sid)
        self.assertTrue(s["_stale"])


class TestRunMetrics(_Scratch):
    """A summary is written from the database, so what the model sees must be
    what it would have seen at capture."""

    def assert_same_payload(self, m, rid):
        again = store.run_metrics(rid, db=self.db)
        self.assertEqual(analyst.build_payload(again, [], {}), analyst.build_payload(m, [], {}))

    def test_an_instrumented_run_round_trips(self):
        rid, m = self.record_swag(seed=2)
        self.assert_same_payload(m, rid)

    def test_a_derived_run_round_trips(self):
        b, _ = gen_android_trace(3, pkg="com.some.competitor")
        p = _write(self.tmp, "c.pftrace", b)
        m = extract_any(p, app_pkg="com.some.competitor")
        rid = store.record(m, device="V2514", app_pkg="com.some.competitor", db=self.db)
        self.assert_same_payload(m, rid)

    def test_an_unknown_run_is_none(self):
        self.assertIsNone(store.run_metrics(999, db=self.db))


class TestSummarise(_Scratch):
    def test_a_summary_is_stored_as_a_summary_and_the_verdict_is_unchanged(self):
        rid, _ = self.record_swag()
        res = summary.write(rid, db=self.db, backend="cli")
        self.assertEqual(res["summary"], REPLY["summary"])
        self.assertEqual(res["_backend"], "cli")
        self.assertEqual(store.latest_analyses("verdict", db=self.db)[rid]["model"], "heuristic")
        self.assertEqual(store.summary_of(rid, db=self.db)["headline"], REPLY["headline"])

    def test_the_model_gets_no_tools_no_mcp_no_session_and_not_the_repository(self):
        rid, _ = self.record_swag()
        summary.write(rid, db=self.db, backend="cli")
        call = self.calls_made()[-1]
        argv = call["argv"]
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertIn("--strict-mcp-config", argv)
        self.assertIn("--no-session-persistence", argv)
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assertFalse(os.path.realpath(call["cwd"]).startswith(os.path.realpath(repo)))

    def test_it_sees_which_run_and_what_startup_measures(self):
        rid, m = self.record_swag()
        payload = analyst.build_payload(store.run_metrics(rid, db=self.db), [], {},
                                        run=summary._run_details(rid, store.run_metrics(rid, db=self.db)))
        self.assertEqual(payload["run"]["id"], rid)
        self.assertEqual(payload["run"]["startup_metric"], "time to first camera frame")
        self.assertFalse(payload["run"]["derived"])

    def test_a_number_not_in_the_run_is_flagged(self):
        rid, _ = self.record_swag()
        res = summary.write(rid, db=self.db, backend="cli")
        self.assertIn("777.7", res["_unverified"])
        self.assertNotIn("320", res["_unverified"])

    def test_no_model_means_no_summary_and_nothing_written(self):
        rid, _ = self.record_swag()
        self.assertIsNone(summary.write(rid, db=self.db, backend="heuristic"))
        self._write_fake(exit_code=1)
        self.assertIsNone(summary.write(rid, db=self.db, backend="cli"))
        self.assertIsNone(store.summary_of(rid, db=self.db))

    def test_an_unknown_run_raises(self):
        with self.assertRaises(LookupError):
            summary.write(12345, db=self.db, backend="cli")


class TestBenchmarkComparison(_Scratch):
    def test_only_when_a_benchmark_is_pinned_for_the_run(self):
        base, _ = self.record_swag(seed=1)
        rid, m = self.record_swag(seed=2)
        self.assertIsNone(summary.benchmark_comparison(rid, store.run_metrics(rid, db=self.db), db=self.db))
        store.set_benchmark(base, db=self.db)
        cmp = summary.benchmark_comparison(rid, store.run_metrics(rid, db=self.db), db=self.db)
        self.assertEqual(cmp["base"]["id"], base)
        self.assertEqual(cmp["run"]["id"], rid)
        self.assertTrue(cmp["metrics"])
        self.assertTrue(all(s["children"] == [] for s in cmp["steps"]))
        # The benchmark run itself has nothing to compare with.
        self.assertIsNone(summary.benchmark_comparison(base, store.run_metrics(base, db=self.db), db=self.db))

    def test_a_simulator_run_gets_none(self):
        base, _ = self.record_swag(seed=1)
        rid, _ = self.record_swag(seed=2)
        store.set_benchmark(base, db=self.db)
        m = store.run_metrics(rid, db=self.db)
        self.assertIsNone(summary.benchmark_comparison(rid, {**m, "simulator": True}, db=self.db))

    def test_the_summary_keeps_the_snapshot_it_was_written_from(self):
        base, _ = self.record_swag(seed=1)
        rid, _ = self.record_swag(seed=2)
        store.set_benchmark(base, db=self.db)
        self._write_fake({**REPLY, "benchmark_comparison": "Slower than the benchmark."})
        res = summary.write(rid, db=self.db, backend="cli")
        self.assertEqual(res["_benchmark"]["base"]["id"], base)
        self.assertEqual(store.summary_of(rid, db=self.db)["_benchmark"]["base"]["id"], base)

    def test_the_payload_never_carries_a_trace(self):
        base, _ = self.record_swag(seed=1)
        rid, _ = self.record_swag(seed=2)
        store.set_benchmark(base, db=self.db)
        m = store.run_metrics(rid, db=self.db)
        payload = analyst.build_payload(m, store.regressions(rid, db=self.db), {},
                                        run=summary._run_details(rid, m),
                                        vs_benchmark=summary.benchmark_comparison(rid, m, db=self.db))
        text = json.dumps(payload)
        self.assertIn("vs_benchmark", payload)
        for needle in ("pftrace", "trace_path", "traces/", self.tmp):
            self.assertNotIn(needle, text, needle)


class TestUnverifiedNumbers(unittest.TestCase):
    def test_rounding_worked_differences_and_identifiers(self):
        res = {"headline": "493 MB vs 320 MB (+54.2%)",
               "summary": "1,217.5 ms vs 1,124.5 ms is 93 ms slower (8.3%); version 2.3.1 on "
                          "2026-09-25 at 14:02; 3 runs. Also 777 ms.",
               "findings": [{"title": "x", "evidence": "0.5% vs 0.52%", "recommendation": "r"}],
               "dismissed": ["thermal: 16.67 ms frames"]}
        payload = {"a": 493.3, "b": 320, "c": 54.2, "d": 1217.5, "e": 0.52, "f": 1124.5}
        self.assertEqual(analyst.unverified_numbers(res, payload), ["777"])

    def test_a_difference_across_fields_and_a_cut_off_value_match(self):
        # Seen in a real summary: headroom worked out from two numbers the
        # headline quotes, and a baseline of 98.75 written as 98.7.
        res = {"headline": "Startup passes at 414.56 ms of a 420 ms target",
               "summary": "Only 5.44 ms of headroom; compose_shell's median is 98.7 ms.",
               "findings": [], "dismissed": []}
        payload = {"startup": 414.56, "target": 420, "median": 98.75}
        self.assertEqual(analyst.unverified_numbers(res, payload), [])


class TestSummaryJobs(_Scratch):
    def setUp(self):
        super().setUp()
        self._orig_backend = analyst.BACKEND
        analyst.BACKEND = "cli"
        self._orig_wait = jobs.SUMMARY_WAIT_S
        jobs.SUMMARY_WAIT_S = 0.05

    def tearDown(self):
        analyst.BACKEND = self._orig_backend
        jobs.SUMMARY_WAIT_S = self._orig_wait
        super().tearDown()

    def wait(self, jid, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            j = jobs.get(jid)
            if j["state"] in ("done", "error"):
                return j
            time.sleep(0.05)
        self.fail(f"job {jid} did not finish")

    def test_a_job_writes_the_summary(self):
        rid, _ = self.record_swag()
        j = self.wait(jobs.start_summary([rid]))
        self.assertEqual(j["state"], "done", j)
        self.assertEqual(j["result"]["written"], [rid])
        self.assertFalse(jobs.summarising(rid))

    def test_a_second_request_for_the_same_run_is_refused(self):
        rid, _ = self.record_swag()
        with jobs._LOCK:
            jobs._summarising.add(rid)
        try:
            with self.assertRaises(RuntimeError):
                jobs.start_summary([rid])
        finally:
            with jobs._LOCK:
                jobs._summarising.discard(rid)

    def test_it_waits_while_a_capture_holds_the_device(self):
        rid, _ = self.record_swag()
        jobs._capture_lock.acquire()
        try:
            jid = jobs.start_summary([rid])
            time.sleep(0.4)
            self.assertEqual(self.calls_made(), [])
            self.assertIn("waiting", " ".join(l["text"] for l in jobs.get(jid)["log"]))
        finally:
            jobs._capture_lock.release()
        self.assertEqual(self.wait(jid)["state"], "done")

    def test_no_model_ends_the_job_in_error_with_the_reason(self):
        rid, _ = self.record_swag()
        analyst.BACKEND = "heuristic"
        j = self.wait(jobs.start_summary([rid]))
        self.assertEqual(j["state"], "error")
        self.assertEqual(j["error"], summary.NO_MODEL)


class TestSummaryEndpoints(_Scratch):
    def setUp(self):
        super().setUp()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def call(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(method, path, body=json.dumps(body) if body is not None else None,
                     headers={"X-Swagperf": "1", "Content-Type": "application/json"})
        r = conn.getresponse()
        out = (r.status, json.loads(r.read() or b"null"))
        conn.close()
        return out

    def test_generate_validates_its_run(self):
        self.assertEqual(self.call("POST", "/api/summary/generate", {})[0], 400)
        self.assertEqual(self.call("POST", "/api/summary/generate", {"run_id": "x"})[0], 400)
        self.assertEqual(self.call("POST", "/api/summary/generate", {"run_id": 999})[0], 404)
        rid, _ = self.record_swag()
        with jobs._LOCK:
            jobs._summarising.add(rid)
        try:
            self.assertEqual(self.call("POST", "/api/summary/generate", {"run_id": rid})[0], 409)
        finally:
            with jobs._LOCK:
                jobs._summarising.discard(rid)

    def test_get_returns_the_summary_body(self):
        rid, _ = self.record_swag()
        status, body = self.call("GET", f"/api/summary?run={rid}")
        self.assertEqual((status, body["summary"], body["generating"]), (200, None, False))
        store.add_analysis(rid, {**REPLY, "_model": "m"}, kind="summary", db=self.db)
        status, body = self.call("GET", f"/api/summary?run={rid}")
        self.assertEqual(body["summary"]["summary"], REPLY["summary"])
        self.assertEqual(body["summary"]["_model"], "m")


if __name__ == "__main__":
    unittest.main()
