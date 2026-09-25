"""Source maps, one per app build, for resolving JS error stacks.

A Release build runs Hermes bytecode, so a JS error's stack reads
`at fn (address at main.jsbundle:1:48213)`: the column is a bytecode offset.
symbolicate.py maps it back to file, line and function with the build's
composed source map. This module keeps those maps and finds the right one for
a run.

Maps live under `sourcemaps/<platform>/<app>/<key>.map`, where the key is:
  - the Hermes bundle's source hash, read from its header (`hbc-<sha1>`).
    It identifies the exact JS the map describes, so a map can never be
    applied to the wrong build.
  - Or the build number (`build-<n>`), when the bundle itself isn't to hand.
An iOS run records its bundle's hash at capture (capture_ios.parse_app_bundle),
so its map is found without any configuration.

Release builds come from Swag Pay's apps/mobile/scripts/release_build.py,
which tags each one (`v1.2.0-42`) and attaches its bundles, composed maps and
a manifest to a GitHub Release on the tag. `import_release` registers such a
build's maps, from the Release (`fetch_release`) or a staged folder, under
the bundle's hash and under `build-<versionCode>`, which that script keeps
unique; a `<key>.json` sidecar next to each map names the release.

Resolution happens when a run is read, not when it is recorded, so a map added
after the run still applies. A stack whose frames don't resolve against the
map is reported as unsymbolicated, never as guessed frames.
"""
import hashlib, json, os, shutil

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sourcemaps"))
RELEASE_REPO = os.environ.get("SWAGPERF_RELEASE_REPO", "swag-app-krafton/swag-pay")


def _dir(platform, pkg, root=None):
    return os.path.join(root or ROOT, platform, pkg)


def bundle_key(bundle_path):
    """`hbc-<sha1>` for a Hermes bytecode bundle, or None for anything else."""
    from .capture_ios import HBC_MAGIC
    with open(bundle_path, "rb") as f:
        head = f.read(32)
    if head[:8] != HBC_MAGIC:
        return None
    return "hbc-" + head[12:32].hex()


def add(platform, pkg, map_path, *, bundle=None, build=None, root=None):
    """Register a composed source map for one build. Returns where it went."""
    key = bundle_key(bundle) if bundle else None
    if not key and build is None:
        raise ValueError("name the build: pass the JS bundle it belongs to (--bundle), "
                         "or its build number (--build)")
    key = key or f"build-{build}"
    d = _dir(platform, pkg, root)
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, f"{key}.map")
    shutil.copyfile(map_path, dest)
    return dest


DERIVED_DATA = os.path.expanduser("~/Library/Developer/Xcode/DerivedData")


def discover_ios(pkg, installed_app, *, derived_data=DERIVED_DATA, root=None):
    """Register the composed map Xcode wrote for the build installed on the
    simulator, if it is still in DerivedData. The build phase writes it to
    `<Products>/<config>-iphone*/sourcemaps/main.jsbundle.map`; the bundle
    beside it must hash the same as the installed one, or it is another
    build's map. Returns the registered path, or None."""
    import glob
    try:
        want = bundle_key(os.path.join(installed_app, "main.jsbundle"))
    except OSError:
        return None
    if not want:
        return None
    existing = os.path.join(_dir("ios", pkg, root), f"{want}.map")
    if os.path.exists(existing):
        return existing
    for m in glob.glob(os.path.join(derived_data, "*", "Build", "Products", "*-iphone*",
                                    "sourcemaps", "main.jsbundle.map")):
        products = os.path.dirname(os.path.dirname(m))
        for bundle in glob.glob(os.path.join(products, "*.app", "main.jsbundle")):
            try:
                if bundle_key(bundle) == want:
                    return add("ios", pkg, m, bundle=bundle, root=root)
            except OSError:
                continue
    return None


def listed(root=None):
    """Every registered map, as (platform, app, key, path)."""
    base = root or ROOT
    out = []
    for platform in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        for pkg in sorted(os.listdir(os.path.join(base, platform))):
            for f in sorted(os.listdir(os.path.join(base, platform, pkg))):
                if f.endswith(".map"):
                    out.append((platform, pkg, f[:-4], os.path.join(base, platform, pkg, f)))
    return out


