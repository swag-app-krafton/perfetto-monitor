"""The PM agent's automatic run review.

When a run is recorded, `request_review()` checks what is new with the
deterministic triage (no model) and hands the tracker work to a background
runner. The runner is the only thing that writes to docs/ on its own:

* runs that raised nothing just move the tracker's "Runs reviewed through"
  marker, without starting a model;
* runs that raised a signal start the product-manager agent headlessly,
  through the user's own Claude Code session, which opens or updates issues
  for a developer to review.

Nothing is committed: new and updated issues show up in `git status`.

One review runs at a time. A run recorded while a review is in progress
leaves a `pending` flag and the runner goes round again before it exits, so
every run is reviewed and no two reviews edit the tracker at once. If the
agent fails, the marker stays put and the next review covers those runs too.

    python -m swagperf.pm run       the runner (started for you; safe to run by hand)
    python -m swagperf.pm status    is a review running, and what did the last one do
"""
import glob, os, signal, subprocess, sys
from datetime import datetime

from . import llm, triage

STATE = os.path.join(triage.ROOT, ".claude", "pm")
# The tracker follows this project's own run history and nothing else.
HISTORY_DB = os.path.join(triage.ROOT, "history.db")
TIMEOUT_S = 600
KEEP_LOGS = 20
# The agent is told to run exactly this; --allowedTools permits exactly this.
TRIAGE_CMD = ".venv/bin/python -m swagperf.cli triage"
ALLOWED_TOOLS = ["Read", "Grep", "Glob", "Edit", "Write",
                 f"Bash({TRIAGE_CMD}:*)", "Bash(git log:*)", "Bash(git show:*)", "Bash(git status:*)"]
PROMPT = ("Review new runs ({runs}). Run the triage, then open or update performance issues exactly as "
          "your instructions describe, and move the \"Runs reviewed through\" marker. This is an automatic "
          "review and nobody is watching: do not ask questions. Where a developer's input is needed, write "
          "the question into the issue.")


def enabled():
    return os.environ.get("SWAGPERF_PM_AUTOTRIAGE", "1").strip().lower() not in ("0", "false", "no", "off")


def _rel(p):
    return os.path.relpath(p, triage.ROOT)


def _triage(after):
    return triage.review(triage.load_history(after), after=after)


# ------------------------------------------------------------------ trigger

def request_review(reason="a run was recorded", *, tracker=None, state=None, triage_fn=None, spawn=None):
    """Called once a run is recorded. Returns one line for the job's log and
    never raises: a tracker problem must not fail the capture that triggered it."""
    try:
        return _request(tracker or triage.TRACKER, state or STATE, triage_fn or _triage, spawn or _spawn)
    except Exception as e:
        return f"PM review not started: {e}"


def _request(tracker, state, triage_fn, spawn):
    if not enabled():
        return "PM review is off (SWAGPERF_PM_AUTOTRIAGE=0)."
    from . import store
    if os.path.abspath(store.DB) != os.path.abspath(HISTORY_DB):
        # A test's temporary database, or SWAGPERF_DB pointing elsewhere. The
        # tracker's marker counts runs in history.db; reviewing another
        # database against it would reset the marker and misfile its issues.
        return f"PM review skipped: this run is in {store.DB}, not the project's history.db."
    after = triage.read_marker(tracker)
    if after is None:
        return f"PM review skipped: {_rel(tracker)} has no 'Runs reviewed through: #N' line."
    t = triage_fn(after)
    if t["through"] <= t["after"] and not t["actionable"]:
        return ("PM review: the run history was reset; reviews restart at run #1." if t["history_reset"]
                else "PM review: no runs since the last review.")
    if t["actionable"] and not llm.claude_bin():
        return (f"PM review skipped: {triage.summary_line(t)}, but the claude CLI is not installed. "
                "Ask the product-manager agent to review new runs by hand.")
    _flag(state, "pending")
    spawn(tracker, state)
    if t["actionable"]:
        return f"PM agent reviewing in the background: {triage.summary_line(t)}. Log in {_rel(os.path.join(state, 'logs'))}/"
    return f"PM review: {triage.summary_line(t)}; the tracker moves on to #{t['through']}."


