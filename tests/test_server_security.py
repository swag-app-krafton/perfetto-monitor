"""Who may talk to the dashboard server (T-001).

The server binds to loopback, but any page open in the user's browser can
reach it. These run the real handler on an ephemeral port and send what a
hostile page could send: a foreign Host (DNS rebinding), a foreign Origin, and
a write without the X-Swagperf header (a cross-site form or simple fetch).
"""
import http.client, json, os, sys, tempfile, threading, unittest
from http.server import ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from swagperf import server, store
from swagperf.extract import extract
from swagperf.synth import gen_trace


class TestAccessRules(unittest.TestCase):
    """access_error() on its own, without a socket."""

    def err(self, method="GET", **headers):
        return server.access_error(method, {k.replace("_", "-"): v for k, v in headers.items()})

    def test_loopback_hosts_on_any_port_are_served(self):
        for host in ("127.0.0.1:8787", "localhost:5173", "[::1]:8799", "LOCALHOST", "127.0.0.1"):
            self.assertIsNone(self.err(Host=host), host)

    def test_other_hosts_are_refused(self):
        for host in ("evil.example", "evil.example:8787", "127.0.0.1.nip.io:8787", "localhost.",
                     "10.0.0.5:8787", "[::2]:8787", "127.0.0.1:port", "[::1", ""):
            self.assertEqual(self.err(Host=host), "host_not_allowed", host)
        self.assertEqual(server.access_error("GET", {}), "host_not_allowed")

    def test_origin_must_be_a_loopback_page_when_sent(self):
        ok = {"Host": "127.0.0.1:8787", "X-Swagperf": "1"}
        for origin in ("http://localhost:5173", "http://127.0.0.1:5199", "http://[::1]:8787"):
            self.assertIsNone(server.access_error("POST", {**ok, "Origin": origin}), origin)
        for origin in ("https://evil.example", "http://evil.example", "null", "file://",
                       "https://localhost:5173", "http://127.0.0.1.nip.io"):
            self.assertEqual(server.access_error("POST", {**ok, "Origin": origin}),
                             "origin_not_allowed", origin)

    def test_writes_need_the_header_reads_do_not(self):
        host = {"Host": "127.0.0.1:8787"}
        self.assertIsNone(server.access_error("GET", host))
        self.assertIsNone(server.access_error("HEAD", host))
        self.assertEqual(server.access_error("POST", host), "missing_x_swagperf_header")
        self.assertEqual(server.access_error("POST", {**host, "X-Swagperf": "yes"}),
                         "missing_x_swagperf_header")
        self.assertIsNone(server.access_error("POST", {**host, "X-Swagperf": "1"}))


class TestLiveServer(unittest.TestCase):
    """The real handler over a socket, against a scratch history."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.db = os.path.join(cls.tmp, "h.db")
        data, _ = gen_trace(seed=3)
        path = os.path.join(cls.tmp, "t.pftrace")
        with open(path, "wb") as fh:
            fh.write(data)
        cls.run_id = store.record(extract(path), device="V2514", db=cls.db)
        cls._orig_db = store.DB
        store.DB = cls.db
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        store.DB = cls._orig_db

    def send(self, method, path, *, body=None, host=None, headers=None, no_host=False):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.putrequest(method, path, skip_host=True)
        if not no_host:
            conn.putheader("Host", host or f"127.0.0.1:{self.port}")
        data = json.dumps(body).encode() if body is not None else b""
        for k, v in (headers or {}).items():
            conn.putheader(k, v)
        if method == "POST":
            conn.putheader("Content-Length", str(len(data)))
        conn.endheaders(data if method == "POST" else None)
        r = conn.getresponse()
        raw = r.read()
        conn.close()
        return r.status, raw

    def pinned(self):
        return [b["run_id"] for b in store.benchmarks(db=self.db)]

    def test_a_loopback_read_is_served(self):
        status, raw = self.send("GET", "/api/history")
        self.assertEqual(status, 200)
        self.assertIn(self.run_id, [r["id"] for r in json.loads(raw)["runs"]])

    def test_a_foreign_host_is_refused_on_every_method_and_path(self):
        for method, path in (("GET", "/api/history"), ("GET", "/"), ("GET", "/overview"),
                             ("GET", "/tokens.html"), ("POST", "/api/benchmark/set")):
            for host in ("evil.example", "127.0.0.1.nip.io"):
                status, raw = self.send(method, path, host=host, body={"run_id": self.run_id},
                                        headers={"X-Swagperf": "1"})
                self.assertEqual(status, 403, (method, path, host))
                self.assertEqual(json.loads(raw)["error"], "host_not_allowed")
        self.assertEqual(self.pinned(), [])

    def test_a_missing_host_is_refused(self):
        status, _ = self.send("GET", "/api/history", no_host=True)
        self.assertEqual(status, 403)

    def test_head_is_refused_without_a_body(self):
        status, raw = self.send("HEAD", "/", host="evil.example")
        self.assertEqual(status, 403)
        self.assertEqual(raw, b"")

    def test_a_write_without_the_header_is_refused_and_writes_nothing(self):
        # What a cross-site <form> or a simple text/plain fetch can send.
        status, raw = self.send("POST", "/api/benchmark/set", body={"run_id": self.run_id},
                                headers={"Content-Type": "text/plain",
                                         "Origin": f"http://127.0.0.1:{self.port}"})
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(raw)["error"], "missing_x_swagperf_header")
        self.assertEqual(self.pinned(), [])

    def test_a_write_from_a_foreign_origin_is_refused(self):
        for origin in ("https://evil.example", "null"):
            status, raw = self.send("POST", "/api/benchmark/set", body={"run_id": self.run_id},
                                    headers={"X-Swagperf": "1", "Origin": origin})
            self.assertEqual(status, 403, origin)
            self.assertEqual(json.loads(raw)["error"], "origin_not_allowed")
        self.assertEqual(self.pinned(), [])

    def test_the_dashboards_own_write_is_served(self):
        status, raw = self.send("POST", "/api/benchmark/set", body={"run_id": self.run_id},
                                headers={"X-Swagperf": "1", "Content-Type": "application/json",
                                         "Origin": "http://localhost:5173"})
        self.assertEqual(status, 200, raw)
        self.assertEqual(self.pinned(), [self.run_id])
        status, _ = self.send("POST", "/api/benchmark/clear", body={"run_id": self.run_id},
                              headers={"X-Swagperf": "1"})
        self.assertEqual(status, 200)
        self.assertEqual(self.pinned(), [])


if __name__ == "__main__":
    unittest.main()
