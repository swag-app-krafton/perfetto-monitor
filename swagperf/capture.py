"""Optional on-device capture via adb. Analysis never depends on this."""
import os, re, shlex, subprocess, time

# android.packages_list records installed packages' version codes in the
# trace, so a trace names the app build it measured even when analysed away
# from the device. No package filter: an unknown config field would make an
# older Perfetto reject the whole config, while an unknown data source is
# simply ignored.
CONFIG = """
buffers: {{ size_kb: 131072 fill_policy: RING_BUFFER }}
buffers: {{ size_kb: 8192 fill_policy: DISCARD }}
data_sources: {{
  config {{
    name: "linux.ftrace"
    ftrace_config {{
      ftrace_events: "sched/sched_switch"
      ftrace_events: "power/suspend_resume"
      ftrace_events: "sched/sched_process_exit"
      atrace_categories: "gfx" atrace_categories: "view" atrace_categories: "am"
      atrace_categories: "camera" atrace_categories: "res" atrace_categories: "sched"
      atrace_apps: "{pkg}"
      buffer_size_kb: 16384
    }}
  }}
}}
data_sources: {{ config {{ name: "linux.process_stats"
  process_stats_config {{ scan_all_processes_on_start: true proc_stats_poll_ms: 1000 }} }} }}
data_sources: {{ config {{ name: "android.surfaceflinger.frametimeline" }} }}
data_sources: {{ config {{ name: "android.packages_list" }} }}
duration_ms: {dur}
"""


def devices():
    out = subprocess.run(["adb", "devices"], capture_output=True, text=True).stdout
    return [l.split()[0] for l in out.splitlines()[1:] if l.strip().endswith("device")]


def installed_packages(serial=None):
    """Third-party packages on the device, for catalogue verification.

    On a multi-user device (a work profile or private space) `pm list packages`
    can print a permission error line for a user the shell can't see, mixed in
    with the real output on stdout rather than stderr. Only lines carrying
    adb's own `package:` marker are accepted, so that error text is never
    mistaken for a package name.
    """
    devs = devices()
    if not devs:
        return []
    serial = serial or devs[0]
    out = subprocess.run(["adb", "-s", serial, "shell", "pm", "list", "packages", "-3"],
                         capture_output=True, text=True).stdout
    return sorted(l.strip()[len("package:"):].strip()
                 for l in out.splitlines() if l.strip().startswith("package:"))


def device_info(serial=None):
    devs = devices()
    if not devs:
        return {}
    serial = serial or devs[0]
    def prop(k):
        return subprocess.run(["adb", "-s", serial, "shell", "getprop", k],
                              capture_output=True, text=True).stdout.strip()
    return {"serial": serial, "model": prop("ro.product.model"),
            "device": prop("ro.product.device"),
            "sdk": prop("ro.build.version.sdk"),
            "release": prop("ro.build.version.release")}


def device_health(serial=None):
    """Battery level, battery temperature and the on-device Perfetto version.

    Best-effort: each is a separate adb call, and any one failing leaves that
    field None rather than failing device detection. Temperature is the
    battery's, which is what Android exposes without root and is a fair proxy
    for how hot the phone is before a run.
    """
    devs = devices()
    if not devs:
        return {}
    serial = serial or devs[0]

    def sh(cmd):
        try:
            return subprocess.run(["adb", "-s", serial, "shell", cmd],
                                  capture_output=True, text=True, timeout=10).stdout
        except (subprocess.SubprocessError, OSError):
            return ""

    out = {"battery_pct": None, "battery_temp_c": None, "perfetto_version": None}
    for line in sh("dumpsys battery").splitlines():
        k, _, v = line.strip().partition(":")
        v = v.strip()
        if k == "level" and v.isdigit():
            out["battery_pct"] = int(v)
        elif k == "temperature" and v.lstrip("-").isdigit():
            out["battery_temp_c"] = int(v) / 10
    ver = sh("perfetto --version").strip().splitlines()
    if ver:
        out["perfetto_version"] = ver[0].replace("Perfetto", "").strip() or None
    return out


# ------------------------------------------------------------ run metadata
#
# What a run was measured on, recorded with the run. Each reading is a parser
# over one adb command's output, kept pure so it can be tested without a
# device; `run_metadata` runs the commands. Any one failing leaves its fields
# out rather than failing the capture.

