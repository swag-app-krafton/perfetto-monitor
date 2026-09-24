"""Symbolication of React Native release-build JS stacks (swagperf/symbolicate.py).

The expected answers are metro-symbolicate's, run on the same stacks and maps
by fixtures/sourcemaps/tools/golden.js and recorded in golden.json. The stacks
are genuine: Hermes printed them, running real bytecode in a small host
(tools/host.cpp) linked against the Hermes VM from Swag Pay's CocoaPods.

  synthetic/  a small program (program/) built as React Native's release
              builds are, twice: v2 adds code that moves offsets and lines.
              Nested and inlined functions, a class method, a getter, an arrow
              calling native JSON.parse, an object method, a React Native
              internal (EventEmitter), a node_modules library, a closure, an
              async function, an uncaught error. v1 is also compiled without
              -output-source-map, the way Swag Pay's iOS Release builds are
              today, which gives file:line:col stacks.
  swagpay/    Swag Pay's own iOS and Android release bundles, rebuilt byte for
              byte (the Android bytecode is identical to Gradle's), driven
              into errors in its own modules. Maps trimmed to what these
              stacks touch; tools/assemble.py says how that preserves lookups.
  maps/       a hand-made index map (sections) and a RAM-bundle map.

tools/regenerate.sh rebuilds all of it.
"""
import glob, hashlib, json, os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from swagperf import symbolicate as sym

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures", "sourcemaps")


def fixture(*parts):
    return os.path.join(FIX, *parts)


def load_json(*parts):
    with open(fixture(*parts)) as fh:
        return json.load(fh)


GOLDEN = load_json("golden.json")
SPEC = load_json("spec.json")
V1_MAP = "synthetic/v1/index.android.bundle.map"
V1_PACKAGER = "synthetic/v1/index.android.bundle.packager.map"
V1_BUNDLE = "synthetic/v1/index.android.bundle"
V2_MAP = "synthetic/v2/main.jsbundle.map"


def smap(rel):
    return sym.load_map(fixture(rel))


def stacks(rel):
    return {s["id"]: s["text"] for s in load_json(rel)}


def golden_cases():
    """(case id, stack text, map, input column start, per-line matches)."""
    texts = {}
    for group in SPEC["stacks"]:
        for sid, text in stacks(group["stacks"]).items():
            texts[f"{group['id']}/{sid}"] = text
    for g in GOLDEN["stacks"]:
        yield g["id"], texts[g["id"]], g["map"], g["inputColumnStart"], g["lines"]


def per_line(text, source_map, **kw):
    """(raw frame, symbolicated frame) for each line of a stack; the
    symbolicated frame is None for blank and message lines."""
    raw = iter(sym.parse_stack(text))
    out = iter(sym.symbolicate(text, source_map, **kw))
    rows = []
    for line in text.split("\n"):
        if not line.strip():
            rows.append((None, None))
            continue
        f = next(raw)
        rows.append((f, None if f["kind"] == "message" else next(out)))
    return rows


# golden match: [fileName, line, column, source, origLine, origColumn, name,
#                functionName, identifierName, isIgnored]
def metro(m):
    return {"source": m[3], "line": m[4], "column": m[5], "name": m[6],
            "functionName": m[7], "identifierName": m[8], "isIgnored": m[9]}


