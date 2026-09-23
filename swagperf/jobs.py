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


def _run_metadata(cap, pkg, device, moment):
    """Device, device state and app version to record with a run. Never fails
    the capture: a device that answers nothing just leaves the run without."""
    try:
        meta = cap.run_metadata(pkg, device)
    except Exception:
        return None
    return {**meta, "moment": moment} if meta else None


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
                catalogue.add(pkg, name=pkg, role="competitor", auto=True)

            meta = _run_metadata(cap, pkg, device, "before capture")
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
                               device=dev_label, trace_path=out, app_pkg=m.get("app_pkg"), meta=meta)
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


def start_stress(pkg, *, sessions=5, cold=True, duration_ms=8000, label=None,
                 settle_ms=1500, use_llm=False, device=None):
    """Capture N cold-start sessions of one app back to back.

    A single cold start is a noisy measurement: the same app on the same device
    varies run to run with cache state, background work and thermal condition.
    Repeating it is the only way to tell a real regression from that noise, so
    this records each session as an ordinary run and groups them, reporting the
    spread rather than a single number.
    """
    if not PKG_RE.match(pkg or ""):
        raise ValueError(f"'{pkg}' does not look like an Android package name")
    sessions = max(2, min(int(sessions), 30))
    duration_ms = max(2000, min(int(duration_ms), 60_000))
    jid = _new("stress", pkg=pkg, cold=bool(cold), duration_ms=duration_ms,
               sessions=sessions)

    def run():
        if not _capture_lock.acquire(blocking=False):
            _set(jid, state="error", error="Another capture is already running "
                 "on this device. Wait for it to finish and try again.")
            return
        stress_id = None
        try:
            _set(jid, state="running")
            from . import capture as cap, extract as ex, store, catalogue
            info = cap.device_info(device)
            if not info:
                raise RuntimeError("No adb device connected.")
            dev_label = info.get("model") or info.get("device")
            if not catalogue.get(pkg):
                catalogue.add(pkg, name=pkg, role="competitor", auto=True)

            stress_id = store.stress_create(
                app_pkg=pkg, device=dev_label, label=label, sessions=sessions,
                cold=cold, duration_ms=duration_ms)
            _set(jid, stress_id=stress_id)
            _log(jid, f"device: {info.get('model')} (Android {info.get('release')})")
            _log(jid, f"stress test #{stress_id}: {sessions} "
                      f"{'cold' if cold else 'warm'} session(s) of {pkg}")

            ok = 0
            for i in range(1, sessions + 1):
                _log(jid, f"session {i}/{sessions}: capturing…")
                _set(jid, progress={"current": i, "total": sessions})
                out = f"traces/stress{stress_id}_{pkg}_{i:02d}.pftrace"
                try:
                    # Per session: battery temperature and thermal state move
                    # over a run of back-to-back cold starts.
                    meta = _run_metadata(cap, pkg, device, "before capture")
                    cap.capture(out, pkg=pkg, duration_ms=duration_ms, cold=cold,
                                serial=device)
                    m = ex.extract_any(out, app_pkg=pkg)
                    problems = ex.capture_problems(m, requested_pkg=pkg)
                    fatal = [p for p in problems
                             if "own process" in p or "never came to the foreground" in p]
                    if fatal:
                        raise RuntimeError(fatal[0])
                    rid = store.record(
                        m, label=f"stress{stress_id}-s{i:02d}", device=dev_label,
                        trace_path=out, app_pkg=m.get("app_pkg"), meta=meta)
                    from .cli import _analyse_run
                    _analyse_run(rid, m, use_llm=use_llm)
                    ttid = m["startup"]["time_to_first_camera_frame_ms"]
                    store.stress_session_done(stress_id, i, run_id=rid, ttid_ms=ttid)
                    ok += 1
                    _log(jid, f"session {i}: run {rid}, startup {ttid}ms")
                except Exception as se:
                    # One bad session does not end the test -- a stress test with
                    # a couple of failures is still informative, and stopping
                    # would discard the sessions already captured.
                    store.stress_session_done(stress_id, i, state="error", error=str(se))
                    _log(jid, f"session {i} FAILED: {se}")
                if i < sessions:
                    time.sleep(settle_ms / 1000)

            if ok == 0:
                store.stress_finish(stress_id, state="error",
                                    error="every session failed to observe the app")
                raise RuntimeError(
                    f"all {sessions} sessions failed to observe {pkg}. The app may "
                    "show a lock or biometric prompt that an adb launch cannot "
                    "dismiss, or block automated launches.")

            store.stress_finish(stress_id, state="done")
            st = store.stress_get(stress_id)
            s = (st.get("stats") or {}).get("ttid_ms") or {}
            if s:
                _log(jid, f"startup across {s['n']} session(s): median {s['median']}ms, "
                          f"min {s['min']}ms, max {s['max']}ms, spread {s.get('spread_pct')}%")
            _set(jid, state="done",
                 result={"stress_id": stress_id, "app_pkg": pkg,
                         "completed": ok, "failed": sessions - ok,
                         "stats": st.get("stats")})
        except Exception as e:
            _log(jid, f"ERROR: {e}")
            if stress_id:
                store.stress_finish(stress_id, state="error", error=str(e))
            _set(jid, state="error", error=str(e))
        finally:
            _capture_lock.release()

    threading.Thread(target=run, daemon=True).start()
    return jid