def parse_getprop(text):
    """`getprop` prints `[key]: [value]` per line."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"\[(.+?)\]: \[(.*)\]", line.strip())
        if m:
            out[m.group(1)] = m.group(2)
    return out


def device_from_props(props):
    g = lambda k: props.get(k) or None
    soc = " ".join(x for x in (g("ro.soc.manufacturer"), g("ro.soc.model")) if x) or None
    return {k: v for k, v in {
        "manufacturer": g("ro.product.manufacturer"),
        "brand": g("ro.product.brand"),
        "model": g("ro.product.model"),
        "market_name": g("ro.product.marketname") or g("ro.vendor.vivo.market.name") or g("ro.config.marketing_name"),
        "codename": g("ro.product.device"),
        "android_release": g("ro.build.version.release"),
        "sdk": int(props["ro.build.version.sdk"]) if (props.get("ro.build.version.sdk") or "").isdigit() else None,
        "security_patch": g("ro.build.version.security_patch"),
        "build_id": g("ro.build.display.id") or g("ro.build.id"),
        "build_type": g("ro.build.type"),
        "fingerprint": g("ro.build.fingerprint"),
        "soc": soc,
        "hardware": g("ro.hardware"),
        "abi": g("ro.product.cpu.abi"),
    }.items() if v is not None}


def parse_dumpsys_package(text, pkg):
    """App version and install facts from `dumpsys package <pkg>`. Only the
    section for `pkg` is read: the output also lists other packages that
    reference it (shared users, queries)."""
    start = text.find(f"Package [{pkg}]")
    if start < 0:
        return {}
    sec = text[start:]
    nxt = re.search(r"\n\s*Package \[", sec[1:])
    if nxt:
        sec = sec[:nxt.start() + 1]
    def first(pattern):
        m = re.search(pattern, sec)
        return m.group(1).strip() if m else None
    code = first(r"versionCode=(\d+)")
    flags = first(r"\bflags=\[([^\]]*)\]") or ""
    out = {
        "version_name": first(r"versionName=(\S+)"),
        "version_code": int(code) if code else None,
        "min_sdk": int(v) if (v := first(r"minSdk=(\d+)")) else None,
        "target_sdk": int(v) if (v := first(r"targetSdk=(\d+)")) else None,
        "first_install": first(r"firstInstallTime=([^\n]+)"),
        "last_update": first(r"lastUpdateTime=([^\n]+)"),
        "installer": first(r"installerPackageName=(\S+)") or first(r"installInitiatingPackageName=(\S+)"),
        "debuggable": "DEBUGGABLE" in flags.split(),
    }
    return {k: v for k, v in out.items() if v is not None}


def parse_battery(text):
    kv = {}
    for line in text.splitlines():
        k, _, v = line.strip().partition(":")
        kv[k.strip()] = v.strip()
    out = {}
    if kv.get("level", "").isdigit():
        out["battery_pct"] = int(kv["level"])
    if kv.get("temperature", "").lstrip("-").isdigit():
        out["battery_temp_c"] = int(kv["temperature"]) / 10
    plugged = [src for src, key in (("AC", "AC powered"), ("USB", "USB powered"), ("wireless", "Wireless powered"))
               if kv.get(key) == "true"]
    if any(k in kv for k in ("AC powered", "USB powered")):
        out["charging"] = " + ".join(plugged) if plugged else "not charging"
    return out


THERMAL = {0: "none", 1: "light", 2: "moderate", 3: "severe", 4: "critical", 5: "emergency", 6: "shutdown"}


def parse_thermal(text):
    m = re.search(r"Thermal Status:\s*(\d+)", text)
    return {"thermal_status": THERMAL.get(int(m.group(1)), m.group(1))} if m else {}


def parse_meminfo(text):
    m = re.search(r"MemTotal:\s*(\d+)\s*kB", text)
    return {"ram_gb": round(int(m.group(1)) / 1024 / 1024, 1)} if m else {}


def parse_display(size_text, density_text, display_text=""):
    out = {}
    sizes = re.findall(r"(Physical|Override) size:\s*(\d+x\d+)", size_text)
    if sizes:
        out["screen"] = dict(sizes).get("Override") or dict(sizes)["Physical"]
    dens = re.findall(r"(Physical|Override) density:\s*(\d+)", density_text)
    if dens:
        out["density_dpi"] = int(dict(dens).get("Override") or dict(dens)["Physical"])
    # The highest rate the display offers (its modes list them); the current
    # rate moves with what is on screen.
    rates = [float(r) for r in re.findall(r"(?:refreshRate|fps)[=:\s]+(\d+(?:\.\d+)?)", display_text, re.I)]
    if rates:
        out["refresh_hz"] = round(max(rates))
    return out


def run_metadata(pkg=None, serial=None):
    """Device and app details at the moment a run is captured: the device's
    identity and build, its state (battery, temperature, thermal status), and
    the app's version and install. Best-effort throughout."""
    devs = devices()
    if not devs:
        return {}
    serial = serial or devs[0]

    def sh(cmd, timeout=15):
        try:
            return subprocess.run(["adb", "-s", serial, "shell", cmd],
                                  capture_output=True, text=True, timeout=timeout).stdout
        except (subprocess.SubprocessError, OSError):
            return ""

    device = {"serial": serial, **device_from_props(parse_getprop(sh("getprop")))}
    device.update(parse_meminfo(sh("cat /proc/meminfo")))
    cores = sh("nproc").strip()
    if cores.isdigit():
        device["cpu_cores"] = int(cores)
    device.update(parse_display(sh("wm size"), sh("wm density"), sh("dumpsys display | grep -m 5 -iE 'refreshRate|fps='")))
    state = {**parse_battery(sh("dumpsys battery")), **parse_thermal(sh("dumpsys thermalservice"))}
    ver = sh("perfetto --version").strip().splitlines()
    if ver:
        state["perfetto_version"] = ver[0].replace("Perfetto", "").strip() or None
    out = {"device": device, "state": state, "source": "device", "recorded_at": _utc_now()}
    if pkg:
        out["app"] = {"package": pkg, **parse_dumpsys_package(sh(f"dumpsys package {pkg}", timeout=20), pkg)}
    return out


