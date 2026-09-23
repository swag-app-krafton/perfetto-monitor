"""Delete every recorded run and start the history again from run #1.

What goes: every run and its steps and analyses, stress tests, benchmarks,
the Copilot's conversations and pins, and the trace files this tool wrote
into the project's own traces/ folder (with their screen cache). What stays:
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
          "benchmarks", "analyses", "step_metrics", "runs"]


def plan(db=None, traces_dir=TRACES):
    """What a reset would delete, without deleting anything."""
    c = store.connect(db)
    rows = {t: c.execute(f"select count(*) from {t}").fetchone()[0] for t in TABLES}
    c.close()
    files = sorted(f for f in os.listdir(traces_dir) if f.endswith(".pftrace")) if os.path.isdir(traces_dir) else []
    size = sum(os.path.getsize(os.path.join(traces_dir, f)) for f in files)
    return {"rows": rows, "trace_files": len(files), "trace_bytes": size,
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
    else:
        done["trace_files"], done["trace_bytes"] = 0, 0
    return done


def describe(p):
    r = p["rows"]
    lines = [f"  {r['runs']} run(s) with {r['step_metrics']} step rows and {r['analyses']} analyses",
             f"  {r['stress_tests']} stress test(s), {r['benchmarks']} pinned benchmark(s)",
             f"  {r['copilot_threads']} Copilot conversation(s), {r['copilot_pins']} pinned answer(s)"]
    if p["trace_files"]:
        lines.append(f"  {p['trace_files']} trace file(s) in traces/, {p['trace_bytes'] / 1e9:.2f} GB")
    return "\n".join(lines)