class TestParseStack(unittest.TestCase):
    """Every frame format Hermes, V8 and JSC print, as parse_stack reads it."""

    CASES = [
        # Hermes bytecode: the column is a 0-based offset into the bytecode.
        ("    at inner (address at index.android.bundle:1:216)",
         "bytecode", "inner", "index.android.bundle", 1, 216),
        ("    at anonymous (address at main.jsbundle:1:48213)",
         "bytecode", "anonymous", "main.jsbundle", 1, 48213),
        ("    at global (address at main.jsbundle:1:19612)",
         "bytecode", "global", "main.jsbundle", 1, 19612),
        ("    at <global> (address at main.jsbundle:1:19612)",
         "bytecode", "<global>", "main.jsbundle", 1, 19612),
        # A URL source is taken whole, colons and spaces included.
        ("    at render (address at file:///private/var/Swag Pay.app/main.jsbundle:1:7)",
         "bytecode", "render", "file:///private/var/Swag Pay.app/main.jsbundle", 1, 7),
        # Names Hermes prints with spaces: getters and displayName.
        ("    at get total (address at index.android.bundle:1:571)",
         "bytecode", "get total", "index.android.bundle", 1, 571),
        ("    at My Display Name (address at index.android.bundle:1:461)",
         "bytecode", "My Display Name", "index.android.bundle", 1, 461),
        ("    at ?anon_0_ (address at index.android.bundle:1:7119)",
         "bytecode", "?anon_0_", "index.android.bundle", 1, 7119),
        # Hermes's own bytecode: its Promise and async machinery.
        ("    at tryCallOne (address at InternalBytecode.js:1:1296)",
         "internal", "tryCallOne", "InternalBytecode.js", 1, 1296),
        ("    at map (native)", "native", "map", None, None, None),
        # Hermes with debug info in the bytecode, V8: a JavaScript position.
        ("    at inner (t1.js:1:49)", "source", "inner", "t1.js", 1, 49),
        ("    at evald (:1:35)", "source", "evald", "", 1, 35),
        ("    at Object.<anonymous> (/app/index.js:10:5)",
         "source", "Object.<anonymous>", "/app/index.js", 10, 5),
        ("    at async loadProfile (/app/api.js:3:9)",
         "source", "async loadProfile", "/app/api.js", 3, 9),
        ("    at /app/index.js:10:5", "source", None, "/app/index.js", 10, 5),
        ("    at Array.map (<anonymous>)", "native", "Array.map", None, None, None),
        # JSC.
        ("render@http://localhost:8081/index.bundle?platform=ios:1234:56",
         "source", "render", "http://localhost:8081/index.bundle?platform=ios", 1234, 56),
        ("global code@main.jsbundle:5:6", "source", "global code", "main.jsbundle", 5, 6),
        ("@main.jsbundle:5:6", "source", None, "main.jsbundle", 5, 6),
        ("forEach@[native code]", "native", "forEach", None, None, None),
        ("[native code]", "native", None, None, None, None),
        ("main.jsbundle:5:6", "source", None, "main.jsbundle", 5, 6),
        # A React component stack entry has a name and nothing else.
        ("    at View", "nolocation", "View", None, None, None),
        ("    ... skipping 53 frames", "skipped", None, None, None, None),
    ]

    def test_every_format(self):
        for line, kind, fn, file, ln, col in self.CASES:
            with self.subTest(line=line):
                f = sym.parse_stack("Error: x\n" + line)[1]
                self.assertEqual((f["kind"], f["fn"], f["file"], f["line"], f["col"]),
                                 (kind, fn, file, ln, col))
                self.assertEqual(f["raw"], line.strip())

    def test_message_lines_come_before_the_first_frame(self):
        frames = sym.parse_stack("Invariant Violation: no config\nsecond line of it\n"
                                 "    at invariant (address at main.jsbundle:1:9)")
        self.assertEqual([f["kind"] for f in frames], ["message", "message", "bytecode"])

    def test_unknown_lines_are_kept_not_dropped(self):
        frames = sym.parse_stack("Error: x\n    at a (address at main.jsbundle:1:9)\n"
                                 "--- something new ---\n    at b (native)")
        self.assertEqual([f["kind"] for f in frames], ["message", "bytecode", "unparsed", "native"])
        self.assertEqual(frames[2]["raw"], "--- something new ---")
        out = sym.symbolicate("Error: x\n--- a ---\n    at a (native)\n--- b ---", smap(V1_MAP))
        self.assertEqual([f["raw"] for f in out], ["at a (native)", "--- b ---"])
        self.assertTrue(all(not f["resolved"] for f in out))

    def test_a_stack_with_no_frames_is_all_unparsed(self):
        frames = sym.parse_stack("just some text\nand more")
        self.assertEqual([f["kind"] for f in frames], ["unparsed", "unparsed"])

    def test_every_captured_line_parses(self):
        """No line Hermes printed in these runs is left unrecognised."""
        for case, text, _, _, _ in golden_cases():
            with self.subTest(case=case):
                kinds = [f["kind"] for f in sym.parse_stack(text)]
                self.assertNotIn("unparsed", kinds)
                self.assertEqual(kinds[0], "message")


