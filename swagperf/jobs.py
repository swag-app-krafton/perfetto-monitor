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
# Android package names; iOS bundle ids are validated by backends.validate_id.
PKG_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$")

# adb only ever talks to one device coherently at a time from this tool, and a
# second concurrent `perfetto` session on the same device would corrupt both
# traces. One capture job at a time, enforced here rather than left to chance.
_capture_lock = threading.Lock()


def busy():
    """Whether a capture, stress test or Flashlight audit holds the device."""
    return _capture_lock.locked()


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


def _require_full_tracing(ex, trace_path):
    """Refuse a device trace whose kernel tracing did not cover it. It would
    otherwise become a run that looks fine and is missing most of its data.
    The file stays on disk, so what happened can still be looked at."""
    lost = ex.tracing_lost(trace_path)
    if lost:
        raise RuntimeError(f"not recorded: {lost} The trace is kept at {trace_path}.")


def _require_complete(cap, trace_path, instrumented=False):
    """_require_full_tracing for either platform: the backend says what makes
    one of its captures unusable (Android: kernel tracing lost; iOS: the
    recording never saw the app)."""
    problem = cap.verify(trace_path, instrumented=instrumented)
    if problem:
        raise RuntimeError(f"not recorded: {problem} The trace is kept at {trace_path}.")


def _platform_label(platform, info):
    return f"{'iOS' if platform == 'ios' else 'Android'} {info.get('release')}" + \
        (", Simulator" if info.get("simulator") else "")


def _trace_out(platform, name):
    """Where a capture's trace goes. iOS keeps its `.trace` bundle beside it."""
    return f"traces/ios/{name}.pftrace" if platform == "ios" else f"traces/{name}.pftrace"


def _capture_kw(platform, jid):
    """The iOS backend reports progress through the job log; adb's does not."""
    return {"on_log": lambda line: _log(jid, line)} if platform == "ios" else {}


def start_capture(pkg, *, cold=True, duration_ms=10000, label=None, ai_summary=False,
                  device=None, platform="android"):
    """Validate inputs, then run capture + extract + record on a background
    thread. Returns the job id immediately."""
    from . import backends
    backends.validate_id(platform, pkg)
    if platform == "ios" and not cold:
        raise ValueError("Warm captures are not supported on iOS yet. Capture cold.")
    duration_ms = max(2000, min(int(duration_ms), 120_000))
    jid = _new("capture", pkg=pkg, cold=bool(cold), duration_ms=duration_ms,
               platform=platform, ai_summary=bool(ai_summary))
    recorded = []

    def run():
        if not _capture_lock.acquire(blocking=False):
            _set(jid, state="error", error="Another capture is already running "
                 "on this device. Wait for it to finish and try again.")
            return
        try:
            _set(jid, state="running")
            from . import backends, extract as ex, store, catalogue
            cap = backends.get(platform)
            info = cap.device_info(device)
            if not info:
                raise RuntimeError(backends.NO_DEVICE[platform])
            _log(jid, f"device: {info.get('model')} ({_platform_label(platform, info)})")

            app = catalogue.get(pkg, platform)
            if not app:
                _log(jid, f"{pkg} is not in the catalogue yet; recording it as an "
                          "unlabelled competitor so this run is still attributable.")
                catalogue.add(pkg, name=pkg, role="competitor", auto=True, platform=platform)

            meta = _run_metadata(cap, pkg, device, "before capture")
            out = _trace_out(platform, f"{pkg}_{'cold' if cold else 'warm'}_{jid}")
            _log(jid, f"{'force-stopping and cold-launching' if cold else 'capturing warm'} "
                      f"{pkg} for {duration_ms}ms…")
            cap.capture(out, pkg=pkg, duration_ms=duration_ms, cold=cold, serial=device,
                        **_capture_kw(platform, jid))
            _log(jid, f"trace saved -> {out}")
            _require_complete(cap, out, instrumented=catalogue.is_instrumented(pkg, platform))

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
            recorded.append(rid)

            from .cli import _analyse_run
            _log(jid, "running analysis (rules)…")
            res, regs = _analyse_run(rid, m, use_llm=False)
            _log(jid, f"verdict: {res.get('verdict')} — {res.get('headline','')}")
            from . import pm
            _log(jid, pm.request_review())

            _set(jid, state="done",
                result={"run_id": rid, "path_kind": m["path_kind"],
                       "app_pkg": m.get("app_pkg"), "verdict": res.get("verdict"),
                       "headline": res.get("headline"),
                       "simulator": bool(m.get("simulator"))})
        except Exception as e:
            _log(jid, f"ERROR: {e}")
            _set(jid, state="error", error=str(e))
        finally:
            _capture_lock.release()
            _summarise_after(jid, recorded, ai_summary)

    threading.Thread(target=run, daemon=True).start()
    return jid


