"""Phase 0: does Flashlight's sampler damage a Perfetto trace recorded at the same time?

    ./.venv/bin/python experiments/flashlight-concurrency/run.py --pkg com.swag.pay

Four modes, interleaved across repetitions so that thermal drift does not line
up with any one of them:

  perfetto_only             control for the trace
  perfetto_then_flashlight  Flashlight's sampler runs for the middle window only
  flashlight_then_perfetto  the sampler is already running when Perfetto starts
  flashlight_only           control for Flashlight's own numbers

Every mode drives the same workload: bottom-tab taps at a steady pace, in three
windows. The tap loop runs on the device and logs the boot-clock time of every
tap -- the clock the trace uses -- so the number of screen markers each window
should hold is known exactly. The device's tracing state (tracing_on, the
atrace tag and app properties, which profiler processes are alive) is recorded
at every boundary, so a damaged trace can be explained and not only observed.

Perfetto is started through swagperf's own manual-session code, so this tests
the session the dashboard and CLI really use.

Output goes to experiments/flashlight-concurrency/results/<timestamp>/: per run
a trace, a sampler log and a run log. analyse.py reads that directory.
"""
import argparse, json, os, re, signal, subprocess, sys, time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
from swagperf import capture as cap  # noqa: E402

MODES = ["perfetto_only", "perfetto_then_flashlight", "flashlight_then_perfetto", "flashlight_only"]
WINDOWS = ["W1", "W2", "W3"]
# The app opens on Home, so this order changes tab on every tap.
TABS = ["store", "rewards", "history", "home"]
PROFILER_PATH = "/data/local/tmp/BAMPerfProfiler"


def adb(serial, *args, timeout=60):
    return subprocess.run(["adb", "-s", serial, *args], capture_output=True, text=True,
                          timeout=timeout).stdout


class Clock:
    """Reads of the device's boot clock, each paired with the host time around
    it. The sampler logs host time; these pairs convert it to trace time."""

    def __init__(self, serial):
        self.serial, self.samples = serial, []

    def now(self):
        t0 = time.time()
        boot = float(adb(self.serial, "shell", "cut -d' ' -f1 /proc/uptime").split()[0])
        t1 = time.time()
        self.samples.append({"boot_s": boot, "host_s": round((t0 + t1) / 2, 3),
                             "rtt_ms": round((t1 - t0) * 1000, 1)})
        return boot


STATE_SH = r"""
T=/sys/kernel/tracing; [ -r $T/tracing_on ] || T=/sys/kernel/debug/tracing
echo "tracing_on=$(cat $T/tracing_on 2>/dev/null)"
echo "sched_switch_enabled=$(cat $T/events/sched/sched_switch/enable 2>/dev/null)"
echo "buffer_kb=$(cat $T/buffer_size_kb 2>/dev/null)"
echo "atrace_tags=$(getprop debug.atrace.tags.enableflags)"
echo "atrace_app_number=$(getprop debug.atrace.app_number)"
echo "atrace_app_0=$(getprop debug.atrace.app_0)"
echo "perfetto_session=$(perfetto --is_detached=swagperf_manual >/dev/null 2>&1 && echo yes || echo no)"
echo "profiler_procs=$(pgrep -f '[B]AMPerfProfiler' | wc -l)"
echo "atrace_procs=$(pgrep -x atrace | wc -l)"
echo "boot_s=$(cut -d' ' -f1 /proc/uptime)"
"""


def tracing_state(serial, label):
    """The device's tracing configuration at one instant. Fields the shell user
    cannot read on this device come back empty rather than failing the run."""
    out = {"label": label}
    for line in adb(serial, "shell", STATE_SH).splitlines():
        k, sep, v = line.partition("=")
        if sep:
            out[k.strip()] = v.strip()
    return out


def reset_tracing(serial):
    """Kill anything Flashlight left behind and switch atrace off. Only ever
    called when no Perfetto session is recording: `atrace --async_stop` is
    exactly the kind of command this experiment suspects of breaking one."""
    if cap.manual_status(serial)["recording"]:
        raise RuntimeError("refusing to reset tracing while a Perfetto session is recording")
    adb(serial, "shell", "pkill -f '[B]AMPerfProfiler'; pkill -x atrace; "
                         "atrace --async_stop >/dev/null 2>&1; true", timeout=60)


def _attr(node, name):
    m = re.search(rf' {name}="([^"]*)"', node)
    return m.group(1) if m else ""