class TestAgainstMetroSymbolicate(unittest.TestCase):
    """The resolver answers as metro-symbolicate does, on every position its
    own stack parser queried (golden.json)."""

    def test_lookups_match_metro(self):
        """Every position metro-symbolicate looked up in every stack: source,
        line, column, the printed name, the function-map and identifier names
        behind it, and the ignore list."""
        n = 0
        for case, _, map_rel, ics, lines in golden_cases():
            sm = smap(map_rel)
            for matches in lines:
                for m in matches:
                    if m[1] is None:
                        continue
                    got = sm.details(m[1], m[2] - ics, sm.parse_file_name(m[0] or ""))
                    got = {"source": got["source"], "line": got["line"], "column": got["column"],
                           "name": got["functionName"] or got["name"],
                           "functionName": got["functionName"], "identifierName": got["name"],
                           "isIgnored": got["isIgnored"]}
                    with self.subTest(case=case, at=m[:3]):
                        self.assertEqual(got, metro(m))
                    n += 1
        self.assertGreater(n, 350)

    def test_symbolicated_frames_match_metro(self):
        """Frame by frame: a frame this module resolves has metro's file, line,
        column and name; one it could look up but leaves unresolved, metro
        found nothing for either, or it comes from a script map_matches
        rejected (a Swag Pay stack's probe.js frames, which metro looks up in
        the bundle's map regardless)."""
        resolved = 0
        for case, text, map_rel, ics, lines in golden_cases():
            sm = smap(map_rel)
            files = sym.map_matches(text, sm)["files"]
            for (raw, frame), matches in zip(per_line(text, sm), lines):
                if frame is None:
                    continue
                with self.subTest(case=case, line=raw["raw"]):
                    usable = (raw["kind"] == "bytecode" and sm.is_hermes) or \
                             (raw["kind"] == "source" and raw["file"] and not sm.is_hermes)
                    if not usable:
                        self.assertFalse(frame["resolved"])
                        continue
                    m = next(metro(m) for m in matches if m[1] == raw["line"] and m[2] == raw["col"])
                    if frame["resolved"]:
                        resolved += 1
                        self.assertEqual((frame["file"], frame["line"], frame["col"], frame["fn"]),
                                         (m["source"], m["line"], m["column"], m["name"]))
                    elif m["source"] is not None:
                        self.assertEqual(files.get(raw["file"]), "rejected")
        self.assertGreater(resolved, 250)

    def test_index_map_positions_match_metro(self):
        """A grid over an index map whose sections include two on one line, a
        sourceRoot, an ignore-listed source and a nested index map."""
        for p in GOLDEN["positions"]:
            sm = smap(p["map"])
            for line, col, source, oline, ocol, name, fname, ident in p["points"]:
                d = sm.details(line, col)
                with self.subTest(at=(line, col)):
                    self.assertEqual((d["source"], d["line"], d["column"], d["functionName"] or d["name"],
                                      d["functionName"], d["name"]),
                                     (source, oline, ocol, name, fname, ident))

    def test_hermes_crash_frames_match_metro(self):
        """Frames given as function id + offset in the function (a Hermes
        crash report), resolved through x_hermes_function_offsets as
        metro-symbolicate --hermes-crash does."""
        n = 0
        for c in GOLDEN["crashes"]:
            sm = smap(c["map"])
            for frame, expected in zip(c["callstack"], c["result"]):
                if frame.get("NativeCode"):
                    self.assertTrue(expected.get("NativeCode"))
                    continue
                got = sm.bytecode_position(frame["FunctionID"], frame["ByteCodeOffset"],
                                           frame["SegmentID"], frame["SourceURL"])
                with self.subTest(crash=c["id"], frame=frame):
                    self.assertEqual({k: got[k] for k in expected}, expected)
                n += 1
        self.assertGreater(n, 100)

    def test_internal_bytecode_is_not_looked_up_in_the_app_map(self):
        """metro-symbolicate looks InternalBytecode.js offsets up in the app's
        map and prints whatever is there; they are Hermes's own code."""
        text = stacks("synthetic/v1/stacks.json")["async_function"]
        g = next(g for g in GOLDEN["stacks"] if g["id"] == "v1/async_function")
        rows = per_line(text, smap(V1_MAP))
        internal = [(frame, matches) for (raw, frame), matches in zip(rows, g["lines"])
                    if raw and raw["kind"] == "internal"]
        self.assertEqual(len(internal), 2)
        self.assertTrue(any(metro(m)["source"] for _, ms in internal for m in ms))
        self.assertTrue(all(not frame["resolved"] for frame, _ in internal))


