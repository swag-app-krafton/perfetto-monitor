"""iOS capture: the Simulator today, through simctl and xctrace.

The same surface as capture.py (devices, device_info, run_metadata,
other_profilers, installed_packages, capture, verify), so jobs.py drives
either platform the same way. Analysis never depends on this module.

A capture records the app with xctrace (see xctrace.INSTRUMENTS), exports the
tables it needs and converts them into a Perfetto trace (convert_ios.py), so
everything downstream reads an iOS run exactly as it reads an Android one.
The `.trace` bundle is kept next to it for Instruments.

Simulator numbers come from the Mac's CPU with a warm page cache: they are
good for comparing one simulator run with another and for checking the
pipeline, never for judging the app against its budgets (extract.py and
store.py enforce that). A physical iPhone is a later phase (devicectl).
"""
import ctypes, ctypes.util, json, os, plistlib, re, subprocess, tempfile, threading, time
from datetime import datetime, timezone

from . import xctrace as xt

PLATFORM = "ios"

# Captures that run longer than this are cut: a cold start plus a few seconds
# of settling is what the lane measures today.
DEFAULT_DURATION_MS = 12_000


def _run(cmd, timeout=30):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except (subprocess.SubprocessError, OSError) as e:
        return 1, "", str(e)


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ devices

def parse_simctl_devices(text):
    """`simctl list devices --json` -> one dict per available simulator."""
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return []
    out = []
    for runtime, devs in (data.get("devices") or {}).items():
        # com.apple.CoreSimulator.SimRuntime.iOS-27-0 -> ("iOS", "27.0")
        m = re.search(r"SimRuntime\.([A-Za-z]+)-([\d-]+)$", runtime)
        os_name, os_version = (m.group(1), m.group(2).replace("-", ".")) if m else (None, None)
        if os_name and os_name != "iOS":
            continue
        for d in devs:
            if not d.get("isAvailable", True):
                continue
            out.append({"udid": d.get("udid"), "name": d.get("name"),
                        "state": d.get("state"), "os_version": os_version,
                        "device_type": (d.get("deviceTypeIdentifier") or "").rsplit(".", 1)[-1] or None,
                        "simulator": True})
    return out


def simulators():
    code, out, _ = _run(["xcrun", "simctl", "list", "devices", "--json"])
    return parse_simctl_devices(out) if code == 0 else []


def devices():
    """Booted simulators' UDIDs, the iOS counterpart of adb serials."""
    return [d["udid"] for d in simulators() if d.get("state") == "Booted"]


def resolve_device(device=None):
    """A booted simulator by UDID or name; the first booted one by default."""
    sims = simulators()
    if device:
        for d in sims:
            if device in (d["udid"], d["name"]):
                return d
        return None
    booted = [d for d in sims if d.get("state") == "Booted"]
    return booted[0] if booted else None


def device_info(device=None):
    d = resolve_device(device)
    if not d or d.get("state") != "Booted":
        return {}
    return {"udid": d["udid"], "model": d["name"], "device": d["name"],
            "release": d["os_version"], "os_version": d["os_version"],
            "platform": PLATFORM, "simulator": True}


def boot(device):
    """Boot a simulator (by UDID or name) if it is not running yet."""
    d = resolve_device(device)
    if not d:
        raise RuntimeError(f"no simulator named {device!r}. List them with: xcrun simctl list devices")
    if d.get("state") != "Booted":
        code, _, err = _run(["xcrun", "simctl", "boot", d["udid"]], timeout=120)
        if code != 0 and "current state: Booted" not in err:
            raise RuntimeError(f"could not boot {d['name']}: {err.strip()[:200]}")
    return d["udid"]


# --------------------------------------------------------------------- apps

def parse_listapps(plist_json):
    """`simctl listapps` (converted to JSON by plutil) -> user apps by bundle id."""
    try:
        data = json.loads(plist_json or "{}")
    except ValueError:
        return {}
    return {k: v for k, v in data.items() if v.get("ApplicationType") == "User"}


def installed_packages(serial=None):
    """Bundle ids of the user apps installed on the simulator."""
    udid = serial or (devices() or [None])[0]
    if not udid:
        return []
    try:
        raw = subprocess.run(["xcrun", "simctl", "listapps", udid], capture_output=True,
                             timeout=30).stdout
        js = subprocess.run(["plutil", "-convert", "json", "-o", "-", "-"], input=raw,
                            capture_output=True, timeout=30).stdout.decode()
    except (subprocess.SubprocessError, OSError):
        return []
    return sorted(parse_listapps(js))


