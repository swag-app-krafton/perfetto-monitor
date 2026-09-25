"""LLM bottleneck analyst.

Receives ONLY the extracted metrics + trailing baselines -- never a raw trace.
Its job is attribution and judgement against the Swag Pay shell architecture:
which runtime owns the regression, which architectural risk it corresponds to,
and whether it is worth a human's attention. Measurement is not its job.
"""
import json, os, re, subprocess, tempfile
from .budgets import RISK_MAP, GLOBAL_BUDGETS, METRIC_UNITS, with_unit

MODEL = os.environ.get("SWAGPERF_MODEL", "claude-opus-5")

# Backend order: the local `claude` CLI (uses your Claude subscription, no API
# key needed), then a direct API key if one is configured, then deterministic
# rules. Override with SWAGPERF_BACKEND=cli|api|heuristic.
BACKEND = os.environ.get("SWAGPERF_BACKEND", "auto")

SYSTEM = """You are a mobile performance analyst for Swag Pay, an Android/iOS app \
with an unusual shape: ONE process hosting THREE runtimes.

  1. Compose / Compose Multiplatform  - the shell, Skia on Metal on iOS
  2. Hermes + Fabric (React Native)   - guest renderer, onboarding + history surfaces
  3. Native camera stack              - CameraX / AVFoundation + ML Kit QR decode

Shared logic lives in KMP commonMain. RN reaches it through one thin TurboModule.

ARCHITECTURAL CONSTRAINTS THAT MATTER FOR PERFORMANCE:

* Startup ordering (the strongest decision on the board): for a returning,
  authenticated, onboarded user NO RN, NO Cronet, NO analytics and NO remote config
  may run before the camera is usable. A deferred step starting before first camera
  frame is a CORRECTNESS violation of the architecture, not merely slow.
* First-run inverts this: onboarding IS an RN surface, so Hermes is on the critical
  path and the camera is not. Two paths, two North Star targets. Never judge one by the other.
* Frame pacing at the interop seam: Compose and RN are two render loops. On iOS the
  RN surface is a UIKit hole punched through a Skia canvas. Jank clustered at surface
  boundaries points here.
* Sustained-scan thermal: continuous preview + per-frame inference throttles mid-range
  devices over minutes. Progressive frame-time drift means thermal, NOT a code change.
  Random scattered jank does NOT mean thermal.
* Peak memory: Hermes + Fabric + Cronet's Chromium stack + CameraX/ML Kit buffers +
  Skia + SQLite are all resident simultaneously. RAM usage (resident set size) growth
  across a session that does
  not return to baseline suggests orphaned RN surfaces -- a Surface started and never
  stopped keeps its whole JS component tree alive for the life of the process.
* Baseline Profiles are known to be ABSENT. Compose startup regressions may reflect
  that gap rather than a specific code change.

HOW TO ANALYSE:
- Attribute each finding to a runtime: compose | hermes_rn | native_camera | cross_runtime | unknown.
- Distinguish a REGRESSION (worse than this step's own trailing baseline) from a
  BREACH (over its stated North Star target; kind "budget_breach"). A step can be
  either, both, or neither.
- Use the child-slice breakdown to attribute within a step. Say which child moved.
- If the evidence does not identify a cause, say so plainly. Do not invent one.
- Be concrete and brief. An engineer reads this at the top of a CI log.
- The payload says which platform the run measured. When "simulator" is true the
  run is on the iOS Simulator: its numbers come from the Mac's CPU with a warm
  cache, it carries no North Star targets, and its regressions are against other simulator
  runs only. Never return "fail" for a simulator run, and say the numbers are
  indicative. Frames are not measured on the simulator; do not read their
  absence as a finding.
- Call the memory metric "RAM usage" (and its growth "RAM growth") in all prose.
  The payload keys are named peak_rss_mb / rss_growth_mb for schema stability, but
  "RSS" is jargon this dashboard does not show the reader -- never write it.
- Call a metric's threshold its "North Star target", never its "budget" (the payload
  keys keep "budget" for schema stability). The time one frame has to draw is the
  "frame deadline".
- The payload's "run" block says what startup measures here ("startup_metric").
  A derived run's startup is time to initial display from Android's launch slices,
  not time to first camera frame, whatever its key is called. When
  "startup_target_reason" is set there is no startup North Star target: say so,
  and never call the startup a pass or a fail against one.
- Every number you write must come from the payload. Don't compute new figures
  beyond a plain difference or percentage of two numbers you quote.
- When the payload has "vs_benchmark", it is this run compared with the pinned
  benchmark run for its app, start path and device ("benchmark" says which run).
  Write "benchmark_comparison": two to four sentences on what moved against it and
  by how much, citing only vs_benchmark's values. Without it, "benchmark_comparison"
  is null.

Return ONLY valid JSON, no markdown fence, matching exactly:
{
  "verdict": "pass" | "warn" | "fail",
  "headline": "one sentence, <=120 chars",
  "findings": [
    {"title": "...", "runtime": "...", "severity": "high|medium|low",
     "kind": "regression|budget_breach|ordering_violation|memory|thermal",
     "evidence": "cite the specific numbers you used",
     "architectural_risk": "which named risk this maps to, or null",
     "recommendation": "concrete next action"}
  ],
  "dismissed": ["signals you looked at and judged benign, with the reason"],
  "summary": "three to five plain sentences for someone who wasn't watching the run: what it measured, what stands out, what to do next",
  "benchmark_comparison": "two to four sentences, or null"
}"""


