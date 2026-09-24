"""Symbolicate JavaScript error stacks from React Native release builds.

Release builds run Hermes bytecode, not JavaScript, so a JS error's stack
reads `at fn (address at main.jsbundle:1:48213)`: the "column" is an offset
into the bundle's bytecode and the name is whatever the function was called
in the bundle. The build's composed source map (Metro's map of the bundle
JS, composed with hermesc's map of the bytecode) takes that offset back to
the original file, line, column and function.

metro-symbolicate is the reference implementation, and this module resolves
exactly as it does (checked frame for frame against its output in
tests/test_symbolicate.py), in pure Python so a run can be symbolicated
without Node. What it mirrors:

  * source-map@0.5.7's lookup, which metro-symbolicate uses: greatest lower
    bound on the frame's own generated line only, sources normalised on load,
    `sourceRoot` joined on the way out, and index maps (`sections`) with that
    library's section-boundary quirk (`_IndexMap`);
  * function names from `x_facebook_sources` (Metro's per-file function
    maps), falling back to the mapping's identifier name, as
    `getOriginalPositionFor` does;
  * `address at` frames looked up as generated line (1 for the main bundle),
    column = the virtual offset, straight from the text. metro-symbolicate
    reads `x_hermes_function_offsets` only for `--hermes-crash` input, where
    a frame is a function id plus an offset inside that function
    (`SourceMap.bytecode_position`);
  * RAM-bundle maps (`x_facebook_segments`, `x_facebook_offsets`) and their
    `seg-N_M.js` / `N.js` frame file names.

Where it deliberately does less than metro-symbolicate, it is to never show a
confident wrong frame:

  * InternalBytecode.js frames are Hermes's own bytecode (its Promise and
    async helpers), not the app's; metro-symbolicate would look their offsets
    up in the app's map anyway. They stay unresolved.
  * `file:line:col` frames are positions in the bundle's JavaScript (Hermes
    prints them when the bytecode kept its own debug info, i.e. was built
    without -output-source-map, and JSC/V8 print them always). Only a map of
    that JavaScript (Metro's packager map) resolves them; a composed Hermes
    map would answer with some unrelated bytecode offset's source. The
    reverse holds for `address at` frames and a packager map. Their columns
    are 1-based, as React Native's own parseErrorStack treats them.
  * A map from a different build still "resolves" most offsets, to the wrong
    code. `map_matches` looks for that two ways. Every Hermes frame's address
    is an instruction that can throw (a call, a property read, a `new`), and
    hermesc's map has a location for those, so with the right map each frame
    lands exactly on a mapping (all 206 bytecode frames captured for the
    tests do). And Hermes prints each frame's function name, which the right
    map must place at that offset. When either fails, `symbolicate` resolves
    nothing.

Columns in results are 0-based, as in source maps and metro-symbolicate's
output; lines are 1-based.
"""
import bisect, hashlib, json, os, re, struct, threading

# ------------------------------------------------------------------ Base64 VLQ