def _utc_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def force_stop(pkg, serial=None):
    serial = serial or (devices() or [None])[0]
    subprocess.run(["adb", "-s", serial, "shell", "am", "force-stop", pkg],
                   capture_output=True)


def launch(pkg, serial=None):
    """Launch an app by package, without needing to know its activity name."""
    serial = serial or (devices() or [None])[0]
    p = subprocess.run(["adb", "-s", serial, "shell", "monkey", "-p", pkg,
                        "-c", "android.intent.category.LAUNCHER", "1"],
                       capture_output=True, text=True)
    if p.returncode != 0 or "No activities found" in (p.stdout + p.stderr):
        raise RuntimeError(f"could not launch {pkg}: {(p.stderr or p.stdout)[:200]}")


def capture(out_path, *, pkg="com.swag.pay", duration_ms=10000, serial=None,
            cold=False, launch_after_ms=600):
    """Record a trace. With cold=True the app is force-stopped first and launched
    just after tracing starts, which is the only way to measure a real cold start.

    Perfetto is started with `--background-wait` (`-D`): it detaches immediately
    but the adb call blocks until the trace config is actually active on-device,
    so force-stop and launch happen with no concurrent `adb shell` session racing
    perfetto's own startup. An earlier version ran `perfetto` and the delayed
    launch as two independent concurrent adb shell invocations; on at least one
    real device that produced traces with zero slices for the target app at all
    even though the app was confirmed in the foreground moments later -- the
    capture and the launch were racing each other, not sequenced.
    """
    devs = devices()
    if not devs:
        raise RuntimeError("No adb device connected. Connect a device or analyse an existing trace file.")
    serial = serial or devs[0]
    base = ["adb", "-s", serial]
    remote = "/data/misc/perfetto-traces/swagperf.pftrace"
    cfg = CONFIG.format(pkg=pkg, dur=duration_ms)
    subprocess.run(base + ["shell", "rm", "-f", remote], capture_output=True)

    if cold:
        force_stop(pkg, serial)

    start = subprocess.run(base + ["shell", f"perfetto --txt -c - -o {remote} --background-wait"],
                           input=cfg, text=True, capture_output=True, timeout=35)
    if start.returncode != 0 or not start.stdout.strip():
        raise RuntimeError(f"perfetto failed to start: {(start.stderr or start.stdout)[:500]}")

    if cold:
        time.sleep(launch_after_ms / 1000)
        launch(pkg, serial)

    # The trace is now actively recording on-device; wait out its configured
    # duration before it self-stops and the file becomes pullable.
    time.sleep(duration_ms / 1000 + 1.0)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    subprocess.run(base + ["pull", remote, out_path], check=True, capture_output=True)
    return out_path


# ---------------------------------------------------------------- manual mode

# A manual session is open-ended: the user drives the app by hand and stops
# tracing when they are done. That needs a detached perfetto session, because
# the trace has to outlive the adb command that started it. `--detach=KEY`
# leaves the session running under a name we can reattach to later.
MANUAL_KEY = "swagperf_manual"
MANUAL_REMOTE = "/data/misc/perfetto-traces/swagperf_manual.pftrace"

