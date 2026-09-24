"""xctrace: record an Instruments trace and read its tables back.

xctrace is Instruments from the command line. A recording is a `.trace`
bundle; `xctrace export` writes its table of contents, or any one table, as
XML. That XML deduplicates repeated values: the first occurrence carries
`id="N"` and every later one is an empty `<tag ref="N"/>`. `parse_table`
resolves those, so a row reads as plain values.

Table timestamps are nanoseconds since the recording started, on one clock
across every table of a run.
"""
import copy, subprocess
import xml.etree.ElementTree as ET

XCRUN = "xcrun"

# What a capture records. Each is cheap: the App Launch template's Time
# Profiler and Thread Activity took a 10 s simulator trace to 140-180 MB,
# against 3 MB for these (docs/decisions/0002-ios-via-xctrace-normalised-to-perfetto.md).
#   os_signpost    the app's own markers, and Apple's launch-measurement signposts
#   os_log         the app's error records
#   Hangs          main-thread stalls, at the threshold in HANGS_OPTIONS
#   dyld Activity  pre-main: process start, image loading, static initializers
INSTRUMENTS = ("os_signpost", "os_log", "Hangs", "dyld Activity")

# Apple calls a main-thread stall of 250 ms or more a hang and a shorter one
# down to 100 ms a microhang. The App Launch template records only >500 ms.
HANGS_OPTIONS = {"Hangs": {"detectPriorityInversions": False, "hangsThreshold": 100}}


def record_cmd(*, device, app, out, instruments=INSTRUMENTS, time_limit_s=None,
               options_path=None):
    """The `xctrace record` argv. `app` is the path to the `.app`: on a
    simulator a bare bundle id is taken as a Mac executable name and the
    recording silently targets the Mac instead."""
    cmd = [XCRUN, "xctrace", "record", "--device", device, "--no-prompt",
           "--output", out]
    for name in instruments:
        cmd += ["--instrument", name]
    if options_path:
        cmd += ["--recording-options", options_path]
    if time_limit_s:
        cmd += ["--time-limit", f"{int(time_limit_s * 1000)}ms"]
    return cmd + ["--launch", "--", app]


def record(**kw):
    """Run a recording to its time limit. Returns (returncode, output).

    xctrace exits 0 even when an instrument failed ("Run issues were
    detected"), so callers check the table of contents, not only the code."""
    limit = (kw.get("time_limit_s") or 60) + 180
    try:
        p = subprocess.run(record_cmd(**kw), capture_output=True, text=True, timeout=limit)
    except subprocess.TimeoutExpired as e:
        # Seen once with the Mac under heavy load: xctrace never started
        # recording and the bundle was left without a template. subprocess.run
        # has killed it; say what happened instead of a traceback.
        out = (e.stdout or b"") + (e.stderr or b"")
        tail = out.decode(errors="replace").strip()[-300:] if isinstance(out, bytes) else str(out)[-300:]
        raise RuntimeError(f"xctrace did not finish within {limit} s and was stopped. "
                           f"Check the simulator responds, then capture again. {tail}".strip())
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _export(trace, *args, timeout=180):
    p = subprocess.run([XCRUN, "xctrace", "export", "--input", trace, *args],
                       capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"xctrace export failed: {(p.stderr or p.stdout).strip()[:300]}")
    return p.stdout


def export_toc(trace):
    return _export(trace, "--toc")


def table_xpath(schema, run=1, where=""):
    """XPath for one table. `where` adds attribute tests: a run can hold two
    tables of one schema (os-log comes both filtered and unfiltered)."""
    extra = f" and {where}" if where else ""
    return f'/trace-toc/run[@number="{run}"]/data/table[@schema="{schema}"{extra}]'


def export_table(trace, schema, run=1, where=""):
    return _export(trace, "--xpath", table_xpath(schema, run, where))


# ------------------------------------------------------------------ parsing

