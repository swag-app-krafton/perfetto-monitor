"""One view of where a run was measured, from what was recorded about it.

A run's metadata has up to three sources, and they are merged in order of
trust: what adb read from the device at capture time (`capture`), what the
trace itself records (`from_trace`), and the run's own columns (the device
label, app version and git SHA passed on the command line). A field no
source recorded is left out rather than guessed, so the dashboard can say
"not recorded" instead of showing a made-up value.
"""


def merge(run, raw, app_name=None):
    cap = (raw or {}).get("capture") or {}
    tr = (raw or {}).get("from_trace") or {}

    device = {**(tr.get("device") or {}), **(cap.get("device") or {})}
    if run.get("device") and not device.get("model"):
        device["model"] = run["device"]

    app = {**(tr.get("app") or {}), **(cap.get("app") or {})}
    if run.get("app_pkg"):
        app.setdefault("package", run["app_pkg"])
    if app_name and app_name != app.get("package"):
        app["name"] = app_name
    if run.get("app_version") and not app.get("version_name"):
        app["version_name"] = run["app_version"]
    if run.get("git_sha"):
        app["git_sha"] = run["git_sha"]

    state = dict(cap.get("state") or {})
    trace = dict(tr.get("trace") or {})
    if state.get("perfetto_version") and not trace.get("perfetto_version"):
        trace["perfetto_version"] = state.pop("perfetto_version")
    state.pop("perfetto_version", None)
    if run.get("trace_path"):
        trace["path"] = run["trace_path"]

    return {
        "device": device,
        "app": app,
        "state": state,
        # The Mac a simulator run executed on: its CPU is the run's CPU.
        "host": dict(cap.get("host") or {}),
        "state_moment": cap.get("moment"),
        "trace": trace,
        "sources": [k for k in ("capture", "from_trace") if (raw or {}).get(k)],
        "trace_error": tr.get("error"),
    }