def start_stress(pkg, *, sessions=5, cold=True, duration_ms=8000, label=None,
                 settle_ms=1500, ai_summary=False, device=None, platform="android"):
    """Capture N cold-start sessions of one app back to back.

    A single cold start is a noisy measurement: the same app on the same device
    varies run to run with cache state, background work and thermal condition.
    Repeating it is the only way to tell a real regression from that noise, so
    this records each session as an ordinary run and groups them, reporting the
    spread rather than a single number.
    """
    from . import backends
    backends.validate_id(platform, pkg)
    if platform == "ios" and not cold:
        raise ValueError("Warm captures are not supported on iOS yet. Stress-test cold.")
    sessions = max(2, min(int(sessions), 30))
    duration_ms = max(2000, min(int(duration_ms), 60_000))
    jid = _new("stress", pkg=pkg, cold=bool(cold), duration_ms=duration_ms,
               sessions=sessions, platform=platform, ai_summary=bool(ai_summary))
    recorded = []

    def run():
        if not _capture_lock.acquire(blocking=False):
            _set(jid, state="error", error="Another capture is already running "
                 "on this device. Wait for it to finish and try again.")
            return
        stress_id = None
        try:
            _set(jid, state="running")
            from . import backends, extract as ex, store, catalogue
            cap = backends.get(platform)
            info = cap.device_info(device)
            if not info:
                raise RuntimeError(backends.NO_DEVICE[platform])
            dev_label = info.get("model") or info.get("device")
            if not catalogue.get(pkg, platform):
                catalogue.add(pkg, name=pkg, role="competitor", auto=True, platform=platform)

            stress_id = store.stress_create(
                app_pkg=pkg, device=dev_label, label=label, sessions=sessions,
                cold=cold, duration_ms=duration_ms, platform=platform)
            _set(jid, stress_id=stress_id)
            _log(jid, f"device: {info.get('model')} ({_platform_label(platform, info)})")
            _log(jid, f"stress test #{stress_id}: {sessions} "
                      f"{'cold' if cold else 'warm'} session(s) of {pkg}")

            ok = 0
            for i in range(1, sessions + 1):
                _log(jid, f"session {i}/{sessions}: capturing…")
                _set(jid, progress={"current": i, "total": sessions})
                out = _trace_out(platform, f"stress{stress_id}_{pkg}_{i:02d}")
                try:
                    # Per session: battery temperature and thermal state move
                    # over a run of back-to-back cold starts.
                    meta = _run_metadata(cap, pkg, device, "before capture")
                    cap.capture(out, pkg=pkg, duration_ms=duration_ms, cold=cold,
                                serial=device)
                    _require_complete(cap, out, instrumented=catalogue.is_instrumented(pkg, platform))
                    m = ex.extract_any(out, app_pkg=pkg)
                    problems = ex.capture_problems(m, requested_pkg=pkg)
                    fatal = [p for p in problems
                             if "own process" in p or "never came to the foreground" in p]
                    if fatal:
                        raise RuntimeError(fatal[0])
                    rid = store.record(
                        m, label=f"stress{stress_id}-s{i:02d}", device=dev_label,
                        trace_path=out, app_pkg=m.get("app_pkg"), meta=meta)
                    recorded.append(rid)
                    from .cli import _analyse_run
                    # Rules only, inside the loop: a model call here would put
                    # minutes between cold starts that should be back to back.
                    _analyse_run(rid, m, use_llm=False)
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
            # One review for the whole test, not one per session.
            from . import pm
            _log(jid, pm.request_review())
            _set(jid, state="done",
                 result={"stress_id": stress_id, "app_pkg": pkg,
                         "completed": ok, "failed": sessions - ok,
                         "stats": st.get("stats")})
        except Exception as e:
            _log(jid, f"ERROR: {e}")
            if stress_id:
                store.stress_finish(stress_id, state="error", error=str(e))
                # Sessions recorded before the failure are runs like any other.
                from . import pm
                _log(jid, pm.request_review())
            _set(jid, state="error", error=str(e))
        finally:
            _capture_lock.release()
            _summarise_after(jid, recorded, ai_summary)

    threading.Thread(target=run, daemon=True).start()
    return jid