def app_path(udid, bundle):
    code, out, err = _run(["xcrun", "simctl", "get_app_container", udid, bundle, "app"])
    if code != 0 or not out.strip():
        raise RuntimeError(f"{bundle} is not installed on this simulator. Build and install "
                           f"it first (xcrun simctl install {udid} <path to .app>).")
    return out.strip()


# The first bytes of a Hermes bytecode bundle. A Release build ships its JS as
# main.jsbundle; a Debug build has none and loads JS from Metro at launch,
# which is a different app to measure.
HBC_MAGIC = bytes.fromhex("c61fbc03c103191f")


def parse_app_bundle(path):
    """Version, build and JS bundle of an installed `.app`."""
    info = {}
    try:
        with open(os.path.join(path, "Info.plist"), "rb") as f:
            p = plistlib.load(f)
        info = {"version_name": p.get("CFBundleShortVersionString"),
                "version_code": p.get("CFBundleVersion"),
                "executable": p.get("CFBundleExecutable"),
                "display_name": p.get("CFBundleDisplayName") or p.get("CFBundleName"),
                "min_os": p.get("MinimumOSVersion")}
    except (OSError, plistlib.InvalidFileException):
        pass
    js = os.path.join(path, "main.jsbundle")
    if os.path.exists(js):
        with open(js, "rb") as f:
            head = f.read(32)
        info["js_bundle"] = "hermes" if head[:8] == HBC_MAGIC else "javascript"
        if head[:8] == HBC_MAGIC:
            info["hbc_version"] = int.from_bytes(head[8:12], "little")
            info["hbc_source_hash"] = head[12:32].hex()
        info["build_type"] = "release"
    else:
        info["js_bundle"] = None
        info["build_type"] = "debug"
    return {k: v for k, v in info.items() if v is not None or k == "js_bundle"}


def terminate(udid, bundle):
    _run(["xcrun", "simctl", "terminate", udid, bundle])


# ------------------------------------------------------------------ the Mac

def parse_pmset_therm(text):
    """`pmset -g therm`: whether macOS has recorded any thermal or
    performance limit. A throttled Mac slows every simulator number."""
    out = {}
    m = re.search(r"CPU_Speed_Limit\s*=\s*(\d+)", text or "")
    if m:
        out["host_cpu_speed_limit_pct"] = int(m.group(1))
    out["host_thermal_warning"] = not re.search(r"No thermal warning level has been recorded", text or "")
    return out


def parse_pmset_batt(text):
    out = {}
    if "AC Power" in (text or ""):
        out["host_power"] = "ac"
    elif "Battery Power" in (text or ""):
        out["host_power"] = "battery"
    m = re.search(r"(\d+)%;\s*([a-z ]+);", text or "")
    if m:
        out["host_battery_pct"] = int(m.group(1))
        out["host_battery_state"] = m.group(2).strip()
    return out


def parse_loadavg(text):
    nums = re.findall(r"[\d.]+", text or "")
    return {"host_load_1m": float(nums[0])} if nums else {}


def host_info():
    def sysctl(name):
        code, out, _ = _run(["sysctl", "-n", name])
        return out.strip() if code == 0 else None
    mem = sysctl("hw.memsize")
    return {k: v for k, v in {
        "model": sysctl("hw.model"), "chip": sysctl("machdep.cpu.brand_string"),
        "ram_gb": round(int(mem) / 2**30) if mem and mem.isdigit() else None,
        "macos": (_run(["sw_vers", "-productVersion"])[1] or "").strip() or None,
    }.items() if v}


def host_state():
    state = {}
    state.update(parse_pmset_therm(_run(["pmset", "-g", "therm"])[1]))
    state.update(parse_pmset_batt(_run(["pmset", "-g", "batt"])[1]))
    state.update(parse_loadavg(_run(["sysctl", "-n", "vm.loadavg"])[1]))
    return state