def _stability_summary(st):
    if not st:
        return None
    h, e, cr, a = (st.get(k) or {} for k in ("hangs", "errors", "crash", "anrs"))
    return {"hangs": {k: h.get(k) for k in ("count", "microhangs", "longest_ms", "total_ms",
                                            "rate_s_per_hr", "startup", "per_screen")},
            "js_errors": {k: e.get(k) for k in ("js", "js_fatal", "by_name", "by_source", "per_screen")},
            "anrs": {k: a.get(k) for k in ("measured", "count", "by_type", "per_screen")} if a else None,
            "crashed": bool(cr.get("crashed")),
            "crashes": {"count": cr.get("count"),
                        "signatures": [c.get("signature") for c in (cr.get("events") or [])][:5]}}


def build_payload(metrics, regs, baselines, *, run=None, vs_benchmark=None):
    """What the model sees: extracted numbers and baselines, never a trace.
    `run` names the run (id, label, device, app version) and `vs_benchmark` is
    the run against its pinned benchmark (F-024, from store.compare)."""
    derived = bool(metrics.get("derived"))
    payload = {
        "run": {**{k: v for k, v in (run or {}).items() if v is not None},
                "derived": derived,
                "startup_metric": metrics.get("startup_metric")
                or ("time to initial display" if derived else "time to first camera frame"),
                "startup_target_reason": (metrics.get("startup") or {}).get("target_reason")},
        "platform": metrics.get("platform") or "android",
        "simulator": bool(metrics.get("simulator")),
        "path_kind": metrics["path_kind"],
        "startup": metrics["startup"],
        "ordering_violations": metrics["ordering_violations"],
        "frames": metrics["frames"],
        "memory": metrics["memory"],
        "global_budgets": GLOBAL_BUDGETS,
        "budget_breaches": metrics["breaches"],
        "steps": [{k: v for k, v in s.items() if k != "start_ms"} for s in metrics["steps"]],
        "regressions_vs_baseline": regs,
        # Counts and names only: no stacks, which can be long and add nothing
        # the numbers don't.
        "stability": _stability_summary(metrics.get("stability")),
        "step_baselines": baselines,
        "risk_map": RISK_MAP,
    }
    if vs_benchmark:
        payload["vs_benchmark"] = vs_benchmark
    return payload


