"""Local dashboard server: static page + JSON history API."""
import json, os
from http.server import HTTPServer, SimpleHTTPRequestHandler
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
            "global_budgets": GLOBAL_BUDGETS, "risk_map": RISK_MAP}


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=os.path.abspath(WEB), **kw)

    def do_GET(self):
        if self.path.startswith("/api/history"):
            body = json.dumps(_payload()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()

    def log_message(self, *a):
        pass


def serve(port=8787):
    print(f"  swagperf dashboard -> http://127.0.0.1:{port}   (ctrl-c to stop)")
    HTTPServer(("127.0.0.1", port), H).serve_forever()
