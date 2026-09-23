"""Synthetic Swag Pay trace generator.

Emits real Perfetto protobuf traces modelling the three-runtime process described
in the shell architecture: the Compose/CMP shell, the Hermes/Fabric runtime and
the native camera stack. Used to develop and test the analysis SQL without a
device, and to seed history for dashboard work.
"""
import random, struct

def _vi(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)

def _tag(f, w): return _vi((f << 3) | w)
def _len(f, payload): return _tag(f, 2) + _vi(len(payload)) + payload
def _varint(f, v): return _tag(f, 0) + _vi(v)
def _str(f, s): return _len(f, s.encode())

# TracePacket field numbers
P_TIMESTAMP, P_TRACK_EVENT, P_TRUSTED_PACKET_SEQ, P_INTERNED, P_TRACK_DESC = 8, 11, 10, 12, 60
# TrackEvent
TE_CATS, TE_NAME, TE_TYPE, TE_TRACK_UUID, TE_NAME_IID = 22, 23, 9, 11, 10
TYPE_BEGIN, TYPE_END, TYPE_INSTANT, TYPE_COUNTER = 1, 2, 3, 4
TE_COUNTER_VALUE = 30


def track_desc(uuid, name, parent=None, pid=None, tid=None, counter=False):
    d = _varint(1, uuid) + _str(2, name)
    if parent: d += _varint(5, parent)
    if pid is not None:
        d += _len(3, _varint(1, pid) + _str(6, name))
    if tid is not None:
        d += _len(4, _varint(1, pid) + _varint(2, tid) + _str(5, name))
    if counter: d += _len(8, b"")
    return _len(P_TRACK_DESC, d)


def packet(ts, body, seq=1):
    return _len(1, _varint(P_TIMESTAMP, ts) + body + _varint(P_TRUSTED_PACKET_SEQ, seq))


def slice_begin(ts, uuid, name):
    te = _varint(TE_TYPE, TYPE_BEGIN) + _varint(TE_TRACK_UUID, uuid) + _str(TE_NAME, name)
    return packet(ts, _len(P_TRACK_EVENT, te))


def slice_end(ts, uuid):
    te = _varint(TE_TYPE, TYPE_END) + _varint(TE_TRACK_UUID, uuid)
    return packet(ts, _len(P_TRACK_EVENT, te))


def counter(ts, uuid, value):
    te = _varint(TE_TYPE, TYPE_COUNTER) + _varint(TE_TRACK_UUID, uuid) + _varint(TE_COUNTER_VALUE, int(value))
    return packet(ts, _len(P_TRACK_EVENT, te))


MS = 1_000_000  # ns per ms

# Track uuids
T_MAIN, T_JS, T_CAM, T_RSS, T_HEAP = 10, 11, 12, 20, 21