def run_metadata(pkg=None, serial=None):
    """Simulator, app and Mac details at the moment a run is captured.
    Best-effort throughout, like capture.run_metadata."""
    info = device_info(serial)
    if not info:
        return {}
    code, xcode, _ = _run(["xcodebuild", "-version"])
    device = {"model": info["model"], "udid": info["udid"], "platform": PLATFORM,
              "os_version": info["os_version"], "simulator": True}
    state = host_state()
    if code == 0 and xcode.strip():
        state["xcode"] = xcode.strip().splitlines()[0].replace("Xcode", "").strip()
    out = {"device": device, "state": state, "host": host_info(),
           "source": "simctl", "recorded_at": _utc_now()}
    if pkg:
        try:
            out["app"] = {"package": pkg, **parse_app_bundle(app_path(info["udid"], pkg))}
        except RuntimeError:
            out["app"] = {"package": pkg}
    return out


# ------------------------------------------------------------ other profilers

def other_profilers(serial=None):
    """Another Instruments recording on this Mac would compete for the same
    device and skew a simulator run's CPU. The bracket stops pgrep matching
    its own shell."""
    found = []
    if _run(["pgrep", "-f", "[x]ctrace record"])[0] == 0:
        found.append("another xctrace recording")
    if _run(["pgrep", "-x", "Instruments"])[0] == 0:
        found.append("Instruments")
    return found


def require_no_other_profiler(serial=None):
    found = other_profilers(serial)
    if found:
        raise RuntimeError(f"{' and '.join(found)} is running. Stop it, then capture again: "
                           "two recordings at once would compete for the same process.")


# ------------------------------------------------------------ RAM sampling

class _RusageInfoV4(ctypes.Structure):
    # rusage_info_v4: a 16-byte uuid, then uint64 fields in this order.
    _fields_ = [("uuid", ctypes.c_uint8 * 16)] + [
        (n, ctypes.c_uint64) for n in (
            "user_time", "system_time", "pkg_idle_wkups", "interrupt_wkups", "pageins",
            "wired_size", "resident_size", "phys_footprint", "proc_start_abstime",
            "proc_exit_abstime")] + [(f"_rest{i}", ctypes.c_uint64) for i in range(30)]


_libc = None


def _lib():
    global _libc
    if _libc is None:
        _libc = ctypes.CDLL(ctypes.util.find_library("c"))
    return _libc


def phys_footprint(pid):
    """A process's physical footprint in bytes: the memory iOS itself counts
    against an app (jetsam limits use it), and what Xcode's memory gauge
    shows. None when the process is gone."""
    ri = _RusageInfoV4()
    if _lib().proc_pid_rusage(ctypes.c_int(pid), ctypes.c_int(4), ctypes.byref(ri)) != 0:
        return None
    return int(ri.phys_footprint)


def _ere_escape(text):
    """Escape for pgrep's POSIX extended regex. Python's re.escape also
    escapes '-', which POSIX leaves undefined, and UDIDs are full of them."""
    return re.sub(r"([.\[\]()*+?{}|^$\\])", r"\\\1", text)


class FootprintSampler(threading.Thread):
    """Samples the simulated app's RAM usage from the Mac while xctrace records.

    A simulator app is an ordinary Mac process, so its physical footprint can
    be read directly; the simulator supports none of Instruments' memory
    instruments (VM Tracker records nothing, Activity Monitor refuses).
    Samples carry wall-clock times and are placed on the trace's clock later,
    by the recording's start time (see convert_recording).
    """

    def __init__(self, udid, app_dir, executable, interval_s=0.1, find_timeout_s=30):
        super().__init__(daemon=True)
        self.pattern = (f"{_ere_escape(udid)}/data/Containers/Bundle/Application/[^/]+/"
                        f"{_ere_escape(os.path.basename(app_dir))}/{_ere_escape(executable)}$")
        self.interval_s, self.find_timeout_s = interval_s, find_timeout_s
        self.samples, self.pid = [], None
        self._halt = threading.Event()

    def _find(self):
        deadline = time.time() + self.find_timeout_s
        while not self._halt.is_set() and time.time() < deadline:
            code, out, _ = _run(["pgrep", "-n", "-f", self.pattern], timeout=5)
            pids = [int(p) for p in out.split() if p.isdigit()]
            if code == 0 and pids:
                return pids[0]  # -n: the newest match, the one xctrace just launched
            time.sleep(0.05)
        return None

    def run(self):
        self.pid = self._find()
        if not self.pid:
            return
        while not self._halt.is_set():
            v = phys_footprint(self.pid)
            if v is None:
                break
            self.samples.append((time.time_ns(), v))
            self._halt.wait(self.interval_s)

    def stop(self):
        self._halt.set()
        self.join(timeout=5)


