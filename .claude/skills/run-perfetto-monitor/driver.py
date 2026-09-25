#!/usr/bin/env python3
"""Drive swagperf with no phone: seed a scratch history, run the dashboard,
screenshot it and click through it in headless Chromium.

Run from the repo root with the project's venv (it has Playwright):

    ./.venv/bin/python .claude/skills/run-perfetto-monitor/driver.py up
    ./.venv/bin/python .claude/skills/run-perfetto-monitor/driver.py tour
    ./.venv/bin/python .claude/skills/run-perfetto-monitor/driver.py down

Everything lives in a scratch workspace ($SWAGPERF_RUN_DIR, default
$TMPDIR/swagperf-run): its own database, app catalogue, traces and
screenshots. The user's history.db, traces/ and docs/ are never touched, no
model is called, and no PM review is started.
"""
import argparse, json, os, re, shutil, signal, socket, subprocess, sys, tempfile, time
import urllib.error, urllib.request

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
WORK = os.path.abspath(os.environ.get("SWAGPERF_RUN_DIR")
                       or os.path.join(tempfile.gettempdir(), "swagperf-run"))
SHOTS = os.path.join(WORK, "shots")
STATE = os.path.join(WORK, "server.json")
LOG = os.path.join(WORK, "server.log")
DB = os.path.join(WORK, "h.db")
PY = sys.executable
ROUTES = os.path.join(REPO, "frontend", "src", "app", "routes.ts")


def env():
    """The environment every swagperf child runs in: scratch data, no model.
    SWAGPERF_RUN_BACKEND opts a check into a model backend (e.g. `cli` with a
    fake `claude` in SWAGPERF_CLAUDE_BIN, to drive AI summaries)."""
    e = dict(os.environ)
    e.update(SWAGPERF_DB=DB, SWAGPERF_APPS=os.path.join(WORK, "apps.json"),
             SWAGPERF_BACKEND=os.environ.get("SWAGPERF_RUN_BACKEND") or "heuristic",
             SWAGPERF_PM_AUTOTRIAGE="0",
             PYTHONUNBUFFERED="1",
             PYTHONPATH=os.pathsep.join(p for p in (REPO, e.get("PYTHONPATH")) if p))
    return e


def swagperf(*args, check=True):
    """`python -m swagperf.cli ...` with cwd = the workspace, because seed and
    the server resolve trace paths against the current directory."""
    os.makedirs(WORK, exist_ok=True)
    r = subprocess.run([PY, "-m", "swagperf.cli", *args], cwd=WORK, env=env())
    if check and r.returncode not in (0, 1):  # analyse exits 1 on a `fail` verdict
        sys.exit(f"swagperf {' '.join(args)} exited {r.returncode}")
    return r.returncode


def pyrun(code):
    subprocess.run([PY, "-c", code], cwd=WORK, env=env(), check=True)


# ---------------------------------------------------------------- seed + server

def seed(runs):
    for p in (DB, os.path.join(WORK, "apps.json")):
        if os.path.exists(p):
            os.remove(p)
    for d in ("traces", "shots"):
        shutil.rmtree(os.path.join(WORK, d), ignore_errors=True)
    os.makedirs(os.path.join(WORK, "traces"))
    print(f"seeding {WORK}", flush=True)
    # Run #1: a competitor-style app on a manual session. It emits no step:
    # markers, so its steps are derived, and it carries SwagTrace screen
    # markers, so the Screens page has data. It is deliberately not
    # com.swag.pay: the app picker prefers Swag Pay's own package, and a Swag
    # Pay run here would hide the seeded builds from the default view.
    pyrun("from swagperf.synth_android import gen_device_session\n"
          "b, _ = gen_device_session(3, pkg='com.example.app', stability=True)\n"
          "open('traces/example_session.pftrace', 'wb').write(b)")
    swagperf("analyse", "traces/example_session.pftrace", "--app", "com.example.app",
             "--device", "pixel7", "--label", "derived-demo", "--no-llm", "--no-review")
    # Runs #2..#N+1: synthetic builds (recorded with no app, so "unknown").
    # The last, and so the latest, regresses camera open and thermals and fails.
    swagperf("seed", "-n", str(runs), "--regress-last")
    # One Flashlight audit, from the test fixture, so its screens have data.
    pyrun("import json\nfrom swagperf import store\n"
          f"s = json.load(open({os.path.join(REPO, 'tests', 'fixtures', 'flashlight_summary.json')!r}))\n"
          "a = store.audit_create(app_pkg='com.swag.pay', device='pixel7', label='fixture',"
          " iterations=3, duration_ms=10000, meta={'device': {'model': 'pixel7'}})\n"
          "store.audit_finish(a, summary=s)\nprint(f'  audit {a}  fixture')")
    print(f"seeded: #1 com.example.app session (derived, has screens), "
          f"#2-#{runs + 1} seed builds (#{runs + 1} regressed, latest), Flashlight audit A-1")


