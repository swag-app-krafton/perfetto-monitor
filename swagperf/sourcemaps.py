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

Resolution happens when a run is read, not when it is recorded, so a map added
after the run still applies. A stack whose frames don't resolve against the
map is reported as unsymbolicated, never as guessed frames.
"""
import os, shutil

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sourcemaps"))


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
    """The map a recorded run's errors resolve against, or None."""
    app = (meta or {}).get("app") or {}
    return find(run.get("platform") or "android", run.get("app_pkg") or "",
                source_hash=app.get("hbc_source_hash"), build=app.get("version_code"),
                root=root)


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
