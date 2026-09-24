"""Synthetic iOS recordings, as parsed xctrace tables with known answers.

The iOS counterpart of synth_android.py. It builds the rows xctrace.parse_table
would return for an Instruments recording of an app launch -- dyld's pre-main
intervals, Apple's launch-measurement signposts, the app's own SwagTrace
signposts and Hangs rows -- so convert_ios.py and everything downstream can
be tested without Xcode or a simulator. Real exports, trimmed, live in
tests/fixtures/ios/ for the shapes this cannot vouch for.
"""
from . import convert_ios

MS = 1_000_000


def cell(fmt, text=None, **kids):
    """One parsed value, the shape xctrace.parse_table gives."""
    return {"tag": "v", "fmt": fmt, "text": str(fmt if text is None else text),
            "kids": {k: v for k, v in kids.items()}}


def _thread(pid, tid, name="Main Thread"):
    return cell(f"{name} (0x{tid:x}) (App, pid: {pid})",
                tid=cell(f"0x{tid:x}", tid),
                process=cell(f"App ({pid})", pid=cell(str(pid), pid)))


class Recording:
    """Accumulates rows; times in milliseconds from the recording's start."""

    def __init__(self, pid=4242, main_tid=100):
        self.pid, self.main = pid, main_tid
        self.signposts, self.dyld, self.hangs, self.logs = [], [], [], []
        self._ids = 1

    # -- signposts
    def _sp(self, t_ms, kind, name, message="", *, sub=convert_ios.APP_SUBSYSTEM,
            category="SwagTrace", ident=None, tid=None):
        self.signposts.append({
            "time": cell(f"{t_ms}ms", int(t_ms * MS)),
            "thread": _thread(self.pid, tid or self.main),
            "event-type": cell(kind), "name": cell(name),
            "subsystem": cell(sub), "category": cell(category),
            "identifier": cell(str(ident or "OS_SIGNPOST_ID_EXCLUSIVE"), ident or 0),
            "message": cell(message) if message else None})

    def span(self, name, start_ms, dur_ms, tid=None):
        self._ids += 1
        ident = 0x1000 + self._ids
        self._sp(start_ms, "Begin", "span", name, ident=ident, tid=tid)
        self._sp(start_ms + dur_ms, "End", "span", ident=ident, tid=tid)

    def open_span(self, name, start_ms, tid=None):
        self._ids += 1
        self._sp(start_ms, "Begin", "span", name, ident=0x1000 + self._ids, tid=tid)

    def unmatched_end(self, t_ms):
        self._sp(t_ms, "End", "span", ident=0xDEAD)

    def async_slice(self, family, name, start_ms, end_ms=None):
        ident = {"screen": 0x5747, "sub": 0x5748, "nav": 0x5749}[family]
        self._sp(start_ms, "Begin", family, name, ident=ident)
        if end_ms is not None:
            self._sp(end_ms, "End", family, name, ident=ident)

    def instant(self, name, t_ms):
        self._sp(t_ms, "Event", "event", name)

    def counter(self, name, value, t_ms):
        self._sp(t_ms, "Event", "counter", f"{name}={value}")

    # -- launch
    def launch(self, *, start_ms=500, pre_main_ms=300, main_to_ff_ms=400,
               responsive_ms=40, static_inits=(("libSystem.B.dylib", 120), ("React", 30))):
        """dyld's intervals and Apple's launch signposts for one cold launch.
        Returns the expected startup time (process start to first frame)."""
        def dy(t, dur, level, kind, desc):
            self.dyld.append({"start": cell(f"{t}ms", int(t * MS)),
                              "duration": cell(f"{dur}ms", int(dur * MS)),
                              "level": cell(str(level)), "type": cell(kind),
                              "description": cell(desc),
                              "thread": _thread(self.pid, self.main)})
        dy(start_ms, 10_000, 1, "Launch Executable", "Launch Executable")
        dy(start_ms + 1, pre_main_ms - 1, 2, "Launch Executable", "Launch Executable")
        t = start_ms + 5
        for lib, dur in static_inits:
            dy(t, dur, 3, "Static Initializer", f"Run static initializer 0x1 {lib}")
            t += dur + 1
        ff = start_ms + pre_main_ms + main_to_ff_ms
        self._sp(ff, "End", "ApplicationFirstFramePresentation",
                 sub=convert_ios.LAUNCH_SUBSYSTEM, category="ApplicationLaunch", ident=0x45)
        self._sp(ff + responsive_ms, "End", "ApplicationFirstFramePresentationResponsive",
                 sub=convert_ios.LAUNCH_SUBSYSTEM, category="ApplicationLaunch", ident=0x45)
        return pre_main_ms + main_to_ff_ms

    # -- JS errors, as the app reports them (errorReporting.ts, SwagErrors)
    def js_error(self, t_ms, *, name="TypeError", source="global", fatal=False,
                 message="boom", stack="TypeError: boom\n    at pay (address at main.jsbundle:1:48213)",
                 err_id=None, chunk=800, drop_chunk=None):
        """The marker and the chunked log lines for one error. `drop_chunk`
        loses one line, as a truncated log would. Returns the id."""
        import json
        self._ids += 1
        err_id = err_id or f"e{self._ids}"
        self.instant(f"error:js:{source}:{name}#{'fatal' if fatal else 'nonfatal'}@{err_id}", t_ms)
        text = json.dumps({"id": err_id, "name": name, "message": message, "stack": stack,
                           "component_stack": None, "fatal": fatal, "source": source})
        chunks = [text[i:i + chunk] for i in range(0, len(text), chunk)] or [""]
        for i, c in enumerate(chunks, 1):
            if i == drop_chunk:
                continue
            self.logs.append({"time": cell(f"{t_ms}ms", int(t_ms * MS) + i),
                              "thread": _thread(self.pid, self.main),
                              "subsystem": cell(convert_ios.APP_SUBSYSTEM),
                              "category": cell(convert_ios.ERROR_CATEGORY),
                              "message": cell(f"swagerr|{err_id}|{i}/{len(chunks)}|{c}")})
        return err_id

    # -- hangs
    def hang(self, start_ms, dur_ms, kind=None):
        kind = kind or ("Hang" if dur_ms >= 250 else "Microhang")
        self.hangs.append({"start": cell(f"{start_ms}ms", int(start_ms * MS)),
                           "duration": cell(f"{dur_ms}ms", int(dur_ms * MS)),
                           "hang-type": cell(kind), "thread": _thread(self.pid, self.main)})

    def tables(self):
        return {"os-signpost": self.signposts, "dyld-activity-interval": self.dyld,
                "potential-hangs": self.hangs, "os-log": self.logs}

    def convert(self, *, bundle_id="com.example.ios", simulator=True, memory=None,
                end_ms=None, crashed=None):
        source = {"platform": "ios", "simulator": int(simulator), "device": "iPhone 17",
                  "os": "27.0", "xctrace": "27.0"}
        if crashed:
            source.update(crashed=1, termination=crashed)
        return convert_ios.convert(
            self.tables(), bundle_id=bundle_id, pid=self.pid, source=source,
            memory=memory, end_ns=int(end_ms * MS) if end_ms else None)


