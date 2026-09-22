"""Synthetic *generic Android* trace generator.

The Swag Pay generator in `synth.py` emits custom `step:` markers, which is what an
instrumented app looks like. This one emits the slice names a plain, uninstrumented
Android app produces, so step derivation can be developed and tested without a
device: `bindApplication`, `activityStart`, `Choreographer#doFrame` and friends,
plus a `launching:` async slice on a system_server-like process.
"""
import random
from .synth import (_len, _varint, _str, packet, track_desc, slice_begin,
                    slice_end, counter, MS)

# Track uuids kept distinct from synth.py's
T_APP_MAIN, T_APP_RT, T_SYS, T_RSS = 100, 101, 102, 110


def gen_android_trace(seed=0, *, pkg="com.example.app", cold=True,
                      scan_s=5, regress=None, rss_base=180):
    """Build a trace that looks like an ordinary Android app launch + use.

    regress keys: 'bindApplication', 'activityStart', 'inflate', 'first_frame',
    'thermal_drift', 'interop_jank', 'mem_leak'.
    """
    rnd = random.Random(seed)
    regress = regress or {}
    out = bytearray()
    pid, sys_pid = 9000 + (seed % 500), 1000

    out += packet(0, track_desc(T_APP_MAIN, pkg, pid=pid, tid=pid))
    out += packet(0, track_desc(T_APP_RT, "RenderThread", pid=pid, tid=pid + 1))
    out += packet(0, track_desc(T_SYS, "system_server", pid=sys_pid, tid=sys_pid))
    out += packet(0, track_desc(T_RSS, "mem.rss", counter=True))

    def j(base, key):
        return int(base * MS * regress.get(key, 1.0) * rnd.uniform(0.9, 1.12))

    t = 5 * MS
    launch_start = t

    # system_server: the async launch slice the android_startups module looks for.
    out += slice_begin(launch_start, T_SYS, f"launching: {pkg}")

    def emit(track, name, dur_ns, children=()):
        """One slice with optional nested children, advancing the clock."""
        nonlocal t
        start = t
        buf = bytearray()
        buf += slice_begin(start, track, name)
        inner = start
        for cname, cdur in children:
            buf += slice_begin(inner, track, cname)
            buf += slice_end(inner + cdur, track)
            inner += cdur
        end = max(start + dur_ns, inner)
        buf += slice_end(end, track)
        t = end
        return bytes(buf)

    if cold:
        # Process + ART work that only a cold start pays for.
        out += emit(T_APP_MAIN, "Start proc: " + pkg, j(18, "proc_start"))
        out += emit(T_APP_MAIN, "bindApplication", j(62, "bindApplication"), [
            ("OpenDexFilesFromOat", j(16, "dex")),
            ("VerifyClass", j(11, "dex")),
            ("ActivityThread.handleBindApplication", j(20, "bindApplication")),
        ])
    else:
        out += emit(T_APP_MAIN, "bindApplication", j(8, "bindApplication"))

    out += emit(T_APP_MAIN, "activityStart", j(54, "activityStart"), [
        ("performCreate", j(24, "activityStart")),
        ("inflate", j(21, "inflate")),
    ])
    out += emit(T_APP_MAIN, "activityResume", j(14, "activityResume"))

    # First frame: the end of the launch window.
    ff = j(24, "first_frame")
    out += slice_begin(t, T_APP_MAIN, "Choreographer#doFrame")
    out += slice_begin(t, T_APP_RT, "DrawFrame")
    out += slice_end(t + int(ff * 0.7), T_APP_RT)
    out += slice_end(t + ff, T_APP_MAIN)
    t += ff
    out += slice_end(t, T_SYS)                  # close launching:
    if rnd.random() < 0.7:                      # many apps call this, some do not
        out += emit(T_APP_MAIN, "reportFullyDrawn() for " + pkg, j(30, "fully_drawn"))

    # Steady-state frames.
    budget = 16_666_667
    n = int(scan_s * 60)
    for i in range(n):
        drift = 1.0 + (i / max(n, 1)) * regress.get("thermal_drift", 0.0)
        dur = int(rnd.gauss(9.0, 2.0) * MS * drift)
        if rnd.random() < 0.03 * (1 + regress.get("interop_jank", 0.0)):
            dur = int(rnd.uniform(20, 48) * MS * drift)
        dur = max(dur, 2 * MS)
        out += slice_begin(t, T_APP_MAIN, "Choreographer#doFrame")
        out += slice_begin(t, T_APP_RT, "DrawFrame")
        out += slice_end(t + int(dur * 0.62), T_APP_RT)
        out += slice_end(t + dur, T_APP_MAIN)
        t += max(dur, budget)

    for k in range(60):
        ts = int(k * (t / 60))
        growth = k * 0.7 * (1 + regress.get("mem_leak", 0.0))
        out += counter(ts, T_RSS, int((rss_base + growth + rnd.uniform(-3, 3)) * 1024 * 1024))

    return bytes(out), {"launch_start_ns": launch_start, "first_frame_ns": t, "pkg": pkg}