def find_tabs(serial, pkg):
    """Bottom-tab tap targets, read from the app's own view hierarchy.

    Only the app's nodes are considered: on the Vivo, a bare "home" also
    matches the system navigation bar's Home key, which would leave the app.
    """
    dump = adb(serial, "shell", "uiautomator dump /sdcard/flc_ui.xml", timeout=40)
    xml = adb(serial, "shell", "cat /sdcard/flc_ui.xml")
    adb(serial, "shell", "rm -f /sdcard/flc_ui.xml")
    if "<hierarchy" not in xml:
        # Home runs a live camera preview, and uiautomator can refuse a screen
        # that never goes idle ("could not get idle state").
        raise RuntimeError(f"uiautomator could not read the screen ({dump.strip()[:120]}). "
                           "Pass the tab positions with --tap-coords 'x,y x,y x,y x,y' in the "
                           "order " + ", ".join(TABS))
    found = {}
    for m in re.finditer(r"<node [^>]*>", xml):
        node = m.group(0)
        if _attr(node, "package") != pkg:
            continue
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
        if not b:
            continue
        x1, y1, x2, y2 = map(int, b.groups())
        names = {_attr(node, "text").strip().lower(), _attr(node, "content-desc").strip().lower()}
        for tab in TABS:
            if tab in names and (tab not in found or (y1 + y2) // 2 > found[tab][1]):
                found[tab] = ((x1 + x2) // 2, (y1 + y2) // 2)
    missing = [t for t in TABS if t not in found]
    if missing:
        raise RuntimeError(f"could not find the {', '.join(missing)} tab(s) on screen. Leave "
                           "the app on Home, or pass --taps 'x,y x,y x,y x,y' in the order "
                           + ", ".join(TABS))
    return [found[t] for t in TABS]


def tap_window(serial, coords, taps, pace_s, first):
    """Tap `taps` times through the tabs, looping on the device so no host
    round trip sits between taps. Returns each tap's boot-clock time."""
    seq = [coords[(first + i) % len(coords)] for i in range(taps)]
    script = "; ".join(f"input tap {x} {y}; echo tap $(cut -d' ' -f1 /proc/uptime); sleep {pace_s}"
                       for x, y in seq)
    out = adb(serial, "shell", script, timeout=int(taps * (pace_s + 5)) + 30)
    return [float(l.split()[1]) for l in out.splitlines() if l.startswith("tap ")]


class Sampler:
    """sampler.js as a child process, logging to a JSONL file."""

    def __init__(self, serial, pkg, path):
        self.path = path
        self._out = open(path + ".out", "w")
        self.p = subprocess.Popen(["node", os.path.join(HERE, "sampler.js"), pkg, path],
                                  cwd=HERE, env={**os.environ, "ANDROID_SERIAL": serial},
                                  stdout=self._out, stderr=subprocess.STDOUT)

    def events(self):
        try:
            lines = open(self.path).read().splitlines()
        except FileNotFoundError:
            return []
        out = []
        for l in lines:
            try:
                out.append(json.loads(l))
            except json.JSONDecodeError:
                pass  # the line being written right now
        return out

    def wait_for(self, event, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if any(e.get("event") == event for e in self.events()):
                return True
            if self.p.poll() is not None:
                return False
            time.sleep(0.25)
        return False

    def stop(self, timeout=15):
        if self.p.poll() is None:
            self.p.send_signal(signal.SIGINT)
            try:
                self.p.wait(timeout)
            except subprocess.TimeoutExpired:
                self.p.kill()
                self.p.wait()
        self._out.close()


def run_one(a, serial, coords, mode, rep, outdir):
    tag = f"r{rep}_{mode}"
    trace_path = os.path.join(outdir, tag + ".pftrace")
    clock = Clock(serial)
    log = {"mode": mode, "rep": rep, "pkg": a.pkg, "serial": serial, "windows": [],
           "states": [], "sampler_marks": {}, "notes": [], "error": None}
    sampler, recording = None, False

    def state(label):
        log["states"].append(tracing_state(serial, label))

    def start_sampler():
        nonlocal sampler
        log["sampler_marks"]["launched"] = clock.now()
        sampler = Sampler(serial, a.pkg, os.path.join(outdir, tag + ".sampler.jsonl"))
        log["sampler_log"] = os.path.basename(sampler.path)
        if sampler.wait_for("measuring", 45):
            log["sampler_marks"]["measuring"] = clock.now()
        else:
            log["notes"].append("the sampler never started measuring; see "
                                + os.path.basename(sampler.path) + ".out")

    def stop_sampler():
        log["sampler_marks"]["stop"] = clock.now()
        sampler.stop()
        log["sampler_marks"]["stopped"] = clock.now()

    try:
        reset_tracing(serial)
        cap.force_stop(a.pkg, serial)
        time.sleep(1)
        cap.launch(a.pkg, serial)
        time.sleep(a.settle_s)
        state("ready")

        if mode in ("flashlight_then_perfetto", "flashlight_only"):
            start_sampler()
            state("sampler_running")
        if mode != "flashlight_only":
            log["perfetto_start"] = clock.now()
            try:
                cap.manual_start(pkg=a.pkg, serial=serial, cold=False)
                recording = True
            except RuntimeError as e:
                # Perfetto refusing to start next to Flashlight is a result,
                # not a harness failure.
                log["notes"].append(f"perfetto failed to start: {e}")
            time.sleep(2)  # let the data sources come up before measuring
            state("perfetto_running")

        first = 0
        for w in WINDOWS:
            if mode == "perfetto_then_flashlight" and w == "W2":
                start_sampler()
                state("sampler_running")
            start = clock.now()
            taps = tap_window(serial, coords, a.taps, a.pace_s, first)
            end = clock.now()
            first += len(taps)
            log["windows"].append({"name": w, "start_boot_s": start, "end_boot_s": end,
                                   "taps_boot_s": taps})
            if mode == "perfetto_then_flashlight" and w == "W2":
                stop_sampler()
                state("sampler_stopped")

        if recording:
            log["perfetto_stop"] = clock.now()
            cap.manual_stop(trace_path, serial=serial)
            recording = False
            log["trace"] = os.path.basename(trace_path)
            state("perfetto_stopped")
        if sampler and sampler.p.poll() is None:
            stop_sampler()
            state("sampler_stopped")
    except Exception as e:
        log["error"] = f"{type(e).__name__}: {e}"
    finally:
        if sampler:
            sampler.stop()
        if recording:
            # A run that failed midway must not leave the phone recording.
            cap.manual_abort(serial)
        try:
            reset_tracing(serial)
        except Exception as e:
            log["notes"].append(f"cleanup: {e}")
        log["clock"] = clock.samples
        with open(os.path.join(outdir, tag + ".run.json"), "w") as f:
            json.dump(log, f, indent=1)
    return log


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pkg", default="com.swag.pay")
    ap.add_argument("--serial", help="device to use (default: the only one connected)")
    ap.add_argument("--reps", type=int, default=3, help="repetitions of each mode")
    ap.add_argument("--taps", type=int, default=10, help="taps per window")
    ap.add_argument("--pace-s", type=float, default=1.0, help="pause after each tap")
    ap.add_argument("--settle-s", type=float, default=8.0, help="wait after launching the app")
    ap.add_argument("--gap-s", type=float, default=5.0, help="pause between runs")
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--tap-coords", help="'x,y x,y x,y x,y' for " + ", ".join(TABS))
    ap.add_argument("--keep-profiler", action="store_true",
                    help="leave Flashlight's profiler binary on the device afterwards")
    a = ap.parse_args(argv)

    devs = cap.devices()
    serial = a.serial or (devs[0] if len(devs) == 1 else None)
    if not serial or serial not in devs:
        sys.exit(f"need exactly one connected device, or --serial (connected: {devs or 'none'})")
    if not os.path.isdir(os.path.join(HERE, "node_modules", "@perf-profiler")):
        sys.exit("Flashlight is not installed here. Run: npm ci --prefix experiments/flashlight-concurrency")
    if not adb(serial, "shell", f"pm path {a.pkg}").strip():
        sys.exit(f"{a.pkg} is not installed on {serial}")
    if cap.manual_status(serial)["recording"]:
        sys.exit("A swagperf manual session is recording on this device. Stop it first: "
                 "this experiment starts and stops that same session.")
    modes = [m for m in a.modes.split(",") if m]
    bad = [m for m in modes if m not in MODES]
    if bad:
        sys.exit(f"unknown mode(s) {bad}; choose from {MODES}")

    outdir = os.path.join(HERE, "results", datetime.now().strftime("%Y%m%d-%H%M%S"))
    os.makedirs(outdir)

    if a.tap_coords:
        coords = [tuple(int(v) for v in xy.split(",")) for xy in a.tap_coords.split()]
    else:
        cap.force_stop(a.pkg, serial)
        cap.launch(a.pkg, serial)
        time.sleep(a.settle_s)
        coords = find_tabs(serial, a.pkg)

    meta = getattr(cap, "run_metadata", None)
    session = {"started": datetime.now().isoformat(timespec="seconds"), "args": vars(a),
               "serial": serial, "tabs": dict(zip(TABS, coords)), "modes": modes,
               "flashlight": json.load(open(os.path.join(
                   HERE, "node_modules", "@perf-profiler", "profiler", "package.json")))["version"],
               "device": meta(a.pkg, serial) if meta else cap.device_info(serial)}
    json.dump(session, open(os.path.join(outdir, "session.json"), "w"), indent=1)

    total = a.reps * len(modes)
    print(f"  {serial}: {total} runs, results -> {os.path.relpath(outdir, ROOT)}")
    n = 0
    try:
        for rep in range(1, a.reps + 1):
            # Rotate the order each repetition so no mode always runs first
            # (coolest phone) or last (warmest).
            k = (rep - 1) % len(modes)
            for mode in modes[k:] + modes[:k]:
                n += 1
                t0 = time.time()
                log = run_one(a, serial, coords, mode, rep, outdir)
                status = log["error"] or "; ".join(log["notes"]) or "ok"
                print(f"  [{n:>2}/{total}] rep {rep} {mode:<26} {time.time() - t0:5.0f}s  {status}")
                time.sleep(a.gap_s)
    finally:
        if not a.keep_profiler:
            adb(serial, "shell", f"rm -f {PROFILER_PATH}")
    print(f"\n  analyse: ./.venv/bin/python experiments/flashlight-concurrency/analyse.py "
          f"{os.path.relpath(outdir, ROOT)}")


if __name__ == "__main__":
    main()
