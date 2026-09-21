"""Local dashboard server: static page + JSON history API."""
import json, os
from http.server import HTTPServer, ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from . import store
from .budgets import STEP_BUDGETS_MS, GLOBAL_BUDGETS, RISK_MAP

WEB = os.path.join(os.path.dirname(__file__), "..", "web")


def _device_payload():
    """Device status merged with the catalogue, for the Capture tab's picker."""
    from . import capture as cap, catalogue
    info = cap.device_info()
    if not info:
        return {"connected": False}
    installed = set(cap.installed_packages())
    known = catalogue.load()
    seen = {a["pkg"] for a in known}
    rows = [{**a, "installed": a["pkg"] in installed} for a in known]
    for pkg in sorted(installed - seen):
        rows.append({"pkg": pkg, "name": pkg, "role": "competitor",
                    "instrumented": False, "verified": True, "installed": True,
                    "in_catalogue": False})
    for r in rows:
        r.setdefault("in_catalogue", True)
    # Installed first, then own > catalogued competitor/reference > anything
    # else on the device, so the apps this tool actually knows about surface
    # above the long tail of unrelated installed packages.
    rows.sort(key=lambda a: (not a["installed"], a["role"] != "own",
                             not a.get("in_catalogue", True),
                             a["role"] != "competitor", a["name"].lower()))
    return {"connected": True, **info, "packages": rows}


def _payload(limit=100):
    from . import catalogue
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
        # Resolve this run's own startup budget from the catalogue rather than
        # letting the client assume Swag Pay's global budget applies to every
        # app. A derived (competitor) run only gets a budget if one was
        # explicitly entered for that package; otherwise it is None, and the
        # dashboard must not draw a budget line or colour a breach for it.
        app = catalogue.get(d.get("app_pkg")) if d.get("app_pkg") else None
        d["app_name"] = (app or {}).get("name") or d.get("app_pkg")
        d["app_role"] = (app or {}).get("role")
        d["ttid_budget_ms"] = (
            GLOBAL_BUDGETS["time_to_first_camera_frame_ms"] if not d.get("derived")
            else (app or {}).get("budgets", {}).get("ttid_ms"))
        out.append(d)
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
        if u.path.startswith("/api/device"):
            return self._json(_device_payload())
        if u.path.startswith("/api/stress"):
            sid = q.get("id", [None])[0]
            if sid:
                st = store.stress_get(int(sid))
                return self._json(st) if st else self._json({"error": "unknown stress test"}, 404)
            return self._json({"stress_tests": store.stress_list()})
        if u.path.startswith("/api/jobs"):
            from . import jobs
            jid = q.get("id", [None])[0]
            if jid:
                job = jobs.get(jid)
                return self._json(job) if job else self._json({"error": "unknown job"}, 404)
            return self._json({"jobs": jobs.recent()})
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
                                      device=payload.get("device"),
                                      app_pkg=payload.get("app_pkg"))
            return self._json({"ok": True, "cleared": k})
        if u.path == "/api/stress/start":
            from . import jobs
            try:
                jid = jobs.start_stress(
                    payload.get("pkg", "").strip(),
                    sessions=payload.get("sessions", 5),
                    cold=payload.get("cold", True),
                    duration_ms=payload.get("duration_ms", 8000),
                    label=payload.get("label"),
                    use_llm=payload.get("use_llm", False))
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            return self._json({"ok": True, "job_id": jid})
        if u.path == "/api/capture/start":
            from . import jobs
            try:
                jid = jobs.start_capture(
                    payload.get("pkg", "").strip(),
                    cold=payload.get("cold", True),
                    duration_ms=payload.get("duration_ms", 10000),
                    label=payload.get("label"),
                    use_llm=payload.get("use_llm", False))
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            return self._json({"ok": True, "job_id": jid})
        return self._json({"error": "unknown endpoint"}, 404)

    def log_message(self, *a):
        pass


def serve(port=8787):
    print(f"  swagperf dashboard -> http://127.0.0.1:{port}   (ctrl-c to stop)")
    # Threading server: a capture job can run for tens of seconds, and the
    # dashboard must keep polling /api/jobs and serving the page while it does.
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
