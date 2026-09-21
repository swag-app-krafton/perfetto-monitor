"""Local dashboard server: static page + JSON history API."""
import json, os
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from . import store

WEB = os.path.join(os.path.dirname(__file__), "..", "web")


def _payload(limit=100):
    runs = store.history(limit)
    c = store.connect()
    an = {}
    for r in c.execute("""select a.run_id, a.json, a.verdict, a.model from analyses a
                          join (select run_id, max(id) mid from analyses group by run_id) m
                          on a.id = m.mid"""):
        try:
            an[r["run_id"]] = json.loads(r["json"])
        except Exception:
            pass
    c.close()
    out = []
    for r in runs:
        d = dict(r)
        for k in ("breaches_json", "violations_json", "frames_json", "memory_json"):
            try:
                d[k.replace("_json", "")] = json.loads(d.pop(k) or "null")
            except Exception:
                d[k.replace("_json", "")] = None
        d["steps"] = [{**s, "children": json.loads(s.pop("children_json") or "[]")}
                      for s in d["steps"]]
        d["analysis"] = an.get(r["id"])
        out.append(d)
    from .budgets import STEP_BUDGETS_MS, GLOBAL_BUDGETS, RISK_MAP
    return {"runs": out, "step_budgets": STEP_BUDGETS_MS,
            "global_budgets": GLOBAL_BUDGETS, "risk_map": RISK_MAP,
            "benchmarks": store.benchmarks(),
            "metric_direction": store.METRIC_DIRECTION,
            "signed_metrics": sorted(store.SIGNED_METRICS)}


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=os.path.abspath(WEB), **kw)

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path.startswith("/api/history"):
            return self._json(_payload())
        if u.path.startswith("/api/compare"):
            try:
                run = int(q.get("run", [""])[0])
                base = int(q.get("base", [""])[0])
            except (ValueError, IndexError):
                return self._json({"error": "run and base query params are required"}, 400)
            try:
                return self._json(store.compare(run, base))
            except ValueError as e:
                return self._json({"error": str(e)}, 404)
        return super().do_GET()

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "invalid JSON body"}, 400)
        # The dashboard is bound to loopback only, so these mutate local history
        # without auth. That is deliberate for a dev/CI tool; do not expose the
        # server on a routable interface.
        if u.path == "/api/benchmark/set":
            try:
                res = store.set_benchmark(int(payload["run_id"]), note=payload.get("note"))
            except (KeyError, ValueError, TypeError) as e:
                return self._json({"error": str(e)}, 400)
            return self._json({"ok": True, "benchmark": res})
        if u.path == "/api/benchmark/clear":
            k = store.clear_benchmark(run_id=payload.get("run_id"),
                                      path_kind=payload.get("path_kind"),
                                      device=payload.get("device"))
            return self._json({"ok": True, "cleared": k})
        return self._json({"error": "unknown endpoint"}, 404)

    def log_message(self, *a):
        pass


def serve(port=8787):
    print(f"  swagperf dashboard -> http://127.0.0.1:{port}   (ctrl-c to stop)")
    HTTPServer(("127.0.0.1", port), H).serve_forever()