def find(platform, pkg, *, source_hash=None, build=None, root=None):
    """The map for a build: by bundle hash first, then by build number."""
    d = _dir(platform, pkg, root)
    for key in ([f"hbc-{source_hash}"] if source_hash else []) + \
               ([f"build-{build}"] if build is not None else []):
        p = os.path.join(d, f"{key}.map")
        if os.path.exists(p):
            return p
    return None


def map_for_run(run, meta, root=None):
    """The map a recorded run's errors resolve against, or None. A run that
    recorded its bundle's hash is matched by it alone: a local build shares
    its build number with others, and that fallback would pick their map."""
    app = (meta or {}).get("app") or {}
    source_hash = app.get("hbc_source_hash")
    return find(run.get("platform") or "android", run.get("app_pkg") or "",
                source_hash=source_hash,
                build=None if source_hash else app.get("version_code"), root=root)


# ------------------------------------------------------------------ releases

def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def import_release(folder, root=None):
    """Register the maps of one release build: a folder with the
    manifest.json, bundles and composed maps release_build.py produced
    (staged locally, or downloaded from the GitHub Release).

    Every file must match the manifest's sha256, each bundle's header must
    carry the manifest's Hermes source hash, and each map must be a composed
    Hermes map with the bundle's function count. All builds are checked
    before any is registered. A tagged release (version code 2 and up) is
    also registered as `build-<versionCode>`; a dry run, or a code of 1 (a
    local build), only by hash. Returns [(platform, app, [map paths])]."""
    from . import symbolicate as sym
    with open(os.path.join(folder, "manifest.json")) as fh:
        manifest = json.load(fh)
    checked = []
    for b in manifest.get("builds") or []:
        paths = {}
        for part in ("bundle", "map"):
            entry = b.get(part) or {}
            p = os.path.join(folder, entry.get("file") or "")
            if not entry.get("file") or not os.path.isfile(p):
                raise ValueError(f"{b.get('platform')}: the {part} {entry.get('file')!r} is missing")
            if _sha256(p) != entry.get("sha256"):
                raise ValueError(f"{entry['file']} doesn't match the manifest's sha256")
            paths[part] = p
        source_hash = (b.get("hbc") or {}).get("sourceHash")
        if bundle_key(paths["bundle"]) != f"hbc-{source_hash}":
            raise ValueError(f"{b['bundle']['file']} doesn't carry the manifest's Hermes "
                             f"source hash {source_hash}")
        sm = sym.load_map(paths["map"])
        if not sm.is_hermes:
            raise ValueError(f"{b['map']['file']} isn't a composed Hermes map")
        verdict = sym.map_matches([], sm, bundle=paths["bundle"])
        if verdict["match"] is False:
            raise ValueError(f"{b['map']['file']} doesn't belong to {b['bundle']['file']}: "
                             f"{verdict['reason']}")
        checked.append((b, paths["map"], source_hash))
    if not checked:
        raise ValueError(f"{folder}/manifest.json lists no builds")

    release = {k: manifest.get(k) for k in ("tag", "versionName", "versionCode", "commit",
                                            "builtAt", "dryRun")}
    tagged = bool(manifest.get("tag")) and not manifest.get("dryRun")
    out = []
    for b, map_path, source_hash in checked:
        platform, pkg, code = b["platform"], b["appId"], b.get("versionCode")
        keys = [f"hbc-{source_hash}"]
        if tagged and isinstance(code, int) and code >= 2:
            keys.append(f"build-{code}")
        d = _dir(platform, pkg, root)
        os.makedirs(d, exist_ok=True)
        written = []
        for key in keys:
            dest = os.path.join(d, f"{key}.map")
            shutil.copyfile(map_path, dest)
            with open(os.path.join(d, f"{key}.json"), "w") as fh:
                json.dump(dict(release, platform=platform, app=pkg, hbcSourceHash=source_hash),
                          fh, indent=2)
            written.append(dest)
        out.append((platform, pkg, written))
    return out


def find_by_tag(tag, platform, pkg=None, root=None):
    """The map a release imported under `tag` registered for `platform`
    (its hash key), or None."""
    for p, app, key, path in listed(root):
        info = release_info(path) or {}
        if (p == platform and (pkg is None or app == pkg) and key.startswith("hbc-")
                and info.get("tag") == tag):
            return path
    return None