class TestResolvedFrames(unittest.TestCase):
    """What a developer reads for the synthetic program's stacks."""

    @classmethod
    def setUpClass(cls):
        sm = smap(V1_MAP)
        cls.v1 = {k: sym.symbolicate(t, sm) for k, t in stacks("synthetic/v1/stacks.json").items()}

    def first(self, case):
        f = self.v1[case][0]
        return f["fn"], f["path"], f["line"], f["col"]

    def test_names_come_from_the_function_map(self):
        self.assertEqual(self.v1["class_method"][1]["fn"], "Cart#perItem")
        self.assertEqual(self.first("object_method"), ("handlers.onPress", "src/api.ts", 11, 23))
        self.assertEqual(self.first("getter"), ("Cart#get__label", "src/cart.ts", 17, 24))

    def test_inlined_code_resolves_to_where_it_was_written(self):
        # Hermes inlined divide() into average(), and names the frame after
        # the function it is running in; the map knows the code is divide's.
        self.assertTrue(self.v1["nested_function"][0]["raw"].startswith("at average "))
        self.assertEqual(self.first("nested_function"), ("divide", "src/math.ts", 3, 24))
        self.assertEqual(self.first("closure"), ("overflow", "src/nested.ts", 7, 23))

    def test_async_function(self):
        self.assertTrue(self.v1["async_function"][0]["raw"].startswith("at ?anon_0_ "))
        self.assertEqual(self.first("async_function"), ("loadProfile", "src/api.ts", 4, 19))

    def test_arrow_calling_native_code(self):
        native, arrow = self.v1["arrow_native"][:2]
        self.assertFalse(native["resolved"])
        self.assertEqual(native["raw"], "at parse (native)")
        self.assertEqual((arrow["fn"], arrow["path"], arrow["line"]), ("parse", "src/cart.ts", 20))

    def test_unresolved_frames_keep_only_their_text(self):
        f = self.v1["arrow_native"][0]
        self.assertEqual(f, {"fn": None, "file": None, "line": None, "col": None, "in_app": False,
                             "resolved": False, "raw": "at parse (native)", "path": None})

    def test_in_app(self):
        def in_app(case):
            return [(f["path"], f["in_app"]) for f in self.v1[case] if f["resolved"]]

        self.assertEqual(in_app("rn_internal")[:3], [
            ("src/events.ts", True),
            ("node_modules/react-native/Libraries/vendor/emitter/EventEmitter.js", False),
            ("src/events.ts", True)])
        self.assertEqual(in_app("third_party")[0], ("node_modules/fake-lib/index.js", False))
        self.assertIn(("node_modules/@babel/runtime/helpers/asyncToGenerator.js", False),
                      in_app("async_function"))
        self.assertIn(("node_modules/metro-runtime/src/polyfills/require.js", False), in_app("uncaught"))

    def test_swagpay_frames(self):
        """Swag Pay's own code, from its real release bundles."""
        for plat in ("ios", "android"):
            sm = smap(f"swagpay/{plat}.map")
            st = stacks(f"swagpay/{plat}.stacks.json")
            with self.subTest(plat=plat):
                top = sym.symbolicate(st["surface_route"], sm)[0]
                self.assertEqual((top["fn"], top["path"], top["line"], top["in_app"]),
                                 ("parseSurfaceRoute", "src/surfaceRoute.ts", 14, True))
                frames = sym.symbolicate(st["filter_contacts"], sm)
                self.assertEqual([(f["fn"], f["path"]) for f in frames[:3]], [
                    ("sorted.filter$argument_0", "src/contactsDirectory.ts"),
                    (None, None), ("filterContacts", "src/contactsDirectory.ts")])
                # The probe's own frames are not in the bundle.
                self.assertFalse(frames[-1]["resolved"])
                self.assertTrue(frames[-1]["raw"].endswith("(/probe/probe.js:12:6)"))

    def test_swagpay_current_ios_release_stacks(self):
        """Today's iOS Release build keeps Hermes debug info (no
        SOURCEMAP_FILE), so stacks carry JavaScript positions; Metro's
        packager map resolves them, 1-based columns and all."""
        st = stacks("swagpay/ios.withdebug.stacks.json")
        top = sym.symbolicate(st["surface_route"], smap("swagpay/ios.packager.map"))[0]
        self.assertEqual((top["fn"], top["path"], top["line"]),
                         ("parseSurfaceRoute", "src/surfaceRoute.ts", 14))
        # The same frame from the -output-source-map build, via the composed map.
        other = sym.symbolicate(stacks("swagpay/ios.stacks.json")["surface_route"],
                                smap("swagpay/ios.map"))[0]
        self.assertEqual((other["fn"], other["path"], other["line"], other["col"]),
                         (top["fn"], top["path"], top["line"], top["col"]))


