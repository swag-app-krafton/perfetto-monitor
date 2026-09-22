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
    label = metrics.get("startup_metric", "time to first camera frame")
    budget_txt = f" / {st['budget_ms']}ms budget" if st.get("budget_ms") else " (no budget set for this app)"
    print(f"  {label}  {st['time_to_first_camera_frame_ms']}ms{budget_txt}")
    if metrics.get("derived"):
        print(f"  app  {metrics.get('app_pkg') or 'unknown'}  (derived steps -- not instrumented)")
    f = metrics["frames"]
    print(f"  frames  {f['total']} total · {f['slow_pct']}% slow · {f['janky_pct']}% janky · drift {f['thermal_drift_pct']}%")
    if metrics.get("memory", {}).get("rss"):
        m = metrics["memory"]["rss"]
        print(f"  RAM  peak {m['peak_mb']}MB · growth {m['growth_mb']}MB")
    for fd in res.get("findings", []):
        print(f"\n  [{fd.get('severity','?').upper()}] {fd.get('title')}  ({fd.get('runtime')})")
        print(f"      {fd.get('evidence')}")
        if fd.get("architectural_risk"):
            print(f"      risk: {fd['architectural_risk']}")
        print(f"      -> {fd.get('recommendation')}")
    for d in res.get("dismissed", []):
        print(f"\n  [dismissed] {d}")
    print()


NAMES = {"ttff_ms": "first camera frame", "slow_pct": "slow frames",
         "janky_pct": "janky frames", "thermal_drift_pct": "thermal drift",
         "peak_rss_mb": "peak RAM usage", "rss_growth_mb": "RAM growth"}
UNITS = {"ttff_ms": "ms", "slow_pct": "%", "janky_pct": "%",
         "thermal_drift_pct": "%", "peak_rss_mb": "MB", "rss_growth_mb": "MB"}
MARK = {"worse": "\033[31mworse\033[0m", "better": "\033[32mbetter\033[0m",
        "same": "\033[90msame\033[0m"}


def _print_compare(d):
    a, b = d["run"], d["base"]
    print(f"\n  run {a['id']} ({a['label'] or 'no label'}{', ' + a['git_sha'] if a['git_sha'] else ''})"
          f"  vs  run {b['id']} ({b['label'] or 'no label'}{', ' + b['git_sha'] if b['git_sha'] else ''})")
    if not d["comparable"]:
        print(f"  \033[33mWARNING\033[0m different startup paths "
              f"({a['path_kind']} vs {b['path_kind']}) \u2014 these budgets are not comparable")
    if not d["same_device"]:
        print(f"  \033[33mWARNING\033[0m different devices "
              f"({a['device'] or '?'} vs {b['device'] or '?'}) \u2014 variance will be inflated")
    s = d["summary"]
    print(f"  {s['worse']} worse \u00b7 {s['better']} better \u00b7 {s['same']} unchanged\n")
    for m in d["metrics"]:
        u = UNITS.get(m["metric"], "")
        dp = "" if m["delta_pct"] is None else f"{m['delta_pct']:+}%"
        print(f"  {NAMES.get(m['metric'], m['metric']):<20} "
              f"{m['value']:>8}{u:<3} vs {m['base_value']:>8}{u:<3} "
              f"{m['delta']:+8.2f}  {dp:>8}  {MARK[m['verdict']]}")
    print("\n  steps")
    for st in d["steps"]:
        if st.get("only_in"):
            where = "only in this run" if st["only_in"] == "run" else "only in base"
            print(f"  {st['step'].replace('step:', ''):<24} \033[33m{where}\033[0m")
            continue
        dp = "" if st.get("delta_pct") is None else f"{st['delta_pct']:+}%"
        print(f"  {st['step'].replace('step:', ''):<24} "
              f"{st['dur_ms']:>8.1f}ms vs {st['base_dur_ms']:>8.1f}ms "
              f"{st['delta_ms']:+8.2f}  {dp:>8}  {MARK.get(st.get('verdict'), '')}")
        if st.get("verdict") == "worse":
            for k in st["children"][:3]:
                if k["delta_ms"] is None or abs(k["delta_ms"]) < 0.5:
                    continue
                kpct = "" if k["delta_pct"] is None else f"  {k['delta_pct']:+}%"
                print(f"      {k['name']:<26} {k['delta_ms']:+8.2f}ms{kpct}")
    print()