def start_manual_stop(*, label=None, app_pkg=None, use_llm=False, device=None):
    """Stop a manual session, then pull, extract and record it.

    Stopping is quick but pulling a long manual trace is not -- a ring buffer
    filled over several minutes can be hundreds of MB -- so this runs as a job
    like every other capture rather than blocking the request.
    """
    from . import capture as cap
    if not cap.manual_status(device)["recording"]:
        raise RuntimeError("No manual trace is recording.")
    jid = _new("manual_stop", pkg=app_pkg)

    def run():
        if not _capture_lock.acquire(blocking=False):
            _set(jid, state="error", error="Another capture is running; try again shortly.")
            return
        try:
            _set(jid, state="running")
            from . import extract as ex, store, catalogue
            info = cap.device_info(device)
            out = f"traces/manual_{jid}.pftrace"
            _log(jid, "stopping the detached session and pulling the trace…")
            cap.manual_stop(out, serial=device)
            _log(jid, f"trace saved -> {out}")

            _log(jid, "extracting metrics…")
            m = ex.extract_any(out, app_pkg=app_pkg)
            pkg = m.get("app_pkg") or app_pkg
            if pkg and not catalogue.get(pkg):
                catalogue.add(pkg, name=pkg, role="competitor", auto=True)

            # A manual session is driven by hand, so it legitimately may contain
            # no launch at all -- the user may have traced an already-open app.
            # Missing startup is therefore reported, not treated as a failure.
            problems = ex.capture_problems(m, requested_pkg=pkg)
            for p in problems:
                _log(jid, "note: " + p)

            meta = _run_metadata(cap, pkg, device, "end of session")
            rid = store.record(m, label=label or "manual-session",
                               device=info.get("model") or info.get("device"),
                               trace_path=out, app_pkg=pkg, meta=meta)
            _log(jid, f"recorded as run {rid}")

            screens = None
            try:
                from .screens import extract_screens
                screens = extract_screens(out)
                if screens.get("instrumented"):
                    _log(jid, f"screen markers found: {len(screens['screens'])} visit(s), "
                              f"{len(screens['actions'])} action type(s)")
                else:
                    _log(jid, "no SwagTrace screen markers in this trace")
            except Exception as se:
                _log(jid, f"screen extraction skipped: {se}")

            from .cli import _analyse_run
            res, _ = _analyse_run(rid, m, use_llm=use_llm)
            _log(jid, f"verdict: {res.get('verdict')} — {res.get('headline','')}")
            _set(jid, state="done",
                 result={"run_id": rid, "app_pkg": pkg, "verdict": res.get("verdict"),
                         "headline": res.get("headline"),
                         "path_kind": m.get("path_kind"),
                         "screens": (len(screens["screens"])
                                     if screens and screens.get("instrumented") else 0)})
        except Exception as e:
            _log(jid, f"ERROR: {e}")
            _set(jid, state="error", error=str(e))
        finally:
            _capture_lock.release()

    threading.Thread(target=run, daemon=True).start()
    return jid