def align_samples(samples, *, wall_start_ns, trace_start_ns):
    """Wall-clock samples on the trace's clock, given one moment both record."""
    offset = trace_start_ns - wall_start_ns
    return [(w + offset, v) for w, v in samples if w + offset >= 0]


# ------------------------------------------------------------------ capture

def trace_bundle_path(out_path):
    return re.sub(r"\.pftrace$", "", out_path) + ".trace"


def report_path(out_path):
    return re.sub(r"\.pftrace$", "", out_path) + ".convert.json"


def capture(out_path, *, pkg, duration_ms=DEFAULT_DURATION_MS, serial=None, cold=True,
            on_log=None):
    """Cold-launch `pkg` on a simulator under xctrace and write a Perfetto trace
    to `out_path`. Returns the capture report (also written beside the trace)."""
    log = on_log or (lambda s: None)
    if not cold:
        raise RuntimeError("Warm captures are not supported on iOS yet. Capture cold.")
    info = device_info(serial)
    if not info:
        raise RuntimeError("No booted iOS Simulator. Boot one (xcrun simctl boot \"iPhone 17\") "
                           "or open Simulator.app.")
    udid = info["udid"]
    require_no_other_profiler(udid)
    app = app_path(udid, pkg)
    bundle = parse_app_bundle(app)
    if bundle.get("build_type") == "debug":
        raise RuntimeError(f"{pkg} is a Debug build: it has no main.jsbundle and loads its JS "
                           "from Metro, which is a different app to measure. Install a Release "
                           "build (xcodebuild -configuration Release -sdk iphonesimulator).")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    trace = trace_bundle_path(out_path)
    if os.path.exists(trace):
        import shutil
        shutil.rmtree(trace)
    terminate(udid, pkg)

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(xt.HANGS_OPTIONS, f)
        opts = f.name
    sampler = FootprintSampler(udid, app, bundle.get("executable") or os.path.basename(app)[:-4])
    try:
        sampler.start()
        log(f"recording {pkg} on {info['model']} (iOS {info['os_version']}) for "
            f"{duration_ms / 1000:.0f}s…")
        code, output = xt.record(device=udid, app=app, out=trace,
                                 time_limit_s=duration_ms / 1000, options_path=opts)
    finally:
        sampler.stop()
        os.unlink(opts)
    if not os.path.exists(trace):
        raise RuntimeError(f"xctrace did not write a trace: {output.strip()[-300:]}")
    log(f"recorded -> {trace}; converting…")
    # The build's source map, for resolving JS error stacks later: best-effort.
    try:
        from . import sourcemaps
        found = sourcemaps.discover_ios(pkg, app)
        if found:
            log(f"source map for this build: {found}")
    except Exception:
        pass
    return convert_recording(trace, out_path, pkg=pkg, info=info, sampler=sampler,
                             record_output=output)


