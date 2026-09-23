"""Flashlight audits: an app's cold start measured by Flashlight, repeated.

Flashlight is a separate profiler with its own lane. It never runs on a device
while Perfetto records: the two share the kernel trace buffer, and Flashlight
starting breaks a Perfetto trace outright (docs/flashlight-perfetto-observations.html).
So an audit takes the same device lock as every capture (jobs.py), refuses
while a manual Perfetto session is recording, and resets atrace when it ends,
because Flashlight leaves its atrace settings behind.

Flashlight runs from the npm packages pinned in flashlight/package.json,
through its own test engine and report maths (flashlight/audit.js), so its
numbers mean what they mean in Flashlight's own report. The standalone
`flashlight` binary is not used: it is Intel-only and needs Rosetta on Apple
Silicon.
"""
import json, os, re, shutil, subprocess, threading

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RUNNER = os.path.join(ROOT, "flashlight")
SCRIPT = os.path.join(RUNNER, "audit.js")

ITERATION_RE = re.compile(r"iteration (\d+)/(\d+)", re.I)
# Flashlight's logger colours its lines and prefixes a clock time and an
# emoji; the job log has its own clock, so all three go, in that order.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_CLOCK = re.compile(r"^\[\d\d:\d\d:\d\d\]\s*")
# Not \w: the info emoji, U+2139, is a Unicode letter.
_SYMBOLS = re.compile(r"^[^A-Za-z0-9(]+")


def runner_status():
    """Whether audits can run on this machine, and why not when they can't."""
    if not shutil.which("node"):
        return {"ready": False, "reason": "Node.js is not installed. Flashlight audits need Node 18 or newer."}
    pkg = os.path.join(RUNNER, "node_modules", "@perf-profiler", "e2e", "package.json")
    if not os.path.exists(pkg):
        return {"ready": False, "reason": "Flashlight is not installed yet. Run: npm ci --prefix flashlight"}
    return {"ready": True, "version": json.load(open(pkg)).get("version")}


def clean_line(line):
    return _SYMBOLS.sub("", _CLOCK.sub("", _ANSI.sub("", line.strip()))).strip()


def summary_path(results_path):
    return re.sub(r"\.json$", "", results_path) + ".summary.json"


def run_audit(pkg, *, iterations, duration_ms, out_path, serial, title=None,
              on_line=None, on_progress=None):
    """Run the audit and return its summary (see flashlight/summary.js).

    `out_path` receives Flashlight's standard results file. A run in which
    some iterations failed still returns a summary, with `failure` set; only
    an audit that produced nothing at all raises.
    """
    status = runner_status()
    if not status["ready"]:
        raise RuntimeError(status["reason"])
    out = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    env = {**os.environ, "ANDROID_SERIAL": serial, "NODE_DISABLE_COLORS": "1", "FORCE_COLOR": "0"}
    p = subprocess.Popen(
        ["node", SCRIPT, "--bundle-id", pkg, "--iterations", str(int(iterations)),
         "--duration", str(int(duration_ms)), "--out", out,
         "--title", title or f"{pkg} cold start"],
        cwd=RUNNER, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1)
    # Each iteration is a force-stop, Flashlight's 3 s settle, a launch and the
    # measured window; retries can add two more. Past this, something hangs.
    budget_s = (int(iterations) + 2) * (int(duration_ms) / 1000 + 20) + 60
    timer = threading.Timer(budget_s, p.kill)
    timer.start()
    tail = []
    try:
        for raw in p.stdout:
            line = clean_line(raw)
            if not line:
                continue
            tail = (tail + [line])[-8:]
            if on_line:
                on_line(line)
            m = ITERATION_RE.search(line)
            if m and on_progress and line.lower().startswith("running"):
                on_progress(int(m.group(1)), int(m.group(2)))
        rc = p.wait()
    finally:
        timer.cancel()
    sp = summary_path(out)
    if not os.path.exists(sp):
        raise RuntimeError(f"Flashlight produced no results (exit {rc}). "
                           + (" / ".join(tail[-3:]) if tail else "No output."))
    return json.load(open(sp))


def reset_atrace(serial):
    """Undo what Flashlight leaves on the device: its profiler process and its
    atrace settings. Never while a Perfetto session records: `atrace
    --async_stop` would switch that session's kernel tracing off too."""
    from .capture import manual_status
    if manual_status(serial).get("recording"):
        return False
    subprocess.run(["adb", "-s", serial, "shell",
                    "pkill -f '[B]AMPerfProfiler'; atrace --async_stop >/dev/null 2>&1; true"],
                   capture_output=True, timeout=60)
    return True
