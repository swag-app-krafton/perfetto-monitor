"""LLM bottleneck analyst.

Receives ONLY the extracted metrics + trailing baselines -- never a raw trace.
Its job is attribution and judgement against the Swag Pay shell architecture:
which runtime owns the regression, which architectural risk it corresponds to,
and whether it is worth a human's attention. Measurement is not its job.
"""
import json, os, shutil, subprocess
from .budgets import RISK_MAP, GLOBAL_BUDGETS

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
  path and the camera is not. Two paths, two budgets. Never judge one by the other.
* Frame pacing at the interop seam: Compose and RN are two render loops. On iOS the
  RN surface is a UIKit hole punched through a Skia canvas. Jank clustered at surface
  boundaries points here.
* Sustained-scan thermal: continuous preview + per-frame inference throttles mid-range
  devices over minutes. Progressive frame-time drift means thermal, NOT a code change.
  Random scattered jank does NOT mean thermal.
* Peak memory: Hermes + Fabric + Cronet's Chromium stack + CameraX/ML Kit buffers +
  Skia + SQLite are all resident simultaneously. RSS growth across a session that does
  not return to baseline suggests orphaned RN surfaces -- a Surface started and never
  stopped keeps its whole JS component tree alive for the life of the process.
* Baseline Profiles are known to be ABSENT. Compose startup regressions may reflect
  that gap rather than a specific code change.

HOW TO ANALYSE:
- Attribute each finding to a runtime: compose | hermes_rn | native_camera | cross_runtime | unknown.
- Distinguish a REGRESSION (worse than this step's own trailing baseline) from a
  BUDGET BREACH (over the stated budget). A step can be either, both, or neither.
- Use the child-slice breakdown to attribute within a step. Say which child moved.
- If the evidence does not identify a cause, say so plainly. Do not invent one.
- Be concrete and brief. An engineer reads this at the top of a CI log.

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
  "dismissed": ["signals you looked at and judged benign, with the reason"]
}"""


def build_payload(metrics, regs, baselines):
    return {
        "path_kind": metrics["path_kind"],
        "startup": metrics["startup"],
        "ordering_violations": metrics["ordering_violations"],
        "frames": metrics["frames"],
        "memory": metrics["memory"],
        "global_budgets": GLOBAL_BUDGETS,
        "budget_breaches": metrics["breaches"],
        "steps": [{k: v for k, v in s.items() if k != "start_ms"} for s in metrics["steps"]],
        "regressions_vs_baseline": regs,
        "step_baselines": baselines,
        "risk_map": RISK_MAP,
    }


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
    exe = shutil.which("claude")
    if not exe:
        return None
    payload = build_payload(metrics, regs, baselines)
    prompt = (SYSTEM + "\n\n---\n\nAnalyse this Swag Pay trace run. "
              "Respond with the JSON object only.\n\n" + json.dumps(payload, indent=2))
    cmd = [exe, "-p", prompt, "--output-format", "json"]
    if model:
        cmd += ["--model", model]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
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
    import anthropic
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key or key.startswith("sk-ant-REPLACE"):
        return {"verdict": "unknown", "headline": "No ANTHROPIC_API_KEY set; analysis skipped.",
                "findings": [], "dismissed": [], "_skipped": True}
    payload = build_payload(metrics, regs, baselines)
    client = anthropic.Anthropic(api_key=key)
    msg = client.messages.create(
        model=model, max_tokens=2000, system=SYSTEM,
        messages=[{"role": "user", "content":
                   "Analyse this Swag Pay trace run.\n\n" + json.dumps(payload, indent=2)}])
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


def run_analysis(metrics, regs, baselines, *, model=MODEL, backend=None):
    """Try each backend in order and return the first that produces a verdict."""
    backend = backend or BACKEND
    if backend in ("auto", "cli"):
        res = analyse_via_cli(metrics, regs, baselines, model=model)
        if res:
            return res
        if backend == "cli":
            return heuristic(metrics, regs)
    if backend in ("auto", "api"):
        res = analyse(metrics, regs, baselines, model=model)
        if res and not res.get("_skipped"):
            return res
    return heuristic(metrics, regs)


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
    for b in metrics["breaches"]:
        findings.append({"title": f"{b['metric']} over budget", "runtime": "unknown",
                         "severity": "medium", "kind": "budget_breach",
                         "evidence": f"{b['value']} vs budget {b['budget']} (+{b['over_by_pct']}%)",
                         "architectural_risk": RISK_MAP.get(b["metric"]),
                         "recommendation": "Investigate or re-baseline the budget."})
    verdict = "fail" if any(f["severity"] == "high" for f in findings) else ("warn" if findings else "pass")
    return {"verdict": verdict,
            "headline": f"{len(findings)} finding(s) from deterministic rules (no LLM).",
            "findings": findings, "dismissed": [], "_heuristic": True}
