"""AI summaries of recorded runs (F-023), compared with the pinned benchmark (F-024).

A summary is written by a model, for any run in history, from the numbers the
run recorded: never from its trace, which may be gone. It is stored as its own
kind of analysis row and never replaces the run's verdict (the rules' verdict
from capture), so triage, the Copilot and the release gates are unaffected by
it. The dashboard's Generate summary button and the capture switch run it as a
background job (jobs.start_summary); `swagperf summary RUN` runs it in place.
"""
from . import analyst, runmeta, store


def _run_details(run_id, metrics, db=None):
    """Who the run is, for the payload: id, label, device and app version."""
    name, build = runmeta.version_of(
        {"device": metrics.get("device"), "app_version": metrics.get("app_version"),
         "app_pkg": metrics.get("app_pkg")}, metrics.get("meta"))
    return {"id": run_id, "label": metrics.get("label"), "device": metrics.get("device"),
            "app_version": runmeta.version_label(name, build) if (name or build is not None) else None}


def benchmark_comparison(run_id, metrics, db=None):
    """This run against the pinned benchmark for its app, start path and device
    (store.get_benchmark's scope), shaped like store.compare so the dashboard's
    comparison tables render it as they render Compare. None for a simulator
    run (a simulator run is never a benchmark and never judged against one),
    for the benchmark run itself, and when nothing is pinned.

    Stored inside the summary as the snapshot the model saw, so the table stays
    true to the text even after someone pins a different run."""
    if metrics.get("simulator"):
        return None
    pin = store.get_benchmark(path_kind=metrics.get("path_kind"), device=metrics.get("device"),
                              app_pkg=metrics.get("app_pkg"),
                              platform=metrics.get("platform") or "android", db=db)
    if not pin or pin["run_id"] == run_id:
        return None
    cmp = store.compare(run_id, pin["run_id"], db=db)
    bench = store.run_metrics(pin["run_id"], db=db) or {}
    name, build = runmeta.version_of({"device": bench.get("device"), "app_version": bench.get("app_version"),
                                      "app_pkg": bench.get("app_pkg")}, bench.get("meta"))
    cmp["base"]["version"] = runmeta.version_label(name, build) if (name or build is not None) else None
    cmp["run"]["version"] = _run_details(run_id, metrics, db)["app_version"]
    # Child slices stay out: the step rows carry the comparison, and the
    # model's payload stays small.
    cmp["steps"] = [{**s, "children": []} for s in cmp["steps"]]
    cmp["pinned_note"] = pin.get("note")
    return cmp


def write(run_id, *, db=None, backend=None):
    """Write and store an AI summary of a recorded run. Returns the stored
    result, or None when no model session answered (nothing is written).
    Raises LookupError for an unknown run."""
    metrics = store.run_metrics(run_id, db=db)
    if metrics is None:
        raise LookupError(f"no run #{run_id}")
    regs = store.regressions(run_id, db=db)
    baselines = store.step_baselines(run_id, metrics, db=db)
    res = analyst.summarise(metrics, regs, baselines, run=_run_details(run_id, metrics, db),
                            vs_benchmark=benchmark_comparison(run_id, metrics, db),
                            backend=backend)
    if res is None:
        return None
    store.add_analysis(run_id, res, kind="summary", db=db)
    return res


NO_MODEL = ("No model session answered, so no summary was written. Summaries use the "
            "`claude` CLI you're logged in to (or SWAGPERF_CLAUDE_BIN), then ANTHROPIC_API_KEY. "
            "The run's verdict is unchanged.")