class TestMapMatches(unittest.TestCase):
    def test_the_right_map_matches_every_stack(self):
        for rel, map_rel in (("synthetic/v1/stacks.json", V1_MAP),
                             ("synthetic/v2/stacks.json", V2_MAP),
                             ("swagpay/ios.stacks.json", "swagpay/ios.map"),
                             ("swagpay/android.stacks.json", "swagpay/android.map")):
            for sid, text in stacks(rel).items():
                with self.subTest(stack=f"{rel}:{sid}"):
                    v = sym.map_matches(text, smap(map_rel))
                    self.assertIs(v["match"], True, v)
                    self.assertEqual(v["failed"], 0)

    def test_a_map_from_another_build_is_caught(self):
        """v1's stacks against v2's map and back, and Swag Pay's iOS stacks
        against its Android map and back: the same source, other bytecode."""
        for rel, map_rel in (("synthetic/v1/stacks.json", V2_MAP),
                             ("synthetic/v2/stacks.json", V1_MAP),
                             ("swagpay/ios.stacks.json", "swagpay/android.map"),
                             ("swagpay/android.stacks.json", "swagpay/ios.map")):
            for sid, text in stacks(rel).items():
                with self.subTest(stack=f"{rel}:{sid}", map=map_rel):
                    v = sym.map_matches(text, smap(map_rel))
                    self.assertIs(v["match"], False, v)
                    self.assertIn("another build", v["reason"])
                    self.assertFalse(any(f["resolved"] for f in sym.symbolicate(text, smap(map_rel))))

    def test_what_the_check_prevents(self):
        """Without it, the wrong map answers with confident, wrong frames."""
        text = stacks("synthetic/v1/stacks.json")["class_method"]
        right = sym.symbolicate(text, smap(V1_MAP))
        wrong = sym.symbolicate(text, smap(V2_MAP), check=False)
        self.assertTrue(any(w["resolved"] and (w["path"], w["line"], w["fn"]) != (r["path"], r["line"], r["fn"])
                            for r, w in zip(right, wrong)))

    def test_bytecode_stack_with_a_javascript_map(self):
        text = stacks("synthetic/v1/stacks.json")["class_method"]
        v = sym.map_matches(text, smap(V1_PACKAGER))
        self.assertIs(v["match"], False)
        self.assertIn("not a composed Hermes map", v["reason"])
        self.assertFalse(any(f["resolved"] for f in sym.symbolicate(text, smap(V1_PACKAGER))))

    def test_javascript_stack_with_a_composed_map(self):
        text = stacks("synthetic/v1/stacks.withdebug.json")["class_method"]
        v = sym.map_matches(text, smap(V1_MAP))
        self.assertIs(v["match"], False)
        self.assertIn("packager map", v["reason"])
        self.assertFalse(any(f["resolved"] for f in sym.symbolicate(text, smap(V1_MAP))))
        self.assertIs(sym.map_matches(text, smap(V1_PACKAGER))["match"], True)

    def test_offset_past_the_end(self):
        text = "Error: x\n    at a (address at index.android.bundle:1:999999)"
        self.assertIs(sym.map_matches(text, smap(V1_MAP))["match"], False)
        self.assertFalse(sym.symbolicate(text, smap(V1_MAP))[0]["resolved"])

    def test_javascript_line_past_the_end(self):
        # Nothing there, and no evidence either way: a JavaScript bundle can
        # end in lines no mapping covers, so a frame past the map is no proof.
        text = "Error: x\n    at a (index.android.bundle.js:99999:3)"
        self.assertIsNone(sym.map_matches(text, smap(V1_PACKAGER))["match"])
        self.assertFalse(sym.symbolicate(text, smap(V1_PACKAGER))[0]["resolved"])

    def test_frames_from_another_script_are_left_alone(self):
        """A stack can hold frames of scripts other than the bundle (here the
        probe that drove Swag Pay's code). metro-symbolicate looks them up in
        the bundle's map anyway; by their names they are not the bundle's."""
        text = stacks("swagpay/ios.withdebug.stacks.json")["format_rupees"]
        sm = smap("swagpay/ios.packager.map")
        v = sym.map_matches(text, sm)
        self.assertIs(v["match"], True)
        self.assertEqual(v["files"]["/probe/probe.js"], "rejected")
        frames = sym.symbolicate(text, sm)
        self.assertEqual([(f["fn"], f["path"]) for f in frames if f["resolved"]],
                         [("formatRupees", "src/money.ts")])
        self.assertTrue(any(f["resolved"] for f in sym.symbolicate(text, sm, check=False)
                            if "probe.js" in f["raw"]))

    def test_names_catch_what_landing_misses(self):
        """Swag Pay's iOS surface_route stack against its Android map: the one
        bundle frame lands exactly on an Android mapping, in another
        function. Only the name gives it away."""
        text = stacks("swagpay/ios.stacks.json")["surface_route"]
        sm = smap("swagpay/android.map")
        frame = next(f for f in sym.parse_stack(text) if f["kind"] == "bytecode")
        self.assertEqual(sm.probe(frame["line"], frame["col"]), "exact")
        v = sym.map_matches(text, sm)
        self.assertIs(v["match"], False)
        self.assertIn("named frames", v["reason"])

    def test_nothing_to_check(self):
        text = "Error: x\n    at parse (native)\n    at tryCallOne (address at InternalBytecode.js:1:1296)"
        self.assertIsNone(sym.map_matches(text, smap(V1_MAP))["match"])

    def test_bundle_function_count(self):
        text = stacks("synthetic/v1/stacks.json")["closure"]
        bundle = fixture(V1_BUNDLE)
        self.assertIs(sym.map_matches(text, smap(V1_MAP), bundle=bundle)["match"], True)
        v = sym.map_matches(text, smap(V2_MAP), bundle=bundle)
        self.assertIs(v["match"], False)
        self.assertIn("functions", v["reason"])

    def test_takes_raw_or_symbolicated_frames(self):
        text = stacks("synthetic/v1/stacks.json")["closure"]
        for frames in (sym.parse_stack(text), sym.symbolicate(text, smap(V1_MAP))):
            self.assertIs(sym.map_matches(frames, smap(V2_MAP))["match"], False)
            self.assertIs(sym.map_matches(frames, smap(V1_MAP))["match"], True)