def _parse(text):
    """Pull the JSON object out of a model response."""
    text = (text or "").strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) > 1:
            text = parts[1].removeprefix("json").strip()
    if not text.startswith("{"):
        i, j = text.find("{"), text.rfind("}")
        if i >= 0 and j > i:
            text = text[i:j + 1]
    return json.loads(text)


def analyse_via_cli(metrics, regs, baselines, *, model=MODEL, timeout=180):
    """Analyse using the local `claude` CLI, which uses the user's subscription.

    No API key required. Returns None if the CLI is unavailable or fails, so the
    caller can fall through to the next backend.
    """
    return _ask_cli(build_payload(metrics, regs, baselines), model=model, timeout=timeout)


def _ask_cli(payload, *, model=MODEL, timeout=180):
    from . import llm
    exe = llm.claude_bin()   # SWAGPERF_CLAUDE_BIN, else PATH
    if not exe:
        return None
    prompt = (SYSTEM + "\n\n---\n\nAnalyse this Swag Pay trace run. "
              "Respond with the JSON object only.\n\n" + json.dumps(payload, indent=2))
    # A dashboard button can start this, so the session gets nothing it could
    # act with: no tools, no MCP servers, nothing saved, and an empty working
    # directory rather than the repository.
    cmd = [exe, "-p", prompt, "--output-format", "json", "--tools", "",
           "--strict-mcp-config", "--no-session-persistence"]
    if model:
        cmd += ["--model", model]
    try:
        with tempfile.TemporaryDirectory(prefix="swagperf-analyst-") as cwd:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if p.returncode != 0:
        return None
    raw = p.stdout.strip()
    try:   # --output-format json wraps the reply in an envelope
        env = json.loads(raw)
        raw = env.get("result", raw) if isinstance(env, dict) else raw
    except json.JSONDecodeError:
        pass
    try:
        out = _parse(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(out, dict) or "verdict" not in out:
        return None
    out["_model"] = f"{model} (claude cli)"
    out["_backend"] = "cli"
    return out


def analyse(metrics, regs, baselines, *, model=MODEL, api_key=None):
    return _ask_api(build_payload(metrics, regs, baselines), model=model, api_key=api_key)


def _ask_api(payload, *, model=MODEL, api_key=None):
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key or key.startswith("sk-ant-REPLACE"):
        return {"verdict": "unknown", "headline": "No ANTHROPIC_API_KEY set; analysis skipped.",
                "findings": [], "dismissed": [], "_skipped": True}
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(
            model=model, max_tokens=3000, system=SYSTEM,
            messages=[{"role": "user", "content":
                       "Analyse this Swag Pay trace run.\n\n" + json.dumps(payload, indent=2)}])
    except Exception:
        # A network or API failure falls through to the next backend (or no
        # summary) rather than failing the capture that asked for it.
        return None
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    if text.startswith("```"):
        text = text.split("```")[1].removeprefix("json").strip()
    try:
        out = _parse(text)
    except json.JSONDecodeError:
        out = {"verdict": "unknown", "headline": "Model returned unparseable JSON",
               "findings": [], "dismissed": [], "_raw": text[:2000]}
    out["_model"] = model
    out["_backend"] = "api"
    return out


SIMULATOR_PREFIX = "Simulator run, indicative only: "


def cap_for_simulator(res, metrics):
    """A simulator run never fails. Its numbers come from the Mac's CPU, so a
    fail would be a verdict on the Mac; the most it can say is warn. Applied
    to the model's answer too, rather than trusting the prompt to hold."""
    if not metrics.get("simulator") or not isinstance(res, dict):
        return res
    if res.get("verdict") == "fail":
        res["verdict"] = "warn"
    head = res.get("headline") or ""
    if not head.startswith(SIMULATOR_PREFIX):
        res["headline"] = SIMULATOR_PREFIX + (head[:1].lower() + head[1:] if head else "")
    return res


def summarise(metrics, regs, baselines, *, run=None, vs_benchmark=None, model=MODEL,
              backend=None):
    """An AI summary of a recorded run (F-023), or None when no model answered.

    Model backends only: under the rules ("heuristic") there is no summary to
    write, because the rules' verdict is already the run's verdict. The result
    never becomes the verdict (store kind 'summary'). Numbers the model wrote
    that aren't in the payload are listed in `_unverified` for the page to flag.
    """
    backend = backend or BACKEND
    payload = build_payload(metrics, regs, baselines, run=run, vs_benchmark=vs_benchmark)
    res = None
    if backend in ("auto", "cli"):
        res = _ask_cli(payload, model=model)
    if res is None and backend in ("auto", "api"):
        res = _ask_api(payload, model=model)
        if res and (res.get("_skipped") or res.get("verdict") not in ("pass", "warn", "fail")):
            res = None
    if res is None:
        return None
    res = cap_for_simulator(res, metrics)
    res["_unverified"] = unverified_numbers(res, payload)
    if vs_benchmark:
        res["_benchmark"] = vs_benchmark
    return res


# Numbers the prompt itself states, which the model may repeat: the three
# runtimes, the 60 Hz frame deadline and its multiples.
_PROMPT_NUMBERS = {16.67, 16.7, 60.0, 90.0, 120.0, 100.0}
_NUMBER = re.compile(r"(?<![\w.])[-+−]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])[-+−]?\d+(?:\.\d+)?")
_TEXT_FIELDS = ("headline", "summary", "benchmark_comparison")


def _numbers_in(obj, out):
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.add(abs(float(obj)))
    elif isinstance(obj, str):
        for tok in _NUMBER.findall(obj):
            out.add(abs(float(tok.replace(",", "").replace("−", "-"))))
    elif isinstance(obj, dict):
        for v in obj.values():
            _numbers_in(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numbers_in(v, out)


# Versions (2.3.1), dates and clock times are identifiers, not measurements.
_NOT_A_NUMBER = re.compile(r"\b\d+(?:\.\d+){2,}\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}:\d{2}\b")


def _tokens(text):
    for tok in _NUMBER.findall(_NOT_A_NUMBER.sub(" ", text)):
        yield tok, abs(float(tok.replace(",", "").replace("−", "-")))


def _matches(v, dp, known):
    """Written at `dp` decimals, `v` stands for a known number when rounding
    it gives `v`, or cutting it off does (98.75 written as 98.7)."""
    unit = 10 ** -dp
    return any(round(k, dp) == round(v, dp) or 0 <= k - v < unit - 1e-9 for k in known)


def unverified_numbers(res, payload):
    """Numbers in the model's text that the payload doesn't contain, as
    written. A number matches when a payload number rounds or truncates to it
    at the precision it was written with (493.3 matches "493"). The prompt
    allows a plain difference or percentage of two numbers it quotes, so one
    worked out from two verified numbers anywhere in the summary also matches
    (420 and 414.56 make 5.44 of headroom). Small whole numbers (0 to 10) are
    counts more often than measurements; versions, dates and times are
    identifiers. Neither is checked."""
    known = set(_PROMPT_NUMBERS)
    _numbers_in(payload, known)
    texts = [res.get(k) for k in _TEXT_FIELDS]
    for f in res.get("findings") or []:
        texts += [f.get("title"), f.get("evidence"), f.get("recommendation")]
    texts += [d if isinstance(d, str) else (d or {}).get("title") for d in res.get("dismissed") or []]
    toks = [(tok, v, len(tok.split(".")[1]) if "." in tok else 0)
            for text in texts if isinstance(text, str) for tok, v in _tokens(text)]
    quoted = {v for _, v, dp in toks if _matches(v, dp, known)}
    worked = {abs(a - b) for a in quoted for b in quoted if a != b}
    worked |= {abs(a - b) / b * 100 for a in quoted for b in quoted if a != b and b}
    out = []
    for tok, v, dp in toks:
        if (v == int(v) and v <= 10) or _matches(v, dp, known) or _matches(v, dp, worked):
            continue
        shown = tok.lstrip("+-−")
        if shown not in out:
            out.append(shown)
    return out


def run_analysis(metrics, regs, baselines, *, model=MODEL, backend=None):
    """Try each backend in order and return the first that produces a verdict."""
    backend = backend or BACKEND
    if backend in ("auto", "cli"):
        res = analyse_via_cli(metrics, regs, baselines, model=model)
        if res:
            return cap_for_simulator(res, metrics)
        if backend == "cli":
            return heuristic(metrics, regs)
    if backend in ("auto", "api"):
        res = analyse(metrics, regs, baselines, model=model)
        if res and not res.get("_skipped"):
            return cap_for_simulator(res, metrics)
    return heuristic(metrics, regs)


# Reader-facing metric names, so a rules-only finding does not show a column key.
METRIC_NAMES = {
    "time_to_first_camera_frame_ms": "Startup time",
    "slow_frame_pct": "Slow frames",
    "janky_frame_pct": "Janky frames",
    "peak_rss_mb": "Peak RAM usage",
    "rss_growth_mb": "RAM growth",
    "thermal_drift_pct": "Thermal drift",
}


# Where to look next for each breach. Every rules-only finding used to end in
# the same "investigate or re-baseline", which tells the reader nothing; each
# of these points at the view that answers the question for that metric.
NEXT_STEP = {
    "peak_rss_mb": "Open Screens > Navigation stack: a high peak on a cheap screen usually "
                   "means screens held open beneath it, not the screen itself.",
    "rss_growth_mb": "Open Screens > Session timeline and find the screen where RAM steps up "
                     "and never comes back down; repeat visits to it should be flat.",
    "janky_frame_pct": "Open Screens and sort by App jank: only 'app deadline missed' frames "
                       "are the app's fault; buffer stuffing and dropped frames are not.",
    "slow_frame_pct": "Open Screens and check Slow frames per screen, then App jank to separate "
                      "the app's misses from the compositor's.",
    "time_to_first_camera_frame_ms": "Open Startup and compare the step breakdown with the "
                                     "benchmark run; the largest step's children name the cost.",
    "thermal_drift_pct": "Re-run as a sustained single-screen session (e.g. a stress test) to "
                         "confirm it is heat and not a change of workload.",
}


def stability_findings(metrics):
    """Crashes, JS errors and hangs after the first frame (stability.py).
    Hangs before the first frame are startup, which has its own metric."""
    st = metrics.get("stability") or {}
    out = []
    cr = st.get("crash") or {}
    if cr.get("crashed"):
        n = cr.get("count") or 1
        sigs = ", ".join(dict.fromkeys(c.get("signature") for c in (cr.get("events") or []) if c.get("signature")))
        out.append({"title": "The app crashed during the run" if n == 1 else f"The app crashed {n} times during the run",
                    "runtime": "unknown", "severity": "high", "kind": "crash",
                    "evidence": sigs or cr.get("reason") or "the process ended on its own",
                    "architectural_risk": None,
                    "recommendation": "Open Crashes & ANRs for the crash log. A fatal JS error just "
                                      "before a crash points at React Native; none points at native code."})
    e = st.get("errors") or {}
    if e.get("js"):
        top = sorted((e.get("by_name") or {}).items(), key=lambda kv: -kv[1])[:3]
        names = ", ".join(f"{k} ×{v}" for k, v in top)
        out.append({"title": f"{e['js']} JS error(s), {e.get('js_fatal', 0)} fatal",
                    "runtime": "hermes_rn", "severity": "high" if e.get("js_fatal") else "medium",
                    "kind": "js_error", "evidence": names, "architectural_risk": None,
                    "recommendation": "Open Crashes & ANRs for the resolved stack and the screen "
                                      "each error happened on."})
    a = st.get("anrs") or {}
    if a.get("count"):
        types = ", ".join(f"{k} ×{v}" for k, v in sorted((a.get("by_type") or {}).items(), key=lambda kv: -kv[1]))
        screens = ", ".join(sorted(a.get("per_screen") or {}))
        out.append({"title": f"{a['count']} ANR(s): Android declared the app not responding",
                    "runtime": "unknown", "severity": "high", "kind": "anr",
                    "evidence": f"{types} on {screens}" if screens else types,
                    "architectural_risk": None,
                    "recommendation": "Open Crashes & ANRs: each ANR names the screen and what the "
                                      "main thread was doing."})
    h = st.get("hangs") or {}
    if h.get("count"):
        out.append({"title": f"{h['count']} hang(s) after the first frame",
                    "runtime": "unknown",
                    "severity": "high" if (h.get("longest_ms") or 0) >= 1000 else "medium",
                    "kind": "hang",
                    "evidence": f"longest {h.get('longest_ms')} ms, {h.get('total_ms')} ms in all",
                    "architectural_risk": None,
                    "recommendation": "Open Frame pacing: each hang names the screen it happened on."})
    return out


def heuristic(metrics, regs):
    """Deterministic fallback so the tool is useful with no API key at all."""
    findings = []
    for v in metrics["ordering_violations"]:
        findings.append({"title": f"Deferred work on critical path: {v['step']}",
                         "runtime": "hermes_rn" if "hermes" in v["step"] else "cross_runtime",
                         "severity": "high", "kind": "ordering_violation",
                         "evidence": v["detail"],
                         "architectural_risk": RISK_MAP["deferred_leak"],
                         "recommendation": "Restore lazy start; this violates startup-routing."})
    for r in regs:
        findings.append({"title": f"{r['step']} regressed {r['delta_pct']}%",
                         "runtime": "unknown", "severity": "high" if r["delta_pct"] > 25 else "medium",
                         "kind": "regression",
                         "evidence": f"{r['dur_ms']}ms vs baseline {r['baseline_ms']}ms (z={r['z']}, n={r['n_baseline']})",
                         "architectural_risk": None,
                         "recommendation": "Compare child slices against the previous run."})
    findings += stability_findings(metrics)
    for b in metrics["breaches"]:
        # Same threshold regressions use. Hard-coding every breach as "medium"
        # meant no breach could ever fail a run: a session at 4x its RAM growth
        # target and 42% over its peak-RAM target still read WARN.
        sev = "high" if (b.get("over_by_pct") or 0) > 25 else "medium"
        unit = METRIC_UNITS.get(b["metric"], "")
        findings.append({"title": f"{METRIC_NAMES.get(b['metric'], b['metric'])} over its North Star target",
                         "runtime": "unknown",
                         "severity": sev, "kind": "budget_breach",
                         "evidence": f"{with_unit(b['value'], unit)} vs {with_unit(b['budget'], unit)} "
                                     f"(+{b['over_by_pct']}%)",
                         "architectural_risk": RISK_MAP.get(b["metric"]),
                         "recommendation": NEXT_STEP.get(b["metric"],
                                                         "Investigate, or revisit the North Star target.")})
    verdict = "fail" if any(f["severity"] == "high" for f in findings) else ("warn" if findings else "pass")
    # Lead with the worst finding rather than a count: "3 finding(s)" makes the
    # reader open the list to learn anything, the top finding usually says it.
    order = {"high": 0, "medium": 1, "low": 2}
    top = sorted(findings, key=lambda f: order.get(f["severity"], 3))
    if not top and metrics.get("simulator"):
        headline = ("No step moved against other simulator runs; no North Star targets apply "
                    "on a simulator (rules only, no LLM).")
    elif not top:
        headline = ("Every measured metric is within its North Star target and baseline "
                    "(rules only, no LLM).")
    else:
        headline = f"{top[0]['title']}: {top[0]['evidence']}"
        if len(top) > 1:
            more = len(top) - 1
            headline += f", and {more} more finding{'s' if more > 1 else ''}"
    return cap_for_simulator({"verdict": verdict,
                              "headline": headline,
                              "findings": findings, "dismissed": [], "_heuristic": True}, metrics)
