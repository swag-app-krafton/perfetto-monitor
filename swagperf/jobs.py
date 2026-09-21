"""In-process background job runner for dashboard-triggered captures.

A capture takes seconds to minutes (device force-stop, launch, trace duration,
pull), which is too long to hold an HTTP request open for. Jobs run on a
background thread; the server returns a job id immediately and the dashboard
polls for status. State lives in memory only -- it does not need to survive a
server restart, and a restart mid-capture just orphans that one job.
"""
import threading, time, uuid, re

_JOBS = {}
_LOCK = threading.Lock()
PKG_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$")

# adb only ever talks to one device coherently at a time from this tool, and a
# second concurrent `perfetto` session on the same device would corrupt both
# traces. One capture job at a time, enforced here rather than left to chance.
_capture_lock = threading.Lock()


def _new(kind, **meta):
    jid = uuid.uuid4().hex[:12]
    with _LOCK:
        _JOBS[jid] = {"id": jid, "kind": kind, "state": "queued", "log": [],
                     "started": time.time(), "result": None, "error": None, **meta}
    return jid


def _log(jid, line):
    with _LOCK:
        if jid in _JOBS:
            _JOBS[jid]["log"].append({"t": round(time.time() - _JOBS[jid]["started"], 1),
                                      "text": line})


def _set(jid, **kw):
    with _LOCK:
        if jid in _JOBS:
            _JOBS[jid].update(kw)


def get(jid):
    with _LOCK:
        j = _JOBS.get(jid)
        return dict(j) if j else None


def recent(limit=10):
    with _LOCK:
        return sorted(_JOBS.values(), key=lambda j: -j["started"])[:limit]


def start_capture(pkg, *, cold=True, duration_ms=10000, label=None, use_llm=False,
                  device=None):
    """Validate inputs, then run capture + extract + record on a background
    thread. Returns the job id immediately."""
    if not PKG_RE.match(pkg or ""):
        raise ValueError(f"'{pkg}' does not look like an Android package name")
    duration_ms = max(2000, min(int(duration_ms), 120_000))
    jid = _new("capture", pkg=pkg, cold=bool(cold), duration_ms=duration_ms)

    def run():
        if not _capture_lock.acquire(blocking=False):
            _set(jid, state="error", error="Another capture is already running "
                 "on this device. Wait for it to finish and try again.")
            return
        try:
            _set(jid, state="running")
            from . import capture as cap, extract as ex, store, catalogue
            info = cap.device_info(device)
            if not info:
                raise RuntimeError("No adb device connected.")
            _log(jid, f"device: {info.get('model')} (Android {info.get('release')})")

            app = catalogue.get(pkg)
            if not app:
                _log(jid, f"{pkg} is not in the catalogue yet; recording it as an "
                          "unlabelled competitor so this run is still attributable.")
                catalogue.add(pkg, name=pkg, role="competitor")

            out = f"traces/{pkg}_{'cold' if cold else 'warm'}_{jid}.pftrace"
            _log(jid, f"{'force-stopping and cold-launching' if cold else 'capturing warm'} "
                      f"{pkg} for {duration_ms}ms…")
            cap.capture(out, pkg=pkg, duration_ms=duration_ms, cold=cold, serial=device)
            _log(jid, f"trace saved -> {out}")

            _log(jid, "extracting metrics…")
            m = ex.extract_any(out, app_pkg=pkg)
            if not m.get("derived") and not m.get("steps"):
                raise RuntimeError(f"{pkg} is marked instrumented but no step: markers "
                                   "were found in this trace.")

            # A trace can pull and parse cleanly while containing nothing about
            # the target app -- a lock screen or biometric prompt can intercept
            # an adb launch so the app never reaches the foreground. Recording
            # that would present an empty capture as a flawless run.
            problems = ex.capture_problems(m, requested_pkg=pkg)
            fatal = [p for p in problems
                     if "own process" in p or "never came to the foreground" in p]
            for p in problems:
                _log(jid, ("FATAL: " if p in fatal else "warning: ") + p)
            if fatal:
                raise RuntimeError(
                    f"capture did not observe {pkg}. {fatal[0]} Common causes: the "
                    "app shows a lock screen or biometric prompt that an adb launch "
                    "cannot dismiss, or it blocks automated launches. Unlock the app "
                    "on the device, leave it in the foreground, and capture again "
                    "with cold turned off.")
            _set(jid, warnings=[p for p in problems if p not in fatal])

            dev_label = info.get("model") or info.get("device")
            rid = store.record(m, label=label or f"{'cold' if cold else 'warm'}-capture",
                               device=dev_label, trace_path=out, app_pkg=m.get("app_pkg"))
            _log(jid, f"recorded as run {rid} ({m['path_kind']})")

            from .cli import _analyse_run
            _log(jid, "running analysis (rules)" + (" + model" if use_llm else "") + "…")
            res, regs = _analyse_run(rid, m, use_llm=use_llm)
            _log(jid, f"verdict: {res.get('verdict')} — {res.get('headline','')}")

            _set(jid, state="done",
                result={"run_id": rid, "path_kind": m["path_kind"],
                       "app_pkg": m.get("app_pkg"), "verdict": res.get("verdict"),
                       "headline": res.get("headline")})
        except Exception as e:
            _log(jid, f"ERROR: {e}")
            _set(jid, state="error", error=str(e))
        finally:
            _capture_lock.release()

    threading.Thread(target=run, daemon=True).start()
    return jid
