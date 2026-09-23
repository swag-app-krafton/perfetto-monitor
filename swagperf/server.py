"""Local dashboard server: static page + JSON history API."""
import json, os, tempfile, threading, time
from http.server import HTTPServer, ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from . import store
from .budgets import STEP_BUDGETS_MS, GLOBAL_BUDGETS, RISK_MAP

WEB = os.path.join(os.path.dirname(__file__), "..", "web")
DIST = os.path.join(WEB, "dist")  # the built dashboard; see frontend/README.md


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
    return {"connected": True, **info, "packages": rows,
            "health": cap.device_health(info.get("serial")),
            "devices": cap.devices()}


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
    from .budgets import CRITICAL_PATH_FIRST_RUN, CRITICAL_PATH_RETURNING, DEFERRED_STEPS, STEP_RUNTIME
    return {"runs": out, "step_budgets": STEP_BUDGETS_MS,
            # The instrumented app's stated startup architecture: which steps a
            # user waits through on each path, and which work must wait for the
            # first frame. Published so the UI does not keep its own copy.
            "startup_model": {"critical_path": {"returning_user": CRITICAL_PATH_RETURNING,
                                                "first_run": CRITICAL_PATH_FIRST_RUN},
                              "deferred_steps": DEFERRED_STEPS,
                              "step_runtime": STEP_RUNTIME},
            "global_budgets": GLOBAL_BUDGETS, "risk_map": RISK_MAP,
            "benchmarks": store.benchmarks(),
            "metric_direction": store.METRIC_DIRECTION,
            "signed_metrics": sorted(store.SIGNED_METRICS)}


# ----------------------------------------------------------- live marker view

# The dashboard polls while a manual session records. Each poll reads only the
# bytes written since the last one (see live.py), so its cost no longer grows
# with the session. The short TTL just stops several open tabs from each
# triggering their own adb read within the same couple of seconds.
_LIVE_TTL_S = 2.0
_live_cache = {"at": 0.0, "value": None}
_live_lock = threading.Lock()
_live = None
_live_mode = {"incremental": True}


def _live_trace():
    global _live
    if _live is None:
        from .capture import manual_read_from
        from .live import LiveTrace
        from .screens import marker_rows
        _live = LiveTrace(manual_read_from, marker_rows)
    return _live


def _live_reset():
    """Forget the previous session's position and markers."""
    with _live_lock:
        if _live is not None:
            _live.reset()
        _live_mode["incremental"] = True   # each new session tries the fast path again
        _live_cache["value"] = None