def gen_ios_trace(seed=0, *, bundle_id="com.example.ios", simulator=True,
                  pre_main_ms=300, main_to_ff_ms=400, rss_mb=(80, 140)):
    """A launch plus a short session: Home, then Pay, with RAM rising.
    Returns (trace bytes, expected)."""
    r = Recording()
    ttid = r.launch(pre_main_ms=pre_main_ms, main_to_ff_ms=main_to_ff_ms)
    r.instant("step:returning_bootstrap", 1250)
    r.async_slice("screen", "screen:Home#compose", 1300, 4000)
    r.async_slice("nav", "nav:Home->Pay", 3990, 4050)
    r.async_slice("screen", "screen:Pay#compose", 4000)          # open at the end
    r.span("action:scan", 1400, 200)
    lo, hi = rss_mb
    memory = [(int(t * MS), (lo + (hi - lo) * i / 50) * 1024 * 1024)
              for i, t in enumerate(range(1200, 6200, 100))]
    data, rep = r.convert(bundle_id=bundle_id, simulator=simulator, memory=memory, end_ms=6500)
    return data, {"ttid_ms": ttid, "report": rep,
                  "peak_mb": round(max(v for _, v in memory) / 2**20, 1),
                  "min_mb": round(min(v for _, v in memory) / 2**20, 1)}