def start_manual_stop(*, label=None, app_pkg=None, ai_summary=False, device=None):
    """Stop a manual session, then pull, extract and record it.

    Stopping is quick but pulling a long manual trace is not -- a ring buffer
    filled over several minutes can be hundreds of MB -- so this runs as a job
    like every other capture rather than blocking the request.
    """
    from . import capture as cap
    if not cap.manual_status(device)["recording"]:
        raise RuntimeError("No manual trace is recording.")
    jid = _new("manual_stop", pkg=app_pkg, ai_summary=bool(ai_summary))
    recorded = []

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
            _require_full_tracing(ex, out)

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

            recorded.append(rid)
            from .cli import _analyse_run
            res, _ = _analyse_run(rid, m, use_llm=False)
            _log(jid, f"verdict: {res.get('verdict')} — {res.get('headline','')}")
            from . import pm
            _log(jid, pm.request_review())
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
            _summarise_after(jid, recorded, ai_summary)

    threading.Thread(target=run, daemon=True).start()
    return jid


def start_audit(pkg, *, iterations=5, duration_ms=10000, label=None, device=None):
    """Measure an app's cold start with Flashlight, `iterations` times.

    Flashlight and Perfetto never share a device at once -- Flashlight
    starting breaks a Perfetto trace -- so an audit takes the same lock as
    every capture and refuses while a manual Perfetto session is recording.
    What it records is an audit, not a run: Flashlight's numbers, in their own
    table, never mixed into Perfetto's baselines.
    """
    if not PKG_RE.match(pkg or ""):
        raise ValueError(f"'{pkg}' does not look like an Android package name")
    iterations = max(2, min(int(iterations), 20))
    duration_ms = max(3000, min(int(duration_ms), 60_000))
    from . import flashlight
    ready = flashlight.runner_status()
    if not ready["ready"]:
        raise ValueError(ready["reason"])
    jid = _new("audit", pkg=pkg, iterations=iterations, duration_ms=duration_ms)

    def run():
        if not _capture_lock.acquire(blocking=False):
            _set(jid, state="error", error="A capture is already running on this device. "
                 "Wait for it to finish and try again.")
            return
        audit_id, serial = None, None
        from . import capture as cap, store, catalogue
        try:
            _set(jid, state="running")
            info = cap.device_info(device)
            if not info:
                raise RuntimeError("No adb device connected.")
            serial = info["serial"]
            if cap.manual_status(serial)["recording"]:
                raise RuntimeError("A Perfetto manual session is recording on this device, and "
                                   "Flashlight would break its trace. Stop the session first.")
            if not catalogue.get(pkg):
                catalogue.add(pkg, name=pkg, role="competitor", auto=True)
            _log(jid, f"device: {info.get('model')} (Android {info.get('release')})")

            meta = _run_metadata(cap, pkg, serial, "before audit")
            audit_id = store.audit_create(
                app_pkg=pkg, device=info.get("model") or info.get("device"), label=label,
                iterations=iterations, duration_ms=duration_ms, meta=meta)
            _set(jid, audit_id=audit_id)
            _log(jid, f"Flashlight audit A-{audit_id}: {iterations} cold starts of {pkg}, "
                      f"{duration_ms / 1000:g} s measured each")
            out = f"traces/flashlight/audit{audit_id}_{pkg}.json"
            summary = flashlight.run_audit(
                pkg, iterations=iterations, duration_ms=duration_ms, out_path=out,
                serial=serial, title=f"{pkg} cold start (A-{audit_id})",
                on_line=lambda line: _log(jid, line),
                on_progress=lambda i, n: _set(jid, progress={"current": i, "total": n}))

            ok = summary.get("successful") or 0
            # Some failed iterations are a note on a finished audit; none
            # succeeding is a failed one.
            store.audit_finish(audit_id, state="done" if ok else "error",
                               error=summary.get("failure"), results_path=out, summary=summary)
            if not ok:
                raise RuntimeError(summary.get("failure") or "no iteration succeeded")
            m = summary.get("metrics") or {}
            _log(jid, f"score {summary.get('score')} · CPU {m.get('cpu_pct')}% · RAM "
                      f"{m.get('ram_mb')} MB · {m.get('fps')} FPS, over {ok} of "
                      f"{summary.get('iterations_run')} iteration(s)")
            _set(jid, state="done",
                 result={"audit_id": audit_id, "app_pkg": pkg, "score": summary.get("score"),
                         "successful": ok, "failed": summary.get("failed")})
        except Exception as e:
            _log(jid, f"ERROR: {e}")
            if audit_id and (store.audit_get(audit_id) or {}).get("state") == "running":
                store.audit_finish(audit_id, state="error", error=str(e))
            _set(jid, state="error", error=str(e))
        finally:
            if serial:
                try:
                    if flashlight.reset_atrace(serial):
                        _log(jid, "atrace reset on the device")
                except Exception as e:
                    _log(jid, f"could not reset atrace: {e}")
            _capture_lock.release()

    threading.Thread(target=run, daemon=True).start()
    return jid