_B64 = {c: i for i, c in enumerate(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")}


def _vlq_strict(text):
    """Decode one mappings segment the way source-map@0.5.7 does: a bad digit
    or a value cut short is an error, and a negative zero reads as 0."""
    out, value, shift, cont = [], 0, 0, False
    for ch in text:
        digit = _B64.get(ch)
        if digit is None:
            raise ValueError(f"invalid base64 digit {ch!r} in source map mappings")
        cont = bool(digit & 32)
        value += (digit & 31) << shift
        if cont:
            shift += 5
        else:
            out.append(-(value >> 1) if value & 1 else value >> 1)
            value = shift = 0
    if cont:
        raise ValueError("source map mappings end inside a VLQ value")
    return out


def _vlq_lenient(text):
    """Decode the way the `vlq` package does, which Metro's function maps go
    through: a value cut short is dropped silently, and a negative zero is
    -2**31."""
    out, value, shift = [], 0, 0
    for ch in text:
        digit = _B64.get(ch)
        if digit is None:
            raise ValueError(f"invalid character {ch!r} in a function map")
        value += (digit & 31) << shift
        if digit & 32:
            shift += 5
        else:
            negate, value = value & 1, value >> 1
            out.append((-value if value else -0x80000000) if negate else value)
            value = shift = 0
    return out


# ------------------------------------------------ source-map@0.5.7 path rules
# Source names are normalised when a map is loaded and joined with
# `sourceRoot` when a lookup returns one. These are that library's util.js
# functions, kept literal so the `file` a frame reports is the string
# metro-symbolicate prints.

_URL = re.compile(r"^(?:([\w+\-.]+):)?//(?:(\w+:\w+)@)?([\w.]*)(?::(\d+))?(\S*)$")
_DATA_URL = re.compile(r"^data:.+,.+$")


def _url_parse(s):
    m = _URL.match(s)
    return None if m is None else dict(zip(("scheme", "auth", "host", "port", "path"), m.groups()))


def _url_generate(u):
    out = (u["scheme"] + ":" if u["scheme"] else "") + "//"
    if u["auth"]:
        out += u["auth"] + "@"
    if u["host"]:
        out += u["host"]
    if u["port"]:
        out += ":" + u["port"]
    return out + (u["path"] or "")


def _is_absolute(p):
    return p.startswith("/") or bool(_URL.match(p))


def _normalize(p):
    url = _url_parse(p)
    path = p
    if url:
        if not url["path"]:
            return p
        path = url["path"]
    absolute = _is_absolute(path)
    parts = re.split(r"/+", path)
    up = 0
    i = len(parts) - 1
    while i >= 0:
        part = parts[i]
        if part == ".":
            del parts[i]
        elif part == "..":
            up += 1
        elif up > 0:
            if part == "":
                # Above the root: the `..` parts right after it are dropped.
                del parts[i + 1:i + 1 + up]
                up = 0
            else:
                del parts[i:i + 2]
                up -= 1
        i -= 1
    path = "/".join(parts) or ("/" if absolute else ".")
    if url:
        url["path"] = path
        return _url_generate(url)
    return path


def _join(root, p):
    root = root or "."
    p = p or "."
    p_url, root_url = _url_parse(p), _url_parse(root)
    if root_url:
        root = root_url["path"] or "/"
    if p_url and not p_url["scheme"]:
        if root_url:
            p_url["scheme"] = root_url["scheme"]
        return _url_generate(p_url)
    if p_url or _DATA_URL.match(p):
        return p
    if root_url and not root_url["host"] and not root_url["path"]:
        root_url["host"] = p
        return _url_generate(root_url)
    joined = p if p.startswith("/") else _normalize(root.rstrip("/") + "/" + p)
    if root_url:
        root_url["path"] = joined
        return _url_generate(root_url)
    return joined


def _relative(root, p):
    root = (root or ".")
    if root.endswith("/"):
        root = root[:-1]
    level = 0
    while not p.startswith(root + "/"):
        i = root.rfind("/")
        if i < 0:
            return p
        root = root[:i]
        if re.match(r"^([^/]+:/)?/*$", root):
            return p
        level += 1
    return "../" * level + p[len(root) + 1:]


def _normalize_source(source, source_root):
    """How a map's `sources` entry is stored after loading (source-map's
    consumer and metro-source-map's normalizeSourcePath agree on this)."""
    s = _normalize(str(source))
    if source_root and _is_absolute(source_root) and _is_absolute(s):
        s = _relative(source_root, s)
    return s


# ------------------------------------------------------------------ map lookup

_NO_POSITION = {"source": None, "line": None, "column": None, "name": None}


def _map_list(section_or_map, what):
    value = section_or_map.get(what)
    if value is None:
        raise ValueError(f"source map has no {what!r}")
    return value


class _BasicMap:
    """One `mappings` map, looked up as source-map@0.5.7's
    BasicSourceMapConsumer does."""

    def __init__(self, raw):
        if str(raw.get("version")) != "3":
            raise ValueError(f"unsupported source map version {raw.get('version')!r}")
        self.source_root = raw.get("sourceRoot")
        self.sources = [_normalize_source(s, self.source_root)
                        for s in _map_list(raw, "sources")]
        self.names = [str(n) for n in (raw.get("names") or [])]
        self._cols, self._entries = self._decode(_map_list(raw, "mappings"))

    @staticmethod
    def _decode(mappings):
        """Per generated line: sorted columns and, parallel, the mapping at
        each. A mapping is (source, original line, original column, name),
        or None for a generated-only segment."""
        cols, entries = [], []
        src = oline = ocol = name = 0
        cache = {}
        for line in mappings.split(";"):
            row, gcol = [], 0
            for seg in line.split(","):
                if not seg:
                    continue
                fields = cache.get(seg)
                if fields is None:
                    fields = cache[seg] = _vlq_strict(seg)
                    if len(fields) in (2, 3):
                        raise ValueError("source map segment has a source but no line and column")
                gcol += fields[0]
                if len(fields) > 1:
                    src += fields[1]
                    oline += fields[2]
                    ocol += fields[3]
                    if len(fields) > 4:
                        name += fields[4]
                        row.append((gcol, src, oline + 1, ocol, name))
                    else:
                        row.append((gcol, src, oline + 1, ocol, None))
                else:
                    row.append((gcol, None, None, None, None))
            # source-map sorts by generated position, then source, original
            # line, column and name, where a missing value compares as 0
            # (JavaScript's null - n). A lookup takes the first of equals.
            row.sort(key=lambda m: (m[0], m[1] or 0, m[2] or 0, m[3] or 0, m[4] or 0))
            cols.append([m[0] for m in row])
            entries.append([None if m[1] is None else m[1:] for m in row])
        return cols, entries

    def _index(self, line, col):
        """Index of the mapping a lookup at (1-based line, 0-based column)
        uses, or None."""
        if line < 1 or line > len(self._cols) or col < 0:
            return None
        cols = self._cols[line - 1]
        i = bisect.bisect_right(cols, col) - 1
        if i < 0:
            return None
        return bisect.bisect_left(cols, cols[i])

    def original(self, line, col):
        i = self._index(line, col)
        if i is None:
            return dict(_NO_POSITION)
        entry = self._entries[line - 1][i]
        if entry is None:
            return dict(_NO_POSITION)
        src, oline, ocol, name = entry
        source = self.sources[src] if 0 <= src < len(self.sources) else None
        if source is not None and self.source_root is not None:
            source = _join(self.source_root, source)
        return {"source": source, "line": oline, "column": ocol,
                "name": self.names[name] if name is not None and 0 <= name < len(self.names) else None}

    def originals_between(self, line, start, end):
        """The original positions of the mappings on `line` whose column is
        in [start, end)."""
        if not 1 <= line <= len(self._cols):
            return
        cols = self._cols[line - 1]
        for i in range(bisect.bisect_left(cols, start), bisect.bisect_left(cols, end)):
            entry = self._entries[line - 1][i]
            if entry is not None and 0 <= entry[0] < len(self.sources):
                source = self.sources[entry[0]]
                if self.source_root is not None:
                    source = _join(self.source_root, source)
                yield source, entry[1], entry[2]

    def probe(self, line, col):
        """Where a position falls among the mappings: 'exact' (a mapping
        starts at this column), 'inside' (between two of the line's
        mappings), 'before' its first or 'after' its last, or 'no_line' past
        the map's last generated line."""
        if line > len(self._cols):
            return "no_line"
        if line < 1 or col < 0:
            return "before"
        cols = self._cols[line - 1]
        if not cols or col < cols[0]:
            return "before"
        if col > cols[-1]:
            return "after"
        i = bisect.bisect_left(cols, col)
        return "exact" if cols[i] == col else "inside"


class _IndexMap:
    """A map made of `sections`, looked up as source-map@0.5.7's
    IndexedSourceMapConsumer does.

    That library stores a section's 0-based offset column as 1-based and
    compares it with the needle's 0-based column, so a position exactly at a
    section's start column (on the section's first line) falls to the section
    before. metro-symbolicate inherits this, and so does this class, so the
    two agree on every position."""

    def __init__(self, raw):
        if str(raw.get("version")) != "3":
            raise ValueError(f"unsupported source map version {raw.get('version')!r}")
        self.sections = []
        last = (-1, 0)
        for s in _map_list(raw, "sections"):
            if s.get("url"):
                raise ValueError("index map sections with a url are not supported")
            off = s.get("offset") or {}
            line, col = off.get("line"), off.get("column")
            if line is None or col is None:
                raise ValueError("index map section without an offset")
            if line < last[0] or (line == last[0] and col < last[1]):
                raise ValueError("index map section offsets must be ordered and non-overlapping")
            last = (line, col)
            sub = _map_list(s, "map")
            if isinstance(sub, str):
                sub = json.loads(sub)
            self.sections.append((line + 1, col + 1, _consumer(sub)))

    def _section(self, line, col):
        """source-map's binary search, kept literal (including how it picks
        among equal offsets): the last section whose (1-based) offset is not
        after the needle."""
        def compare(i):
            sline, scol, _ = self.sections[i]
            return (line - sline) or (col - scol)

        def search(low, high):
            mid = (high - low) // 2 + low
            cmp = compare(mid)
            if cmp == 0:
                return mid
            if cmp > 0:
                return search(mid, high) if high - mid > 1 else mid
            return search(low, mid) if mid - low > 1 else (-1 if low < 0 else low)

        if not self.sections:
            return None
        i = search(-1, len(self.sections))
        return None if i < 0 else self.sections[i]

    def _local(self, line, col):
        section = self._section(line, col)
        if section is None:
            return None
        sline, scol, consumer = section
        return consumer, line - (sline - 1), col - (scol - 1 if sline == line else 0)

    def original(self, line, col):
        local = self._local(line, col)
        return dict(_NO_POSITION) if local is None else local[0].original(local[1], local[2])

    def probe(self, line, col):
        local = self._local(line, col)
        return "before" if local is None else local[0].probe(local[1], local[2])


def _consumer(raw):
    return _IndexMap(raw) if raw.get("sections") is not None else _BasicMap(raw)


# ------------------------------------------------------------- metadata fields

def _metadata_by_source(raw):
    """metro-symbolicate's SourceMetadataMapConsumer table: each source's
    `x_facebook_sources` entry, keyed by normalised source name, merged over
    an index map's sections (a later section wins)."""
    if raw.get("mappings") is None:
        out = {}
        for s in raw.get("sections") or []:
            out.update(_metadata_by_source(s.get("map") or {}))
        return out
    if "x_facebook_sources" not in raw:
        return {}
    out, sources = {}, raw.get("sources") or []
    for i, meta in enumerate(raw.get("x_facebook_sources") or []):
        if i < len(sources) and sources[i] is not None:
            out[_normalize_source(sources[i], raw.get("sourceRoot"))] = meta
    return out


def _ignored_sources(raw, into):
    """metro-symbolicate's GoogleIgnoreListConsumer: sources listed in
    `x_google_ignoreList` in any section. Metro lists node_modules there."""
    if raw.get("mappings") is None:
        for s in raw.get("sections") or []:
            _ignored_sources(s.get("map") or {}, into)
        return into
    sources = raw.get("sources") or []
    for i in raw.get("x_google_ignoreList") or []:
        if isinstance(i, int) and 0 <= i < len(sources) and sources[i] is not None:
            into.add(_normalize_source(sources[i], raw.get("sourceRoot")))
    return into


def _decode_function_map(fmap):
    """Metro's function map: `names` plus `mappings` of
    (column delta, name delta, line delta). ';' only resets the column; the
    line moves by the deltas. Decoded as metro-symbolicate does, including
    the NaNs JavaScript produces for an empty segment."""
    if not fmap:
        return []
    names, out = fmap.get("names") or [], []
    line, name, nan = 1, 0, float("nan")
    for group in (fmap.get("mappings") or "").split(";"):
        col = 0
        for seg in group.split(","):
            fields = _vlq_lenient(seg)
            col += fields[0] if len(fields) > 0 else nan
            name += fields[1] if len(fields) > 1 else nan
            line += fields[2] if len(fields) > 2 else 0
            ok = isinstance(name, int) and 0 <= name < len(names)
            out.append((line, col, names[name] if ok else None))
    return out


def _enclosing(mappings, line, col):
    """findEnclosingMapping: the last function-map entry at or before the
    position (an upper-bound search, kept literal)."""
    first, count = 0, len(mappings)
    while count > 0:
        step = count // 2
        it = first + step
        mline, mcol, _ = mappings[it]
        cmp = (col - mcol) if line == mline else (line - mline)
        if cmp >= 0:
            first = it + 1
            count -= step + 1
        else:
            count = step
    return mappings[first - 1] if first else None


class _Segment:
    """One map of a (possibly segmented) bundle: its lookup, its function
    names, its ignore list, and its Hermes function offsets."""

    def __init__(self, raw):
        self.consumer = _consumer(raw)
        self.module_offsets = raw.get("x_facebook_offsets") or []
        self.hermes_offsets = raw.get("x_hermes_function_offsets")
        self._metadata = _metadata_by_source(raw)
        self._functions = {}
        self.names_by_function = {}
        self.ignored = _ignored_sources(raw, set())

    def function_name(self, source, line, column):
        if not source or line is None or column is None:
            return None
        if source not in self._functions:
            if source in self._metadata:
                meta = self._metadata[source] or []
                self._functions[source] = _decode_function_map(meta[0] if meta else None)
            else:
                self._functions[source] = None
        mappings = self._functions[source]
        if not mappings:
            return None
        hit = _enclosing(mappings, line, column)
        return hit[2] if hit else None


# ---------------------------------------------------------------- loaded map

class SourceMap:
    """A loaded source map, resolving positions as metro-symbolicate's
    SingleMapSymbolicationContext does with its default options (input and
    output lines 1-based, columns 0-based, function names on)."""

    def __init__(self, raw, path=None):
        self.path = path
        self._segments = {"0": _Segment(raw)}
        for key, seg in (raw.get("x_facebook_segments") or {}).items():
            self._segments[str(key)] = _Segment(seg)
        self.legacy = raw.get("x_facebook_segments") is not None or raw.get("x_facebook_offsets") is not None
        self.is_hermes = any(_has_hermes_offsets(raw))
        self.project_root = _project_root(_all_sources(raw))

    @classmethod
    def from_json(cls, text, path=None):
        # Maps served to browsers may start with an XSSI guard.
        if text.startswith(")]}'"):
            text = text[4:]
        return cls(json.loads(text), path=path)

    def parse_file_name(self, name):
        """metro-symbolicate's parseSingleMapFileName: `N.js` is module N of a
        RAM bundle and `seg-S.js` / `seg-S_N.js` a segment's; only for maps
        that carry segment or module offsets."""
        if not self.legacy:
            return (0, None)
        m = re.match(r"^(\d+).js$", name or "")
        if m:
            return (0, int(m.group(1)))
        m = re.match(r"^seg-(\d+)(?:_(\d+))?.js$", name or "")
        if m:
            return (int(m.group(1)), int(m.group(2)) if m.group(2) else None)
        return (0, None)

    def _locate(self, line, col, module_ids):
        seg_id, local_id = module_ids or (0, None)
        seg = self._segments.get(str(seg_id))
        if seg is None:
            return None
        offset = 0
        if local_id is not None:
            if local_id >= len(seg.module_offsets) or seg.module_offsets[local_id] is None:
                return None
            offset = seg.module_offsets[local_id]
        return seg, line + offset, col

    def details(self, line, col, module_ids=None):
        """getOriginalPositionDetailsFor: source, 1-based line, 0-based
        column, the mapping's identifier `name`, the enclosing function's
        `functionName`, and whether the source is on the ignore list."""
        located = self._locate(line, col, module_ids)
        if located is None:
            out = dict(_NO_POSITION)
            out.update(functionName=None, isIgnored=False)
            return out
        seg, line, col = located
        out = seg.consumer.original(line, col)
        out["functionName"] = seg.function_name(out["source"], out["line"], out["column"]) or None
        out["isIgnored"] = out["source"] is not None and out["source"] in seg.ignored
        return out

    def position(self, line, col, module_ids=None):
        """getOriginalPositionFor: like `details`, with `name` the function
        name when the map has one and the identifier name otherwise."""
        d = self.details(line, col, module_ids)
        return {"source": d["source"], "line": d["line"], "column": d["column"],
                "name": d["functionName"] or d["name"], "isIgnored": d["isIgnored"]}

    def probe(self, line, col, module_ids=None):
        located = self._locate(line, col, module_ids)
        if located is None:
            return "no_line"
        seg, line, col = located
        return seg.consumer.probe(line, col)

    def function_names(self, line, col, module_ids=None, bytecode=False):
        """The functions (as Metro's function maps name them) whose code is
        at this position, or None when the map has no function maps here.

        For a Hermes offset that is every function with code inside the
        bytecode function holding the offset (from x_hermes_function_offsets),
        because Hermes inlines: a frame is named after the function it runs
        in, while the offset can point at code inlined from another."""
        located = self._locate(line, col, module_ids)
        if located is None:
            return None
        seg, line, col = located
        starts = (seg.hermes_offsets or {}).get(str(line - 1)) if bytecode else None
        if not starts or not isinstance(seg.consumer, _BasicMap):
            o = seg.consumer.original(line, col)
            name = seg.function_name(o["source"], o["line"], o["column"])
            return {name} if name else None
        fid = bisect.bisect_right(starts, col) - 1
        if fid < 0:
            return None
        key = (line, fid)
        if key not in seg.names_by_function:
            end = starts[fid + 1] if fid + 1 < len(starts) else float("inf")
            names = {seg.function_name(src, oline, ocol)
                     for src, oline, ocol in seg.consumer.originals_between(line, starts[fid], end)}
            names.discard(None)
            seg.names_by_function[key] = names or None
        return seg.names_by_function[key]

    def function_offsets(self, segment_id=0):
        """Bytecode start offset of every function in a Hermes segment, from
        `x_hermes_function_offsets`, or None."""
        offsets = self._segments["0"].hermes_offsets
        return None if not offsets else offsets.get(str(segment_id))

    def bytecode_position(self, function_id, bytecode_offset, segment_id=0, source_url=""):
        """A frame given as function id plus offset inside the function, as a
        Hermes crash report records it (metro-symbolicate --hermes-crash): the
        function's start offset from `x_hermes_function_offsets` plus the
        local offset, on generated line segment_id + 1. Returns `details`, or
        None when the map has no offsets for it."""
        module_ids = self.parse_file_name(source_url)
        seg = self._segments.get(str(module_ids[0]))
        offsets = seg.hermes_offsets if seg else None
        if not offsets:
            return None
        starts = offsets.get(str(segment_id))
        if starts is None or not 0 <= function_id < len(starts):
            return None
        return self.details(segment_id + 1, starts[function_id] + bytecode_offset, module_ids)


def _has_hermes_offsets(raw):
    yield bool(raw.get("x_hermes_function_offsets"))
    for s in raw.get("sections") or []:
        yield from _has_hermes_offsets(s.get("map") or {})
    for seg in (raw.get("x_facebook_segments") or {}).values():
        yield from _has_hermes_offsets(seg)


def _all_sources(raw):
    yield from (s for s in raw.get("sources") or [] if isinstance(s, str))
    for s in raw.get("sections") or []:
        yield from _all_sources(s.get("map") or {})


def _project_root(sources):
    """The build's project directory, so a source path can be told apart
    from the machine it was built on: the directory holding node_modules,
    taken from the library sources (the most common one, when node_modules
    sit in more than one place, as in a monorepo)."""
    counts = {}
    for s in sources:
        i = s.find("/node_modules/")
        if i > 0 and _is_absolute(s):
            counts[s[:i]] = counts.get(s[:i], 0) + 1
    if not counts:
        return None
    return min(counts, key=lambda p: (-counts[p], len(p)))


_cache = {}
_cache_lock = threading.Lock()


def load_map(path):
    """Load a source map, cached per path and modification time: a composed
    map of a large app is megabytes of mappings to decode."""
    path = os.path.abspath(os.fspath(path))
    st = os.stat(path)
    key = (st.st_mtime_ns, st.st_size)
    with _cache_lock:
        hit = _cache.get(path)
        if hit and hit[0] == key:
            return hit[1]
    with open(path, encoding="utf-8") as fh:
        loaded = SourceMap.from_json(fh.read(), path=path)
    with _cache_lock:
        _cache[path] = (key, loaded)
    return loaded


def _as_map(source_map):
    if isinstance(source_map, SourceMap):
        return source_map
    if isinstance(source_map, dict):
        return SourceMap(source_map)
    return load_map(source_map)


# --------------------------------------------------------------- stack parsing

INTERNAL_BYTECODE = "InternalBytecode.js"

# Hermes and V8: `at NAME (LOCATION)`. The name is everything up to the
# first " (": Hermes prints getters as "get total" and a function's
# displayName as it is, spaces included.
_AT_NAMED = re.compile(r"^at (?P<fn>.+?) \((?P<loc>.*)\)$")
_AT_BARE = re.compile(r"^at (?P<loc>.+)$")
_FILE_LINE_COL = re.compile(r"^(?P<file>.*):(?P<line>\d+):(?P<col>\d+)$")
# JSC: `NAME@FILE:LINE:COL`, `NAME@[native code]`, or no name at all.
_JSC = re.compile(r"^(?P<fn>[^\s@]*|global code|module code|eval code)@(?P<loc>.+)$")
_SKIPPED = re.compile(r"^\.\.\. skipping (\d+) frames?$")


def _frame(raw, kind, fn=None, file=None, line=None, col=None):
    return {"raw": raw, "kind": kind, "fn": fn, "file": file, "line": line, "col": col}


def _location(raw, fn, loc):
    """A frame from its location text. Kinds: `bytecode` (an `address at`
    offset in the bundle), `internal` (Hermes's own InternalBytecode.js),
    `source` (file:line:col, 1-based column) and `native`."""
    if loc in ("native", "[native code]", "<anonymous>", "native code"):
        return _frame(raw, "native", fn)
    bytecode = loc.startswith("address at ")
    m = _FILE_LINE_COL.match(loc[len("address at "):] if bytecode else loc)
    if not m:
        return None
    file, line, col = m.group("file"), int(m.group("line")), int(m.group("col"))
    if bytecode:
        kind = "internal" if file == INTERNAL_BYTECODE else "bytecode"
    else:
        kind = "source"
    return _frame(raw, kind, fn, file, line, col)


def _parse_line(raw):
    m = _AT_NAMED.match(raw)
    if m:
        return _location(raw, m.group("fn"), m.group("loc"))
    m = _AT_BARE.match(raw)
    if m:
        # V8 prints an anonymous function's frame without parentheses; a
        # React component stack entry has a name and no location at all.
        loc = m.group("loc")
        return _location(raw, None, loc) or _frame(raw, "nolocation", loc)
    m = _SKIPPED.match(raw)
    if m:
        return _frame(raw, "skipped")
    if raw == "[native code]":
        return _frame(raw, "native")
    m = _JSC.match(raw)
    if m:
        return _location(raw, m.group("fn") or None, m.group("loc"))
    if " " not in raw:
        return _location(raw, None, raw)
    return None


def parse_stack(stack):
    """Split a stack into raw frames, one per non-empty line, in order.

    Each is {raw, kind, fn, file, line, col} with the values as printed.
    Kinds: bytecode, internal, source, native, nolocation (a name only),
    skipped (Hermes's "... skipping N frames"), message (the error's own
    text, the lines before the first frame) and unparsed (anything else;
    kept, never dropped)."""
    # Split on "\n" only, as React Native's parser does: a message may hold
    # other line separators.
    frames = [_parse_line(line.strip()) or _frame(line.strip(), "unparsed")
              for line in (stack or "").split("\n") if line.strip()]
    first = next((i for i, f in enumerate(frames) if f["kind"] != "unparsed"), None)
    if first is not None:
        for f in frames[:first]:
            f["kind"] = "message"
    return frames


# ---------------------------------------------------------------- symbolicate

def _is_third_party(source, ignored):
    return (ignored or "/node_modules/" in "/" + source
            # Metro's virtual modules, e.g. __prelude__.
            or source.startswith("__"))


def _relative_path(source, root):
    if root and source.startswith(root + "/"):
        return source[len(root) + 1:]
    return source


def _entries(stack_or_frames):
    if isinstance(stack_or_frames, str):
        return [f for f in parse_stack(stack_or_frames) if f["kind"] != "message"]
    out = []
    for f in stack_or_frames:
        if "kind" in f:
            out.append(f)
        else:
            out.extend(parse_stack(f.get("raw") or ""))
    return [f for f in out if f["kind"] != "message"]


def _query(frame, sm):
    """The (line, column, module ids) this frame is looked up at, or None
    when this map can't answer for it."""
    kind = frame["kind"]
    if kind == "bytecode" and sm.is_hermes:
        return frame["line"], frame["col"], sm.parse_file_name(frame["file"])
    if kind == "source" and not sm.is_hermes and frame["file"] and frame["col"] >= 1:
        return frame["line"], frame["col"] - 1, sm.parse_file_name(frame["file"])
    return None


# Names Hermes gives functions it has no name for, or that say nothing
# about which function it is.
_UNNAMED = {"", "anonymous", "<anonymous>", "global", "<global>", "get", "set", "eval"}


def _name_key(name):
    """A function name reduced to what Hermes prints and Metro's function
    map records alike: Hermes prints `get total` for a getter, Metro records
    `Cart#perItem`, `handlers.onPress`, `Cart#get__label`; Babel prefixes
    `_` to the functions it splits out of async functions."""
    name = re.split(r"[#.]", name.split(" ")[-1])[-1]
    return re.sub(r"^(?:get|set)__", "", name).lstrip("_")


def _names_match(runtime, mapped):
    key = _name_key(runtime)
    for name in mapped:
        if _name_key(name) == key:
            return True
        # Metro names a constructor Class#constructor; Hermes prints Class.
        if name.endswith("#constructor") and _name_key(name[:-len("#constructor")]) == key:
            return True
    return False


def _named(frame):
    """A Hermes frame whose function name says which function it is: not
    anonymous, not a name Hermes made up (`?anon_0_`), and not JSC's
    `fn@file` style, whose names come from a minified bundle."""
    fn = frame["fn"] or ""
    return (frame["raw"].startswith("at ") and not fn.startswith("?")
            and fn not in _UNNAMED and _name_key(fn) not in _UNNAMED)


def map_matches(stack_or_frames, source_map, *, bundle=None):
    """Whether a map belongs to the build that produced a stack.

    Returns {match, checked, failed, reason, files}: match is True, False,
    or None when the stack gives no evidence either way; files gives each
    frame file's verdict ('confirmed', 'rejected' or 'unknown'), since a
    stack can hold frames from scripts other than the bundle the map
    describes. Two tests, either of which rejects a file:

    Landing. Every Hermes offset must land exactly on a mapping (see the
    module docstring). A map from another build fails that on most frames
    whose code moved between the builds, but not all: 7 of the 17 distinct
    offsets in the captured Swag Pay iOS stacks land exactly on a mapping of
    the Android map (none the other way), so a stack with one or two such
    frames can pass.

    Names. Hermes prints each frame's function name, and Swag Pay's release
    bundles are not minified, so it is the source's name. With the right map,
    that name is one of the functions whose code sits in the bytecode
    function holding the offset (inlining puts several there). A file is
    rejected when more of its named frames fail this than pass it: with the
    right maps every named frame in the captured stacks passes; with the
    Android map for iOS stacks none do. A function given a displayName, which
    Hermes prints instead, fails it on the right map, so a stack of little
    else would be refused and left unsymbolicated.

    JavaScript positions (file:line:col) get the names test only, at the
    position itself, where inlined code can't be told from a wrong map.

    The match is False when a file is rejected and none is confirmed. With
    `bundle` (a Hermes bytecode file), its function count must also equal
    the map's, which rejects most pairings of a map with the wrong bundle
    outright."""
    sm = _as_map(source_map)
    frames = _entries(stack_or_frames)
    kinds = {f["kind"] for f in frames if f["kind"] != "source" or f["file"]}

    def verdict(match, reason, checked=0, failed=0, files=None):
        return {"match": match, "checked": checked, "failed": failed, "reason": reason,
                "files": files or {}}

    if bundle is not None:
        info = hbc_info(bundle)
        offsets = sm.function_offsets(0)
        if info["magic_ok"] and offsets is not None and info.get("function_count") != len(offsets):
            return verdict(False, f"the bundle has {info.get('function_count')} functions "
                                  f"and the map describes {len(offsets)}")
    if "bytecode" in kinds and not sm.is_hermes:
        return verdict(False, "the stack has Hermes bytecode offsets and this is not a "
                              "composed Hermes map (no x_hermes_function_offsets)")
    if "source" in kinds and "bytecode" not in kinds and sm.is_hermes:
        return verdict(False, "the stack has JavaScript positions (bytecode built without "
                              "-output-source-map, or not Hermes); they need Metro's "
                              "packager map, not a composed Hermes map")
    tally = {}
    checked = failed = 0
    for f in frames:
        q = _query(f, sm)
        if q is None:
            continue
        t = tally.setdefault(f["file"], {"landed": 0, "missed": 0, "named": 0, "misnamed": 0})
        checked += 1
        bad = False
        if f["kind"] == "bytecode":
            if sm.probe(*q) == "exact":
                t["landed"] += 1
            else:
                t["missed"] += 1
                bad = True
        if _named(f):
            mapped = sm.function_names(*q, bytecode=f["kind"] == "bytecode")
            if mapped is not None:
                t["named"] += 1
                if not _names_match(f["fn"], mapped):
                    t["misnamed"] += 1
                    bad = True
        failed += bad
    files = {}
    for file, t in tally.items():
        if t["missed"] or t["misnamed"] * 2 > t["named"]:
            files[file] = "rejected"
        elif t["landed"] or t["named"]:
            files[file] = "confirmed"
        else:
            files[file] = "unknown"
    states = set(files.values())
    if "confirmed" in states:
        return verdict(True, None, checked, failed, files)
    if "rejected" in states:
        missed = sum(t["missed"] for t in tally.values())
        landed = sum(t["landed"] for t in tally.values())
        if missed:
            reason = (f"{missed} of {landed + missed} frames do not land on an instruction "
                      "this map knows: the map is from another build")
        else:
            named = sum(t["named"] for t in tally.values())
            misnamed = sum(t["misnamed"] for t in tally.values())
            reason = (f"{misnamed} of {named} named frames are not functions this map has "
                      "at their positions: the map is from another build")
        return verdict(False, reason, checked, failed, files)
    return verdict(None, "no frames this map could confirm", checked, failed, files)


def symbolicate(stack, source_map, *, check=True):
    """Resolve a stack against a source map (a path or a loaded map).

    Returns one dict per frame line, in order (the error's message lines are
    left out): {fn, file, line, col, in_app, resolved, raw, path}. `path` is
    `file` relative to the build's project directory, for grouping across
    machines. An unresolved frame (native code, Hermes internals, no mapping,
    a map this frame kind can't use) has resolved False, None in fn, file,
    line and col, and its text in `raw`.

    With `check`, frames are resolved only from files `map_matches`
    confirms, or, when it can confirm none, from files it has no evidence
    against. A map from another build resolves nothing."""
    sm = _as_map(source_map)
    frames = _entries(stack)
    allowed = None
    if check:
        v = map_matches(frames, sm)
        if v["match"] is False:
            allowed = set()
        else:
            wanted = "confirmed" if v["match"] else "unknown"
            allowed = {f for f, state in v["files"].items() if state == wanted}
    out = []
    for f in frames:
        q = _query(f, sm) if allowed is None or f["file"] in allowed else None
        pos = sm.position(*q) if q else None
        if pos is None or pos["source"] is None:
            out.append({"fn": None, "file": None, "line": None, "col": None, "in_app": False,
                        "resolved": False, "raw": f["raw"], "path": None})
            continue
        out.append({"fn": pos["name"], "file": pos["source"], "line": pos["line"],
                    "col": pos["column"],
                    "in_app": not _is_third_party(pos["source"], pos["isIgnored"]),
                    "resolved": True, "raw": f["raw"],
                    "path": _relative_path(pos["source"], sm.project_root)})
    return out


def fingerprint(frames):
    """A short id for grouping errors: the first resolved in-app frame's
    file and function, which don't move when a build shifts offsets and
    lines. None when no frame is both resolved and in the app."""
    for f in frames:
        if f.get("resolved") and f.get("in_app"):
            key = f"{f.get('path') or f.get('file') or ''}\n{f.get('fn') or ''}"
            return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return None


# ------------------------------------------------------------------ HBC header

HBC_MAGIC = 0x1F1903C103BC1FC6


def hbc_info(bundle_path):
    """The Hermes bytecode header: magic, bytecode version, and the SHA-1 of
    the JavaScript it was compiled from (hermesc writes it at offset 12), so
    a map can be matched to a bundle. `file_length` and `function_count`
    follow it (read as laid out in version 98, the version checked);
    `function_count` equals the length of the map's
    x_hermes_function_offsets."""
    with open(bundle_path, "rb") as fh:
        head = fh.read(44)
    if len(head) < 12 or struct.unpack_from("<Q", head, 0)[0] != HBC_MAGIC:
        return {"magic_ok": False, "version": None, "source_hash": None}
    info = {"magic_ok": True, "version": struct.unpack_from("<I", head, 8)[0],
            "source_hash": head[12:32].hex() if len(head) >= 32 else None}
    if len(head) >= 44:
        info["file_length"], _, info["function_count"] = struct.unpack_from("<III", head, 32)
    return info