def gen_swagpay_trace(seed=0, *, pkg="com.swagpay", flow=None, regress=None):
    """Synthetic trace carrying SwagTrace screen/action/nav markers.

    Mirrors what the instrumented Swag Pay app emits so `screens.py` can be
    developed and tested without a device. `flow` is the sequence of screens
    visited; each entry is (route, dwell_ms).
    """
    rnd = random.Random(seed)
    regress = regress or {}
    flow = flow or [("Home", 2200), ("Store", 1400), ("Pay", 2600),
                    ("History", 1100), ("Home", 900)]
    out = bytearray()
    pid = 7000 + (seed % 400)

    out += packet(0, track_desc(T_APP_MAIN, pkg, pid=pid, tid=pid))
    out += packet(0, track_desc(T_APP_RT, "RenderThread", pid=pid, tid=pid + 1))
    out += packet(0, track_desc(T_RSS, "mem.rss", counter=True))

    t = 5 * MS
    # Startup steps, as the coordinator emits them.
    for step in ("step:returning_bootstrap", "step:first_usable_camera_frame",
                 "step:hermes_runtime_active"):
        out += slice_begin(t, T_APP_MAIN, step)
        out += slice_end(t + 1 * MS, T_APP_MAIN)
        t += 30 * MS

    rss = 190.0
    prev = None
    for route, dwell in flow:
        dwell = int(dwell * MS * regress.get(route, 1.0))
        # The navigation slice must OPEN AND CLOSE before the screen slice
        # opens. Sync slices on one track are a stack: emitting nav-begin,
        # screen-begin, nav-end would make the reader close the screen slice
        # first and swap the two durations.
        if prev:
            nav_dur = int(rnd.uniform(8, 26) * MS)
            out += slice_begin(t, T_APP_MAIN, f"nav:{prev}->{route}")
            out += slice_end(t + nav_dur, T_APP_MAIN)
            t += nav_dur
        out += slice_begin(t, T_APP_MAIN, f"screen:{route}")
        screen_start = t
        end = t + dwell

        # Frames and per-screen actions inside the visit.
        ts = t
        while ts < end - 16_666_667:
            fdur = int(rnd.gauss(9.5, 2.5) * MS)
            if rnd.random() < 0.05:
                fdur = int(rnd.uniform(18, 40) * MS)
            fdur = max(fdur, 2 * MS)
            out += slice_begin(ts, T_APP_MAIN, "Choreographer#doFrame")
            out += slice_end(ts + fdur, T_APP_MAIN)
            ts += max(fdur, 16_666_667)

        if route == "Home":
            for _ in range(int(dwell / MS / 250)):
                a = screen_start + int(rnd.uniform(0, dwell))
                out += slice_begin(a, T_APP_MAIN, "action:qr_validate_valid_upi")
                out += slice_end(a + 1 * MS, T_APP_MAIN)
        if route == "Pay":
            for i, nm in enumerate(("pay_amount_to_choosebank",
                                    "pay_choosebank_to_upipin",
                                    "pay_upipin_to_processing",
                                    "pay_processing_to_success")):
                a = screen_start + int(dwell * (i + 1) / 6)
                out += slice_begin(a, T_APP_MAIN, f"action:{nm}")
                out += slice_end(a + 1 * MS, T_APP_MAIN)

        # RAM grows while a screen is open; Pay grows fastest (RN surface).
        grow = {"Pay": 9.0, "Store": 5.0}.get(route, 2.0) * regress.get("mem", 1.0)
        for k in range(6):
            out += counter(screen_start + int(dwell * k / 6), T_RSS,
                           int((rss + grow * k / 6 + rnd.uniform(-1, 1)) * 1024 * 1024))
        rss += grow
        out += slice_end(end, T_APP_MAIN)
        t = end + int(rnd.uniform(40, 120) * MS)
        prev = route

    return bytes(out), {"pkg": pkg, "flow": flow}
