"""Turn build outputs into the committed symbolicate fixtures.

    python3 assemble.py <work dir> <fixtures dir>

The work dir holds what regenerate.sh built and captured (see there). This
script rewrites build-machine paths to neutral ones, drops sourcesContent,
trims the multi-megabyte Swag Pay maps down to the mappings the captured
stacks touch, writes the hand-made index-map and RAM-bundle maps, and writes
spec.json for golden.js. It never changes a mapping a lookup in the spec can
reach: a trimmed map keeps, for every queried position, the mappings at the
lookup's column and at the next column after it (see trim()).
"""
import bisect, json, os, re, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..", "..")))
from swagperf import symbolicate as sym  # noqa: E402

WORK, OUT = sys.argv[1], sys.argv[2]
APP = os.environ.get("APP_RN") or os.path.expanduser("~/Documents/swag-pay/apps/mobile/react-native")
NM = APP + "/node_modules"
# Where regenerate.sh puts the iOS JS bundle, standing in for Xcode's build
# products directory (its path is in the debug-info stacks).
PRODUCTS = WORK + "/ios/Release-iphonesimulator"

B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


def vlq(n):
    n = (-n << 1) | 1 if n < 0 else n << 1
    out = ""
    while True:
        digit, n = n & 31, n >> 5
        out += B64[digit | (32 if n else 0)]
        if not n:
            return out


def encode_mappings(lines):
    """lines: per generated line, a list of (col, src, oline0, ocol, name)
    with None for a generated-only segment. oline0 is 0-based."""
    out, src, oline, ocol, name = [], 0, 0, 0, 0
    for row in lines:
        segs, gcol = [], 0
        for col, s, ol, oc, nm in row:
            seg = vlq(col - gcol)
            gcol = col
            if s is not None:
                seg += vlq(s - src) + vlq(ol - oline) + vlq(oc - ocol)
                src, oline, ocol = s, ol, oc
                if nm is not None:
                    seg += vlq(nm - name)
                    name = nm
            segs.append(seg)
        out.append(",".join(segs))
    return ";".join(out)


def encode_function_map(entries):
    """entries: (line, col, name index), sorted. Metro's format: ';' starts
    a group and resets the column, lines move by explicit deltas."""
    groups, line, col, name, cur = [], 1, 0, 0, None
    for ln, c, nm in entries:
        if cur is None or ln != line:
            cur, col = [], 0
            groups.append(cur)
            cur.append(vlq(c - col) + vlq(nm - name) + vlq(ln - line))
        else:
            cur.append(vlq(c - col) + vlq(nm - name))
        line, col, name = ln, c, nm
    return ";".join(",".join(g) for g in groups)


def load(path):
    with open(path) as fh:
        return json.load(fh)


def write_json(path, obj, compact=True):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        if compact:
            json.dump(obj, fh, separators=(",", ":"))
        else:
            json.dump(obj, fh, indent=1)
        fh.write("\n")


def rewrite(text, pairs):
    for old, new in pairs:
        text = text.replace(old, new)
    return text


def clean_map(raw, pairs):
    raw = dict(raw)
    raw.pop("sourcesContent", None)
    raw["sources"] = [rewrite(s, pairs) for s in raw["sources"]]
    if "file" in raw:
        raw["file"] = rewrite(raw["file"], pairs)
    return raw


def decode_rows(raw):
    """Per generated line, the segments in source-map's lookup order, with
    source/name indices into the raw arrays."""
    basic = sym._BasicMap(raw)
    rows = []
    for cols, entries in zip(basic._cols, basic._entries):
        rows.append([(c,) + (e if e is not None else (None, None, None, None))
                     for c, e in zip(cols, entries)])
    return rows