# ------------------------------------------------------------- AI summaries
# Run ids with a summary being written, so two requests can't write two at
# once (under _LOCK).
_summarising = set()
# How often a waiting summary job checks whether the device is free.
SUMMARY_WAIT_S = 1.0


def _summarise_after(jid, run_ids, wanted):
    """After a capture job has released the device: start the AI summaries
    its switch asked for, and link that job from the capture job."""
    if not (wanted and run_ids):
        return
    try:
        sid = start_summary(run_ids)
        _set(jid, summary_job=sid)
        _log(jid, f"writing the AI summary in job {sid}")
    except Exception as e:   # never let a summary fail the capture
        _log(jid, f"AI summary not started: {e}")


def start_summary(run_ids):
    """Write an AI summary for each run, one after another, on a background
    thread (F-023). Returns the job id immediately.

    It doesn't hold the capture lock: it touches no device. It waits while a
    capture holds it instead, because a model call during a capture competes
    for the machine a simulator run measures, and a capture's own timing
    shouldn't depend on it. A run already being summarised is refused."""
    ids = []
    for r in run_ids:
        r = int(r)
        if r not in ids:
            ids.append(r)
    if not ids:
        raise ValueError("no run to summarise")
    with _LOCK:
        taken = [r for r in ids if r in _summarising]
        if taken:
            raise RuntimeError(f"A summary of run #{taken[0]} is already being written.")
        _summarising.update(ids)
    jid = _new("summary", run_ids=ids)

    def run():
        written, failed = [], []
        try:
            _set(jid, state="running")
            from . import summary
            for i, rid in enumerate(ids, 1):
                _set(jid, progress={"current": i, "total": len(ids)})
                if busy():
                    _log(jid, "waiting for the capture on the device to finish…")
                    while busy():
                        time.sleep(SUMMARY_WAIT_S)
                _log(jid, f"run {rid}: writing the AI summary…")
                try:
                    res = summary.write(rid)
                except Exception as e:
                    failed.append({"run_id": rid, "error": str(e)})
                    _log(jid, f"run {rid}: FAILED: {e}")
                    continue
                if res is None:
                    failed.append({"run_id": rid, "error": summary.NO_MODEL})
                    _log(jid, f"run {rid}: {summary.NO_MODEL}")
                    continue
                written.append(rid)
                _log(jid, f"run {rid}: {res.get('headline', '')}")
            result = {"run_ids": ids, "written": written, "failed": failed}
            if written:
                _set(jid, state="done", result=result)
            else:
                _set(jid, state="error", result=result,
                     error=failed[0]["error"] if failed else "nothing was written")
        except Exception as e:
            _log(jid, f"ERROR: {e}")
            _set(jid, state="error", error=str(e), result={"run_ids": ids, "written": written,
                                                           "failed": failed})
        finally:
            with _LOCK:
                _summarising.difference_update(ids)

    threading.Thread(target=run, daemon=True).start()
    return jid


def summarising(run_id):
    """Whether a summary of this run is being written now."""
    with _LOCK:
        return int(run_id) in _summarising