# No `duration_ms` here: the session runs until stopped. A long-but-finite
# duration would silently truncate a long manual session and waste buffer on a
# short one. The ring buffer is drained to the on-device file every few
# seconds (see write_into_file below), so a long session accumulates in the
# file instead of overwriting itself in memory.
# Lean on purpose. A manual session is open-ended, and the original config grew
# at ~230MB a minute (975MB for a 4-minute session on a V2514): cpu_idle and
# cpu_frequency were 5.3M counter events, the `camera` category 2.2M camera-HAL
# slices, `binder_driver` ~600K, SurfaceFlinger (`gfx`) ~900K more -- none read
# by any extractor. Every live poll pulled that file over adb (~30s a poll) and
# stopping took ~70s. Measured on the same device and flow, this config runs at
# ~53MB/min, stops in ~7s, and gives the same startup steps, RAM, frames and
# per-screen data as the full set.
#
# task_newtask / task_rename are what name the app's process. Dropping `gfx`
# without them left the app unnamed, and anything scoped by package name then
# silently measured the whole device (an 876MB "peak"). Our own app can also be
# found through its markers; a competitor cannot, so the names matter.
# The short automated capture config keeps the full set.
MANUAL_CONFIG = """
buffers: {{ size_kb: 262144 fill_policy: RING_BUFFER }}
buffers: {{ size_kb: 8192 fill_policy: DISCARD }}
# `--detach` requires write_into_file: a detached session outlives the adb
# command that started it, so there is no pipe left to stream the trace back
# through -- traced has to write it to MANUAL_REMOTE itself. Perfetto rejects
# the config outright without it. Each periodic drain appends to the file, so
# the ring buffer only has to hold one drain window and the full session is
# preserved on device.
write_into_file: true
file_write_period_ms: 2500
data_sources: {{
  config {{
    name: "linux.ftrace"
    ftrace_config {{
      ftrace_events: "sched/sched_switch"
      ftrace_events: "sched/sched_process_exit"
      ftrace_events: "power/suspend_resume"
      ftrace_events: "task/task_newtask"
      ftrace_events: "task/task_rename"
      atrace_categories: "view" atrace_categories: "am" atrace_categories: "res"
      atrace_apps: "{pkg}"
      buffer_size_kb: 32768
    }}
  }}
}}
data_sources: {{ config {{ name: "linux.process_stats"
  process_stats_config {{ scan_all_processes_on_start: true proc_stats_poll_ms: 500 }} }} }}
data_sources: {{ config {{ name: "linux.sys_stats"
  sys_stats_config {{ stat_period_ms: 500 stat_counters: STAT_CPU_TIMES
    stat_counters: STAT_FORK_COUNT meminfo_period_ms: 500 }} }} }}
data_sources: {{ config {{ name: "android.surfaceflinger.frametimeline" }} }}
data_sources: {{ config {{ name: "android.packages_list" }} }}
"""


def manual_status(serial=None):
    """Whether a detached swagperf session is currently recording.

    `--is_detached` exits 0 when the key exists, 2 when it does not, so the
    exit code is the answer.
    """
    devs = devices()
    if not devs:
        return {"device": False, "recording": False}
    serial = serial or devs[0]
    p = subprocess.run(["adb", "-s", serial, "shell",
                        f"perfetto --is_detached={MANUAL_KEY}"],
                       capture_output=True, text=True)
    return {"device": True, "serial": serial, "recording": p.returncode == 0}


def manual_start(*, pkg="com.swag.pay", serial=None, cold=False):
    """Begin an open-ended trace the user drives by hand.

    With cold=True the app is force-stopped and launched once tracing is live,
    so a manual session can still start from a real cold start.
    """
    devs = devices()
    if not devs:
        raise RuntimeError("No adb device connected.")
    serial = serial or devs[0]
    base = ["adb", "-s", serial]

    if manual_status(serial)["recording"]:
        raise RuntimeError(
            "A manual trace is already recording. Stop it before starting another.")

    subprocess.run(base + ["shell", "rm", "-f", MANUAL_REMOTE], capture_output=True)
    if cold:
        force_stop(pkg, serial)

    cfg = MANUAL_CONFIG.format(pkg=pkg)
    p = subprocess.run(
        base + ["shell", f"perfetto --txt -c - -o {MANUAL_REMOTE} --detach={MANUAL_KEY}"],
        input=cfg, text=True, capture_output=True, timeout=40)
    if p.returncode != 0:
        raise RuntimeError(f"perfetto failed to start: {(p.stderr or p.stdout)[:400]}")

    launched = False
    if cold:
        time.sleep(0.6)
        try:
            launch(pkg, serial)
            launched = True
        except RuntimeError:
            # Failing to launch is not fatal: the session is recording, and the
            # user can open the app by hand -- which is the point of this mode.
            launched = False
    return {"key": MANUAL_KEY, "pkg": pkg, "serial": serial, "launched": launched}


