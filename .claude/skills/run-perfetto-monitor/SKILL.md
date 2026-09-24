---
name: run-perfetto-monitor
description: Build, start, run, screenshot and drive the swagperf dashboard and CLI (perfetto-monitor) headlessly with no phone attached. Use when asked to run or launch the dashboard, take a screenshot of a page, smoke-test a UI or backend change in the real app, click through Overview/Startup/Memory/Screens/Compare/Copilot/Flashlight, run the swagperf CLI against scratch data, or run the Python, frontend and Flashlight tests.
---

# Run swagperf (perfetto-monitor)

swagperf is a Python CLI and HTTP server (`swagperf/`) that serves a React dashboard, built from `frontend/` into `web/dist`. An agent drives it with **`.claude/skills/run-perfetto-monitor/driver.py`**. The driver:
- seeds a scratch history from synthetic traces, so no device is needed
- starts the server
- screenshots and clicks through pages in headless Chromium, using the venv's Python Playwright

All paths are relative to the repo root. Run every command from there.

The driver doesn't touch the user's `history.db`, `traces/`, `apps.local.json` or `docs/`. It calls no model and starts no PM review. Its workspace is `$SWAGPERF_RUN_DIR` (default `$TMPDIR/swagperf-run`), which holds `h.db`, `traces/`, `shots/` and `server.log`.

## Prerequisites

Verified on macOS with Python 3.9 in `.venv` and Node 26. `adb` is only needed for real captures. If `.venv` is missing, create it with the README's `python3 -m venv .venv` line first.

```bash
./.venv/bin/pip install perfetto anthropic playwright
./.venv/bin/python -m playwright install chromium
```

Node dependencies install from the lockfiles. This was verified by running `npm ci` on copies of both lockfiles; `node_modules` was already present in the repo.

```bash
(cd frontend && npm ci)
(cd flashlight && npm ci)
```

## Build

The server serves the committed `web/dist`. After frontend changes, rebuild it with `cd frontend && npm run build`, which runs `tsc -b && vite build` into `../web/dist`. Here the two halves were verified separately, without overwriting the tracked build:

```bash
(cd frontend && npm run typecheck)
(cd frontend && npx vite build --outDir "$TMPDIR/swagperf-dist-check" --emptyOutDir)
```

To look at frontend changes, `up --dev` (below) is usually better than a rebuild. It serves live `frontend/src` and leaves `web/dist` alone.

## Run (agent path)

```bash
./.venv/bin/python .claude/skills/run-perfetto-monitor/driver.py up --fresh   # seed, then serve web/dist on :8799 (~20 s)
./.venv/bin/python .claude/skills/run-perfetto-monitor/driver.py tour         # screenshot all 15 pages; exit 1 on any error
./.venv/bin/python .claude/skills/run-perfetto-monitor/driver.py shot /screens --run 1 --full
```

Screenshots are saved to `$TMPDIR/swagperf-run/shots/*.png`. **Read them.** A clean tour only proves that nothing threw an error.

While seeding, `up --fresh` prints each run's verdict, including a red `FAIL` block for #1 and for #17. That output is expected: those runs are seeded to fail.

Stop the server when you're done. `down` always stops everything `up` started:

```bash
./.venv/bin/python .claude/skills/run-perfetto-monitor/driver.py down
```

What `up --fresh` seeds:

| id | what | where it shows |
|---|---|---|
| #1 | `com.example.app` manual session: derived steps and SwagTrace screen markers | Screens (`--run 1`) |
| #2–#17 | `seed` builds, app "unknown". #17 (the latest) regresses camera open and thermals, so its verdict is FAIL | default view of Overview, Startup, Frames, Memory, Steps, Compare, History |
| A-1 | Flashlight audit from `tests/fixtures/flashlight_summary.json` | `/flashlight/*` |