def trim(raw, points):
    """Keep only what lookups at `points` ((line, 0-based col)) can reach:
    on each queried line, every mapping at the lookup's column and at the
    next column after it. Lookups (greatest lower bound, first of equals)
    and exact/inside/before/after probes then answer as on the full map."""
    rows = decode_rows(raw)
    keep = set()
    for line, col in points:
        if not 1 <= line <= len(rows) or not rows[line - 1]:
            continue
        cols = [m[0] for m in rows[line - 1]]
        i = bisect.bisect_right(cols, col) - 1
        wanted = {cols[i]} if i >= 0 else set()
        j = bisect.bisect_right(cols, col)
        if j < len(cols):
            wanted.add(cols[j])
        if i < 0:
            wanted.add(cols[0])
        for k, c in enumerate(cols):
            if c in wanted:
                keep.add((line - 1, k))
    src_map, name_map = {}, {}
    new_rows = []
    for li, row in enumerate(rows):
        new_row = []
        for k, (c, s, ol, oc, nm) in enumerate(row):
            if (li, k) not in keep:
                continue
            if s is not None:
                s = src_map.setdefault(s, len(src_map))
                if nm is not None:
                    nm = name_map.setdefault(nm, len(name_map))
                new_row.append((c, s, ol - 1, oc, nm))
            else:
                new_row.append((c, None, None, None, None))
        new_rows.append(new_row)
    while new_rows and not new_rows[-1]:
        new_rows.pop()
    old_src = sorted(src_map, key=src_map.get)
    old_names = sorted(name_map, key=name_map.get)
    out = {"version": 3,
           "sources": [raw["sources"][i] for i in old_src],
           "names": [raw["names"][i] for i in old_names],
           "mappings": encode_mappings(new_rows)}
    if "x_facebook_sources" in raw:
        fb = raw["x_facebook_sources"] or []
        out["x_facebook_sources"] = [fb[i] if i < len(fb) else None for i in old_src]
    ignored = set(raw.get("x_google_ignoreList") or [])
    listed = [n for n, i in enumerate(old_src) if i in ignored]
    if listed:
        out["x_google_ignoreList"] = listed
    if "x_hermes_function_offsets" in raw:
        out["x_hermes_function_offsets"] = raw["x_hermes_function_offsets"]
    return out


BLOCK = re.compile(r"@@(STACK ([^\n]*)|UNCAUGHT)\n(.*?)\n@@END", re.S)


def stacks_from(path, pairs):
    """The host's output as [{id, text}]: one per printed or uncaught error."""
    out, n = [], 0
    for m in BLOCK.finditer(open(path).read()):
        label = m.group(2)
        if label is None:
            n += 1
            label = "uncaught" if n == 1 else f"uncaught_{n}"
        out.append({"id": label, "text": rewrite(m.group(3), pairs)})
    return out


# Every (line, col) metro-symbolicate's text regex queries in a stack, and
# the ones this module queries, so a trimmed map answers both as the full.
METRO_RE = re.compile(r"(?:([^@: \n(]+)(@|:))?(?:(?:([^@: \n(]+):)?(\d+):(\d+)|\[native code\])")


def query_points(stacks, input_column_start=0):
    pts = set()
    for st in stacks:
        for m in METRO_RE.finditer(st["text"]):
            if m.group(4) is not None:
                pts.add((int(m.group(4)), int(m.group(5)) - input_column_start))
        for f in sym.parse_stack(st["text"]):
            if f["kind"] in ("bytecode", "internal"):
                pts.add((f["line"], f["col"]))
            elif f["kind"] == "source":
                pts.add((f["line"], f["col"] - 1))
    return pts


def crash_callstack(stacks, raw, url):
    """A --hermes-crash callstack for the bundle frames of `stacks`: each
    offset split into the function that holds it and the offset inside it,
    as a Hermes crash report records a frame."""
    starts = raw["x_hermes_function_offsets"]["0"]
    out = []
    for st in stacks:
        for f in sym.parse_stack(st["text"]):
            if f["kind"] == "bytecode":
                fid = bisect.bisect_right(starts, f["col"]) - 1
                out.append({"SegmentID": 0, "FunctionID": fid, "ByteCodeOffset": f["col"] - starts[fid],
                            "SourceURL": url, "StackFrameRegOffs": "0"})
            elif f["kind"] == "native":
                out.append({"NativeCode": True, "StackFrameRegOffs": "0"})
    return out


spec = {"stacks": [], "positions": [], "crashes": []}


def add_stacks(stacks_rel, map_rel, ics=0, group=None):
    spec["stacks"].append({"id": group, "stacks": stacks_rel, "map": map_rel, "inputColumnStart": ics})