def _spawn(tracker, state):
    """Start the runner detached, so it outlives a CLI capture that exits now."""
    env = dict(os.environ, SWAGPERF_PM_TRACKER=tracker, SWAGPERF_PM_STATE=state)
    subprocess.Popen([sys.executable, "-m", "swagperf.pm", "run"], cwd=triage.ROOT, env=env,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


# ------------------------------------------------------------------ runner

def run(tracker=None, state=None, *, triage_fn=None, claude=None, timeout=TIMEOUT_S):
    """Review until nothing is pending. Returns the passes made -- 0 when
    another runner holds the lock (it will see the pending flag)."""
    tracker, state = tracker or triage.TRACKER, state or STATE
    triage_fn = triage_fn or _triage
    passes = 0
    while True:
        if not _lock(state):
            return passes
        try:
            while _take(state, "pending"):
                _pass(tracker, state, triage_fn, claude or llm.claude_bin(), timeout)
                passes += 1
        finally:
            _unlock(state)
        # A trigger that set `pending` just before the unlock found the lock
        # held and left it to us: go round once more rather than strand it.
        if not os.path.exists(os.path.join(state, "pending")):
            return passes


def _pass(tracker, state, triage_fn, claude, timeout):
    after = triage.read_marker(tracker)
    if after is None:
        return
    t = triage_fn(after)
    # After `swagperf reset` the marker has to move back to the new history.
    # Not before the agent has run, though: it learns of the reset from the
    # marker being past the newest run, and notes it on the open issues.
    if not t["actionable"]:
        triage.write_marker(t["through"], tracker, force=t["history_reset"])
        return
    ids = [r["id"] for r in t["runs"]] or [t["through"]]
    runs = f"run #{ids[0]}" if len(ids) == 1 else f"runs #{ids[0]}–#{ids[-1]}"
    if t["history_reset"]:
        runs += ", after the run history was reset"
    log = _new_log(state, f"runs-{ids[0]}-{ids[-1]}")
    with open(log, "w") as fh:
        fh.write(f"{datetime.now().isoformat(timespec='seconds')}  review {runs}\n{triage.format_text(t)}\n\n")
        fh.flush()
        if not claude:
            fh.write("The claude CLI is not installed; nothing was changed.\n")
            return
        code = _agent(claude, PROMPT.format(runs=runs), fh, timeout)
        fh.write(f"\nexit {code}\n")
    # The agent moves the marker itself; this covers an agent that finished
    # its issues but not that last edit. A failed review leaves the marker, so
    # the next one picks these runs up again.
    if code == 0:
        triage.write_marker(t["through"], tracker, force=t["history_reset"])


def agent_command(claude):
    model = os.environ.get("SWAGPERF_PM_MODEL", "sonnet")
    return [claude, "-p", "--agent", "product-manager", "--model", model,
            "--permission-mode", "acceptEdits", "--allowedTools", *ALLOWED_TOOLS,
            "--strict-mcp-config", "--no-session-persistence", "--output-format", "text"]


def _agent(claude, prompt, fh, timeout):
    """Run the product-manager agent headlessly, output into `fh`."""
    p = subprocess.Popen(agent_command(claude), cwd=triage.ROOT, stdin=subprocess.PIPE, stdout=fh,
                         stderr=subprocess.STDOUT, text=True, start_new_session=True)
    try:
        p.communicate(prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGTERM)
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()
        fh.write(f"\nStopped after {timeout} s.\n")
        return 124
    return p.returncode


# ------------------------------------------------------------------ state files

def _flag(state, name):
    os.makedirs(state, exist_ok=True)
    open(os.path.join(state, name), "a").close()


def _take(state, name):
    """Remove a flag; True if it was set."""
    try:
        os.remove(os.path.join(state, name))
        return True
    except FileNotFoundError:
        return False


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _lock(state):
    os.makedirs(state, exist_ok=True)
    path = os.path.join(state, "lock")
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                with open(path) as fh:
                    pid = int(fh.read().strip() or 0)
            except (OSError, ValueError):
                pid = 0
            if pid and _alive(pid):
                return False
            _take(state, "lock")  # its runner died without unlocking
            continue
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    return False


def _unlock(state):
    _take(state, "lock")


def _new_log(state, tag):
    d = os.path.join(state, "logs")
    os.makedirs(d, exist_ok=True)
    for old in sorted(glob.glob(os.path.join(d, "*.log")))[:-(KEEP_LOGS - 1)]:
        os.remove(old)
    return os.path.join(d, f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{tag}.log")


def status(state=None):
    state = state or STATE
    lock = os.path.join(state, "lock")
    running = os.path.exists(lock)
    logs = sorted(glob.glob(os.path.join(state, "logs", "*.log")))
    lines = [f"automatic review: {'on' if enabled() else 'off (SWAGPERF_PM_AUTOTRIAGE=0)'}",
             f"claude CLI: {llm.claude_bin() or 'not found'}",
             f"reviewed through: #{triage.read_marker()}",
             f"review running: {'yes' if running else 'no'}"
             + (" (more runs pending)" if os.path.exists(os.path.join(state, "pending")) else "")]
    if logs:
        lines.append(f"last review log: {_rel(logs[-1])}")
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "status"
    if cmd == "run":
        run(os.environ.get("SWAGPERF_PM_TRACKER"), os.environ.get("SWAGPERF_PM_STATE"))
        return 0
    if cmd == "status":
        print(status())
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