| command | what it does |
|---|---|
| `up [--fresh] [--port 8799] [--runs 16]` | Seeds if the workspace has no DB (or with `--fresh`), starts the server detached and waits for `/api/history`. Warns if `web/dist` is older than `frontend/src`. |
| `up --dev [--vite-port 5199]` | Backend on :8787 plus Vite on :5199 serving live `frontend/src`. Browser commands then go through Vite. |
| `down` / `status` | `down` stops everything `up` started. `status` prints the URL and run count, and exits 1 when nothing is running. |
| `shot PATH [--run ID] [--out NAME] [--full] [--light]` | One screenshot, saved to `shots/NAME.png`. Without `--out`, the name comes from the path: `/screens` is saved as `screens.png`. |
| `tour [--run ID] [--full] [--light]` | Screenshots every path in `frontend/src/app/routes.ts`, plus `/design-system`. |
| `do PATH STEP...` | Runs steps in order: `click:SEL` `fill:SEL=>TEXT` `type:TEXT` `press:KEY` `wait:MS\|SEL` `goto:PATH` `shot:NAME` `eval:JS`. See `do -h`. |
| `eval PATH JS` | Prints the JSON value of a JS expression. |
| `cli ARGS...` | Runs `python -m swagperf.cli ARGS` against the scratch DB. |

Every browser command prints console errors, uncaught page errors and HTTP responses ≥400, and exits 1 if there were any. Selectors use Playwright syntax (CSS, `text=…`, `role=button[name='…']`).

Flows verified end to end:

```bash
./.venv/bin/python .claude/skills/run-perfetto-monitor/driver.py up   # reuses the seeded workspace; a no-op if already up

# Copilot: open with Cmd/Ctrl+K, ask, screenshot the streamed (rules-based) answer
./.venv/bin/python .claude/skills/run-perfetto-monitor/driver.py do /overview "press:ControlOrMeta+k" "wait:textarea[placeholder^='Ask about runs']" "fill:textarea[placeholder^='Ask about runs']=>Why did the latest run fail?" "press:Enter" "wait:4000" "shot:copilot_answer"

# Overview -> Compare through the UI
./.venv/bin/python .claude/skills/run-perfetto-monitor/driver.py do /overview "click:role=button[name='Open in Compare']" "wait:text=Top-line metrics" "eval:location.pathname" "shot:compare"

# Live frontend source, no rebuild
./.venv/bin/python .claude/skills/run-perfetto-monitor/driver.py down
./.venv/bin/python .claude/skills/run-perfetto-monitor/driver.py up --dev
./.venv/bin/python .claude/skills/run-perfetto-monitor/driver.py tour
./.venv/bin/python .claude/skills/run-perfetto-monitor/driver.py down
```

## Direct invocation (backend changes)

The CLI runs against the scratch history. Relative trace paths resolve inside the workspace, not the repo.

```bash
./.venv/bin/python .claude/skills/run-perfetto-monitor/driver.py cli list
./.venv/bin/python .claude/skills/run-perfetto-monitor/driver.py cli compare 17 16 --json
./.venv/bin/python .claude/skills/run-perfetto-monitor/driver.py cli benchmark set 10 --note known-good
```

Extraction alone needs no DB and no server:

```bash
./.venv/bin/python -c "
import os, tempfile
from swagperf.synth_android import gen_android_trace
from swagperf.extract import extract_any
p = os.path.join(tempfile.gettempdir(), 'swagperf-direct.pftrace')
open(p, 'wb').write(gen_android_trace(1, pkg='com.example.app')[0])
m = extract_any(p, app_pkg='com.example.app')
print(m['derived'], m['startup']['time_to_first_camera_frame_ms'], [s['step'] for s in m['steps']][:4])
"
```

`swagperf/synth.py` and `swagperf/synth_android.py` also build Swag Pay traces with step markers (`gen_trace`, `gen_swagpay_trace`) and a manual session with screen markers (`gen_device_session`).

## Run (human path)

- `./perfetto_init` starts the real dashboard on :8787 against the real `history.db` and opens a browser. `./perfetto_init stop` stops it.
- `cd frontend && npm run dev` hot-reloads on :5173 and proxies `/api` to :8787.

Neither path isolates data, so agents shouldn't use either. They weren't run for this skill.

## Test

```bash
./.venv/bin/python -m unittest discover -s tests   # ~3 min
(cd frontend && npm test)                           # vitest, ~2 s
(cd frontend && npm run typecheck && npm run lint)
(cd flashlight && node summary.test.js)             # prints "summary.test.js: ok"
```

There is no CI config; these commands are the whole suite. The Python tests use their own temporary databases.

Other sessions share this worktree, so a suite can go red partway through while one of them has an edit half-done. This was seen once: 3 `test_triage` failures while `swagperf/triage.py` was being edited. Re-run before blaming your own change.

## Gotchas

