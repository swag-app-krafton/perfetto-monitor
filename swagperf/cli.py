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
    baselines = store.step_baselines(rid, metrics, db=db)
    if use_llm:
        res = analyst.run_analysis(metrics, regs, baselines)
    else:
        res = analyst.heuristic(metrics, regs)
    store.add_analysis(rid, res, kind="verdict", db=db)
    return res, regs


def _print(res, regs, metrics):
    V = {"pass": "\033[32mPASS\033[0m", "warn": "\033[33mWARN\033[0m",
         "fail": "\033[31mFAIL\033[0m"}
    # A simulator run is never judged against budgets: nothing moved is "steady", not a pass.
    word = "\033[90mSTEADY\033[0m" if metrics.get("simulator") and res.get("verdict") == "pass" \
        else V.get(res.get('verdict'), res.get('verdict', '?').upper())
    print(f"\n  {word}  {res.get('headline','')}\n")
    st = metrics["startup"]
    label = metrics.get("startup_metric", "time to first camera frame")
    target_txt = (f" / {st['budget_ms']}ms North Star target" if st.get("budget_ms")
                  else " (simulator run: no North Star target applies)" if metrics.get("simulator")
                  else " (no startup North Star target)")
    print(f"  {label}  {st['time_to_first_camera_frame_ms']}ms{target_txt}")
    if not st.get("budget_ms") and st.get("target_reason") and not metrics.get("simulator"):
        print(f"  {st['target_reason']}")
    if metrics.get("derived"):
        why = ("its step: markers are untimed" if "untimed" in (metrics.get("note") or "")
               else "not instrumented")
        print(f"  app  {metrics.get('app_pkg') or 'unknown'}  (derived steps -- {why})")
    f = metrics["frames"]
    print(f"  frames  {f['total']} total · {f['slow_pct']}% slow · {f['janky_pct']}% janky · drift {'not measured' if f['thermal_drift_pct'] is None else str(f['thermal_drift_pct']) + '%'}")
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
              f"({a['path_kind']} vs {b['path_kind']}) \u2014 their North Star targets are not comparable")
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


def _print_audit(a):
    s = a.get("summary") or {}
    m = s.get("metrics") or {}
    print(f"\n  Flashlight audit A-{a['id']}  {a['app_pkg']}  {a['state']}  "
          f"{s.get('successful', 0)}/{a['iterations']} iteration(s)"
          + (f", {s['failed']} failed" if s.get("failed") else ""))
    if s.get("score") is not None:
        print(f"  score {s['score']}  CPU {m.get('cpu_pct')}%  RAM {m.get('ram_mb')} MB  "
              f"{m.get('fps')} FPS  (Flashlight's own definitions; not comparable with Perfetto runs)")
        kt = {k: v for k, v in (s.get("key_threads") or {}).items() if v}
        if kt:
            print("  threads  " + "  ".join(f"{v['name']} {v['cpu_pct']}%" for v in kt.values()))
        print("\n  iteration   CPU %    RAM MB    FPS")
        for it in s.get("iterations") or []:
            mark = "" if it["status"] == "SUCCESS" and not it.get("retried") else "  (failed, retried)"
            print(f"  {it['index']:>9}  {it.get('cpu_pct') or '-':>6}  {it.get('ram_mb') or '-':>8}  "
                  f"{it.get('fps') or '-':>5}{mark}")
    if a.get("error"):
        print(f"  note: {a['error']}")
    if a.get("results_path"):
        print(f"  results: {a['results_path']}")
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


