"""Delete every recorded run and start the history again from run #1.

What goes: every run and its steps and analyses, stress tests, benchmarks,
Flashlight audits, the Copilot's conversations and pins, and the files this
tool wrote into the project's own traces/ folder (traces, the screen cache,
Flashlight's results in traces/flashlight/ and iOS captures in traces/ios/,
Instruments `.trace` bundles included). What stays:
the app catalogue (apps.json, apps.local.json), which is configuration rather
than data, and any trace that lives outside traces/ -- a file you analysed
from elsewhere is yours, not the tool's.
"""
import os
import shutil

from . import store

TRACES = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "traces"))

# Children before parents, so nothing is ever left pointing at a deleted row.
TABLES = ["copilot_pins", "copilot_messages", "copilot_threads", "stress_sessions", "stress_tests",
          "benchmarks", "analyses", "step_metrics", "runs", "flashlight_audits"]


def _flashlight_files(traces_dir):
    d = os.path.join(traces_dir, "flashlight")
    return [os.path.join(d, f) for f in os.listdir(d)] if os.path.isdir(d) else []


def _ios_files(traces_dir):
    """Every file under traces/ios/: converted traces, capture reports and the
    Instruments `.trace` bundles, which are directories."""
    d = os.path.join(traces_dir, "ios")
    return [os.path.join(root, f) for root, _, fs in os.walk(d) for f in fs] if os.path.isdir(d) else []


def plan(db=None, traces_dir=TRACES):
    """What a reset would delete, without deleting anything."""
    c = store.connect(db)
    rows = {t: c.execute(f"select count(*) from {t}").fetchone()[0] for t in TABLES}
    c.close()
    files = sorted(f for f in os.listdir(traces_dir) if f.endswith(".pftrace")) if os.path.isdir(traces_dir) else []
    audit_files = _flashlight_files(traces_dir)
    ios_files = _ios_files(traces_dir)
    size = sum(os.path.getsize(os.path.join(traces_dir, f)) for f in files) + \
        sum(os.path.getsize(f) for f in audit_files + ios_files)
    return {"rows": rows, "trace_files": len(files) + len(audit_files) + len(ios_files),
            "trace_bytes": size,
            "cache": os.path.isdir(os.path.join(traces_dir, ".screens-cache"))}


def reset(db=None, traces_dir=TRACES, keep_traces=False):
    """Delete it all. Run ids start again at 1. Returns what was deleted."""
    done = plan(db, traces_dir)
    c = store.connect(db)
    for t in TABLES:
        c.execute(f"delete from {t}")
    c.execute("delete from sqlite_sequence where name in ({})".format(",".join("?" * len(TABLES))), TABLES)
    c.commit()
    c.execute("vacuum")  # hand the space back rather than leave a large empty file
    c.close()
    if not keep_traces and os.path.isdir(traces_dir):
        for f in os.listdir(traces_dir):
            if f.endswith(".pftrace"):
                os.remove(os.path.join(traces_dir, f))
        shutil.rmtree(os.path.join(traces_dir, ".screens-cache"), ignore_errors=True)
        shutil.rmtree(os.path.join(traces_dir, "flashlight"), ignore_errors=True)
        shutil.rmtree(os.path.join(traces_dir, "ios"), ignore_errors=True)
    else:
        done["trace_files"], done["trace_bytes"] = 0, 0
    return done


def describe(p):
    r = p["rows"]
    lines = [f"  {r['runs']} run(s) with {r['step_metrics']} step rows and {r['analyses']} analyses",
             f"  {r['stress_tests']} stress test(s), {r['benchmarks']} pinned benchmark(s)",
             f"  {r['flashlight_audits']} Flashlight audit(s)",
             f"  {r['copilot_threads']} Copilot conversation(s), {r['copilot_pins']} pinned answer(s)"]
    if p["trace_files"]:
        lines.append(f"  {p['trace_files']} trace file(s) in traces/, {p['trace_bytes'] / 1e9:.2f} GB")
    return "\n".join(lines)