- **`chromium-cli` isn't installed here.** The venv's Python Playwright is used instead; its Chromium was already cached in `~/Library/Caches/ms-playwright`.
- **Trace paths are relative to the process's current directory.**
  - `seed` writes `traces/seed_NNN.pftrace` into the current directory, overwriting what's there.
  - The server resolves stored trace paths against its own current directory.
  - So the driver runs everything with the workspace as the current directory and `PYTHONPATH=<repo>`. `web/dist` and `.env` are found relative to the package, so they still load.
  - **Never run `swagperf.cli seed` from the repo root**: it writes into the user's `history.db` and `traces/`.
- **`swagperf.cli reset` deletes `<repo>/traces` whatever `SWAGPERF_DB` says.** To start over, use `up --fresh`.
- **Model calls and PM review are on by default.**
  - `.env` sets `SWAGPERF_BACKEND=auto`, which tries the `claude` CLI. PM auto-review, which runs `claude` and edits `docs/`, defaults to on.
  - The driver exports `SWAGPERF_BACKEND=heuristic` and `SWAGPERF_PM_AUTOTRIAGE=0`, and passes `--no-llm --no-review`.
  - `.env` only fills variables that aren't already set, so exported values win.
- **The app picker prefers Swag Pay (`com.swag.pay`).** If the DB holds even one Perfetto run for it, the default view is that run and every other series is hidden. That's why the screens demo run uses `com.example.app`. `seed` records no app, so its runs show as "unknown" / "Unknown app".
- **A `gen_device_session` trace analysed as `com.swag.pay` prints "derived steps -- not instrumented".** This is expected. The trace has screen markers but no timed `step:` spans, so extraction falls back to derived steps.
- **`analyse` exits 1 on a FAIL verdict, and 2 when an instrumented app has no step markers.** Exit 1 is not a crash.
- **`web/dist` can lag `frontend/src`.** Other sessions edit the frontend without rebuilding. `up` warns about this; `up --dev` shows the live source.
- **`--dev` needs port 8787**, because the proxy target is hard-coded in `frontend/vite.config.ts`. So it can't run while the real dashboard is up.
- **`--dev` hides 404s for missing files.** Vite answers any unknown path with a 200, so a missing asset only shows up as an error in built mode.
- **`?run=ID` is consumed.** The app selects that run once `/api/history` loads, then strips the parameter, so `location.search` is empty afterwards.
- **The shell scrolls `<main>`, not the document.** Playwright's own full-page option therefore captures one viewport. `--full` grows the viewport by the height `<main>` hides.
- **The theme ignores the OS colour scheme.** It defaults to dark and persists in the `swagperf-ui` localStorage key. `--light` seeds that key.
- **Each browser command is a fresh browser context.** Theme, profiler, app filter and Copilot state don't carry over between commands; chain steps inside one `do` to keep them.
- **Capture, Stress, Manual and Run audit poll `adb` every 15 s.** With no phone they show "No device connected". With a phone plugged in they talk to it, and their Profile / Start buttons start real device jobs. Don't click those in a smoke test.
- **Auto mode may ask for approval.** In auto mode, the permission check blocked the Copilot `do` flow and `up --dev` for an agent. It judged them as changes to shared resources, though both only touch the scratch workspace and ports 8787/5199. If that happens, ask the user to approve; don't work around the check.
- **Some pages write to the scratch workspace.** Copilot has no model behind it, and asking it something saves the thread to the scratch DB. Opening Screens writes `.screens-cache/` beside the trace. Everything stays inside the workspace.

## Troubleshooting

- **`! web/dist is older than N file(s) in frontend/src`** after `up`: the pages show the last build, not the current source. Run `down` then `up --dev`, or rebuild with `npm run build` if you own the frontend change.
- **`already running: … ; down first to switch mode or port`**: `up` doesn't restart a running server. Run `down` first, or use `up --fresh`, which also reseeds.
- **`port 8799 is taken by something else; pass --port`**: another server holds the port. It may be a second workspace, since `SWAGPERF_RUN_DIR` separates state but not ports. Pass `--port`.
- **`no dashboard running; start it with driver.py up`** from `shot`, `tour`, `do` or `eval`: nothing is up for this workspace.
- **`npm warn install-scripts … fsevents@2.3.3`** during `npm ci`: harmless. It's an optional macOS file watcher, and vite, tsc and vitest all run without it.