def state():
    try:
        st = json.load(open(STATE))
    except (OSError, ValueError):
        return None
    st.setdefault("url", f"http://127.0.0.1:{st['port']}")
    return st


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def port_busy(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def get(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read()


def base():
    st = state()
    if not st or not alive(st["pid"]):
        sys.exit("no dashboard running; start it with `driver.py up`")
    return st["url"]


def wait_for(url, procs, what):
    for _ in range(60):
        if any(p.poll() is not None for p in procs):
            break
        try:
            if get(url)[0] == 200:
                return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.5)
    print(open(LOG).read()[-2000:], file=sys.stderr)
    cmd_down(None)
    sys.exit(f"{what} did not come up; log above")


def stale_build():
    """Files in frontend/src newer than the web/dist the server will serve."""
    index = os.path.join(REPO, "web", "dist", "index.html")
    if not os.path.exists(index):
        return ["web/dist/index.html is missing"]
    built = os.path.getmtime(index)
    return [os.path.relpath(os.path.join(d, f), REPO)
            for d, _, fs in os.walk(os.path.join(REPO, "frontend", "src"))
            for f in fs if os.path.getmtime(os.path.join(d, f)) > built]


def cmd_up(a):
    st = state()
    if st and alive(st["pid"]):
        if not a.fresh:
            print(f"already running: {st['url']}  (pid {st['pid']}); `down` first to switch mode or port")
            return 0
        cmd_down(a)
    # Vite's dev proxy sends /api to 127.0.0.1:8787 (frontend/vite.config.ts),
    # so in --dev mode the backend has to sit on 8787.
    port = 8787 if a.dev else a.port
    busy = [q for q in ([port, a.vite_port] if a.dev else [port]) if port_busy(q)]
    if busy:
        sys.exit(f"port {busy[0]} is taken by something else"
                 + ("; is the real dashboard (perfetto_init) running?" if 8787 in busy else "; pass --port"))
    if a.fresh or not os.path.exists(DB):
        seed(a.runs)
    log = open(LOG, "ab")
    server = subprocess.Popen([PY, "-m", "swagperf.cli", "dashboard", "-p", str(port), "--no-open"],
                              cwd=WORK, env=env(), stdout=log, stderr=subprocess.STDOUT,
                              start_new_session=True)
    st = {"pid": server.pid, "port": port, "url": f"http://127.0.0.1:{port}", "pids": [server.pid]}
    json.dump(st, open(STATE, "w"))
    wait_for(st["url"] + "/api/history", [server], "dashboard")
    if a.dev:
        vite = subprocess.Popen(["npx", "vite", "--host", "127.0.0.1", "--port", str(a.vite_port),
                                 "--strictPort"],
                                cwd=os.path.join(REPO, "frontend"), stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)
        st.update(url=f"http://127.0.0.1:{a.vite_port}", pids=[server.pid, vite.pid])
        json.dump(st, open(STATE, "w"))
        wait_for(st["url"] + "/api/history", [server, vite], "vite")
        print(f"dev server up: {st['url']} (live frontend/src)  ->  backend :{port}  "
              f"(workspace {WORK})")
        return 0
    print(f"dashboard up: {st['url']}  (pid {server.pid}, workspace {WORK})")
    newer = stale_build()
    if newer:
        print(f"  ! web/dist is older than {len(newer)} file(s) in frontend/src "
              f"(e.g. {newer[0]}); pages show the last build. Rebuild, or use `up --dev`.")
    return 0


def cmd_down(a):
    st = state()
    if not st:
        print("not running")
        return 0
    for pid in st.get("pids") or [st["pid"]]:
        if alive(pid):
            os.killpg(pid, signal.SIGTERM)  # its own session: takes npx's children too
            for _ in range(20):
                if not alive(pid):
                    break
                time.sleep(0.25)
    os.remove(STATE)
    print(f"stopped {st['url']}")
    return 0


def cmd_status(a):
    st = state()
    if not st or not alive(st["pid"]):
        print("not running")
        return 1
    h = json.loads(get(base() + "/api/history")[1])
    runs = h.get("runs") or []
    print(f"running: {st['url']}  backend :{st['port']}  runs {len(runs)}  workspace {WORK}")
    return 0


def cmd_cli(a):
    return swagperf(*a.args, check=False)


# ---------------------------------------------------------------- browser

class Browser:
    """One headless Chromium page that records every error it sees."""

    def __init__(self, width=1440, height=900, light=False):
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch()
        self.ctx = self.browser.new_context(viewport={"width": width, "height": height})
        if light:
            # The app ignores the OS colour scheme: it defaults to dark and
            # persists the choice in the `swagperf-ui` zustand store.
            self.ctx.add_init_script("""if (!localStorage.getItem('swagperf-ui'))
                localStorage.setItem('swagperf-ui', JSON.stringify({state: {theme: 'light'}, version: 0}))""")
        self.page = self.ctx.new_page()
        self.errors = []
        self.page.on("console", lambda m: m.type == "error" and self.errors.append(f"console: {m.text}"))
        self.page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        self.page.on("response", lambda r: r.status >= 400 and self.errors.append(f"HTTP {r.status} {r.url}"))

    def open(self, path, run=None):
        url = base() + path
        if run:
            url += ("&" if "?" in url else "?") + f"run={run}"
        r = self.page.goto(url, wait_until="networkidle")
        if r and r.status == 503:
            self.errors.append("503: web/dist is not built (cd frontend && npm run build)")
        self.page.wait_for_timeout(400)  # let charts lay out after the last fetch

    def shot(self, name, full=False):
        os.makedirs(SHOTS, exist_ok=True)
        p = os.path.join(SHOTS, re.sub(r"[^\w.-]+", "_", name).strip("_") + ".png")
        if not full:
            self.page.screenshot(path=p)
            return p
        # The shell scrolls <main>, not the document, so Playwright's
        # full_page sees one viewport. Grow the viewport by what <main> hides.
        vp = self.page.viewport_size
        hidden = self.page.evaluate("""Math.max(0, ...[...document.querySelectorAll('*')]
            .filter(e => ['auto', 'scroll'].includes(getComputedStyle(e).overflowY))
            .map(e => e.scrollHeight - e.clientHeight))""")
        self.page.set_viewport_size({"width": vp["width"], "height": vp["height"] + hidden})
        self.page.wait_for_timeout(300)
        self.page.screenshot(path=p, full_page=True)
        self.page.set_viewport_size(vp)
        return p

    def close(self):
        self.browser.close()
        self.pw.stop()


def slug(path):
    return re.sub(r"[^\w]+", "_", path).strip("_") or "root"


def report(errors):
    for e in errors:
        print(f"  ! {e}")
    return 1 if errors else 0


def cmd_shot(a):
    b = Browser(a.width, a.height, a.light)
    try:
        b.open(a.path, a.run)
        print(b.shot(a.out or slug(a.path), a.full))
        return report(b.errors)
    finally:
        b.close()


def cmd_tour(a):
    paths = re.findall(r"path: '(/[^']*)'", open(ROUTES).read()) + ["/design-system"]
    b = Browser(a.width, a.height, a.light)
    bad = 0
    try:
        for p in paths:
            b.errors = []
            b.open(p, a.run)
            png = b.shot("tour_" + slug(p), a.full)
            print(f"{'FAIL' if b.errors else 'ok  '}  {p:<22} {png}")
            bad += report(b.errors)
    finally:
        b.close()
    print(f"{len(paths) - bad}/{len(paths)} pages clean")
    return 1 if bad else 0


def cmd_eval(a):
    b = Browser(a.width, a.height, a.light)
    try:
        b.open(a.path, a.run)
        print(json.dumps(b.page.evaluate(a.js), indent=2, default=str))
        return report(b.errors)
    finally:
        b.close()


def cmd_do(a):
    """Steps, in order:
      goto:/path         navigate (keeps localStorage)
      click:SELECTOR     Playwright selector: css, text=..., role=button[name="Send"]
      fill:SELECTOR=>TEXT
      type:TEXT          type into whatever has focus
      press:KEY          e.g. ControlOrMeta+k, Enter, Escape
      wait:MS | wait:SELECTOR
      shot:NAME          screenshot into shots/
      eval:JS            print the JSON result of a JS expression
    """
    b = Browser(a.width, a.height, a.light)
    pg = b.page
    try:
        b.open(a.path, a.run)
        for step in a.steps:
            verb, _, arg = step.partition(":")
            if verb == "goto":
                b.open(arg)
            elif verb == "click":
                pg.click(arg)
            elif verb == "fill":
                sel, _, text = arg.partition("=>")
                pg.fill(sel, text)
            elif verb == "type":
                pg.keyboard.type(arg)
            elif verb == "press":
                pg.keyboard.press(arg)
            elif verb == "wait":
                pg.wait_for_timeout(int(arg)) if arg.isdigit() else pg.wait_for_selector(arg)
            elif verb == "shot":
                print(b.shot(arg, a.full))
            elif verb == "eval":
                print(json.dumps(pg.evaluate(arg), indent=2, default=str))
            else:
                sys.exit(f"unknown step {step!r}; see `driver.py do -h`")
        return report(b.errors)
    finally:
        b.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    up = sub.add_parser("up", help="seed the scratch history if needed and start the dashboard")
    up.add_argument("--port", type=int, default=8799)
    up.add_argument("--runs", type=int, default=16)
    up.add_argument("--fresh", action="store_true", help="wipe the workspace and reseed")
    up.add_argument("--dev", action="store_true",
                    help="serve live frontend/src through Vite (backend on 8787) instead of web/dist")
    up.add_argument("--vite-port", type=int, default=5199)
    sub.add_parser("down", help="stop the dashboard")
    sub.add_parser("status", help="is it running, and how many runs")
    c = sub.add_parser("cli", help="swagperf.cli against the scratch history")
    c.add_argument("args", nargs=argparse.REMAINDER)

    def browser_args(p):
        p.add_argument("--run", type=int, help="select this run (?run=ID)")
        p.add_argument("--width", type=int, default=1440)
        p.add_argument("--height", type=int, default=900)
        p.add_argument("--full", action="store_true", help="full-page screenshot")
        p.add_argument("--light", action="store_true", help="light theme (the app defaults to dark)")
        return p

    s = browser_args(sub.add_parser("shot", help="screenshot one page"))
    s.add_argument("path")
    s.add_argument("--out", help="file name in shots/ (default: from the path)")
    browser_args(sub.add_parser("tour", help="screenshot every page, fail on any error"))
    e = browser_args(sub.add_parser("eval", help="print a JS expression's value on a page"))
    e.add_argument("path")
    e.add_argument("js")
    d = browser_args(sub.add_parser("do", help="run interaction steps on a page",
                                    description=cmd_do.__doc__,
                                    formatter_class=argparse.RawDescriptionHelpFormatter))
    d.add_argument("path")
    d.add_argument("steps", nargs="+")

    a = ap.parse_args()
    return globals()["cmd_" + a.cmd](a) or 0


if __name__ == "__main__":
    sys.exit(main())