def _print_stress(t):
    st = (t.get("stats") or {}).get("ttid_ms")
    print(f"\n  stress test #{t['id']}  {t.get('app_pkg')}  "
          f"{t['completed']}/{t['sessions_requested']} session(s)"
          + (f", {t['failed']} failed" if t.get("failed") else ""))
    if st:
        print(f"  startup  median {st['median']}ms  min {st['min']}  max {st['max']}  "
              f"p90 {st['p90']}  \u03c3 {st['stdev']}  spread {st['spread_pct']}%")
        # The spread is the point of the exercise: it says whether a single
        # capture could be trusted at all.
        if st["spread_pct"] and st["spread_pct"] > 25:
            print(f"  \033[33mnote\033[0m spread is wide -- a single capture of this app "
                  "would not be reproducible; compare medians, not one-off runs.")
    print("\n  session   startup      run")
    for x in t.get("sessions", []):
        mark = "ok " if x["state"] == "done" else ("ERR" if x["state"] == "error" else "...")
        val = f"{x['ttid_ms']:.1f}ms" if x.get("ttid_ms") else "-"
        extra = f"  {x['error'][:60]}" if x.get("error") else ""
        print(f"  {x['seq']:>5}  {mark}  {val:>10}   {x.get('run_id') or '-'}{extra}")
    print()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="swagperf", description="Swag Pay Perfetto monitor")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyse", help="analyse a trace file and record it")
    a.add_argument("trace")
    # No default here. "returning_user" is only a sensible default for Swag
    # Pay's own instrumented runs; a derived (competitor) run must infer its
    # own cold/warm classification from what was actually derived, and a
    # hardcoded default would silently overwrite that -- which is exactly how
    # a competitor's trace once ended up mislabeled "returning_user" and
    # mixed into Swag Pay's own bucket.
    a.add_argument("--path-kind", default=None,
                   help="returning_user | first_run for Swag Pay; omit for a "
                        "derived app to auto-classify cold/warm")
    a.add_argument("--label"); a.add_argument("--git-sha")
    a.add_argument("--app-version"); a.add_argument("--device")
    a.add_argument("--app", help="package under test (default: auto-detect from the trace)")
    a.add_argument("--derive", action="store_true",
                   help="force step derivation even for an instrumented app")
    a.add_argument("--no-llm", action="store_true", help="skip the model, use rules only")
    a.add_argument("--backend", choices=["auto", "cli", "api", "heuristic"],
                   help="auto (default): claude CLI, then API key, then rules")
    a.add_argument("--json", action="store_true")
    a.add_argument("--fail-on", default="fail", choices=["never", "fail", "warn"])

    c = sub.add_parser("capture", help="capture a trace from a connected device")
    c.add_argument("-o", "--out", default=None)
    c.add_argument("--pkg", default="com.swagpay")
    c.add_argument("--duration-ms", type=int, default=10000)
    c.add_argument("--cold", action="store_true",
                   help="force-stop then launch inside the trace window (real cold start)")
    c.add_argument("--repeat", type=int, default=1,
                   help="capture N times; cold-start numbers are noisy, so several runs matter")
    c.add_argument("--analyse", action="store_true")
    c.add_argument("--label")

    mn = sub.add_parser("manual", help="drive the app by hand; start/stop tracing yourself")
    mnx = mn.add_subparsers(dest="mcmd", required=True)
    mst = mnx.add_parser("start", help="begin an open-ended trace")
    mst.add_argument("--pkg", default="com.swagpay")
    mst.add_argument("--cold", action="store_true",
                     help="force-stop and launch the app once tracing is live")
    msp = mnx.add_parser("stop", help="stop tracing, pull and analyse the trace")
    msp.add_argument("-o", "--out", default=None)
    msp.add_argument("--label")
    msp.add_argument("--app")
    msp.add_argument("--no-analyse", action="store_true")
    mnx.add_parser("status", help="is a manual trace recording?")
    mnx.add_parser("abort", help="stop and discard without analysing")

    sc = sub.add_parser("screens", help="per-screen CPU/RAM from SwagTrace markers")
    sc.add_argument("trace")
    sc.add_argument("--json", action="store_true")

    stp = sub.add_parser("stress", help="repeat cold starts and report the spread")
    stx = stp.add_subparsers(dest="scmd", required=True)
    sr = stx.add_parser("run", help="capture N sessions of one app")
    sr.add_argument("--pkg", required=True)
    sr.add_argument("-n", "--sessions", type=int, default=5)
    sr.add_argument("--warm", action="store_true", help="warm starts instead of cold")
    sr.add_argument("--duration-ms", type=int, default=8000)
    sr.add_argument("--label")
    stx.add_parser("list", help="list stress tests")
    sh = stx.add_parser("show", help="show one stress test")
    sh.add_argument("id", type=int)

    s = sub.add_parser("seed", help="generate synthetic history for development")
    s.add_argument("-n", type=int, default=15)
    s.add_argument("--regress-last", action="store_true")

    d = sub.add_parser("dashboard", help="serve the dashboard")
    d.add_argument("-p", "--port", type=int, default=8787)
    d.add_argument("--no-open", action="store_true")

    sub.add_parser("list", help="list recorded runs")
    sub.add_parser("reextract", help="recompute metrics for all runs whose traces still exist")

    appsp = sub.add_parser("apps", help="the catalogue of apps under test")
    apx = appsp.add_subparsers(dest="acmd", required=True)
    apl = apx.add_parser("list", help="show the catalogue")
    apl.add_argument("--role", choices=["own", "competitor", "reference"])
    apa = apx.add_parser("add", help="add or update an app")
    apa.add_argument("pkg")
    apa.add_argument("--name"); apa.add_argument("--vendor")
    apa.add_argument("--role", default="competitor",
                     choices=["own", "competitor", "reference"])
    apa.add_argument("--category"); apa.add_argument("--region")
    apa.add_argument("--instrumented", action="store_true")
    apa.add_argument("--ttid-budget", type=float,
                     help="startup budget in ms; only meaningful for your own app")
    apa.add_argument("--notes")
    apr = apx.add_parser("remove", help="remove an app")
    apr.add_argument("pkg")
    apx.add_parser("discover", help="match the catalogue against a connected device")

    cm = sub.add_parser("compare", help="diff two runs")
    cm.add_argument("run", type=int, help="the run to inspect")
    cm.add_argument("base", nargs="?", type=int,
                    help="the run to compare against (default: the pinned benchmark)")
    cm.add_argument("--json", action="store_true")

    bm = sub.add_parser("benchmark", help="pin, show or clear the reference run")
    bmx = bm.add_subparsers(dest="bcmd", required=True)
    bset = bmx.add_parser("set", help="pin a run as the benchmark for its scope")
    bset.add_argument("run", type=int)
    bset.add_argument("--note")
    bclr = bmx.add_parser("clear", help="unpin")
    bclr.add_argument("--run", type=int)
    bclr.add_argument("--app", help="package the scope belongs to")
    bclr.add_argument("--path-kind")
    bclr.add_argument("--device")
    bmx.add_parser("list", help="show pinned benchmarks")

    n = ap.parse_args(argv)

    if n.cmd == "analyse":
        from . import catalogue
        # path_kind is now None unless the caller explicitly asked for one, so
        # extract_any's own defaulting applies: "returning_user" for an
        # instrumented app, auto cold/warm classification for a derived one.
        m = ex.extract_any(n.trace, app_pkg=n.app, path_kind=n.path_kind, force_derive=n.derive)

        # An "instrumented" app that produced zero step: markers is a silent
        # failure waiting to happen -- everything downstream would report a
        # clean PASS off empty data. Fail loudly instead, and point at the
        # escape hatch (--derive) rather than recording a misleading run.
        if not m.get("derived") and not m.get("steps"):
            print(f"  \033[31mERROR\033[0m {m.get('app_pkg') or n.app or 'this app'} is marked "
                  "instrumented in the catalogue, but no step: markers were found in this trace.")
            print("  Re-run with --derive to fall back to generic Android step derivation, "
                  "or check that this build still emits step: markers.")
            return 2

        rid = store.record(m, label=n.label, git_sha=n.git_sha,
                           app_version=n.app_version, device=n.device,
                           trace_path=n.trace, app_pkg=m.get("app_pkg"))
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
        from .capture import capture, device_info
        from . import catalogue
        info = device_info()
        dev = info.get("model") or info.get("device")
        app = catalogue.get(n.pkg)
        if not app:
            print(f"  note: {n.pkg} is not in the catalogue; add it with "
                  f"`swagperf apps add {n.pkg}` to label it in reports.")
        rc = 0
        for i in range(max(n.repeat, 1)):
            out = n.out or f"traces/{n.pkg}_{'cold' if n.cold else 'warm'}_{i:02d}.pftrace"
            p = capture(out, pkg=n.pkg, duration_ms=n.duration_ms, cold=n.cold)
            print(f"  captured -> {p}")
            if n.analyse:
                args = ["analyse", p, "--app", n.pkg]
                if dev:
                    args += ["--device", dev]
                lbl = n.label or f"{'cold' if n.cold else 'warm'}-{i:02d}"
                args += ["--label", lbl]
                rc = main(args) or rc
        return rc

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

    if n.cmd == "manual":
        from .capture import (manual_start, manual_stop, manual_status,
                              manual_abort, device_info)
        if n.mcmd == "status":
            st = manual_status()
            if not st["device"]:
                print("  no adb device connected")
                return 2
            print(f"  device {st['serial']}: "
                  + ("\033[32mrecording\033[0m" if st["recording"] else "idle"))
            return 0
        if n.mcmd == "start":
            try:
                r = manual_start(pkg=n.pkg, cold=n.cold)
            except RuntimeError as e:
                print(f"  \033[31mERROR\033[0m {e}")
                return 1
            print(f"  recording (detached session '{r['key']}') for {r['pkg']}")
            if n.cold and not r["launched"]:
                print("  note: could not launch the app automatically; open it by hand.")
            print("  drive the app now, then: swagperf manual stop")
            return 0
        if n.mcmd == "abort":
            print("  discarded" if manual_abort() else "  nothing was recording")
            return 0
        # stop
        out = n.out or f"traces/manual_{int(__import__('time').time())}.pftrace"
        try:
            p = manual_stop(out)
        except RuntimeError as e:
            print(f"  \033[31mERROR\033[0m {e}")
            return 1
        print(f"  trace saved -> {p}")
        if n.no_analyse:
            return 0
        return main(["analyse", p, "--label", n.label or "manual-session"]
                    + (["--app", n.app] if n.app else [])
                    + (["--device", (device_info().get("model") or "")]
                       if device_info().get("model") else []))

    if n.cmd == "screens":
        from .screens import extract_screens
        d = extract_screens(n.trace)
        if n.json:
            print(json.dumps(d, indent=2))
            return 0
        if not d["instrumented"]:
            print(f"\n  {d['note']}\n")
            return 0
        print(f"\n  screens ({len(d['screens'])} visit(s))")
        print(f"  {'route':<20}{'visits':>7}{'total ms':>10}{'cpu ms':>9}"
              f"{'slow %':>8}{'RAM delta':>11}")
        for s2 in d["screen_summary"]:
            print(f"  {s2['route']:<20}{s2['visits']:>7}{s2['total_ms']:>10.1f}"
                  f"{s2['total_cpu_ms']:>9.1f}"
                  f"{(s2['slow_frame_pct'] or 0):>8.2f}"
                  f"{(s2['max_rss_delta_mb'] if s2['max_rss_delta_mb'] is not None else 0):>10.1f}M")
        if d["navigations"]:
            print("\n  transitions")
            for nv in d["navigations"]:
                print(f"  {nv['transition']:<30} x{nv['count']:<4} "
                      f"worst {nv['max_ms'] or 0:.1f}ms")
        if d["actions"]:
            print("\n  actions")
            for a in d["actions"]:
                extra = (f"  mean {a['mean_ms']}ms  worst {a['max_ms']}ms"
                         if a["mean_ms"] else "")
                print(f"  {a['action']:<34} x{a['count']}{extra}")
        print()
        return 0

    if n.cmd == "stress":
        if n.scmd == "run":
            from . import jobs
            import time as _t
            jid = jobs.start_stress(n.pkg, sessions=n.sessions, cold=not n.warm,
                                    duration_ms=n.duration_ms, label=n.label)
            seen = 0
            while True:
                j = jobs.get(jid)
                for l in (j.get("log") or [])[seen:]:
                    print(f"  [{l['t']}s] {l['text']}")
                seen = len(j.get("log") or [])
                if j["state"] in ("done", "error"):
                    break
                _t.sleep(1)
            if j["state"] == "error":
                print(f"\n  \033[31mFAILED\033[0m {j.get('error')}")
                return 1
            _print_stress(store.stress_get(j["result"]["stress_id"]))
            return 0
        if n.scmd == "list":
            rows = store.stress_list()
            if not rows:
                print("  no stress tests recorded")
                return 0
            for t in rows:
                st = (t.get("stats") or {}).get("ttid_ms")
                print(f"  #{t['id']:<4} {t['ts']}  {(t['app_pkg'] or ''):<38} "
                      f"{t['completed']}/{t['sessions_requested']} sessions  "
                      + (f"median {st['median']}ms spread {st['spread_pct']}%" if st else "no data"))
            return 0
        t = store.stress_get(n.id)
        if not t:
            print(f"  no stress test #{n.id}")
            return 2
        _print_stress(t)
        return 0

    if n.cmd == "apps":
        from . import catalogue
        if n.acmd == "list":
            rows = [a for a in catalogue.load()
                    if not n.role or a.get("role") == n.role]
            for a in rows:
                flags = []
                if a.get("instrumented"):
                    flags.append("instrumented")
                if not a.get("verified"):
                    flags.append("unverified pkg")
                if a.get("budgets"):
                    flags.append("has budgets")
                print(f"  {a.get('role',''):<11} {a['pkg']:<42} {a.get('name',''):<20}"
                      + (f"  [{', '.join(flags)}]" if flags else ""))
            print(f"\n  {len(rows)} app(s). Unverified package names should be confirmed "
                  "with: swagperf apps discover")
            return 0
        if n.acmd == "add":
            e = catalogue.add(n.pkg, name=n.name, role=n.role, category=n.category,
                              vendor=n.vendor, region=n.region,
                              instrumented=n.instrumented, notes=n.notes,
                              budgets={"ttid_ms": n.ttid_budget} if n.ttid_budget else None)
            print(f"  added {e['pkg']} ({e['name']}) as {e['role']}")
            return 0
        if n.acmd == "remove":
            catalogue.remove(n.pkg)
            print(f"  removed {n.pkg}")
            return 0
        if n.acmd == "discover":
            from .capture import installed_packages, device_info
            info = device_info()
            if not info:
                print("  no adb device connected. Connect one and enable USB debugging.")
                return 2
            print(f"  device: {info.get('model')} ({info.get('device')}) "
                  f"Android {info.get('release')} / API {info.get('sdk')}\n")
            inst = set(installed_packages())
            known = {a["pkg"]: a for a in catalogue.load()}
            present = sorted(inst & set(known))
            missing = sorted(set(known) - inst)
            if present:
                catalogue.mark_verified(present)
                print("  in the catalogue and installed:")
                for p in present:
                    print(f"    \u2713 {p:<42} {known[p].get('name','')}")
            if missing:
                print("\n  in the catalogue but NOT installed:")
                for p in missing:
                    print(f"    \u2717 {p:<42} {known[p].get('name','')}")
            extra = sorted(inst - set(known))
            if extra:
                print(f"\n  {len(extra)} other third-party package(s) installed. "
                      "Add any you want to track:")
                for p in extra[:25]:
                    print(f"      {p}")
                if len(extra) > 25:
                    print(f"      \u2026 and {len(extra) - 25} more")
            print("\n  verified flags updated for installed catalogue apps.")
            return 0

    if n.cmd == "benchmark":
        if n.bcmd == "set":
            b = store.set_benchmark(n.run, note=n.note)
            print(f"  pinned run {b['run_id']} ({b['label'] or 'no label'}) as benchmark "
                  f"for {b['path_kind']} / {b['device'] or 'any device'}")
            print("  regressions for that scope are now measured against this run")
            return 0
        if n.bcmd == "clear":
            k = store.clear_benchmark(run_id=n.run, path_kind=n.path_kind,
                                      device=n.device, app_pkg=n.app)
            print(f"  cleared {k} benchmark(s); regressions fall back to the trailing baseline")
            return 0
        rows = store.benchmarks()
        if not rows:
            print("  no benchmarks pinned; regressions use the trailing baseline")
            return 0
        for b in rows:
            print(f"  {b['scope']:<28} run {b['run_id']:<4} {b['label'] or '':<18} "
                  f"set {b['set_at']}" + (f"  \u2014 {b['note']}" if b["note"] else ""))
        return 0

    if n.cmd == "compare":
        base = n.base
        if base is None:
            c = store.connect()
            meta = c.execute("select path_kind, device from runs where id=?", (n.run,)).fetchone()
            c.close()
            if not meta:
                print(f"  no run with id {n.run}")
                return 2
            b = store.get_benchmark(path_kind=meta["path_kind"], device=meta["device"])
            if not b:
                print("  no base run given and no benchmark pinned.")
                print("  pass a base run id, or pin one with: swagperf benchmark set <run>")
                return 2
            base = b["run_id"]
        d = store.compare(n.run, base)
        if n.json:
            print(json.dumps(d, indent=2))
            return 0
        _print_compare(d)
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