def convert_recording(trace, out_path, *, pkg, info=None, sampler=None, record_output=None):
    """Export a `.trace`'s tables and write the Perfetto trace and report.
    Also used on its own (`swagperf ios convert`) for a recording made by hand."""
    from . import convert_ios as cv
    toc = xt.parse_toc(xt.export_toc(trace))
    pid = (toc.get("process") or {}).get("pid")
    tables = {}
    for schema, where in (("os-signpost", ""), ("dyld-activity-interval", ""),
                          ("potential-hangs", ""), ("os-log", "not(@subsystem)")):
        if schema in toc.get("schemas", []):
            tables[schema] = xt.parse_table(xt.export_table(trace, schema, where=where))

    dev = toc.get("device") or {}
    simulator = "Simulator" in (dev.get("platform") or "")
    crashed, termination = crash_of(toc)
    source = {"platform": PLATFORM, "simulator": int(simulator),
              "device": dev.get("name"), "os": (dev.get("os_version") or "").split(" ")[0],
              "xctrace": (toc.get("instruments_version") or "").split(" ")[0],
              "crashed": int(crashed),
              # The provenance marker is `k=v;k=v`, so the reason must hold neither.
              "termination": re.sub(r"[;=]", " ", termination or "") or None}

    # RAM samples go on the trace's clock through the recording's own start
    # time: table timestamps count from it. Not through the process start:
    # Instruments spawns the app suspended and resumes it once recording is
    # ready, so the kernel's spawn time sits ~0.6 s before dyld begins (measured:
    # spawn 35 ms before the recording started, dyld at 549 ms, the footprint
    # still 0.1 MB until then).
    #
    # Only samples from the first frame on are kept. Before it the process is
    # still loading, so min-to-peak "RAM growth" would measure the launch
    # itself; Android's first process_stats sample lands after launch, and
    # growth has to mean the same thing on both platforms.
    memory = None
    start = _epoch_ns(toc.get("start_date"))
    if sampler and sampler.samples and start:
        memory = align_samples(sampler.samples, wall_start_ns=start, trace_start_ns=0)
        first_frame = [xt.num(r["time"]) for r in tables.get("os-signpost") or []
                       if xt.fmt(r.get("name")) == "ApplicationFirstFramePresentation"]
        if first_frame:
            memory = [(t, v) for t, v in memory if t >= min(first_frame)]
    end_ns = int((toc.get("duration_s") or 0) * 1e9) or None
    data, rep = cv.convert(tables, bundle_id=pkg, pid=pid or 0, source=source,
                           memory=memory, end_ns=end_ns)
    with open(out_path, "wb") as f:
        f.write(data)
    report = {"toc": {k: toc.get(k) for k in ("device", "process", "duration_s", "end_reason",
                                              "instruments_version", "start_date")},
              "convert": rep, "xctrace": trace,
              "record_issues": _record_issues(record_output)}
    with open(report_path(out_path), "w") as f:
        json.dump(report, f, indent=1)
    return report


# How a process ended when it crashed: a signal or a Mach exception, never a
# plain exit. xctrace ends a recording at its time limit by stopping the app,
# and reports that as exit(0).
_CRASH = re.compile(r"SIG[A-Z]+|EXC_[A-Z_]+|crash|abort|signal", re.I)


def crash_of(toc):
    """(crashed, termination reason) from a table of contents: the app died
    on its own, before the recording's time limit stopped it."""
    proc = toc.get("process") or {}
    reason = proc.get("termination_reason") or ""
    early = (toc.get("end_reason") or "") != "Time limit reached"
    crashed = bool(_CRASH.search(reason)) or (
        early and proc.get("exit_status") not in (None, 0) and "exit(0)" not in reason)
    return crashed, reason or None


def _epoch_ns(iso):
    """`2026-09-24T12:49:58.019+05:30` -> nanoseconds since the epoch."""
    try:
        return int(datetime.fromisoformat(iso).timestamp() * 1e9) if iso else None
    except ValueError:
        return None


def _record_issues(output):
    """The "[Error]" and "[Warning]" lines xctrace prints for a run that still saved."""
    return [ln.strip(" *\t") for ln in (output or "").splitlines()
            if "[Error]" in ln or "[Warning]" in ln]


def verify(trace_path, *, instrumented=False):
    """Why this capture should not become a run, or None. The iOS counterpart
    of extract.tracing_lost: a recording can save cleanly and still hold
    nothing about the app."""
    try:
        with open(report_path(trace_path)) as f:
            rep = json.load(f)
    except (OSError, ValueError):
        return None  # not a capture this module made (an analysed file)
    toc, conv = rep.get("toc") or {}, rep.get("convert") or {}
    if not (toc.get("process") or {}).get("pid"):
        return "xctrace recorded no target process: the app never launched."
    if crash_of(toc)[0]:
        return None  # a crash is a result: the run is recorded as crashed
    errors = [i for i in rep.get("record_issues") or [] if i.startswith("[Error]")]
    if errors:
        return f"xctrace reported {errors[0]}"
    if not (conv.get("launch") or {}).get("first_frame") and not conv.get("app_signposts"):
        return ("the recording holds neither a first frame nor any of the app's markers, "
                "so it did not observe the app.")
    if instrumented and not conv.get("app_signposts"):
        return ("the app is marked instrumented but emitted no com.swag.pay.trace signposts: "
                "is this build older than the signpost instrumentation?")
    return None
