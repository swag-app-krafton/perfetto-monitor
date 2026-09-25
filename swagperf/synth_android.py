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


def gen_swagpay_trace(seed=0, *, pkg="com.swag.pay", flow=None, regress=None):
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


# ---------------------------------------------------------- device-shaped trace
#
# gen_swagpay_trace models the app in isolation. Real device traces broke the
# extractors in ways it could not show: they carry every process on the phone
# (an unscoped RAM "peak" was system_server's 803MB), Android 12+ suffixes
# doFrame with a vsync id (an exact match counted zero frames), and the
# per-screen jank split, CPU timeline and transition costs read tables the
# generator never wrote. This one writes them, with a noisy system_server
# alongside, and returns the answers it built in so tests can check the
# numbers rather than just that something came out.

from .synth import _len, _str, _varint


def _process_tree(procs, threads):
    body = b"".join(_len(1, _varint(1, pid) + _varint(2, 1) + _str(3, name))
                    for pid, name in procs)
    # ProcessTree.Thread: tid = 1, name = 2, tgid = 3.
    body += b"".join(_len(2, _varint(1, tid) + _str(2, name) + _varint(3, tgid))
                     for tid, tgid, name in threads)
    return _len(2, body)


def _process_stats(rows):
    """ProcessStats: per-process vm_rss_kb, which becomes `mem.rss`."""
    return _len(9, b"".join(_len(1, _varint(1, pid) + _varint(3, int(kb))) for pid, kb in rows))


def _sched(cpu, ts, prev, nxt):
    """One sched_switch on `cpu`: (pid, comm) -> (pid, comm)."""
    sw = (_str(1, prev[1]) + _varint(2, prev[0]) + _varint(3, 120) + _varint(4, 1)
          + _str(5, nxt[1]) + _varint(6, nxt[0]) + _varint(7, 120))
    return _len(1, _varint(1, cpu) + _len(2, _varint(1, ts) + _varint(2, prev[0]) + _len(4, sw)))


# FrameTimeline jank_type bits, as SurfaceFlinger reports them.
JANK_NONE, JANK_APP, JANK_STUFFING, JANK_DROPPED = 1, 64, 128, 1024


def _frame_timeline(cookie, token, pid, jank):
    exp = _varint(1, cookie) + _varint(2, token) + _varint(3, token) + _varint(4, pid) + _str(5, "app")
    act = (_varint(1, cookie + 1) + _varint(2, token) + _varint(3, token) + _varint(4, pid)
           + _str(5, "app") + _varint(6, 1) + _varint(7, 1) + _varint(9, jank) + _varint(10, 1))
    return _len(76, _len(3, exp)), _len(76, _len(4, act)), \
        _len(76, _len(5, _varint(1, cookie))), _len(76, _len(5, _varint(1, cookie + 1)))


