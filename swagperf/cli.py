"""swagperf CLI."""
import argparse, json, sys, os, webbrowser

# Load a local .env if present so ANTHROPIC_API_KEY can be set without exporting.
def _load_env():
    p = os.path.join(os.path.dirname(__file__), "..", ".env")
    if not os.path.exists(p):
        return
    for line in open(p):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()
from . import extract as ex, store, analyst, synth


def _analyse_run(rid, metrics, *, use_llm, db=None):
    regs = store.regressions(rid, db=db)
    baselines = {s["step"]: store.baseline(s["step"], exclude_run=rid, db=db)
                 for s in metrics["steps"]}
    baselines = {k: v for k, v in baselines.items() if v}
    if use_llm:
        res = analyst.run_analysis(metrics, regs, baselines)
    else:
        res = analyst.heuristic(metrics, regs)
    c = store.connect(db)
    from datetime import datetime, timezone
    c.execute("insert into analyses (run_id,created,model,verdict,json) values (?,?,?,?,?)",
              (rid, datetime.now(timezone.utc).isoformat(timespec="seconds"),
               res.get("_model", "heuristic"), res.get("verdict"), json.dumps(res)))
    c.commit(); c.close()
    return res, regs


def _print(res, regs, metrics):
    V = {"pass": "\033[32mPASS\033[0m", "warn": "\033[33mWARN\033[0m",
         "fail": "\033[31mFAIL\033[0m"}
    print(f"\n  {V.get(res.get('verdict'), res.get('verdict','?').upper())}  {res.get('headline','')}\n")
    st = metrics["startup"]
    print(f"  time to first camera frame  {st['time_to_first_camera_frame_ms']}ms / {st['budget_ms']}ms budget")
    f = metrics["frames"]
    print(f"  frames  {f['total']} total · {f['slow_pct']}% slow · {f['janky_pct']}% janky · drift {f['thermal_drift_pct']}%")
    if metrics.get("memory", {}).get("rss"):
        m = metrics["memory"]["rss"]
        print(f"  memory  peak {m['peak_mb']}MB · growth {m['growth_mb']}MB")
    for fd in res.get("findings", []):
        print(f"\n  [{fd.get('severity','?').upper()}] {fd.get('title')}  ({fd.get('runtime')})")
        print(f"      {fd.get('evidence')}")
        if fd.get("architectural_risk"):
            print(f"      risk: {fd['architectural_risk']}")
        print(f"      -> {fd.get('recommendation')}")
    for d in res.get("dismissed", []):
        print(f"\n  [dismissed] {d}")
    print()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="swagperf", description="Swag Pay Perfetto monitor")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyse", help="analyse a trace file and record it")
    a.add_argument("trace")
    a.add_argument("--path-kind", default="returning_user",
                   choices=["returning_user", "first_run"])
    a.add_argument("--label"); a.add_argument("--git-sha")
    a.add_argument("--app-version"); a.add_argument("--device")
    a.add_argument("--no-llm", action="store_true", help="skip the model, use rules only")
    a.add_argument("--backend", choices=["auto", "cli", "api", "heuristic"],
                   help="auto (default): claude CLI, then API key, then rules")
    a.add_argument("--json", action="store_true")
    a.add_argument("--fail-on", default="fail", choices=["never", "fail", "warn"])

    c = sub.add_parser("capture", help="capture a trace from a connected device")
    c.add_argument("-o", "--out", default="traces/capture.pftrace")
    c.add_argument("--pkg", default="com.swagpay")
    c.add_argument("--duration-ms", type=int, default=10000)
    c.add_argument("--analyse", action="store_true")

    s = sub.add_parser("seed", help="generate synthetic history for development")
    s.add_argument("-n", type=int, default=15)
    s.add_argument("--regress-last", action="store_true")

    d = sub.add_parser("dashboard", help="serve the dashboard")
    d.add_argument("-p", "--port", type=int, default=8787)
    d.add_argument("--no-open", action="store_true")

    sub.add_parser("list", help="list recorded runs")
    sub.add_parser("reextract", help="recompute metrics for all runs whose traces still exist")

    n = ap.parse_args(argv)

    if n.cmd == "analyse":
        m = ex.extract(n.trace, path_kind=n.path_kind)
        rid = store.record(m, label=n.label, git_sha=n.git_sha,
                           app_version=n.app_version, device=n.device, trace_path=n.trace)
        if n.backend:
            analyst.BACKEND = n.backend
        res, regs = _analyse_run(rid, m, use_llm=not n.no_llm and n.backend != "heuristic")
        if n.json:
            print(json.dumps({"run_id": rid, "metrics": m, "analysis": res,
                              "regressions": regs}, indent=2))
        else:
            _print(res, regs, m)
        if n.fail_on == "fail" and res.get("verdict") == "fail":
            return 1
        if n.fail_on == "warn" and res.get("verdict") in ("fail", "warn"):
            return 1
        return 0

    if n.cmd == "capture":
        from .capture import capture
        p = capture(n.out, pkg=n.pkg, duration_ms=n.duration_ms)
        print(f"captured -> {p}")
        if n.analyse:
            return main(["analyse", p])
        return 0

    if n.cmd == "seed":
        import random
        for i in range(n.n):
            last = (i == n.n - 1) and n.regress_last
            reg = {"step:camera_open": 1.8, "CameraX.bindToLifecycle": 2.2,
                   "thermal_drift": 0.5} if last else {}
            b, _ = synth.gen_trace(1000 + i, regress=reg)
            p = f"traces/seed_{i:03d}.pftrace"
            os.makedirs("traces", exist_ok=True)
            open(p, "wb").write(b)
            m = ex.extract(p)
            rid = store.record(m, label=("regressed" if last else f"build-{i}"),
                               git_sha=f"{random.randrange(16**7):07x}",
                               app_version=f"2.{i//5}.{i%5}", device="pixel7", trace_path=p)
            res, regs = _analyse_run(rid, m, use_llm=False)
            print(f"  run {rid:>3}  {m['startup']['time_to_first_camera_frame_ms']:>7}ms  {res['verdict']}")
        return 0

    if n.cmd == "reextract":
        res = store.reextract()
        print(f"  re-extracted {res['reextracted']} run(s)")
        if res["missing_trace"]:
            print(f"  skipped (trace file gone): {res['missing_trace']}")
        return 0

    if n.cmd == "list":
        for r in store.history(50):
            print(f"  {r['id']:>4}  {r['ts']}  {r['label'] or '':<14} "
                  f"ttff={r['ttff_ms']}ms slow={r['slow_pct']}%")
        return 0

    if n.cmd == "dashboard":
        from .server import serve
        url = f"http://127.0.0.1:{n.port}"
        if not n.no_open:
            webbrowser.open(url)
        serve(n.port)
        return 0


if __name__ == "__main__":
    sys.exit(main())