def _maps_resolve(n, sourcemaps):
    """`maps resolve`: pasted stacks or SwagErrors log lines, resolved."""
    if n.map:
        map_path = n.map
    elif n.tag:
        map_path = sourcemaps.find_by_tag(n.tag, n.platform, n.app)
    elif not n.app:
        print("  \033[31mERROR\033[0m --build and --hash need --app")
        return 2
    else:
        map_path = sourcemaps.find(n.platform, n.app, source_hash=n.hash, build=n.build)
    if not map_path or not os.path.isfile(map_path):
        print("  \033[31mERROR\033[0m no source map registered for that build "
              "(swagperf maps fetch --tag …, or maps list)")
        return 2
    text = open(n.file).read() if n.file else sys.stdin.read()
    errors, incomplete = sourcemaps.resolve_text(text, map_path)
    info = sourcemaps.release_info(map_path) or {}
    rel = f" ({info.get('tag') or 'dry run'} · {info.get('versionName')})" if info else ""
    print(f"\n  source map: {os.path.basename(map_path)}{rel}")
    if not errors:
        print("  no JS error found in the text")
    for e in errors:
        kind = ", ".join(x for x in ("fatal" if e.get("fatal") else "non-fatal" if "fatal" in e else "",
                                     e.get("source") or "") if x)
        print(f"\n  {e.get('name') or 'Error'}: {e.get('message') or ''}" + (f"   ({kind})" if kind else ""))
        for f in e["frames"]:
            if f["resolved"]:
                where = f"{f['path'] or f['file']}:{f['line']}:{f['col']}"
                indent = "    " if f["in_app"] else "      "
                print(f"{indent}{(f['fn'] or '?'):<34} {where}")
            else:
                print(f"      \033[2m{f['raw'].strip()}\033[0m")
        if e.get("frames") and not any(f["resolved"] for f in e["frames"]):
            print("    (nothing resolved: this map is from another build)")
    if incomplete:
        print(f"\n  {incomplete} record(s) had a chunk missing and were skipped")
    print()
    return 0


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
    a.add_argument("--app", help="package or bundle id under test (default: auto-detect from "
                   "the trace; required for an Instruments .trace)")
    a.add_argument("--derive", action="store_true",
                   help="force step derivation even for an instrumented app")
    a.add_argument("--no-llm", action="store_true", help="skip the model, use rules only")
    a.add_argument("--backend", choices=["auto", "cli", "api", "heuristic"],
                   help="auto (default): claude CLI, then API key, then rules")
    a.add_argument("--json", action="store_true")
    a.add_argument("--fail-on", default="fail", choices=["never", "fail", "warn"])
    # `capture --repeat` analyses each trace and asks for one review at the end.
    a.add_argument("--no-review", action="store_true", help=argparse.SUPPRESS)

    c = sub.add_parser("capture", help="capture a trace from a connected device or a booted iOS Simulator")
    c.add_argument("-o", "--out", default=None)
    c.add_argument("--platform", choices=["android", "ios"], default="android")
    c.add_argument("--device", help="adb serial, or a simulator's name or UDID")
    c.add_argument("--pkg", default="com.swag.pay")
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
    mst.add_argument("--pkg", default="com.swag.pay")
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

    rs = sub.add_parser("reset", help="delete every recorded run and its traces; start again from run #1")
    rs.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    rs.add_argument("--keep-traces", action="store_true", help="keep the trace files in traces/")

    stp = sub.add_parser("stress", help="repeat cold starts and report the spread")
    stx = stp.add_subparsers(dest="scmd", required=True)
    sr = stx.add_parser("run", help="capture N sessions of one app")
    sr.add_argument("--pkg", required=True)
    sr.add_argument("--platform", choices=["android", "ios"], default="android")
    sr.add_argument("--device", help="adb serial, or a simulator's name or UDID")
    sr.add_argument("-n", "--sessions", type=int, default=5)
    sr.add_argument("--warm", action="store_true", help="warm starts instead of cold")
    sr.add_argument("--duration-ms", type=int, default=8000)
    sr.add_argument("--label")
    stx.add_parser("list", help="list stress tests")
    sh = stx.add_parser("show", help="show one stress test")
    sh.add_argument("id", type=int)

    au = sub.add_parser("audit", help="Flashlight audits: cold starts measured by Flashlight")
    aux = au.add_subparsers(dest="aucmd", required=True)
    aur = aux.add_parser("run", help="measure N cold starts of one app with Flashlight")
    aur.add_argument("--pkg", required=True)
    aur.add_argument("-n", "--iterations", type=int, default=5)
    aur.add_argument("--duration-ms", type=int, default=10000)
    aur.add_argument("--label")
    aux.add_parser("list", help="list Flashlight audits")
    aus = aux.add_parser("show", help="show one Flashlight audit")
    aus.add_argument("id", type=int)

    s = sub.add_parser("seed", help="generate synthetic history for development")
    s.add_argument("-n", type=int, default=15)
    s.add_argument("--regress-last", action="store_true")

    d = sub.add_parser("dashboard", help="serve the dashboard")
    d.add_argument("-p", "--port", type=int, default=8787)
    d.add_argument("--no-open", action="store_true")

    sub.add_parser("list", help="list recorded runs")

    tr = sub.add_parser("triage", help="what runs since the last PM review raised, for the tracker")
    tr.add_argument("--after", type=int, help="review runs after this id (default: the tracker's marker)")
    tr.add_argument("--lookback", type=int, default=10,
                    help="runs before the window checked to tell an ongoing signal from a new one")
    tr.add_argument("--screens", action="store_true",
                    help="attribute RAM signals to screens (reads the traces; slower)")
    tr.add_argument("--json", action="store_true")
    tr.add_argument("--mark", type=int, metavar="RUN_ID",
                    help="move the tracker's 'Runs reviewed through' marker to RUN_ID and exit")

    pmp = sub.add_parser("pm", help="the PM agent's automatic run review")
    pmx = pmp.add_subparsers(dest="pcmd", required=True)
    pmx.add_parser("status", help="is a review running, and where is its log")
    pmx.add_parser("review", help="review runs since the last review now, in the background")
    sub.add_parser("reextract", help="recompute metrics for all runs whose traces still exist")

    appsp = sub.add_parser("apps", help="the catalogue of apps under test")
    apx = appsp.add_subparsers(dest="acmd", required=True)
    apl = apx.add_parser("list", help="show the catalogue")
    apl.add_argument("--role", choices=["own", "competitor", "reference"])
    apl.add_argument("--platform", choices=["android", "ios"])
    apa = apx.add_parser("add", help="add or update an app")
    apa.add_argument("pkg")
    apa.add_argument("--platform", choices=["android", "ios"], default="android")
    apa.add_argument("--name"); apa.add_argument("--vendor")
    apa.add_argument("--role", default="competitor",
                     choices=["own", "competitor", "reference"])
    apa.add_argument("--category"); apa.add_argument("--region")
    apa.add_argument("--instrumented", action="store_true")
    apa.add_argument("--ttid-budget", type=float,
                     help="startup North Star target in ms; only meaningful for your own app")
    apa.add_argument("--notes")
    apr = apx.add_parser("remove", help="remove an app")
    apr.add_argument("pkg")
    apr.add_argument("--platform", choices=["android", "ios"], default="android")
    apd = apx.add_parser("discover", help="match the catalogue against a connected device")
    apd.add_argument("--platform", choices=["android", "ios"], default="android")

    cm = sub.add_parser("compare", help="diff two runs")
    cm.add_argument("run", type=int, help="the run to inspect")
    cm.add_argument("base", nargs="?", type=int,
                    help="the run to compare against (default: the pinned benchmark)")
    cm.add_argument("--json", action="store_true")

    sm = sub.add_parser("summary", help="write an AI summary of a recorded run (never changes its verdict)")
    sm.add_argument("run", type=int)
    sm.add_argument("--json", action="store_true")

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
    bclr.add_argument("--platform", choices=["android", "ios"], default="android")
    bmx.add_parser("list", help="show pinned benchmarks")

    mp = sub.add_parser("maps", help="source maps for resolving JS error stacks, one per build")
    mpx = mp.add_subparsers(dest="mcmd2", required=True)
    mpa = mpx.add_parser("add", help="register a build's composed Hermes source map")
    mpa.add_argument("map")
    mpa.add_argument("--app", required=True, help="package or bundle id")
    mpa.add_argument("--platform", choices=["android", "ios"], default="android")
    mpa.add_argument("--bundle", help="the build's JS bundle (main.jsbundle / index.android.bundle): "
                     "keys the map by the bundle's own hash")
    mpa.add_argument("--build", help="the build number, when the bundle isn't to hand")
    mpi = mpx.add_parser("import", help="register a release build's maps from a folder staged by "
                         "Swag Pay's apps/mobile/scripts/release_build.py")
    mpi.add_argument("folder", help="the folder holding its manifest.json")
    mpf = mpx.add_parser("fetch", help="download release builds' maps from their GitHub Releases")
    mpfw = mpf.add_mutually_exclusive_group(required=True)
    mpfw.add_argument("--tag", help="one release, e.g. v1.2.0-42")
    mpfw.add_argument("--all", action="store_true", help="every Release not imported yet")
    mpf.add_argument("--repo", help="GitHub repository (default swag-app-krafton/swag-pay, "
                     "or $SWAGPERF_RELEASE_REPO)")
    mpr = mpx.add_parser("resolve", help="resolve JS error stacks from pasted text: a stack as "
                         "Hermes printed it, or SwagErrors log lines "
                         "(adb logcat -d -v raw -s SwagPerfError)")
    mpr.add_argument("file", nargs="?", help="the text (default: stdin)")
    mpr.add_argument("--app", help="package or bundle id (needed with --build or --hash)")
    mpr.add_argument("--platform", choices=["android", "ios"], default="android")
    mprw = mpr.add_mutually_exclusive_group(required=True)
    mprw.add_argument("--tag", help="a release imported with maps fetch, e.g. v1.2.0-42")
    mprw.add_argument("--build", help="the build number (version code)")
    mprw.add_argument("--hash", help="the Hermes bundle's source hash")
    mprw.add_argument("--map", help="a composed source map file")
    mpx.add_parser("list", help="registered source maps")

    io = sub.add_parser("ios", help="iOS tools: simulators, and reading Instruments traces")
    iox = io.add_subparsers(dest="icmd", required=True)
    iox.add_parser("devices", help="list iOS simulators")
    iot = iox.add_parser("toc", help="what an Instruments .trace recorded")
    iot.add_argument("trace")
    ioc = iox.add_parser("convert", help="convert an Instruments .trace to a Perfetto trace")
    ioc.add_argument("trace")
    ioc.add_argument("--app", required=True, help="the app's bundle id")
    ioc.add_argument("-o", "--out", default=None)

    n = ap.parse_args(argv)

    if n.cmd == "analyse":
        from . import catalogue
        if n.trace.rstrip("/").endswith(".trace"):
            # An Instruments recording: convert it first; everything after
            # reads the Perfetto trace like any other.
            if not n.app:
                print("  \033[31mERROR\033[0m an Instruments .trace needs --app <bundle id>")
                return 2
            from .capture_ios import convert_recording
            out = n.trace.rstrip("/")[:-len(".trace")] + ".pftrace"
            convert_recording(n.trace, out, pkg=n.app)
            print(f"  converted -> {out}", file=sys.stderr)
            n.trace = out
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
        if not n.no_review:
            from . import pm
            print(f"  {pm.request_review()}", file=sys.stderr)
        if n.fail_on == "fail" and res.get("verdict") == "fail":
            return 1
        if n.fail_on == "warn" and res.get("verdict") in ("fail", "warn"):
            return 1
        return 0

    if n.cmd == "capture":
        from . import backends, catalogue
        cap = backends.get(n.platform)
        ios = n.platform == "ios"
        try:
            backends.validate_id(n.platform, n.pkg)
        except ValueError as e:
            print(f"  \033[31mERROR\033[0m {e}")
            return 2
        info = cap.device_info(n.device)
        if not info:
            print(f"  \033[31mERROR\033[0m {backends.NO_DEVICE[n.platform]}")
            return 1
        dev = info.get("model") or info.get("device")
        app = catalogue.get(n.pkg, n.platform)
        if not app:
            print(f"  note: {n.pkg} is not in the catalogue; add it with "
                  f"`swagperf apps add {n.pkg}{' --platform ios' if ios else ''}` to label it in reports.")
        # An iOS capture is always a cold launch under xctrace.
        cold = n.cold or ios
        rc = 0
        for i in range(max(n.repeat, 1)):
            out = n.out or (f"traces/{'ios/' if ios else ''}{n.pkg}_"
                            f"{'cold' if cold else 'warm'}_{i:02d}.pftrace")
            try:
                meta = cap.run_metadata(n.pkg, n.device)
            except Exception:
                meta = None
            try:
                r = cap.capture(out, pkg=n.pkg, duration_ms=n.duration_ms, cold=cold,
                                serial=n.device)
            except RuntimeError as e:
                print(f"  \033[31mERROR\033[0m {e}")
                return 1
            p = r if isinstance(r, str) else out
            print(f"  captured -> {p}")
            lost = cap.verify(p, instrumented=catalogue.is_instrumented(n.pkg, n.platform)) \
                if n.analyse else None
            if lost:
                print(f"  \033[31mERROR\033[0m not analysed: {lost}")
                rc = 1
            elif n.analyse:
                args = ["analyse", p, "--app", n.pkg]
                if dev:
                    args += ["--device", dev]
                lbl = n.label or f"{'cold' if cold else 'warm'}-{i:02d}"
                args += ["--label", lbl, "--no-review"]
                rc = main(args) or rc
                rid = store.run_id_for_trace(p)
                if meta and rid:
                    store.set_run_meta(rid, "capture", {**meta, "moment": "before capture"})
        if n.analyse:
            from . import pm
            print(f"  {pm.request_review()}", file=sys.stderr)
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
        lost = ex.tracing_lost(p)
        if lost:
            print(f"  \033[31mERROR\033[0m not analysed: {lost}")
            return 1
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
                  + (f"{s2['total_cpu_ms']:>9.1f}" if s2['total_cpu_ms'] is not None else f"{'-':>9}")
                  + f"{(s2['slow_frame_pct'] or 0):>8.2f}"
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
                                    duration_ms=n.duration_ms, label=n.label,
                                    device=n.device, platform=n.platform)
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

    if n.cmd == "audit":
        if n.aucmd == "run":
            from . import jobs
            import time as _t
            try:
                jid = jobs.start_audit(n.pkg, iterations=n.iterations,
                                       duration_ms=n.duration_ms, label=n.label)
            except ValueError as e:
                print(f"  \033[31mERROR\033[0m {e}")
                return 1
            seen = 0
            while True:
                j = jobs.get(jid)
                for l in (j.get("log") or [])[seen:]:
                    print(f"  [{l['t']}s] {l['text']}")
                seen = len(j.get("log") or [])
                if j["state"] in ("done", "error"):
                    break
                _t.sleep(1)
            if j.get("audit_id"):
                _print_audit(store.audit_get(j["audit_id"]))
            if j["state"] == "error":
                print(f"\n  \033[31mFAILED\033[0m {j.get('error')}")
                return 1
            return 0
        if n.aucmd == "list":
            rows = store.audit_list()
            if not rows:
                print("  no Flashlight audits recorded")
                return 0
            for a in rows:
                m = (a.get("summary") or {}).get("metrics") or {}
                print(f"  A-{a['id']:<4} {a['ts']}  {a['app_pkg']:<38} {a['state']:<11} "
                      + (f"score {a['score']:.0f}  CPU {m.get('cpu_pct')}%  RAM {m.get('ram_mb')} MB  "
                         f"{m.get('fps')} FPS" if a.get("score") is not None else (a.get("error") or "")))
            return 0
        a = store.audit_get(n.id)
        if not a:
            print(f"  no Flashlight audit A-{n.id}")
            return 2
        _print_audit(a)
        return 0

    if n.cmd == "apps":
        from . import catalogue
        if n.acmd == "list":
            rows = [a for a in catalogue.load()
                    if (not n.role or a.get("role") == n.role)
                    and (not n.platform or a["platform"] == n.platform)]
            for a in rows:
                flags = []
                if a.get("instrumented"):
                    flags.append("instrumented")
                if not a.get("verified"):
                    flags.append("unverified pkg")
                if a.get("budgets"):
                    flags.append("has North Star targets")
                print(f"  {a['platform']:<8} {a.get('role',''):<11} {a['pkg']:<42} {a.get('name',''):<20}"
                      + (f"  [{', '.join(flags)}]" if flags else ""))
            print(f"\n  {len(rows)} app(s). Unverified package names should be confirmed "
                  "with: swagperf apps discover")
            return 0
        if n.acmd == "add":
            e = catalogue.add(n.pkg, name=n.name, role=n.role, category=n.category,
                              vendor=n.vendor, region=n.region,
                              instrumented=n.instrumented, notes=n.notes,
                              budgets={"ttid_ms": n.ttid_budget} if n.ttid_budget else None,
                              platform=n.platform)
            print(f"  added {e['pkg']} ({e['name']}) as {e['role']} ({n.platform})")
            return 0
        if n.acmd == "remove":
            catalogue.remove(n.pkg, n.platform)
            print(f"  removed {n.pkg} ({n.platform})")
            return 0
        if n.acmd == "discover":
            from . import backends
            cap = backends.get(n.platform)
            info = cap.device_info()
            if not info:
                print(f"  {backends.NO_DEVICE[n.platform]}")
                return 2
            print(f"  device: {info.get('model')} ({info.get('device')}) "
                  + (f"iOS {info.get('release')}\n" if n.platform == "ios"
                     else f"Android {info.get('release')} / API {info.get('sdk')}\n"))
            inst = set(cap.installed_packages())
            known = {a["pkg"]: a for a in catalogue.load() if a["platform"] == n.platform}
            present = sorted(inst & set(known))
            missing = sorted(set(known) - inst)
            if present:
                catalogue.mark_verified(present, n.platform)
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

    if n.cmd == "summary":
        from . import summary
        try:
            res = summary.write(n.run)
        except LookupError as e:
            print(f"  {e}", file=sys.stderr)
            return 2
        if res is None:
            print(f"  {summary.NO_MODEL}", file=sys.stderr)
            return 1
        if n.json:
            print(json.dumps(res, indent=2))
            return 0
        print(f"\n  {res.get('headline', '')}\n")
        if res.get("summary"):
            print(f"  {res['summary']}\n")
        b = res.get("_benchmark")
        if b and res.get("benchmark_comparison"):
            print(f"  Against benchmark run {b['base']['id']}: {res['benchmark_comparison']}\n")
        if res.get("_unverified"):
            print(f"  \033[33mnot found in the run's data:\033[0m {', '.join(res['_unverified'])}")
        print(f"  written by {res.get('_model')}; the run's verdict is unchanged")
        return 0

    if n.cmd == "benchmark":
        if n.bcmd == "set":
            try:
                b = store.set_benchmark(n.run, note=n.note)
            except ValueError as e:
                print(f"  \033[31mERROR\033[0m {e}")
                return 2
            print(f"  pinned run {b['run_id']} ({b['label'] or 'no label'}) as benchmark "
                  f"for {b['path_kind']} / {b['device'] or 'any device'}")
            print("  regressions for that scope are now measured against this run")
            return 0
        if n.bcmd == "clear":
            k = store.clear_benchmark(run_id=n.run, path_kind=n.path_kind,
                                      device=n.device, app_pkg=n.app, platform=n.platform)
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

    if n.cmd == "maps":
        from . import sourcemaps
        if n.mcmd2 == "add":
            try:
                dest = sourcemaps.add(n.platform, n.app, n.map, bundle=n.bundle, build=n.build)
            except ValueError as e:
                print(f"  \033[31mERROR\033[0m {e}")
                return 2
            print(f"  registered -> {dest}")
            return 0
        if n.mcmd2 in ("import", "fetch"):
            if n.mcmd2 == "import":
                todo = [(n.folder, lambda: sourcemaps.import_release(n.folder))]
            else:
                try:
                    tags = [n.tag] if n.tag else [
                        t for t in sourcemaps.release_tags(n.repo) if t not in sourcemaps.imported_tags()]
                except ValueError as e:
                    print(f"  \033[31mERROR\033[0m {e}")
                    return 2
                if not tags:
                    print("  every Release is already imported")
                todo = [(t, lambda t=t: sourcemaps.fetch_release(t, repo=n.repo)) for t in tags]
            failed = 0
            for what, do in todo:
                try:
                    for platform, pkg, paths in do():
                        print(f"  {what}  {platform:<8} {pkg:<28} "
                              + ", ".join(os.path.basename(p) for p in paths))
                except (OSError, ValueError) as e:
                    failed += 1
                    print(f"  \033[31mERROR\033[0m {what}: {e}")
            return 2 if failed else 0
        if n.mcmd2 == "resolve":
            return _maps_resolve(n, sourcemaps)
        rows = sourcemaps.listed()
        for platform, pkg, key, path in rows:
            info = sourcemaps.release_info(path)
            rel = ""
            if info:
                rel = (f"  {info.get('tag') or 'dry run'} · {info.get('versionName')} "
                       f"({info.get('versionCode')})")
            print(f"  {platform:<8} {pkg:<36} {key}{rel}")
        print(f"\n  {len(rows)} map(s) in {sourcemaps.ROOT}")
        return 0

    if n.cmd == "ios":
        from . import capture_ios, xctrace
        if n.icmd == "devices":
            sims = capture_ios.simulators()
            for d in sims:
                print(f"  {d['state']:<10} {d['name']:<32} iOS {d['os_version']:<6} {d['udid']}")
            print(f"\n  {len(sims)} simulator(s). Boot one with: xcrun simctl boot \"<name>\"")
            return 0
        if n.icmd == "toc":
            print(json.dumps({k: v for k, v in xctrace.parse_toc(xctrace.export_toc(n.trace)).items()
                              if k != "tables"}, indent=2))
            return 0
        if n.icmd == "convert":
            out = n.out or n.trace.rstrip("/")[:-len(".trace")] + ".pftrace"
            rep = capture_ios.convert_recording(n.trace, out, pkg=n.app)
            print(f"  converted -> {out}")
            print(json.dumps(rep["convert"], indent=2))
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

    if n.cmd == "reset":
        from . import reset
        p = reset.plan()
        if not any(p["rows"].values()) and not p["trace_files"]:
            print("  nothing to delete: the history is already empty")
            return 0
        print("  This deletes, and cannot be undone:")
        print(reset.describe(p) if not n.keep_traces else reset.describe({**p, "trace_files": 0}))
        print("  The app catalogue (apps.json, apps.local.json) is kept.")
        if not n.yes:
            if not sys.stdin.isatty():
                print("  refusing without --yes: not an interactive terminal")
                return 2
            if input("  Type 'delete' to confirm: ").strip() != "delete":
                print("  cancelled; nothing was deleted")
                return 1
        done = reset.reset(keep_traces=n.keep_traces)
        print(f"  deleted {done['rows']['runs']} run(s)"
              + (f" and {done['trace_files']} trace file(s)" if done["trace_files"] else "")
              + "; the next run is #1")
        return 0

    if n.cmd == "reextract":
        res = store.reextract()
        print(f"  re-extracted {res['reextracted']} run(s)")
        if res["missing_trace"]:
            print(f"  skipped (trace file gone): {res['missing_trace']}")
        # A verdict is computed from metrics, so new metrics leave the stored
        # verdict describing numbers that no longer exist -- a run re-extracted
        # into four budget breaches would still read PASS. Rules-only verdicts
        # are cheap and deterministic, so they are recomputed. An LLM-written
        # analysis is not regenerated behind the user's back (it costs API
        # calls); those runs are listed so they can be re-analysed on purpose.
        # Verdict rows only: an AI summary (F-023) is never the verdict.
        latest = {rid: r["model"] for rid, r in store.latest_analyses("verdict").items()}
        summarised = set(store.latest_analyses("summary"))
        redone, stale = 0, []
        for rid, m in res.get("metrics", {}).items():
            if latest.get(rid, "heuristic") == "heuristic":
                _analyse_run(rid, m, use_llm=False)
                redone += 1
            else:
                stale.append(rid)
        print(f"  re-analysed {redone} rules-only verdict(s)")
        if stale:
            print(f"  left as-is (LLM analysis; re-run `analyse` to refresh): {stale}")
        # A summary describes the numbers it was written from. The new verdict
        # row marks it stale on the dashboard; say so here too.
        outdated = sorted(summarised & set(res.get("metrics", {})))
        if outdated:
            print(f"  AI summaries now out of date (regenerate with `swagperf summary RUN`): {outdated}")
        return 0

    if n.cmd == "triage":
        from . import triage
        if n.mark is not None:
            print(f"  reviewed through #{triage.write_marker(n.mark)}")
            return 0
        after = n.after if n.after is not None else triage.read_marker()
        if after is None:
            print(f"  {os.path.relpath(triage.TRACKER)} has no 'Runs reviewed through: #N' line; pass --after N.",
                  file=sys.stderr)
            return 2
        screens_of = None
        if n.screens:
            from .screens import extract_screens
            screens_of = extract_screens
        t = triage.review(triage.load_history(after, n.lookback), after=after,
                          lookback=n.lookback, screens_of=screens_of)
        print(json.dumps(t, indent=1) if n.json else triage.format_text(t))
        return 0

    if n.cmd == "pm":
        from . import pm
        print(pm.status() if n.pcmd == "status" else f"  {pm.request_review('asked from the command line')}")
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