def gen_device_session(seed=0, *, pkg="com.swag.pay", process_name=None, stability=False):
    """A manual session as a real device records it, with the answers.

    Flow: Home -> Send -> Home -> Store -> History, via push/pop/tab markers
    and kind-tagged screen slices. Built-in facts the returned dict exposes:

    * app RSS climbs 200 -> ~320MB; system_server sits at 800MB throughout
    * app frames are named `Choreographer#doFrame <vsync>`; system_server
      renders its own, much slower, frames the whole time
    * Send misses app deadlines, History only buffer-stuffs
    * the first app frame after navigating into Home lands 90ms later,
      into anything else 30ms later
    * with stability=True (synth_stability.Session): a non-fatal JS error
      on Send; a 5 s main-thread stall from 2.9 s that Android declares an
      ANR at its end, on Store; then on History a fatal JS error, the
      Kotlin crash it causes, and a native crash
    """
    rnd = random.Random(seed)
    APP, SYS = 7100, 1500
    T_MAIN, T_SYS = 900, 901
    out = bytearray()
    # process_name models a capture that missed the app's rename: on a V2514
    # the app stayed `zygote64` for its whole life without the task events.
    out += packet(1, _process_tree([(APP, process_name or pkg), (SYS, "system_server")],
                                   [(APP, APP, "swag.pay"), (APP + 1, APP, "RenderThread"),
                                    (SYS, SYS, "system_server")]))
    out += packet(1, track_desc(T_MAIN, process_name or pkg, pid=APP, tid=APP))
    out += packet(1, track_desc(T_SYS, "system_server", pid=SYS, tid=SYS))

    flow = [("Home", "native_view", None, 3000), ("Send", "compose", "open", 2000),
            ("Home", "native_view", "back", 1500), ("Store", "compose", "tab", 1500),
            ("History", "compose", "tab", 1200)]
    jank_for = {"Send": JANK_APP, "History": JANK_STUFFING}
    busy_for = {"Home": 0.6, "Send": 0.4, "Store": 0.2, "History": 0.2}

    t, vsync, cookie, rss = 10 * MS, 1000, 1, 200.0
    prev = None
    expect = {"transitions": {}, "app_jank": {}, "stuffing": {}, "frames": 0, "slow": 0}
    for route, kind, op, dwell_ms in flow:
        nav_t = t
        if prev:
            out += slice_begin(t, T_MAIN, f"nav:{op}-{route}")
            out += slice_end(t + 20_000, T_MAIN)
            # The same transition, emitted twice as the app does: plain and tagged.
            for name in (f"nav:{prev[0]}->{route}", f"nav:{prev[0]}#{prev[1]}->{route}#{kind}"):
                out += slice_begin(t + 30_000, T_MAIN, name)
                out += slice_end(t + 40_000, T_MAIN)
        out += slice_begin(t + 50_000, T_MAIN, f"screen:{route}#{kind}")
        start, end = t + 50_000, t + dwell_ms * MS

        # First frame lands after the transition delay, then every 16.7ms.
        ft = nav_t + (90 if route == "Home" else 30) * MS - 4 * MS if prev else start + MS
        if prev:
            expect["transitions"][(prev[0], route)] = 90.0 if route == "Home" else 30.0
        n = 0
        while ft < end - 20 * MS:
            fdur = 22 * MS if n % 10 == 5 else 4 * MS   # every 10th frame is slow
            out += slice_begin(ft, T_MAIN, f"Choreographer#doFrame {vsync}")
            out += slice_end(ft + fdur, T_MAIN)
            jank = jank_for.get(route, JANK_NONE) if n % 5 == 0 else JANK_NONE
            for pkt in _frame_timeline(cookie, vsync, APP, jank):
                out += packet(ft, pkt)
            if jank == JANK_APP:
                expect["app_jank"][route] = expect["app_jank"].get(route, 0) + 1
            if jank == JANK_STUFFING:
                expect["stuffing"][route] = expect["stuffing"].get(route, 0) + 1
            expect["frames"] += 1
            expect["slow"] += fdur > 16_666_667
            vsync += 1; cookie += 2; n += 1
            ft += int(16_666_667)

        # CPU: the app's main thread runs `busy` of each 100ms on cpu0.
        b = busy_for[route]
        for s in range(start, end - 100 * MS, 100 * MS):
            out += packet(s, _sched(0, s, (0, "swapper"), (APP, "swag.pay")))
            out += packet(s + int(b * 100 * MS), _sched(0, s + int(b * 100 * MS),
                                                       (APP, "swag.pay"), (0, "swapper")))
        # RAM: the app grows on every screen; system_server does not move.
        for s in range(start, end, 250 * MS):
            rss += 1.6 + rnd.uniform(-0.2, 0.2)
            out += packet(s, _process_stats([(APP, rss * 1024), (SYS, 800 * 1024)]))

        out += slice_end(end, T_MAIN)
        t, prev = end + 5 * MS, (route, kind)

    # system_server renders slowly for the whole session: counting its frames
    # as the app's would make the app look janky.
    for ft in range(10 * MS, t, 50 * MS):
        out += slice_begin(ft, T_SYS, f"Choreographer#doFrame {ft}")
        out += slice_end(ft + 40 * MS, T_SYS)

    if stability:
        from .synth_stability import Session
        s = Session(pkg, APP)
        s.js_error(3500, "d1", name="TypeError", message="Cannot read property 'amount' of undefined")
        s.slice(2900, 5000, "binder transaction")
        s.anr(7900, "demo-anr", "Input dispatching timed out (demo "
              f"{pkg}/.MainActivity is not responding. Waited 5001ms for MotionEvent)")
        s.js_error(8600, "d2", name="RangeError", fatal=True, source="promise")
        s.java_crash(8700, exc="com.facebook.react.common.JavascriptException",
                     message="RangeError: amount out of range")
        s.native_crash(9150)
        out += s.bytes()

    expect.update({"pkg": pkg, "app_rss_peak_mb": round(rss, 1), "sys_rss_mb": 800.0,
                   "routes": [f[0] for f in flow]})
    return bytes(out), expect