# ------------------------------------------------------------ synthetic builds
roots = {"v1": "/Users/dev/swagpay-fixture", "v2": "/home/ci/work/swagpay-fixture"}
names = {"v1": "index.android.bundle", "v2": "main.jsbundle"}
synthetic = {}
for v in ("v1", "v2"):
    root, name = roots[v], names[v]
    work = os.path.join(WORK, "work", v)
    pairs = [(NM, root + "/node_modules"), (work + "/proj", root), (work + "/out", root + "/build")]
    d = os.path.join(OUT, "synthetic", v)
    os.makedirs(d, exist_ok=True)
    composed = clean_map(load(f"{work}/out/{name}.composed.map"), pairs)
    write_json(f"{d}/{name}.map", composed)
    stacks = stacks_from(f"{work}/out/stacks.txt", pairs)
    write_json(f"{d}/stacks.json", stacks, compact=False)
    add_stacks(f"synthetic/{v}/stacks.json", f"synthetic/{v}/{name}.map", group=v)
    synthetic[v] = (composed, stacks)
    if v == "v1":
        shutil.copyfile(f"{work}/out/{name}", f"{d}/{name}")
        write_json(f"{d}/{name}.packager.map", clean_map(load(f"{work}/out/{name}.packager.map"), pairs))
        wd = stacks_from(f"{work}/out/stacks.withdebug.txt", pairs)
        write_json(f"{d}/stacks.withdebug.json", wd, compact=False)
        add_stacks(f"synthetic/{v}/stacks.withdebug.json", f"synthetic/{v}/{name}.packager.map", ics=1,
                   group="v1-withdebug")
        spec["crashes"].append({"id": "v1", "map": f"synthetic/{v}/{name}.map",
                                "callstack": crash_callstack(stacks, composed, name)})

# ----------------------------------------------------------- Swag Pay, real
# probe.*.js reach app modules by Metro module id. The ids were found by
# walking the bundle's `__d(...)` factories (`},ID,[deps]);` closes each) and
# looking up a line inside each in the packager map: iOS 517 surfaceRoute.ts,
# 545 contactsDirectory.ts, 542 money.ts; Android 520, 548, 545.
real_pairs = [(WORK + "/probe.android.js", "/probe/probe.js"), (WORK + "/probe.ios.js", "/probe/probe.js"),
              (PRODUCTS, "/Users/dev/Library/Developer/Xcode/DerivedData/iosApp/Build/Products/Release-iphonesimulator"),
              (APP, "/Users/dev/swag-pay/apps/mobile/react-native")]
ios_stacks = stacks_from(f"{WORK}/ios/stack.real.txt", real_pairs)
android_stacks = stacks_from(f"{WORK}/android/stack.real.txt", real_pairs)
both = query_points(ios_stacks) | query_points(android_stacks)
d = os.path.join(OUT, "swagpay")
for plat, full, stacks, name in (
        ("ios", f"{WORK}/ios/main.composed.map", ios_stacks, "main.jsbundle"),
        ("android", f"{WORK}/android/index.android.bundle.map", android_stacks, "index.android.bundle")):
    raw = load(full)
    # Trimmed for both platforms' stacks, so each map also answers the other
    # platform's offsets exactly as the full map would (the mismatch test).
    trimmed = clean_map(trim(raw, both), real_pairs)
    write_json(f"{d}/{plat}.map", trimmed)
    write_json(f"{d}/{plat}.stacks.json", stacks, compact=False)
    add_stacks(f"swagpay/{plat}.stacks.json", f"swagpay/{plat}.map", group=f"swagpay-{plat}")
    spec["crashes"].append({"id": f"swagpay-{plat}", "map": f"swagpay/{plat}.map",
                            "callstack": crash_callstack(stacks, raw, name)})
wd = stacks_from(f"{WORK}/ios/stack.withdebug.txt", real_pairs)
pk = trim(load(f"{WORK}/ios/main.jsbundle.packager.map"), query_points(wd, 1) | query_points(wd, 0))
write_json(f"{d}/ios.packager.map", clean_map(pk, real_pairs))
write_json(f"{d}/ios.withdebug.stacks.json", wd, compact=False)
add_stacks("swagpay/ios.withdebug.stacks.json", "swagpay/ios.packager.map", ics=1, group="swagpay-ios-withdebug")