def parse_toc(xml):
    """The parts of a table of contents a capture needs: what was recorded,
    on what, for how long, how it ended, and which tables exist."""
    root = ET.fromstring(xml)
    run = root.find("run")
    if run is None:
        return {}
    info = run.find("info")
    target = info.find("target") if info is not None else None
    summary = info.find("summary") if info is not None else None

    def attrs(el):
        return dict(el.attrib) if el is not None else {}

    def text(tag):
        el = summary.find(tag) if summary is not None else None
        return (el.text or "").strip() or None if el is not None else None

    device = attrs(target.find("device")) if target is not None else {}
    proc = attrs(target.find("process")) if target is not None else {}
    duration = text("duration")
    tables = []
    for t in run.iter("table"):
        a = dict(t.attrib)
        if a.get("schema"):
            tables.append(a)
    return {
        "device": {
            "platform": device.get("platform"), "model": device.get("model"),
            "name": device.get("name"), "os_version": device.get("os-version"),
            "udid": device.get("uuid"), "memory_bytes": _int(device.get("memory-size")),
        },
        "host": attrs(target.find("host-device")) if target is not None else {},
        "process": {
            "name": proc.get("name"), "pid": _int(proc.get("pid")),
            "type": proc.get("type"), "exit_status": _int(proc.get("return-exit-status")),
            "termination_reason": proc.get("termination-reason"),
        } if proc else {},
        "start_date": text("start-date"),
        "end_date": text("end-date"),
        "duration_s": float(duration) if duration else None,
        "end_reason": text("end-reason"),
        "instruments_version": text("instruments-version"),
        "template": text("template-name"),
        "schemas": sorted({t["schema"] for t in tables}),
        "tables": tables,
    }


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _cell(el, ids):
    """One value as {tag, fmt, text, kids}; `kids` holds nested values by tag
    (a thread carries its tid and process). A <sentinel/> is an empty cell."""
    ref = el.get("ref")
    if ref is not None:
        return ids.get(ref)
    if el.tag == "sentinel":
        return None
    c = {"tag": el.tag, "fmt": el.get("fmt"), "text": (el.text or "").strip(), "kids": {}}
    for k in el:
        kc = _cell(k, ids)
        if kc is not None:
            c["kids"].setdefault(kc["tag"], kc)
    if el.get("id") is not None:
        ids[el.get("id")] = c
    return c


def parse_table(source):
    """Rows of an exported table as {column mnemonic: cell}. Streams, so a
    large table is never held as a tree. Several tables in one export are
    read in order, each row against its own table's columns."""
    ids, cols, rows = {}, [], []
    for event, el in ET.iterparse(source if hasattr(source, "read") else _as_file(source),
                                  events=("start", "end")):
        if event == "start":
            if el.tag == "schema":
                cols = []
            continue
        if el.tag == "mnemonic":
            cols.append((el.text or "").strip())
        elif el.tag == "row":
            rows.append({c: _cell(k, ids) for c, k in zip(cols, list(el))})
            el.clear()
    return rows


def _as_file(text):
    import io
    return io.BytesIO(text.encode() if isinstance(text, str) else text)


# Cell accessors. Every one tolerates a missing cell.

def fmt(c):
    return c.get("fmt") if c else None


def raw(c):
    return c.get("text") if c else None


def num(c):
    """The raw numeric value (nanoseconds, a pid, a tid), or None."""
    try:
        return int(c["text"]) if c and c.get("text") not in (None, "") else None
    except ValueError:
        return None


def kid(c, tag):
    return (c or {}).get("kids", {}).get(tag)


# --------------------------------------------------------------- fixtures

def trim_export(xml, keep, blank=()):
    """A smaller, still self-consistent export: only rows where keep(row) is
    true, with any value a kept row refers to but whose definition was in a
    dropped row copied in place. Columns named in `blank` (backtraces,
    narratives) are emptied. For turning real exports into test fixtures.
    `keep` receives the parsed row (as parse_table gives it)."""
    root = ET.fromstring(xml)
    cols = [(m.text or "").strip() for m in root.iter("mnemonic")]
    blank_at = {i for i, c in enumerate(cols) if c in blank}
    defs = {el.get("id"): el for el in root.iter() if el.get("id") is not None}
    parsed = parse_table(xml)
    i = 0
    emitted = set()

    def materialise(el):
        for child in list(el):
            ref = child.get("ref")
            if ref is not None and ref not in emitted:
                full = copy.deepcopy(defs[ref])
                el[list(el).index(child)] = full
                emitted.update(e.get("id") for e in full.iter() if e.get("id"))
                materialise(full)
            elif child.get("id") is not None:
                emitted.add(child.get("id"))
                materialise(child)
            else:
                materialise(child)

    for node in root.iter("node"):
        for row in list(node.findall("row")):
            if keep(parsed[i]):
                for j in blank_at:
                    if j < len(row):
                        row[j] = ET.Element("sentinel")
                materialise(row)
            else:
                node.remove(row)
            i += 1
    return ET.tostring(root, encoding="unicode")
