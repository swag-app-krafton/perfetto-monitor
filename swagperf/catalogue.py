"""Registry of apps under test: our own app, competitors, and references.

Keeping this in one file rather than scattered through CLI flags means a
comparison can be labelled ("Swag Pay vs PhonePe") and scoped correctly: an
instrumented app is read through `extract.py`, everything else through
`derive.py`, and only our own app has budgets worth asserting.

Roles:
  own         the app we build; instrumented, has budgets
  competitor  someone else's binary; derived steps only, no budgets
  reference   not a rival, used to validate the pipeline or bound the scale
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


def load():
    """Built-in catalogue with any local additions merged in by package name."""
    base = {a["pkg"]: a for a in _read(BUILTIN).get("apps", [])}
    for a in _read(USER).get("apps", []):
        if a.get("_deleted"):
            base.pop(a["pkg"], None)
            continue
        base[a["pkg"]] = {**base.get(a["pkg"], {}), **a}
    return sorted(base.values(),
                  key=lambda a: (ROLES.index(a.get("role", "competitor"))
                                 if a.get("role") in ROLES else 9, a.get("name", "")))


def get(pkg):
    for a in load():
        if a["pkg"] == pkg:
            return a
    return None


def display(pkg):
    a = get(pkg)
    return a["name"] if a else (pkg or "unknown")


def is_instrumented(pkg):
    a = get(pkg)
    return bool(a and a.get("instrumented"))


def budgets_for(pkg):
    a = get(pkg)
    return (a or {}).get("budgets") or {}


def save_user(apps):
    with open(USER, "w") as f:
        json.dump({"version": 1, "apps": apps}, f, indent=2)


def add(pkg, *, name=None, role="competitor", category=None, vendor=None,
        region=None, instrumented=False, notes=None, verified=False, budgets=None):
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    cur = _read(USER).get("apps", [])
    cur = [a for a in cur if a.get("pkg") != pkg]
    entry = {"pkg": pkg, "name": name or pkg, "role": role,
             "instrumented": bool(instrumented), "verified": bool(verified)}
    for k, v in (("category", category), ("vendor", vendor), ("region", region),
                 ("notes", notes), ("budgets", budgets)):
        if v:
            entry[k] = v
    cur.append(entry)
    save_user(cur)
    return entry


def remove(pkg):
    """Tombstone a package so a built-in entry can be hidden too."""
    cur = [a for a in _read(USER).get("apps", []) if a.get("pkg") != pkg]
    if any(a["pkg"] == pkg for a in _read(BUILTIN).get("apps", [])):
        cur.append({"pkg": pkg, "_deleted": True})
    save_user(cur)


def mark_verified(pkgs):
    """Record that these packages were seen on a real device."""
    cur = {a["pkg"]: a for a in _read(USER).get("apps", [])}
    for p in pkgs:
        base = copy.deepcopy(get(p) or {"pkg": p, "name": p, "role": "competitor"})
        base.update(cur.get(p, {}))
        base["verified"] = True
        base.pop("_deleted", None)
        cur[p] = base
    save_user(list(cur.values()))
