"""Optional on-device capture via adb. Analysis never depends on this."""
import subprocess, time, os, shlex

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


def capture(out_path, *, pkg="com.swagpay", duration_ms=10000, serial=None,
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