def manual_stop(out_path, *, serial=None):
    """Stop the detached session and pull its trace."""
    devs = devices()
    if not devs:
        raise RuntimeError("No adb device connected.")
    serial = serial or devs[0]
    base = ["adb", "-s", serial]

    if not manual_status(serial)["recording"]:
        raise RuntimeError("No manual trace is recording.")

    # Reattach and stop. --stop makes the reattached session finalise the file.
    p = subprocess.run(base + ["shell", f"perfetto --attach={MANUAL_KEY} --stop"],
                       capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError(f"failed to stop the session: {(p.stderr or p.stdout)[:400]}")

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    pull = subprocess.run(base + ["pull", MANUAL_REMOTE, out_path],
                          capture_output=True, text=True)
    if pull.returncode != 0:
        raise RuntimeError(f"failed to pull the trace: {(pull.stderr or pull.stdout)[:300]}")
    subprocess.run(base + ["shell", "rm", "-f", MANUAL_REMOTE], capture_output=True)
    return out_path


def manual_abort(serial=None):
    """Discard a recording session without pulling it."""
    devs = devices()
    if not devs:
        return False
    serial = serial or devs[0]
    if not manual_status(serial)["recording"]:
        return False
    subprocess.run(["adb", "-s", serial, "shell",
                    f"perfetto --attach={MANUAL_KEY} --stop"],
                   capture_output=True, timeout=120)
    subprocess.run(["adb", "-s", serial, "shell", "rm", "-f", MANUAL_REMOTE],
                   capture_output=True)
    return True


def manual_snapshot(out_path, *, serial=None):
    """Copy the in-progress manual trace off the device without stopping it.

    The manual config sets `write_into_file` with `file_write_period_ms`, so
    traced is already appending completed windows to MANUAL_REMOTE while the
    session records. Pulling that file mid-session therefore yields a valid,
    if truncated, trace -- which is exactly what a live marker view needs.

    The session is left untouched: no attach, no stop, no flush. A pull is a
    plain file read, so the worst case is that the newest couple of seconds are
    still in the ring buffer and not yet on disk. Markers appear a beat late
    rather than the session being disturbed to fetch them, which is the right
    trade for a dashboard that refreshes every few seconds anyway.
    """
    devs = devices()
    if not devs:
        raise RuntimeError("No adb device connected.")
    serial = serial or devs[0]

    if not manual_status(serial)["recording"]:
        raise RuntimeError("No manual trace is recording.")

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    pull = subprocess.run(["adb", "-s", serial, "pull", MANUAL_REMOTE, out_path],
                          capture_output=True, text=True, timeout=180)
    if pull.returncode != 0:
        raise RuntimeError(f"failed to pull the partial trace: "
                           f"{(pull.stderr or pull.stdout)[:300]}")
    return out_path


def manual_remote_size(serial=None):
    """Current size of the in-progress manual trace on the device, or None."""
    devs = devices()
    if not devs:
        return None
    serial = serial or devs[0]
    p = subprocess.run(["adb", "-s", serial, "shell", f"stat -c %s {MANUAL_REMOTE}"],
                       capture_output=True, text=True, timeout=20)
    try:
        return int(p.stdout.strip())
    except ValueError:
        return None


def manual_read_from(offset, serial=None, max_bytes=64 * 1024 * 1024):
    """Bytes of the in-progress manual trace from `offset` on, capped per call.

    Only what was appended since the last read crosses the USB link, so a poll
    stays cheap however long the session has run -- `adb pull` of the whole
    file took ~30s four minutes into a session on the original config.
    `exec-out` is binary-safe, unlike `shell`, which would mangle line endings.
    The cap keeps a first read of a long-running session (the dashboard
    restarted mid-recording) from arriving as one enormous chunk; the rest
    comes on the following polls.
    """
    devs = devices()
    if not devs:
        raise RuntimeError("No adb device connected.")
    serial = serial or devs[0]
    p = subprocess.run(
        ["adb", "-s", serial, "exec-out",
         f"tail -c +{int(offset) + 1} {MANUAL_REMOTE} | head -c {int(max_bytes)}"],
        capture_output=True, timeout=180)
    if p.returncode != 0:
        raise RuntimeError(f"failed to read the live trace: {p.stderr[:300]!r}")
    return p.stdout