class TestFingerprint(unittest.TestCase):
    def test_stable_across_builds(self):
        """v2 added code above the failing functions, on another machine
        (another project directory), as an iOS build: every offset and many
        lines moved, the fingerprints did not."""
        v1 = {k: sym.symbolicate(t, smap(V1_MAP)) for k, t in stacks("synthetic/v1/stacks.json").items()}
        v2 = {k: sym.symbolicate(t, smap(V2_MAP)) for k, t in stacks("synthetic/v2/stacks.json").items()}
        self.assertEqual(set(v1), set(v2))
        moved_lines = 0
        for case in v1:
            with self.subTest(case=case):
                a = next(f for f in v1[case] if f["resolved"])
                b = next(f for f in v2[case] if f["resolved"])
                self.assertNotEqual(sym.parse_stack(a["raw"])[0]["col"], sym.parse_stack(b["raw"])[0]["col"])
                self.assertNotEqual(a["file"], b["file"])
                moved_lines += a["line"] != b["line"]
                self.assertIsNotNone(sym.fingerprint(v1[case]))
                self.assertEqual(sym.fingerprint(v1[case]), sym.fingerprint(v2[case]))
        self.assertGreaterEqual(moved_lines, 3)

    def test_stable_across_platforms(self):
        """Swag Pay's iOS and Android bundles put the same code at other
        offsets."""
        ios, android = stacks("swagpay/ios.stacks.json"), stacks("swagpay/android.stacks.json")
        for case in ("surface_route", "filter_contacts", "build_contact_list", "format_rupees"):
            with self.subTest(case=case):
                a = sym.symbolicate(ios[case], smap("swagpay/ios.map"))
                b = sym.symbolicate(android[case], smap("swagpay/android.map"))
                self.assertIsNotNone(sym.fingerprint(a))
                self.assertEqual(sym.fingerprint(a), sym.fingerprint(b))

    def test_distinct_crash_sites(self):
        st = stacks("synthetic/v1/stacks.json")
        prints = {sym.fingerprint(sym.symbolicate(st[c], smap(V1_MAP)))
                  for c in ("getter", "object_method", "rn_internal", "third_party",
                            "third_party_callback", "closure", "uncaught", "async_function")}
        self.assertEqual(len(prints), 8)

    def test_skips_library_frames(self):
        # fake-lib's validate() threw; the app's caller is the fingerprint.
        frames = sym.symbolicate(stacks("synthetic/v1/stacks.json")["third_party"], smap(V1_MAP))
        key = f"{frames[1]['path']}\n{frames[1]['fn']}"
        self.assertEqual(sym.fingerprint(frames), hashlib.sha1(key.encode()).hexdigest()[:12])

    def test_none_without_an_in_app_frame(self):
        # Swag Pay failing inside React Native's own startup, and a wrong map.
        self.assertIsNone(sym.fingerprint(
            sym.symbolicate(stacks("swagpay/ios.stacks.json")["uncaught"], smap("swagpay/ios.map"))))
        self.assertIsNone(sym.fingerprint(
            sym.symbolicate(stacks("synthetic/v1/stacks.json")["closure"], smap(V2_MAP))))


