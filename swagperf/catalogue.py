"""Registry of apps under test: our own app, competitors, and references.

Keeping this in one file rather than scattered through CLI flags means a
comparison can be labelled ("Swag Pay vs PhonePe") and scoped correctly: an
instrumented app is read through `extract.py`, everything else through
`derive.py`, and only our own app has budgets worth asserting.

Roles:
  own         the app we build; instrumented, has budgets
  competitor  someone else's binary; derived steps only, no budgets
  reference   not a rival, used to validate the pipeline or bound the scale

Entries are keyed by (platform, pkg): an iOS bundle id can equal the Android
package name (`com.swag.pay` on both), and the two are different binaries
with different budgets. `platform` defaults to "android".
"""
import json, os, copy

HERE = os.path.dirname(os.path.abspath(__file__))
BUILTIN = os.path.join(HERE, "apps.json")
# A user file, if present, is layered over the built-in list so local additions
# survive an upgrade of this package.
USER = os.environ.get("SWAGPERF_APPS",
                      os.path.join(HERE, "..", "apps.local.json"))

ROLES = ("own", "competitor", "reference")


def _read(path):
    if not path or not os.path.exists(path):
        return {"apps": []}
    with open(path) as f:
        return json.load(f)


def _is_placeholder(a):
    """An entry the tool wrote on its own, with nothing a person decided.

    Profiling an unknown package records it as an unlabelled competitor so the
    run is attributable. That must never *override* a real built-in entry: it
    is how Swag Pay's own package ended up shown as a nameless competitor --
    the built-in listed a mistyped package, the real one was auto-added as a
    placeholder, and the placeholder then won the merge even once the typo was
    fixed. `auto` marks new placeholders; the name-equals-package test catches
    ones written before that flag existed.
    """
    return bool(a.get("auto")) or a.get("name") == a.get("pkg")


PLATFORMS = ("android", "ios")


def platform_of(a):
    return a.get("platform") or "android"


def _key(a):
    return (platform_of(a), a["pkg"])


def load():
    """Built-in catalogue with any local additions merged in by (platform, package)."""
    base = {_key(a): {**a, "platform": platform_of(a)} for a in _read(BUILTIN).get("apps", [])}
    for a in _read(USER).get("apps", []):
        k = _key(a)
        if a.get("_deleted"):
            base.pop(k, None)
            continue
        if k in base and _is_placeholder(a):
            continue
        base[k] = {**base.get(k, {}), **a, "platform": platform_of(a)}
    return sorted(base.values(),
                  key=lambda a: (ROLES.index(a.get("role", "competitor"))
                                 if a.get("role") in ROLES else 9, a.get("name", "")))


def get(pkg, platform="android"):
    for a in load():
        if a["pkg"] == pkg and a["platform"] == (platform or "android"):
            return a
    return None


def display(pkg, platform="android"):
    a = get(pkg, platform)
    return a["name"] if a else (pkg or "unknown")


def is_instrumented(pkg, platform="android"):
    a = get(pkg, platform)
    return bool(a and a.get("instrumented"))


def budgets_for(pkg, platform="android"):
    a = get(pkg, platform)
    return (a or {}).get("budgets") or {}


def save_user(apps):
    with open(USER, "w") as f:
        json.dump({"version": 1, "apps": apps}, f, indent=2)


def add(pkg, *, name=None, role="competitor", category=None, vendor=None,
        region=None, instrumented=False, notes=None, verified=False, budgets=None,
        auto=False, platform="android"):
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if platform not in PLATFORMS:
        raise ValueError(f"platform must be one of {PLATFORMS}")
    cur = _read(USER).get("apps", [])
    cur = [a for a in cur if _key(a) != (platform, pkg)]
    entry = {"pkg": pkg, "name": name or pkg, "role": role,
             "instrumented": bool(instrumented), "verified": bool(verified)}
    if platform != "android":
        entry["platform"] = platform
    for k, v in (("category", category), ("vendor", vendor), ("region", region),
                 ("notes", notes), ("budgets", budgets), ("auto", auto)):
        if v:
            entry[k] = v
    cur.append(entry)
    save_user(cur)
    return entry


def remove(pkg, platform="android"):
    """Tombstone a package so a built-in entry can be hidden too."""
    cur = [a for a in _read(USER).get("apps", []) if _key(a) != (platform, pkg)]
    if any(_key(a) == (platform, pkg) for a in _read(BUILTIN).get("apps", [])):
        tomb = {"pkg": pkg, "_deleted": True}
        if platform != "android":
            tomb["platform"] = platform
        cur.append(tomb)
    save_user(cur)


def mark_verified(pkgs, platform="android"):
    """Record that these packages were seen on a real device."""
    cur = {_key(a): a for a in _read(USER).get("apps", [])}
    for p in pkgs:
        base = copy.deepcopy(get(p, platform) or {"pkg": p, "name": p, "role": "competitor"})
        base.update(cur.get((platform, p), {}))
        base["verified"] = True
        base.pop("_deleted", None)
        if platform != "android":
            base["platform"] = platform
        cur[(platform, p)] = base
    save_user(list(cur.values()))