def gen_trace(seed=0, *, path="returning_user", regress=None, duration_scan_s=6):
    """Build a Swag Pay trace.

    path: 'returning_user' (camera on critical path, RN deferred) or
          'first_run' (onboarding is an RN surface, Host starts immediately).
    regress: optional dict of step-name -> multiplier, to simulate a regression.
    """
    rnd = random.Random(seed)
    regress = regress or {}
    out = bytearray()
    pid = 4242

    out += packet(0, track_desc(T_MAIN, "com.swag.pay", pid=pid, tid=pid))
    out += packet(0, track_desc(T_JS, "mqt_js", pid=pid, tid=pid + 1))
    out += packet(0, track_desc(T_CAM, "CameraX", pid=pid, tid=pid + 2))
    out += packet(0, track_desc(T_RSS, "mem.rss", counter=True))
    out += packet(0, track_desc(T_HEAP, "mem.hermes_heap", counter=True))

    def j(base, name):
        """jittered duration in ns, with optional injected regression"""
        m = regress.get(name, 1.0)
        return int(base * MS * m * rnd.uniform(0.92, 1.10))

    t = 5 * MS
    marks = []  # (step, track, start, end)

    def step(name, track, dur_ms, children=()):
        nonlocal t
        start = t
        out_local = bytearray()
        out_local += slice_begin(start, track, name)
        inner = start
        d = j(dur_ms, name)
        for cname, cdur in children:
            cd = j(cdur, cname)
            out_local += slice_begin(inner, track, cname)
            out_local += slice_end(inner + cd, track)
            inner += cd
        end = max(start + d, inner)
        out_local += slice_end(end, track)
        marks.append((name, start, end))
        t = end
        return bytes(out_local)

    if path == "returning_user":
        # CRITICAL PATH — budgeted. Nothing expensive before first camera frame.
        out += step("step:bootstrap", T_MAIN, 42, [("Zygote.fork", 12), ("Application.onCreate", 22)])
        out += step("step:session_read", T_MAIN, 18, [("AppStorage.read", 14)])
        out += step("step:compose_shell", T_MAIN, 95,
                    [("ComposeView.inflate", 30), ("Recomposer.firstFrame", 48)])
        out += step("step:camera_open", T_CAM, 130,
                    [("CameraX.bindToLifecycle", 70), ("Surface.configure", 44)])
        out += step("step:first_qr_decode", T_CAM, 88, [("MLKit.process", 74)])
        first_frame_ts = t
        # DEFERRED — must not block. Starts only after first usable camera frame.
        out += step("step:hermes_boot", T_JS, 210, [("JSBundle.parse", 120), ("TurboModule.init", 40)])
        out += step("step:cronet_init", T_MAIN, 64)
        out += step("step:remote_config", T_MAIN, 38)
    else:
        # FIRST RUN — order inverts, RN onboarding is on the critical path.
        out += step("step:bootstrap", T_MAIN, 44, [("Zygote.fork", 12), ("Application.onCreate", 24)])
        out += step("step:hermes_boot", T_JS, 240, [("JSBundle.parse", 140), ("TurboModule.init", 44)])
        out += step("step:rn_onboarding_surface", T_JS, 180,
                    [("Surface.start", 40), ("Fabric.mount", 95)])
        first_frame_ts = t
        out += step("step:compose_shell", T_MAIN, 90)
        out += step("step:camera_open", T_CAM, 128)

    # Steady-state: sustained scanning, frame pacing at the interop seam.
    frame_budget = 16_666_667
    n = int(duration_scan_s * 60)
    jank = slow = 0
    for i in range(n):
        drift = 1.0 + (i / n) * regress.get("thermal_drift", 0.0)
        dur = int(rnd.gauss(9.5, 2.2) * MS * drift)
        if rnd.random() < 0.035 * (1 + regress.get("interop_jank", 0.0)):
            dur = int(rnd.uniform(18, 46) * MS * drift)
        dur = max(dur, 2 * MS)
        out += slice_begin(t, T_MAIN, "Choreographer#doFrame")
        out += slice_begin(t, T_MAIN, "MLKit.process")
        out += slice_end(t + int(dur * 0.55), T_MAIN)
        out += slice_end(t + dur, T_MAIN)
        if dur > frame_budget:
            slow += 1
        if dur > 3 * frame_budget:
            jank += 1
        t += max(dur, frame_budget)

    # Memory counters — all three runtimes resident.
    rss_base = 210 if path == "returning_user" else 240
    for k in range(60):
        ts = int(k * (t / 60))
        growth = k * 0.9 * (1 + regress.get("mem_leak", 0.0))
        out += counter(ts, T_RSS, int((rss_base + growth + rnd.uniform(-4, 4)) * 1024 * 1024))
        out += counter(ts, T_HEAP, int((38 + k * 0.25) * 1024 * 1024))

    return bytes(out), {"first_frame_ns": first_frame_ts, "slow_frames": slow,
                        "janky_frames": jank, "total_frames": n}