class TestHbcInfo(unittest.TestCase):
    def test_bundle_header(self):
        info = sym.hbc_info(fixture(V1_BUNDLE))
        self.assertTrue(info["magic_ok"])
        self.assertEqual(info["version"], 98)
        self.assertRegex(info["source_hash"], r"^[0-9a-f]{40}$")
        self.assertEqual(info["file_length"], os.path.getsize(fixture(V1_BUNDLE)))
        self.assertEqual(info["function_count"], len(smap(V1_MAP).function_offsets()))

    def test_not_bytecode(self):
        self.assertEqual(sym.hbc_info(fixture(V1_MAP)),
                         {"magic_ok": False, "version": None, "source_hash": None})

    @unittest.skipUnless(glob.glob(os.path.expanduser(
        "~/Library/Developer/Xcode/DerivedData/iosApp-*/Build/Products/Release-iphonesimulator/main.jsbundle")),
        "no Swag Pay iOS Release build on this machine")
    def test_swagpay_ios_release_build(self):
        """The source hash is the SHA-1 of the JavaScript hermesc compiled,
        which Xcode leaves next to the app."""
        products = os.path.dirname(glob.glob(os.path.expanduser(
            "~/Library/Developer/Xcode/DerivedData/iosApp-*/Build/Products/"
            "Release-iphonesimulator/main.jsbundle"))[0])
        info = sym.hbc_info(os.path.join(products, "Swag Pay.app", "main.jsbundle"))
        self.assertTrue(info["magic_ok"])
        self.assertEqual(info["version"], 98)
        with open(os.path.join(products, "main.jsbundle"), "rb") as fh:
            self.assertEqual(info["source_hash"], hashlib.sha1(fh.read()).hexdigest())

    ANDROID = os.path.expanduser("~/Documents/swag-pay/apps/mobile/composeApp/build/generated")

    @unittest.skipUnless(os.path.exists(os.path.join(ANDROID, "sourcemaps/react/release/index.android.bundle.map")),
                         "no Swag Pay Android release bundle on this machine")
    def test_swagpay_android_release_build(self):
        """The Gradle plugin's bundle and composed map pair up."""
        bundle = os.path.join(self.ANDROID, "assets/react/release/index.android.bundle")
        sm = sym.load_map(os.path.join(self.ANDROID, "sourcemaps/react/release/index.android.bundle.map"))
        self.assertTrue(sm.is_hermes)
        self.assertEqual(sym.hbc_info(bundle)["function_count"], len(sm.function_offsets()))