# ----------------------------------------------------------------- index map
# Four sections: two on one generated line (the second at column 20, where
# source-map's boundary quirk shows), a sourceRoot, an ignore-listed
# node_modules source, and a nested index map.
def section_map(sources, names, rows, fmaps=None, **extra):
    m = {"version": 3, "sources": sources, "names": names, "mappings": encode_mappings(rows)}
    if fmaps is not None:
        m["x_facebook_sources"] = [None if f is None else [{"names": f[0], "mappings": encode_function_map(f[1])}]
                                   for f in fmaps]
    m.update(extra)
    return m


a = section_map(["/app/src/a.js"], ["alpha", "beta", "gamma"],
                [[(0, 0, 0, 0, None), (6, 0, 0, 9, 0), (15, 0, 1, 2, 1)],
                 [(0, 0, 2, 0, None), (4, 0, 3, 4, 2), (30, None, None, None, None)],
                 [(2, 0, 4, 0, 1)]],
                fmaps=[(["<global>", "alpha", "beta"], [(1, 0, 0), (1, 9, 1), (3, 0, 2), (4, 6, 0)])])
b = section_map(["/app/src/b.js", "/app/node_modules/lib/index.js"], ["render", "helper"],
                [[(0, 0, 0, 0, 0), (8, 1, 10, 4, 1), (14, 0, 0, 12, None)],
                 [(3, 1, 11, 0, None)]],
                fmaps=[(["Screen#render"], [(1, 0, 0)]), (["helper"], [(1, 0, 0)])],
                x_google_ignoreList=[1])
c = section_map(["c.js", "./lib/../d.js"], ["onPress"],
                [[(0, 0, 5, 1, 0), (5, 1, 7, 3, None), (11, 0, 6, 0, None)]],
                fmaps=[(["Button.onPress", "<anonymous>"], [(6, 0, 0), (6, 1, 1)]), None],
                sourceRoot="/app/src/")
inner = {"version": 3, "sections": [
    {"offset": {"line": 0, "column": 4}, "map": section_map(
        ["/app/src/e.ts"], ["deep"], [[(0, 0, 20, 2, 0), (9, 0, 21, 0, None)], [(1, 0, 22, 5, 0)]],
        fmaps=[(["deep"], [(21, 0, 0)])])}]}
index_map = {"version": 3, "sections": [
    {"offset": {"line": 0, "column": 0}, "map": a},
    {"offset": {"line": 3, "column": 0}, "map": b},
    {"offset": {"line": 3, "column": 20}, "map": c},
    {"offset": {"line": 5, "column": 0}, "map": inner}]}
write_json(os.path.join(OUT, "maps", "index.map"), index_map, compact=False)
spec["positions"].append({"id": "index", "map": "maps/index.map",
                          "points": [[ln, col] for ln in range(1, 9) for col in range(0, 42)]})

# --------------------------------------------------------- RAM bundle map
ram = section_map(["/app/src/main.js"], ["start"],
                  [[(0, 0, 0, 0, 0)], [(0, 0, 1, 0, None)], [(0, 0, 2, 0, None), (6, 0, 2, 8, 0)],
                   [(0, 0, 3, 0, None)], [(0, 0, 4, 0, None)], [(0, 0, 5, 0, None)]],
                  x_facebook_offsets=[0, 2, 4])
ram["x_facebook_segments"] = {"1": section_map(["/app/src/seg1.js"], ["segFn"],
                                               [[(0, 0, 0, 0, 0)], [(0, 0, 1, 0, None)], [(0, 0, 2, 0, 0)]],
                                               x_facebook_offsets=[0, 1])}
write_json(os.path.join(OUT, "maps", "ram.map"), ram, compact=False)
write_json(os.path.join(OUT, "maps", "ram.stacks.json"), [{"id": "modules", "text": "\n".join([
    "Error: from a RAM bundle",
    "    at start (0.js:1:1)",
    "    at b (1.js:1:1)",
    "    at c (2.js:2:7)",
    "    at d (seg-1.js:2:1)",
    "    at e (seg-1_1.js:2:1)",
    "    at f (main.js:3:9)"])}], compact=False)
add_stacks("maps/ram.stacks.json", "maps/ram.map", ics=1, group="ram")

write_json(os.path.join(OUT, "spec.json"), spec, compact=False)
print("stack files", len(spec["stacks"]), "positions", sum(len(p["points"]) for p in spec["positions"]),
      "crashes", len(spec["crashes"]))