def _live_markers():
    """Markers seen so far in the in-progress manual session.

    Best-effort by design: the session keeps recording whatever happens here,
    so a failed read degrades to the last good answer with a note rather than
    disturbing the capture.
    """
    from .capture import manual_remote_size, manual_snapshot, manual_status
    from .screens import live_markers, summarise_markers

    st = manual_status()
    if not st.get("recording"):
        return {"recording": False, "events": [], "counts": {}}

    now = time.time()
    with _live_lock:
        c = _live_cache["value"]
        if c and (now - _live_cache["at"]) < _LIVE_TTL_S:
            return {**c, "cached": True}
        lt = _live_trace()
        try:
            t0 = time.time()
            if _live_mode["incremental"]:
                try:
                    size = manual_remote_size()
                    # A file smaller than what was already read is a new session.
                    if size is not None and size < lt.offset:
                        lt.reset()
                    rows = lt.poll()
                    out = {"recording": True, **summarise_markers(rows),
                           "read_mb": round(lt.offset / 1e6, 1),
                           "remote_mb": round(size / 1e6, 1) if size is not None else None}
                except (ValueError, RuntimeError):
                    # The phone's tail/head, or exec-out, did not hand back the
                    # bytes asked for (misaligned or failed). Rather than a blank
                    # feed, fall back to copying the whole file for the rest of
                    # this session: slower, but known to work.
                    _live_mode["incremental"] = False
                    lt.reset()
            if not _live_mode["incremental"]:
                tmp = os.path.join(tempfile.gettempdir(), "swagperf_live.pftrace")
                manual_snapshot(tmp)
                out = {"recording": True, **live_markers(tmp), "mode": "full-copy fallback"}
            out["poll_s"] = round(time.time() - t0, 2)
        except Exception as e:
            prev = _live_cache["value"] or {"recording": True, "events": [], "counts": {}}
            out = {**prev, "note": f"markers unavailable this poll: {e}"}
        _live_cache["at"] = time.time()
        _live_cache["value"] = out
        return out


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=os.path.abspath(WEB), **kw)

    def send_response(self, code, *a):
        # The dashboard is edited and reloaded constantly, and this is a local
        # single-user server, so caching buys nothing and costs real confusion:
        # SimpleHTTPRequestHandler sends Last-Modified and answers a browser's
        # If-Modified-Since with 304, which silently served a stale index.html
        # long after its CSS had changed -- the red titles were in the file but
        # never on the page. Dropping the request's If-Modified-Since (below)
        # stops the 304, and this no-store header stops the browser reusing a
        # response it already holds, so an edit is one ordinary reload away.
        super().send_response(code, *a)
        self.send_header("Cache-Control", "no-store, must-revalidate")

    def translate_path(self, path):
        """Map a URL to a file: the built app, or the token-usage page.

        The React app (web/dist, built from frontend/) owns every client route,
        so any path that is not a real file falls back to its index.html --
        /overview, /steps/... are routes, not files. A missing *asset* (a name
        with an extension) still 404s rather than silently getting HTML.
        """
        p = urlparse(path).path
        if p == "/tokens.html":
            return super().translate_path(path)
        dist = os.path.abspath(DIST)
        cand = os.path.normpath(os.path.join(dist, p.lstrip("/")))
        # `..` in a raw request path must never reach a file outside the build
        # (a browser normalises it away; curl --path-as-is does not).
        if cand != dist and not cand.startswith(dist + os.sep):
            return os.path.join(dist, ".not-found")
        if os.path.isfile(cand):
            return cand
        if "." not in os.path.basename(p):
            return os.path.join(dist, "index.html")
        return cand

    def send_head(self):
        # Static files only reach here, so this is where the conditional-GET
        # negotiation happens: drop the browser's validators so the base class
        # cannot answer 304 from a file it thinks is unchanged.
        for h in ("If-Modified-Since", "If-None-Match"):
            if h in self.headers:
                del self.headers[h]
        return super().send_head()

    def _text(self, text, code=200):
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # The page went away before a slow answer (a live poll, a trace
            # extraction) was ready -- a tab switch or a closed window. Normal,
            # and not worth a traceback in the server log every time.
            pass

    def _sse_start(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

    def _sse(self, kind, data):
        """One server-sent event. Returns False once the client has gone (Stop
        in the panel aborts the request), so the producer can stop early."""
        try:
            self.wfile.write(f"event: {kind}\ndata: {json.dumps(data)}\n\n".encode())
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError):
            return False

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
        if u.path.startswith("/api/tokens"):
            from . import tokens as _tokens
            try:
                return self._json(_tokens.payload(os.getcwd()))
            except Exception as e:
                return self._json({"error": str(e), "sessions": []}, 500)
        if u.path.startswith("/api/device"):
            return self._json(_device_payload())
        if u.path.startswith("/api/manual/status"):
            from .capture import manual_status
            return self._json(manual_status())
        if u.path.startswith("/api/manual/live"):
            return self._json(_live_markers())
        if u.path.startswith("/api/screens"):
            from .screens import extract_screens
            import os as _os
            rid = q.get("run", [None])[0]
            if not rid:
                return self._json({"error": "run query param is required"}, 400)
            c = store.connect()
            row = c.execute("select trace_path, app_pkg from runs where id=?",
                            (rid,)).fetchone()
            c.close()
            if not row or not row["trace_path"]:
                return self._json({"error": "no trace recorded for that run"}, 404)
            if not _os.path.exists(row["trace_path"]):
                return self._json({"error": f"trace file is gone: {row['trace_path']}"}, 404)
            try:
                return self._json(extract_screens(row["trace_path"]))
            except Exception as e:
                return self._json({"error": str(e)}, 500)
        if u.path == "/api/copilot/threads":
            tid = q.get("id", [None])[0]
            if tid:
                t = store.copilot_thread(int(tid))
                return self._json(t) if t else self._json({"error": "unknown thread"}, 404)
            return self._json({"threads": store.copilot_threads()})
        if u.path == "/api/copilot/pins":
            rid = q.get("run", [None])[0]
            return self._json({"pins": store.copilot_pins(int(rid) if rid else None)})
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
        if not os.path.isfile(os.path.join(DIST, "index.html")):
            return self._text("The dashboard is not built. Run `npm install && npm run build` in frontend/.", 503)
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
        if u.path == "/api/copilot/ask":
            return self._copilot_ask(payload)
        if u.path == "/api/copilot/pin":
            try:
                return self._json({"ok": True, "pin": store.copilot_pin(int(payload["message_id"]))})
            except (KeyError, ValueError, TypeError) as e:
                return self._json({"error": str(e)}, 400)
        if u.path == "/api/copilot/unpin":
            try:
                return self._json({"ok": bool(store.copilot_unpin(int(payload["id"])))})
            except (KeyError, ValueError, TypeError) as e:
                return self._json({"error": str(e)}, 400)
        if u.path == "/api/copilot/feedback":
            try:
                n = store.copilot_feedback(int(payload["message_id"]), payload.get("value"))
            except (KeyError, ValueError, TypeError) as e:
                return self._json({"error": str(e)}, 400)
            return self._json({"ok": bool(n)})
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
        if u.path == "/api/manual/start":
            from .capture import manual_start
            try:
                _live_reset()
                r = manual_start(pkg=(payload.get("pkg") or "com.swag.pay").strip(),
                                 cold=bool(payload.get("cold")))
            except RuntimeError as e:
                return self._json({"error": str(e)}, 409)
            return self._json({"ok": True, **r})
        if u.path == "/api/manual/stop":
            from . import jobs
            try:
                jid = jobs.start_manual_stop(label=payload.get("label"),
                                             app_pkg=payload.get("pkg"),
                                             use_llm=payload.get("use_llm", False))
            except RuntimeError as e:
                return self._json({"error": str(e)}, 409)
            return self._json({"ok": True, "job_id": jid})
        if u.path == "/api/manual/abort":
            from .capture import manual_abort
            return self._json({"ok": True, "discarded": manual_abort()})
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

    def _copilot_ask(self, payload):
        """Stream a Copilot answer as server-sent events.

        The question and the finished answer are saved to the thread, so it
        reopens as it was. A client that stops mid-stream simply stops
        receiving: nothing half-finished is saved as an answer.
        """
        from . import copilot
        from .screens import extract_screens
        text = (payload.get("text") or "").strip()
        if not text:
            return self._json({"error": "empty question"}, 400)
        tid = payload.get("thread_id") or store.copilot_thread_new(text)
        store.copilot_message_add(tid, "user", {"text": text, "context": payload.get("context") or []})
        self._sse_start()
        self._sse("thread", {"id": tid})
        blocks, final = [], {}
        alive = [True]

        def emit(kind, data):
            if not alive[0]:
                return
            if kind == "block":
                blocks.append(data)
            elif kind in ("done", "error"):
                final.update({"kind": kind, **data})
            alive[0] = self._sse(kind, data)

        services = {"stress_tests": lambda: [store.stress_get(t["id"]) for t in store.stress_list()],
                    "compare": store.compare, "extract_screens": extract_screens,
                    "trace_path": lambda r: r["trace_path"]}
        copilot.answer(text, history=_payload(), scope=payload.get("scope") or {},
                       chips=payload.get("context") or [], deep=bool(payload.get("deep")),
                       emit=emit, services=services)
        if alive[0] and final:
            mid = store.copilot_message_add(tid, "assistant", {"blocks": blocks, "result": final})
            self._sse("saved", {"message_id": mid})

    def log_message(self, *a):
        pass


def serve(port=8787):
    print(f"  swagperf dashboard -> http://127.0.0.1:{port}   (ctrl-c to stop)")
    # Jobs live in this process, so nothing can still be running at startup.
    stale = store.stress_mark_interrupted()
    if stale:
        print(f"  marked {stale} stress test(s) left running by a previous server as interrupted")
    # Threading server: a capture job can run for tens of seconds, and the
    # dashboard must keep polling /api/jobs and serving the page while it does.
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