class TestLoadMap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "m.map")
        shutil.copyfile(fixture(V1_MAP), self.path)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_cached_until_the_file_changes(self):
        a = sym.load_map(self.path)
        self.assertIs(sym.load_map(self.path), a)
        st = os.stat(self.path)
        os.utime(self.path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
        self.assertIsNot(sym.load_map(self.path), a)

    def test_symbolicate_takes_a_path_a_map_or_json(self):
        text = stacks("synthetic/v1/stacks.json")["closure"]
        with open(self.path) as fh:
            raw = json.load(fh)
        expected = sym.symbolicate(text, sym.load_map(self.path))
        self.assertEqual(sym.symbolicate(text, self.path), expected)
        self.assertEqual(sym.symbolicate(text, raw), expected)

    def test_xssi_prefix(self):
        with open(self.path) as fh:
            body = fh.read()
        with open(self.path, "w") as fh:
            fh.write(")]}'" + body)
        self.assertTrue(sym.load_map(self.path).is_hermes)

    def test_invalid_maps_are_refused(self):
        with self.assertRaises(ValueError):
            sym.SourceMap({"version": 2, "sources": [], "mappings": ""})
        with self.assertRaises(ValueError):
            sym.SourceMap({"version": 3, "sources": ["a.js"], "mappings": "AA"})
        with self.assertRaises(ValueError):
            sym.SourceMap({"version": 3, "sources": ["a.js"], "mappings": "A!AA"})


class TestRamBundles(unittest.TestCase):
    def test_module_and_segment_file_names(self):
        sm = smap("maps/ram.map")
        self.assertEqual(sm.parse_file_name("12.js"), (0, 12))
        self.assertEqual(sm.parse_file_name("seg-3.js"), (3, None))
        self.assertEqual(sm.parse_file_name("seg-3_5.js"), (3, 5))
        self.assertEqual(sm.parse_file_name("main.js"), (0, None))
        self.assertEqual(smap(V1_MAP).parse_file_name("12.js"), (0, None))

    def test_unknown_module_is_unresolved(self):
        out = sym.symbolicate("Error: x\n    at a (9.js:1:1)", smap("maps/ram.map"))
        self.assertFalse(out[0]["resolved"])

    def test_names_check_applies_the_module_offset_once(self):
        # Module 1 starts at line 3; its line 2 is the map's line 4, in second().
        sm = sym.SourceMap({"version": 3, "sources": ["/app/main.js"], "names": [],
                            "mappings": "AAAA;AACA;AACA;AACA", "x_facebook_offsets": [0, 2],
                            "x_facebook_sources": [[{"names": ["<global>", "first", "second"],
                                                     "mappings": "AAA;ACC;ACC"}]]})
        self.assertEqual(sm.function_names(2, 0, sm.parse_file_name("1.js")), {"second"})
        self.assertIs(sym.map_matches("Error: x\n    at second (1.js:2:1)", sm)["match"], True)
        self.assertIs(sym.map_matches("Error: x\n    at first (1.js:2:1)", sm)["match"], False)


if __name__ == "__main__":
    unittest.main()