def resolve_text(text, map_path):
    """JS errors in pasted text, resolved against one map.

    The text is either SwagErrors log lines (`adb logcat -d -v raw -s
    SwagPerfError`, or the simulator's os_log), whose chunked records are put
    back together first, or one stack as Hermes printed it. Returns
    (errors, incomplete): each error is its record ({name, message, stack,
    component_stack, fatal, source}, as far as the text gives them) plus
    `frames` from symbolicate.symbolicate; incomplete counts records with a
    chunk missing."""
    import re
    from . import stability, symbolicate as sym
    lines = [(i, line[line.index("swagerr|"):].rstrip())
             for i, line in enumerate(text.splitlines()) if "swagerr|" in line]
    if lines:
        if any("\\134" in chunk for _, chunk in lines):
            # `log show` prints a backslash as \134 (octal), and the JSON
            # record escapes every newline with one.
            octal = re.compile(r"\\([0-3][0-7]{2})")
            lines = [(i, octal.sub(lambda m: chr(int(m.group(1), 8)), chunk)) for i, chunk in lines]
        records, incomplete = stability.assemble_records(lines)
        errors = [stability._loads(t) or {"name": "Unreadable record", "message": t[:120]}
                  for _, t in sorted(records.values())]
    else:
        incomplete = 0
        head = next((line for line in text.splitlines() if line.strip()), "")
        name, _, message = head.strip().partition(": ")
        errors = [{"name": name, "message": message, "stack": text}] if head else []
    return [dict(e, frames=sym.symbolicate(e["stack"], map_path) if e.get("stack") else [])
            for e in errors], incomplete


def release_info(map_path):
    """What release a registered map came from (its sidecar), or None for a
    map added by hand."""
    try:
        with open(map_path[:-len(".map")] + ".json") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def imported_tags(root=None):
    return {info["tag"] for *_, path in listed(root)
            for info in [release_info(path)] if info and info.get("tag")}


def _gh(args):
    import subprocess
    p = subprocess.run(["gh", *args], capture_output=True, text=True)
    if p.returncode:
        raise ValueError(f"gh {' '.join(args)} failed: {(p.stderr or p.stdout).strip()}")
    return p.stdout


def release_tags(repo=None):
    """Tags of the repository's published GitHub Releases, newest first."""
    rows = json.loads(_gh(["release", "list", "-R", repo or RELEASE_REPO, "--limit", "1000",
                           "--json", "tagName,isDraft"]))
    return [r["tagName"] for r in rows if not r.get("isDraft")]


def fetch_release(tag, *, repo=None, root=None, download=None):
    """Download a GitHub Release's files and register its maps."""
    import tempfile
    tmp = tempfile.mkdtemp(prefix="swagperf-release-")
    try:
        (download or _download)(tag, repo or RELEASE_REPO, tmp)
        return import_release(tmp, root=root)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _download(tag, repo, dest):
    _gh(["release", "download", tag, "-R", repo, "-D", dest, "--clobber"])


def _library_fingerprint(frames):
    """For an error thrown with no app frame on the stack (inside React Native
    or a library): the first resolved frame, so the fingerprint still names a
    place, not just the error class."""
    import hashlib
    f = next((f for f in frames if f.get("resolved")), None)
    if not f:
        return None
    key = f"{f.get('path') or f.get('file')}:{f.get('fn')}"
    return "lib-" + hashlib.sha1(key.encode()).hexdigest()[:12]


def resolve(stability, map_path):
    """The stability dict with each JS error's stack resolved.

    Adds to every error: `frames` (resolved frames, or None), `symbolicated`,
    and `fingerprint`, which is stable across builds, unlike a raw bytecode
    offset. Without a map or a resolver, errors keep their raw stacks and
    fall back to their class name as the fingerprint.
    """
    try:
        from . import symbolicate as sym
    except ImportError:
        sym = None
    st = dict(stability or {})
    errs = dict(st.get("errors") or {})
    events = []
    for e in errs.get("events") or []:
        e = dict(e)
        frames, fp = None, None
        if sym and map_path and e.get("stack"):
            try:
                frames = sym.symbolicate(e["stack"], map_path)
                if not any(f.get("resolved") for f in frames):
                    frames = None
                else:
                    fp = sym.fingerprint(frames) or _library_fingerprint(frames)
            except Exception:
                frames = None
        e["frames"] = frames
        e["symbolicated"] = frames is not None
        e["fingerprint"] = fp or f"{e.get('name') or 'Error'}"
        events.append(e)
    errs["events"] = events
    errs["source_map"] = os.path.basename(map_path) if map_path else None
    st["errors"] = errs
    return st
