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


# The app version a run measured, read the way the dashboard's versionOf and
# versionKey read it (frontend/src/domain/versions.ts), so the top bar's
# Version filter, summaries and the trend view group runs identically.
NO_VERSION = "unknown"


def version_of(run, raw):
    """(version name, build): the merged app details' version_name (falling
    back to the run's own app_version column) and version_code. None where
    nothing recorded one."""
    app = merge(run, raw)["app"]
    code = app.get("version_code")
    return (app.get("version_name") or run.get("app_version") or None,
            code if code not in ("", None) else None)


def version_key(name, build):
    return NO_VERSION if name is None and build is None else f"{name or ''}|{'' if build is None else build}"


def version_label(name, build):
    if name and build is not None:
        return f"{name} (build {build})"
    if name:
        return name
    if build is not None:
        return f"build {build}"
    return "Version not recorded"
