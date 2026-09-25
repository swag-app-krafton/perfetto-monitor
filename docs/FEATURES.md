# swagperf feature notes

A reference for everything swagperf does. The first section lists what changed on 2026-09-24. The rest of the file covers every feature built so far.

- **When this was written.** 2026-09-24, about 13:30 IST, from the history up to `0083bc9` and the working tree at that time. Other sessions were still editing the iOS and stability work, so for those two sections check `git status` before relying on the details.
- **Status labels.** ✅ means committed, with the commit given. 🚧 means built but not yet committed. 📝 means designed or planned, with no code.
- **Device.** Each feature says whether it needs a real Android phone, a Mac with Xcode and a booted iOS Simulator, or nothing.
- **Testing.** Everything that changed today has a test plan in [TESTING-PLAN.md](TESTING-PLAN.md). Open items are in [TRACKER.md](TRACKER.md).

## Contents

1. [What changed today (2026-09-24)](#what-changed-today-2026-09-24)
2. [Analysis pipeline](#1-analysis-pipeline)
3. [Capture on Android](#2-capture-on-android)
4. [Stress tests](#3-stress-tests)
5. [Screens: cost per screen](#4-screens-cost-per-screen)
6. [History and storage](#5-history-and-storage)
7. [Compare and benchmarks](#6-compare-and-benchmarks)
8. [App catalogue and competitors](#7-app-catalogue-and-competitors)
9. [Dashboard](#8-dashboard)
10. [Copilot](#9-copilot)
11. [Flashlight audit lane](#10-flashlight-audit-lane)
12. [Token-consumption monitor](#11-token-consumption-monitor)
13. [Tracker and product-manager automation](#12-tracker-and-product-manager-automation)
14. [Launchers and agent tooling](#13-launchers-and-agent-tooling)
15. [iOS lane (F-013)](#14-ios-lane-f-013)
16. [Crashes & ANRs, and hangs on Frame pacing (F-014, F-028)](#15-crashes--anrs-and-hangs-on-frame-pacing-f-014-f-028)
17. [Designs on paper](#16-designs-on-paper)
18. [AI run summary and trend (F-023, F-024, F-026)](#17-ai-run-summary-and-trend-f-023-f-024-f-026)
19. [Design rules](#design-rules)
20. [Reference: commands, API routes, settings](#reference)
21. [Known gaps and open items](#known-gaps-and-open-items)
22. [Commit timeline](#commit-timeline)

---

## What changed today (2026-09-24)

### Committed

| Commit | Change | What it means for a user |
|---|---|---|
| `9ca753a` | **Dashboard pages built only from the design system (T-003)** | Nothing should look or behave differently. Three hand-drawn charts moved into the design system: Stress's box plot became `DotBoxPlot`, Startup's ordering timeline became `SpanTimeline`, and Memory's breakdown became `StackedBars` in size `lg`. The two hand-built expandable tables (Screens and Steps) became `ExpandableTable`. Other parts moved too: the navigation stack to `FlowList`, the Capture app list to `ChoiceList`, the Overview verdict strip to `StatusStrip`, and the top-bar pickers to `Table`/`SortTh`/`RowAction`. Hard-coded colours moved into tokens. A lint rule now stops pages from using raw controls or inline styles. |
| `1d6b4fb` | **Run skill** (`.claude/skills/run-perfetto-monitor/`) | An agent can start the dashboard on made-up data, screenshot every page, click through flows and run the CLI, all without a phone and without touching `history.db`, `traces/` or `docs/`. It also adds tracker row B-005: `seed` records its runs without an app. |
| `0083bc9` | **Maestro screenshot testing designed and parked (F-012); one product-manager skill for every agent** | Docs and agent setup only. `docs/screenshot-testing-plan.html` and a BACKLOG write-up describe the design. `.agents/skills/product-manager/SKILL.md` is now the only definition of the product-manager role; the Claude Code agent, Claude Code skill and Cursor skill just point to it. It adds a queue of parked work and a fixed answer shape for "what's next". This commit is local and not pushed yet. |

`1d6b4fb` and everything before it is pushed as branch `flashlight-profiler`, and pull request #1 into `main` is open.

### Built but not committed yet

| Item | Change | Details |
|---|---|---|
| **F-013** 🚧 | **iOS lane.** Instruments recordings from a booted iOS Simulator are converted into Perfetto traces, so the rest of the tool reads them unchanged. | [Section 14](#14-ios-lane-f-013) |
| **F-014** 🚧 | **Stability.** Hangs, JS errors with stacks resolved against the build's source map, and crashes, on both platforms. F-028 (committed `58fe6fa`…`d21da60`) adds ANRs and every crash with its crash log, and splits the screen: Crashes & ANRs for JS exceptions, ANRs and crashes, and hangs on Frame pacing. | [Section 15](#15-crashes--anrs-and-hangs-on-frame-pacing-f-014-f-028) |
| **B-006** 🚧 | Per-screen CPU used to read 0 ms when a trace had no scheduler data. It is now "not measured" and shows as "–". | [Section 4](#4-screens-cost-per-screen) |
| **T-004** 📝 | The frame deadline is still fixed at 60 Hz (16.67 ms). Tracker row only, no code yet. | [Known gaps](#known-gaps-and-open-items) |
| Two changes that affect Android too 🚧 | Startup is "not measured" when the recorded critical path is incomplete, and average and longest frame time are "not measured" when no frames were counted. | [Section 1](#1-analysis-pipeline) |
| Tracker upkeep | The run history was reset, and the review was redone from run #1. B-007 was logged: `triage --mark` can't move the review marker back after a reset. B-008 was logged: `triage` never reports a step-based issue as quiet. | [TRACKER.md](TRACKER.md) |

---

## 1. Analysis pipeline

The core. One rule shapes all of it: **measurement is deterministic, judgement is not.** Every number comes from SQL run over the trace with Perfetto's TraceProcessor. The analyst, whether rules or a model, sees only the extracted numbers and trailing baselines, **never a raw trace**, and a test enforces this.

| Feature | What it does | Entry points | Key code | Since |
|---|---|---|---|---|
| **Analyse a trace** ✅ | Extracts metrics from a `.pftrace`, records the run, works out regressions and gives a verdict. | `swagperf analyse <trace>` with `--app`, `--derive`, `--path-kind`, `--label`, `--git-sha`, `--app-version`, `--device`, `--no-llm`, `--backend auto\|cli\|api\|heuristic`, `--json`, `--fail-on never\|fail\|warn`. Exit code 1 on a fail verdict. Exit code 2 when an app marked instrumented has no `step:` markers. | `cli.py`, `extract.extract_any()`, `store.record()` | `84e4b02` |
| **Steps from the app's own markers** ✅ | Reads the app's `step:<name>` slices: each step's duration and North Star target. Each step is split into its direct children, plus a "(self / untraced)" remainder so the parts add up to the step. An app that emits only instant (zero-length) step markers falls back to derived steps, with a note. | automatic | `extract._extract()`, `_with_self_time()` | `84e4b02`, `a792525` |
| **Startup (TTID) on two paths, and the ordering rule** ✅ | Startup is the end of the last critical-path step. The returning-user path is bootstrap → session_read → compose_shell → camera_open → first_qr_decode. The first-run path is bootstrap → hermes_boot → rn_onboarding_surface. On the returning path, deferred work (hermes_boot, cronet_init, remote_config) that starts before the first frame is an ordering violation, with 1 ms of tolerance. 🚧 Today's change: if some critical-path steps are recorded but others are missing, startup is "not measured" (with a note), not a shorter number. | Startup page | `budgets.py`, `extract._extract()` | `84e4b02` |
| **Frame pacing and thermal drift** ✅ | Counts the app's `Choreographer#doFrame` slices. Slow means over 16.67 ms; janky means over 3 × 16.67 ms. Thermal drift compares the mean frame time in the second half of the session with the first half. It skips the first second, needs at least 120 frames, and is "not measured" when the screen changes during the trace. Zero frames means "not measured", never 0%. 🚧 Today: average and longest frame time are also "not measured" with zero frames. | Frame pacing page | `extract._frames()` | `84e4b02`, `a792525` |
| **RAM usage** ✅ | Peak RAM usage, RAM growth and the Hermes heap, always for the app's own process. An earlier version reported the whole device's 803 MB. | Memory page | `extract._memory()` | `84e4b02`, `a792525` |
| **Finding the app's process** ✅ | Finds the app's process by name. For an instrumented app only, an unnamed or zygote-named process that emitted the app's markers also counts. A process carrying another package's name never borrows them. If the app can't be found, frames and RAM usage are "not measured", not device-wide. | automatic | `extract._app_upids()` | `a792525`, `7c09021` |
| **Derived steps for any Android app** ✅ | For apps without markers, such as competitors, steps come from ordinary Android slices: process_start, bind_application, activity_create, layout_inflate, activity_resume, first_frame and fully_drawn. The package and the start type come from Perfetto's startup tables. A missing phase is left out, never reported as zero. Cold versus warm is decided by whether process_start was found. | automatic, or `--derive` | `derive.py` | `377aa0d`, `e67cc03` |
| **North Star targets and risk map** ✅ | Global North Star targets: TTID 420 ms, slow frames 5%, janky frames 0.5%, peak RAM usage 320 MB, RAM growth 60 MB, thermal drift 15%. There are per-step North Star targets for Swag Pay, and each metric maps to an architectural risk. **Swag Pay's North Star targets are never applied to another app.** A derived run gets a TTID North Star target only if the catalogue states one. RAM and thermal North Star targets apply only to our own app. The frame deadline applies to every app. | automatic | `budgets.py`, `extract_any()`, `server._payload()`, `frontend/src/domain/metrics.ts` | `84e4b02`… |
| **Regressions against a trailing baseline** ✅ | A step has regressed when it clears all three bars against the median of its last 20 runs for the same app: z ≥ 2.5, at least 8% slower, and at least 5 ms slower. A baseline needs at least 5 runs. 🚧 Today: baselines also keep platforms and simulator runs apart. | automatic | `store.baseline()`, `store.regressions()` | `84e4b02`, `a792525` |
| **Verdict and analyst** ✅ | The analyst tries the local `claude` CLI first, then the Anthropic API, then built-in rules. A verdict is pass, warn or fail, with findings: runtime, severity, evidence, architectural risk and a recommendation. Under the rules, an ordering violation is high severity, and so is a regression or a breach of a North Star target by more than 25%. Dashboard jobs record the rules' verdict. ✅ A model's reading of a run is a separate AI summary that never changes the verdict ([section 17](#17-ai-run-summary-and-trend-f-023-f-024-f-026)). | `--backend`, `SWAGPERF_BACKEND`, `SWAGPERF_MODEL` | `analyst.py` | `84e4b02`, `a792525` |
| **Capture checks** ✅ | **An empty capture is never a pass.** `capture_problems()` flags a trace with no slices from the target app, a launch that belongs to another package, no startup phases, or no frames; in capture jobs the first two are fatal. `tracing_lost()` rejects a device trace whose kernel scheduler data is missing or stops early: the run isn't recorded and the file is kept (B-004). A 0 ms startup reads "not measured". | automatic | `extract.capture_problems()`, `tracing_lost()` | `e67cc03`, `e9d7162` |
| **Plain-language step and thread descriptions** ✅ (F-011) | Every step and every common thread name has a short description. It appears behind a "?" beside the name on the Screens, Steps, Startup, Compare and Audit pages. A test fails if any step lacks one. | dashboard | `budgets.STEP_DESCRIPTIONS`, `threads.py` | `e9d7162` |

Device: none. Everything here reads a trace file.

## 2. Capture on Android

All of this needs an Android phone with USB debugging on.

| Feature | What it does | Entry points | Since |
|---|---|---|---|
| **CLI capture** ✅ | Pushes a Perfetto config and records. With `--cold`, it force-stops the app, then launches it 600 ms after tracing starts. `--background-wait` keeps start, stop and launch in order; racing them used to give empty traces. The config uses a 128 MB buffer and records: scheduler, gfx/view/am/camera/res atrace, process stats every second, FrameTimeline and the package list. 🚧 Today it also records the Android log, filtered to the SwagPerfError, AndroidRuntime, DEBUG and libc tags. | `swagperf capture --pkg X [--cold] [--repeat N] [--duration-ms] [--analyse] [--label] [-o]` | `84e4b02`, `377aa0d`, `e67cc03` |
| **Capture from the dashboard** ✅ | The Capture page lists the connected phone and its installed apps, catalogue apps first. You pick cold or warm, 5, 10 or 20 s, and press **Profile**. A five-stage progress bar and a log follow the job, then **View results**. Only one device job runs at a time. Package names are validated and durations clamped to 2–120 s. An unknown package is added to the catalogue as an unlabelled competitor. | `/capture`, `POST /api/capture/start`, `GET /api/jobs` | `e67cc03`, `b46f5fe` |
| **Device status** ✅ | Shows the phone's battery level and temperature, the Perfetto version on it, its third-party packages, and whether another profiler is running. The Capture, Stress, Manual and Run audit pages check every 15 s. | `GET /api/device` | `e67cc03`, `e9d7162` |
| **Where each run was measured** ✅ | At capture, each run records its device (model, Android version, SoC, RAM, screen), the device's state (battery, temperature, thermal status) and the app build (version name and code, SDK levels, installer, install dates). Older runs are filled in from the trace itself when first opened. Anything not recorded shows "not recorded", and collecting this never fails a capture. | Run details dialog, `GET /api/run/meta?id=` | `d43fe8a` |
| **One profiler at a time** ✅ (B-004) | A capture or manual session is refused while Flashlight's profiler or another atrace session is running on the phone. The experiment showed that running both destroys the Perfetto trace silently. | automatic | `e9d7162` |
| **Manual sessions** ✅ | Record while you drive the app by hand: start cold or warm, use the app, then **Stop & analyse** or **Abort**. The session survives a page reload. A slimmed-down config records about 53 MB per minute instead of about 230, and stopping takes about 7 s. | `swagperf manual start\|stop\|status\|abort`, `/manual`, `POST /api/manual/*` | `d4b18b3`, `feb61cc`, `db78f77` |
| **Live markers** ✅ | While a manual session records, the Manual page shows screens, actions, navigations and steps as they happen, newest first. It reads only the new bytes each poll and never disturbs the recording. If a partial read goes wrong, it falls back to copying the whole file. | `GET /api/manual/live` | `e4c67be`, `f190cda` |

## 3. Stress tests

✅ `7ddf1b9`, `b46f5fe`. Needs an Android phone. 🚧 Today's change also allows the iOS Simulator.

A stress test runs N cold (or warm) starts back to back. Each session becomes an ordinary run, and the test reports the spread across sessions: n, min, max, mean, median, p90, standard deviation, and spread = (max − min) / median, for TTID, peak RAM usage and slow frames.
- **Limits.** 2–30 sessions, 2–60 s each, with a 1.5 s pause between them. A failed session doesn't end the test.
- **Deciding whether a shift is real.** The dashboard calls a shift real only when Mann-Whitney p < 0.05 **and** the median moved by more than the baseline test's interquartile range. Fewer than 10 sessions is flagged as low confidence.
- **Interrupted tests.** A test left running when the server stopped is marked interrupted at the next start.
- **Entry points:** `swagperf stress run --pkg X -n 5 [--warm]`, `stress list`, `stress show ID`, the `/stress` page (TTID strip and box plot against the previous test), and `POST /api/stress/start`.

## 4. Screens: cost per screen

✅ `d4b18b3` through `db78f77`, and the React page in `ebd91d6`. Device: none, it reads a trace.

The app marks screens and actions in the trace with SwagTrace markers:
- `screen:<Route>#compose|#rn|#native_view` for a visit
- `action:<name>`
- `nav:<From>-><To>` for a transition
- `nav:open-/back-/tab-<Route>` for navigation stack operations

Only fixed names and outcome classes go into markers, never user data.

The Screens page has two views.
- **Screen usage:**
  - a table of cost per screen: CPU busy, CPU time, peak RAM usage, RAM growth, app jank and time on screen
  - each visit charted on its own, with visits more than 2σ from the mean drawn red
  - a session timeline with RAM and CPU panels sharing one time axis
  - the navigation stack, with how long each transition took to draw
  - the user's actions
  - cost by stack depth
- **Launch metrics:** TTID and the startup steps from the same trace.

How it measures:
- **CPU** is scheduled time clipped to each visit.
- **RAM** is the app's own process. RAM growth is the lowest-to-highest change within a visit.
- **Open visits.** A visit that never closed runs to the end of the trace and is flagged.
- **Sub-screens** are their own rows, never added into their parent.
- **The navigation stack** is replayed from the nav markers, and back never removes the root screen.
- **App jank** comes from FrameTimeline, split into the app's own missed deadlines, the system's, dropped frames and buffer stuffing.
- **Caching.** Results are cached next to the trace.

🚧 **B-006, today.** When a trace has no scheduler data, CPU is now "not measured", shown as "–". It used to read 0 ms. Totals leave unmeasured visits out, and the timeline hides its CPU panel. The cache version changed from 5 to 6, so old cached results are recomputed. This affects every iOS run, and Android traces recorded without scheduler data.

Entry points: `swagperf screens <trace> [--json]`, `GET /api/screens?run=N`, `/screens`.

## 5. History and storage

✅ Device: none.
- **The history.** All history lives in one SQLite file, `history.db`; set `SWAGPERF_DB` to use a different one.
- **What's stored.**
  - `runs`: headline metrics, JSON details and run metadata
  - `step_metrics`, `analyses`
  - stress tests and their sessions
  - Copilot threads, messages and pins
  - benchmarks and Flashlight audits
- **Upgrades.** Older history files are upgraded automatically when opened. 🚧 Today's upgrade adds `platform` (default `android`) and `simulator` (default 0) to runs, `platform` to stress tests, and the stability columns `hang_count`, `longest_hang_ms`, `js_errors`, `crashed` and `stability_json`. F-028 adds `anr_count` and `crash_count`.
- **`swagperf list`** shows the last 50 runs.
- **`swagperf reextract`** recomputes every run whose trace still exists, after extraction code changes. Verdicts are recomputed with rules; runs a model analysed are listed as out of date rather than sent to the model again.
- **`swagperf reset [--yes] [--keep-traces]`** ✅ `7d36827`:
  - Empties the history and restarts run numbers at #1.
  - Deletes the files under `traces/` and the Screens cache. 🚧 Today it deletes `traces/ios/` as well.
  - Keeps the app catalogue.
  - You must type "delete" to confirm.
  - It always deletes the repo's `traces/`, even when `SWAGPERF_DB` points elsewhere.
- **`swagperf seed -n 15 [--regress-last]`** writes made-up Swag Pay runs, the last one regressed. Known issue: B-005, these runs are recorded with no app.
- **Generators.** Made-up traces come from `synth.py` (Swag Pay with step markers), `synth_android.py` (any app, Swag Pay screens, a device-shaped manual session) and 🚧 `synth_ios.py`.

## 6. Compare and benchmarks

✅ `88ba98d`. Device: none.
- **Compare** is descriptive. It diffs the metrics, steps and child slices of any two runs:
  - A change under 5% counts as "same".
  - Thermal drift, which can be negative, uses absolute differences with a ±3 point band.
  - It warns when the runs used different start paths or different devices. 🚧 Today it also warns across platforms, or between a simulator run and a device run.
  - Entry points: `swagperf compare RUN [BASE] [--json]`, `/compare` (against the benchmark, or `?mode=run&a=&b=`), `GET /api/compare`.
- **Benchmarks** change what "regressed" means:
  - One run is pinned per app, path and device; if there's no pin for that device, the app and path's pin for any device is used. A benchmark is **never taken from another app**, and 🚧 never from another platform.
  - A pinned benchmark replaces the trailing baseline. The gate is at least 20% and 5 ms slower, with no z-score.
  - The pinned run never regresses against itself.
  - 🚧 A simulator run can't be pinned.
  - Entry points: `swagperf benchmark set|clear|list`, the History page's **Pin as benchmark**, `POST /api/benchmark/set|clear`.

## 7. App catalogue and competitors

✅ `377aa0d`, `a792525`.
- **Where apps come from.** The built-in list (`swagperf/apps.json`) sits under a local list (`apps.local.json`, or `SWAGPERF_APPS`), which is not committed.
- **Roles:** own, competitor or reference, plus flags for instrumented and verified, and optional North Star targets.
- **Built-in entries:**
  - Our app: Swag Pay (`com.swag.pay`, instrumented, TTID North Star target 420 ms).
  - Competitors: PhonePe, Google Pay, Paytm, BHIM, CRED, MobiKwik and WhatsApp.
  - References: Chrome and Clock.
  - 🚧 Today adds `com.cambench.compose.ios`, Swag Pay on iOS, with no North Star targets.
- **Placeholders.** An entry the tool added automatically never overrides a built-in one.
- **Triage** skips competitor runs.
- 🚧 **Keyed by platform.** Entries are now keyed by (platform, package), so the same id can mean different apps on Android and iOS.
- **Entry points:** `swagperf apps list|add|remove|discover`; `discover` needs a phone.

## 8. Dashboard

✅ React 19 + TypeScript + Vite in `frontend/`, built into the committed `web/dist`. Device: none.
- **Server.** `swagperf dashboard [-p 8787] [--no-open]`, or `./perfetto_init`.
  - It listens on 127.0.0.1 only and has no login. It refuses other websites' pages (T-001): the `Host` must be `localhost`, `127.0.0.1` or `[::1]` on any port, a browser's `Origin` must be a loopback page, and every write must send `X-Swagperf: 1`, which forces a CORS preflight the server never approves. Refused requests get 403 with `host_not_allowed`, `origin_not_allowed` or `missing_x_swagperf_header`.
  - Unknown paths return the app, and paths outside the build are blocked.
  - It answers 503 when the build is missing.
- **Top bar.** Controls, left to right:
  - **Profiler.** It was Perfetto or Flashlight. 🚧 Today it is a select with Perfetto · Android, Instruments · iOS and Flashlight · Android.
  - **App**, **Path** and **Version** filters.
  - **Run** picker: a sortable table of runs, with "Follow the latest run".
  - **Range:** last 30 runs, last 10, or last 7 days.
  - A link to the design system, and the theme (dark by default).
- **Sidebar.** Analyse, Run and Data groups.
  - It collapses to a rail of two-letter codes, and becomes a drawer on narrow screens.
  - The footer links to "LLM token usage".
- **Run box and Run details.** Every page header shows the run in view: its verdict, device and app build. Run details lists the app, device, device state and trace, with "not recorded" gaps and **Copy details**.
- **Links land on what they name.** `?focus=` rings the named item, and `?run=` selects a run and is then removed from the address.

| Page | What it shows |
|---|---|
| `/overview` | The verdict, what it was compared against, and who wrote it (the rules or a model). The worst regression, with its share of the startup change and links to inspect it, compare, or ask Copilot. Release gates. The AI summary ([section 17](#17-ai-run-summary-and-trend-f-023-f-024-f-026)). KPI tiles with change and a 12-run sparkline. Verdict by run, findings, and Copilot pins. |
| `/trend` ✅ | Each metric across app versions, a line per device, with its pinned benchmark dotted ([section 17](#17-ai-run-summary-and-trend-f-023-f-024-f-026)). |
| `/startup` | TTID over runs against its North Star target. Critical-path composition, where unaccounted time stays visible as a gap. The ordering constraint. |
| `/frames` | Slow frames, janky frames and thermal drift per run, then hangs (F-028). On the iOS Simulator, frames read "not measured" and the hangs still show. |
| `/memory` | Peak breakdown by runtime against the previous run. Peak RAM usage, RAM growth and Hermes heap, with North Star targets for Swag Pay only. |
| `/steps` | Sortable steps against the baseline (benchmark, or the median of the last 10 runs). Drill-down into p50/p90 and child slices. |
| `/screens` | See [section 4](#4-screens-cost-per-screen). |
| `/capture`, `/stress`, `/manual` | See sections [2](#2-capture-on-android) and [3](#3-stress-tests). |
| `/compare` | See [section 6](#6-compare-and-benchmarks). |
| `/history` | Search, verdict filter, sortable columns, Open / Compare / Pin, and the pinned benchmarks. |
| `/flashlight/audit`, `/flashlight/run`, `/flashlight/audits` | See [section 10](#10-flashlight-audit-lane). |
| `/crashes` | JS exceptions, ANRs and crashes. See [section 15](#15-crashes--anrs-and-hangs-on-frame-pacing-f-014-f-028). The old `/stability` address redirects here. |
| `/ios/*` 🚧 | The same trace pages for iOS runs, without Manual. |
| `/design-system` | The living reference of every component. |

- **Design system** ✅ `51f403f`, `a7e66df`, `9ca753a`. It lives in `frontend/src/design/`: foundations (colour tokens per theme), primitives, components, charts and hooks. Pages import only from `@/design`.
  - Lint rules forbid raw buttons, inputs, tables, SVG and inline styles in pages.
  - A test requires every component to appear on `/design-system`.
  - Typography follows krafton.com. KRAFTON red is used only for titles; status colours are separate.

## 9. Copilot

✅ `04c2129`, `a7e66df`. Device: none.

A docked panel that answers questions about the runs. Open it with ⌘K / Ctrl+K or the **Ask** button. It is **rule-based: no model**, and every number comes from the data.
- **Question types:**
  - why a run failed, which step grew most, a single step in detail
  - a PR summary
  - RAM peak, first run over its North Star target
  - stress noise (Mann-Whitney)
  - ordering, comparisons
  - the most expensive screens, screens that leak RAM
  - frames, explaining a finding
- **Answers** stream in as blocks: verdict, headings, paragraphs, tables, bars and code. Every figure cites its source, and a citation opens the page and rings the item.
- **Context.** Context chips cover the tab, the run in view and the benchmark. You can add a run, step or finding with `@`.
- **Deep answers** add a cross-check against stress tests.
- **Actions on each answer:** Copy as Markdown, Open in Compare, Pin as finding (it then shows on Overview), Export .md, and 👍/👎.
- **Threads** are saved, and Stop discards a half-finished answer.
- **Unknown runs.** A run that isn't in the history gets "no data", never a guess.
- 🚧 **Today:** answers are scoped to the platform, and screens without scheduler data are handled.
- **API:** `POST /api/copilot/ask` (streamed), `/api/copilot/threads`, `/pins`, `/pin`, `/unpin`, `/feedback`.
- **Planned (F-001):** answers written by a local Claude or Codex session.

## 10. Flashlight audit lane

✅ `e9d7162` (F-006; its code is committed, but it has not yet been run end to end on a phone). Needs an Android phone, Node, and `npm ci --prefix flashlight`.

Flashlight's own engine runs N cold starts. The stored figures are Flashlight's own:
- the score
- CPU, RAM, FPS and runtime
- CPU per thread, and the key threads: UI, RenderThread, the React Native JS thread and native modules
- the spread across cold starts, and the average cold start over time

Rules:
- **Never at the same time as Perfetto.** An audit holds the capture lock, refuses during a manual session, and resets atrace at the end.
- **Limits:** 2–20 cold starts, 3–60 s each.
- **Separate numbering.** Audits are numbered A-n, not #n, and their figures are never compared with Perfetto runs (F-008 was dismissed).

Entry points:
- CLI: `swagperf audit run --pkg X -n 5`, `audit list`, `audit show ID`.
- Dashboard: the Profiler switch, then Flashlight · Android, with the Audit, Run audit and Audits pages and an Audit picker.
- API: `POST /api/audit/start`, `GET /api/audits`.

The experiment behind the "never at the same time" rule (`2e6ce6e`, `experiments/flashlight-concurrency/`, `docs/flashlight-perfetto-observations.html`) found that once Flashlight starts, Perfetto loses its scheduler data, slices, markers and RAM samples for good, and neither tool logs an error.

## 11. Token-consumption monitor

✅ `0aabe16`. Device: none.

It reads the usage figures in Claude Code session logs, from the 12 most recent sessions. It splits them into graphify calls, file reads, searches and read-only shell commands.
- **Where to see it:** `/tokens.html` (the sidebar's "LLM token usage"), or `GET /api/tokens`.
- **What it never shows:** "tokens saved", because that figure can't be measured.

## 12. Tracker and product-manager automation

✅ `7cddefc`, `0083bc9`. Device: none.
- **The tracker.** `docs/TRACKER.md` lists every open item:
  - B- bugs, F- features, T- tech debt and security
  - P- performance issues, one file each in `docs/issues/`
  - Long write-ups go in `docs/BACKLOG.md`.
- **Triage** needs no model. `swagperf triage [--json] [--after N] [--screens] [--mark N]` groups problems into signals with stable keys:
  - `budget:`, `regression:` and `ordering:` keys
  - 🚧 `crash:` and `js_error:` keys, and iOS keys prefixed `ios:`
  - Each signal carries its occurrences, trend, first and last seen, and a link to any existing issue.
  - Triage reviews our own app only, and 🚧 skips simulator runs.
- **Automatic review.** `pm.py` runs after every capture, analyse, stress test and manual stop.
  - A clean run only moves the "Runs reviewed through" marker.
  - Otherwise it starts the product-manager agent in the background, with limited tools. The agent opens or updates issues and never commits.
  - It only reviews the project's own `history.db`.
  - Turn it off with `SWAGPERF_PM_AUTOTRIAGE=0`.
  - `swagperf pm status`, `swagperf pm review`.
- **The role.** `.agents/skills/product-manager/SKILL.md` defines it for every agent. It never closes an issue on its own, never reuses an ID, and answers "what's next" with a fixed shape.

## 13. Launchers and agent tooling

- **`./perfetto_init`** ✅ `cead9cf`, with `./perfetto` as an alias:
  - With no arguments, it starts the dashboard and opens a browser.
  - `stop` stops it.
  - `doctor` checks Python dependencies, the phone, manual-session state and the history. 🚧 It also checks Xcode's `xctrace`, the booted simulator and each iOS app's build type.
  - Anything else is passed to the CLI.
- **Run skill** ✅ `1d6b4fb`. `.claude/skills/run-perfetto-monitor/driver.py`:
  - `up` fills a scratch workspace with made-up runs and a Flashlight audit, and serves them on :8799.
  - `tour` screenshots every page and fails on any console, page or HTTP error.
  - `shot`, `do` and `eval` drive single pages and flows.
  - `cli` runs the CLI against the scratch history.
  - `up --dev` serves the live frontend source through Vite.
  - It never touches `history.db`, `traces/` or `docs/`, and calls no model.
- **Graphify** ✅ `80f8b93`. A query-first hook for Cursor, and the committed knowledge graph in `graphify-out/`.

## 14. iOS lane (F-013)

🚧 Not committed. Tracker F-013 (P1, in-progress). Decision record: [ADR 0002](decisions/0002-ios-via-xctrace-normalised-to-perfetto.md). **It needs a Mac with Xcode (`xcrun xctrace`) and a booted iOS Simulator for real captures. The logic can be exercised with made-up traces and no Xcode.**

**How a run is made:**
1. **Capture** (`capture_ios.py`, `xctrace.py`):
   - Finds a booted simulator.
   - Refuses a Debug build, which has no `main.jsbundle`, and refuses while Instruments or another `xctrace record` is running.
   - Stops the app, then records a launch with `xctrace record --launch`, using the os_signpost, os_log, Hangs (100 ms threshold) and dyld Activity instruments.
   - Samples the app's memory every 100 ms from the Mac.
   - Keeps the `.trace` bundle, the converted `.pftrace` and a `.convert.json` under `traces/ios/`.
   - Warm captures are refused. The default length is 12 s.
   - A recording is rejected if it has no process, an xctrace error, neither a first frame nor any markers, or an instrumented app without its signposts. A crash is kept as a result.
2. **Convert** (`convert_ios.py`) writes a Perfetto trace:
   - The process is named after the bundle id.
   - Signpost spans become slices. Screen and navigation markers become async slices. Events become instants, and counters and memory become counters.
   - Launch phases become steps: pre_main, main_to_first_frame (or to_first_frame) and first_frame_to_responsive, with the dyld work nested under them.
   - Hangs and error records are written into the trace.
   - A provenance marker records the platform, simulator, device, iOS version, xctrace version and whether the app crashed.
3. **Extract.** The platform comes from the provenance, and iOS runs use their own derived steps. **Simulator runs:**
   - no North Star targets
   - the verdict is capped at warn, and a pass shows as STEADY
   - frames are "not measured"
   - they can't be pinned as a benchmark
   - triage skips them
   - they are marked "indicative only"
4. **Everything downstream keeps platforms apart:** baselines, benchmarks, compare, catalogue, Copilot and the dashboard lanes.

**Where you see it:**
- **CLI:**
  - `swagperf capture --platform ios --device "iPhone 17" --pkg com.cambench.compose.ios`
  - `stress run --platform ios`
  - `apps … --platform`
  - `analyse recording.trace --app <bundle>`, which converts first
  - `swagperf ios devices|toc|convert`
- **API:** `GET /api/device?platform=ios`. The capture and stress POSTs take `platform`, and manual sessions and audits on iOS return 409.
- **Dashboard:** "Instruments · iOS" in the top bar, and pages under `/ios/*`.
  - The Capture page shows "No iOS Simulator booted", a Mac status line, and a Debug-build refusal.
  - The Frames page shows "Not measured on the iOS Simulator".
  - History disables Pin for simulator runs.
  - Run details adds a Mac section and build rows.

**Android is affected too:**
- The critical-path guard and "not measured" frame times described in [section 1](#1-analysis-pipeline).
- `analyse` baselines are now scoped by app, platform and simulator.

**Tests:**
- `tests/test_ios.py`, 41 tests, from real xctrace exports that were trimmed, and from made-up recordings.
- `frontend/src/app/routes.test.ts`, and the iOS cases in `runMeta`, `metrics` and `scope` tests.

## 15. Crashes & ANRs, and hangs on Frame pacing (F-014, F-028)

F-014 is committed in `d007f5a`. F-028 is committed in `58fe6fa`…`d21da60` (2026-09-25); its phone check (a real ANR and crashes on the V2514) is still open. Design: `docs/superpowers/specs/2026-09-25-crashes-anrs-tab-design.md`.

**Hangs** use Apple's definitions:
- A microhang is 100–250 ms and a hang is 250 ms or more.
- On iOS they come from the Hangs instrument. On Android they are top-level main-thread slices of 100 ms or more.
- Stalls before the first frame are counted separately.
- A rate per hour is given only for sessions of 60 s or more.
- Hangs are attributed to screens.

**JS errors:**
- The app marks each error in the trace as `error:js:<source>:<Name>#fatal|nonfatal@<id>`.
- The full record (message, stack, component stack) travels in the platform log in chunks: the SwagPerfError logcat tag on Android, and the `errors` os_log category on iOS.
- A record with a missing chunk is counted and shown as "only the marker arrived".
- Hermes stacks are resolved against the build's source map by a pure-Python equivalent of metro-symbolicate (`symbolicate.py`), checked against metro's own answers.
- A map from a different build is refused, never used to give wrong frames.
- A fingerprint groups the same crash site across builds and platforms.

**ANRs** (F-028, Android only):
- Android, not the app, declares an ANR. System_server then writes two atrace counters under the `am` category, `ErrorId:<process> <pid>#<id>` and `Subject(for ErrorId <id>):<subject>`. The trace processor's `android.anrs` module reads them.
- Each ANR has its type in plain words (e.g. "A touch or key went unanswered"), the system's reason line, the timeout behind it, the screen on display, and the longest main-thread slice in the window before it.
- An ANR of another app is never the app's. A trace recorded without the `am` category measured none, so it reads "not measured", never 0. iOS has no ANRs.

**Crashes** (every one in the run since F-028, each with its crash log):
- On iOS, from how xctrace saw the process end.
- On Android:
  - Kotlin/Java: AndroidRuntime's report, put back together (exception class, message, every frame).
  - Native: libc's `Fatal signal` line from the app, joined to the tombstone crash_dump writes from its own process. The tombstone's header (`pid: N, … >>> <pkg> <<<`) names the app.
  - Reports are matched by the package they name, so a restarted app's second crash counts and another app's never does.
- A trace whose recorded config has no `android.log` source measured none: "not measured", never 0. Run #1 (`traces/manual_b073b3b4500c.pftrace`) is one.

**Findings and triage:**
- A crash is high severity. An ANR is high severity too (F-028), so a run with one fails.
- A JS error is high if fatal, otherwise medium.
- Hangs after the first frame are high when the longest is 1 s or more.
- Triage opens `js_error:` signals, one `crash:<exception or signal>:…` signal per kind of crash, and one `anr:<type>:…` signal per kind of ANR. Runs recorded before F-028 keep `crash:app:…`. These signals link to Crashes & ANRs; they no longer get the ordering-violation advice (TESTING-PLAN S-02).

**Where you see it:**
- **Crashes & ANRs** (`/crashes`, `/ios/crashes`; `/stability` redirects there):
  - tiles for JS exceptions, ANRs and crashes against the previous run;
  - a per-run chart;
  - one list of every event in time order, with a filter (All, JS exceptions, ANRs, Crashes). Expanding a row shows the JS stack (resolved, raw and component), the ANR's reason and main-thread work, or the crash log;
  - a hint to register a source map.
- **Frame pacing** (`/frames`): the hang tiles, a hangs-per-run chart and the hangs table.
- **Other pages:** Compare gets stability rows, including ANRs and crashes.
- **API:** `GET /api/stability?run=N`, and stability on every run in `/api/history`.
- **CLI:** `swagperf maps add <map> --app <id> [--platform] (--bundle <jsbundle> | --build <n>)`, and `maps list`.

**Release archive** (F-030):
- **Swag Pay's release pipeline** builds both platforms at one commit, tags it `v1.2.0-42`, and attaches the Hermes bundles, composed maps, a manifest, the APK and the simulator app to a GitHub Release on the tag.
  - It runs on GitHub Actions (`release.yml`, Release → Run workflow) or on this Mac (`yarn release`). The Bash scripts are in `apps/mobile/scripts/release/`, and the app now uses Yarn classic.
  - A pull request touching the pipeline runs it as a dry run.
- `swagperf maps fetch --tag v1.2.0-42` (or `--all`) downloads a Release and registers its maps, and `maps import <folder>` does the same for a staged build. Each map is registered under its bundle's hash and under `build-<versionCode>`.
- A map is refused unless every file matches the manifest's sha256, the bundle carries the manifest's Hermes source hash, and the map has the bundle's function count.
- A run that recorded its bundle's hash (iOS) is matched by that hash alone. Local builds share a build number, so falling back to it could pick another build's map.
- `swagperf maps resolve` resolves JS errors without recording a trace. It takes pasted text: a Hermes stack, `adb logcat -d -v raw -s SwagPerfError` output, or the simulator's `log show` output. Pick the map with `--tag`, `--build`, `--hash` or `--map`. Records split across log lines are put back together first.
- **Demo error:** in Swag Pay a long-press on the Contacts title throws a non-fatal `TypeError`. On 2026-09-25 one from the release build on the iOS simulator resolved to `src/contactsDirectory.ts:166` (see the swag-pay release README).

**Tests:**
- `tests/test_stability.py`: F-028 adds ANR, crash, run-data, triage and demo-session tests, built on `swagperf/synth_stability.py`. The release-archive tests are F-030's.
- `frontend/src/domain/incidents.test.ts` and `frontend/src/app/routes.test.ts` (F-028).
- `tests/test_symbolicate.py`, 45 tests, checked against metro-symbolicate's own answers.

## 16. Designs on paper

- **NLP mobile automation in CI** 📝 `c16d23d`. [Plan](nlp-mobile-automation-ci-plan.html) and [ADR 0001](decisions/0001-nlp-mobile-automation-ci.md) (proposed).
  - A model compiles a test intent into versioned steps once.
  - Maestro then runs that frozen plan inside one Perfetto session.
  - The model never sees a raw trace.
- **Screenshot testing with Maestro (F-012)** 📝 parked on 2026-09-24. [Plan](screenshot-testing-plan.html) and the BACKLOG entry. Screenshots are taken at named checkpoints and compared with an approved baseline per app, cohort and device class, with approvals in the dashboard. The product-manager skill's parked-work queue says when to raise it again.
- **Backlog:**
  - F-003: widget-level TTI
  - F-004: an A/B measurement of graphify's savings
  - F-005: split onboarding into its nine steps
  - F-007: per-thread CPU from Perfetto (planned)
  - T-002: the navigation stack is replayed, not recorded
  - F-009 and F-010: app-side work in the `swag-pay` repo

---

## 17. AI run summary and trend (F-023, F-024, F-026)

✅ `d2feed5` (2026-09-25). Device: none.

- **AI summary (F-023).** A model's reading of one recorded run: a headline, three to five plain sentences, findings, and what it looked at and set aside.
  - **It never changes the verdict** (the user's answer to Q-S2). It is stored as its own kind of analysis row (`analyses.kind = 'summary'`); the run's verdict stays the newest `verdict` row, which is what triage, the Copilot and the release gates read. When the model reads the run differently, Overview says so beside the recorded verdict.
  - **Written from the database, never the trace.** `store.run_metrics` rebuilds what the analyst reads, so any run in history can be summarised, even with its trace gone.
  - **Where:** Overview's AI summary section (**Generate summary**, **Regenerate**); a **Write an AI summary** switch on Capture, Stress and Manual, off by default and remembered; `swagperf summary RUN [--json]`.
  - **When:** after the capture, once the device is free. A stress test writes one summary per session after the last cold start, so the model never runs between them. A summary job waits while any capture holds the device.
  - **Which model:** the `claude` CLI you're logged in to (or `SWAGPERF_CLAUDE_BIN`), then `ANTHROPIC_API_KEY`. The CLI runs with no tools, no MCP servers, no saved session, in an empty temporary directory. With no model session, nothing is written and the page says why.
  - **Checks:** every number in the model's text is checked against the run's data; numbers it can't find are listed in a warning. A summary is marked out of date when `reextract` writes a newer verdict.
- **Against the pinned benchmark (F-024).** When a benchmark is pinned for the run's app, start path and device, the summary compares the run with it: the model's sentences, plus the metric and step tables built from the data (`store.compare`). The comparison is stored with the summary, so it stays true to the text if the pin later moves. None for a simulator run or the benchmark itself.
- **Trend (F-026).** `/trend` and `GET /api/trend?app=&path=&platform=`.
  - The top bar's App and Path choose the scope; its Version, Run and Range don't apply and are hidden.
  - Pick up to 3 devices (each keeps its colour while picked), the metrics (startup time, janky and slow frames, peak RAM usage, RAM growth) and any launch steps. One chart per metric.
  - x is the app version, oldest first: by build number when every version has one, else by name with numbers compared as numbers. A point is the median of that version's runs on that device; a gap is a version with no measurement. Runs with no app version are counted, not plotted.
  - Each device's pinned benchmark is a dotted line in its colour, named in a key under the plot; the North Star target is the dashed line, where one applies.
  - Built from every run of the scope, not the newest 100 that `/api/history` holds. Scopes never mix apps, start paths or platforms; a simulator is its own device with no benchmark and no targets; a device measured both ways gets two startup lines.
  - 3 devices, not 4: the dataviz validator puts `--c4` too close to `--c2` to tell apart (T-006).
- **Server access (T-001).** See [section 8](#8-dashboard).
- **B-010 interim guard.** `budgets.startup_target` is the one rule for a run's startup target. A derived startup of our own instrumented app (Android's first frame, before the camera's) has none, and Startup, Overview, Screens, the CLI and the Copilot say why.

## Design rules

These hold across the whole tool. A change that breaks one is a bug.

1. **Measurement is deterministic; judgement is not.** The model never sees a raw trace, and a test enforces this.
2. **Never apply Swag Pay's North Star targets to another app.** A derived run gets no invented North Star target. The 60 fps frame deadline applies to every app. 🚧 A simulator run gets no North Star targets at all.
3. **An empty capture is never a pass.** A trace that lost kernel tracing is never recorded.
4. **Unmeasured is not zero.** No frames, a 0 ms startup, a missing process or 🚧 missing scheduler data all read "not measured".
5. **Scope everything by app,** and 🚧 by platform and simulator. Benchmarks never cross apps or platforms.
6. **Two startup paths, two North Star targets.**
7. **Compare describes; a benchmark decides what "regressed" means.**
8. **Status is never colour alone.** It always has a symbol (✓ ! ✕ ▲ ▼ =). A metric warns within 10% of its North Star target, and moves under 5 ms are not coloured.
9. **Links land on the thing they name.**
10. **Say "RAM usage" and "RAM growth"** in anything a reader sees. The `rss` names stay in code keys.
11. **Update the tracker in the same change.** Performance issues are opened only by the automatic review. The product-manager agent never closes an issue and never commits.
12. **One profiler at a time per device.** Flashlight's numbers are never compared with Perfetto's.
13. **Tracing never changes the app's behaviour.** Markers carry only fixed names and outcome classes.
14. **Pages are built only from the design system,** and every component is on `/design-system`.
15. **Every step has a plain-language description.**
16. **The dashboard listens on the loopback address only, and refuses other websites' pages** (loopback `Host` and `Origin`, `X-Swagperf: 1` on every write). Restart it after Python changes.

## Reference

**CLI** (`./.venv/bin/python -m swagperf.cli <cmd>`, or `./perfetto_init <cmd>`):
- **Analysing and viewing:** `analyse`, `screens`, `dashboard`, `list`, `compare`, `benchmark set|clear|list`.
- **Recording (needs a device):** `capture`, `manual start|stop|status|abort`, `stress run|list|show`, `audit run|list|show`.
- **Data:** `seed`, `reextract`, `reset`, `apps list|add|remove|discover`.
- **Tracker:** `triage`, `pm status|review`.
- 🚧 **New today:** `ios devices|toc|convert`, `maps add|list`.

**API routes.**
- **GET:**
  - `/api/history`, `/api/compare`, `/api/tokens`
  - `/api/device` (🚧 `?platform=`)
  - `/api/manual/status`, `/api/manual/live`
  - `/api/screens`, `/api/run/meta`
  - `/api/copilot/threads`, `/api/copilot/pins`
  - `/api/audits`, `/api/stress`, `/api/jobs`
  - 🚧 `/api/stability`
- **POST:**
  - `/api/copilot/ask` (streamed), `/pin`, `/unpin`, `/feedback`
  - `/api/benchmark/set|clear`
  - `/api/manual/start|stop|abort`
  - `/api/stress/start`, `/api/capture/start`, `/api/audit/start`

**Settings.**
- `SWAGPERF_DB`: which history file to use.
- `SWAGPERF_APPS`: which local app catalogue to use.
- `SWAGPERF_BACKEND` and `SWAGPERF_MODEL`: the analyst. `ANTHROPIC_API_KEY`, for the API backend only.
- `SWAGPERF_PM_AUTOTRIAGE`, `SWAGPERF_PM_MODEL`, `SWAGPERF_PM_TRACKER`, `SWAGPERF_PM_STATE`: the automatic review.
- `SWAGPERF_DASHBOARD_URL`, `SWAGPERF_CLAUDE_BIN`, `SWAGPERF_CODEX_BIN`, `SWAGPERF_PORT` (the launcher), `SWAGPERF_RUN_DIR` (the run skill).
- `.env` is read at start and never overrides a variable that is already set.

## Known gaps and open items

- **Open bugs:**
  - B-001: the verdict headline has no units.
  - B-002: the Peak RAM tile shows green while its gate fails.
  - B-003: a baseline can include later runs and mix start paths.
  - B-005: seeded runs have no app.
  - B-007: `triage --mark` can't move the marker back after a reset.
  - B-008: `triage` never reports a step-based issue as quiet.
- **Tech debt and security:**
  - T-004: the frame deadline is fixed at 60 Hz.
- **Performance issues in Swag Pay:**
  - P-001 janky frames, P-002 peak RAM usage, P-003 RAM growth, P-004 activity_create regression.
  - All are awaiting review.
- **Features in progress:**
  - F-006: Flashlight lane, not yet run on a phone end to end.
  - F-009 and F-010: app-side.
  - F-013 (iOS) and F-014 (stability), both uncommitted.
- **Planned:** F-001 (Copilot on Claude or Codex), F-007 (per-thread CPU from Perfetto).
- **Parked:** F-012.
- **Not supported yet:**
  - iOS on a real iPhone; the lane is simulator-first.
  - Frame attribution is per screen, not per surface.
  - Trailing baselines are not split by device.
  - Copilot is rule-based.
  - The dashboard has no login.
  - There is no CI.

## Commit timeline

| Commit | Date | Change |
|---|---|---|
| `84e4b02` | 09-22 | Perfetto regression monitor for the Swag Pay shell: extraction, history, analyst, North Star targets, CLI, first dashboard, made-up traces, tests |
| `88ba98d` | 09-22 | Run comparison and pinned benchmark runs |
| `377aa0d` | 09-22 | Any Android app through derived steps, plus a competitor catalogue |
| `c817bb8` | 09-22 | Stop tracking `apps.local.json` |
| `e67cc03` | 09-22 | Capture from the dashboard, app scoping, real-device capture fixes |
| `7ddf1b9` | 09-22 | Stress tests |
| `d4b18b3` | 09-22 | Manual tracing and per-screen CPU and RAM usage |
| `cead9cf`, `4ad15d9` | 09-22 | `perfetto_init` launcher and the `perfetto` alias |
| `e4c67be`…`2142245` | 09-22 | Screens fixes, screen kinds, navigation stack, live markers endpoint, "RAM usage" wording, token monitor |
| `a792525` | 09-23 | Device-trace accuracy: RAM usage and frames scoped to the app, honest verdicts |
| `feb61cc` | 09-23 | Manual trace config slimmed from about 230 to about 53 MB per minute |
| `db78f77` | 09-23 | Screens: session timeline, per-screen app jank, transition costs, cache |
| `f190cda` | 09-23 | Live markers read incrementally |
| `7c09021` | 09-23 | Device-shaped made-up traces; no borrowing another app's markers |
| `51f403f`…`b46f5fe` | 09-23 | Dashboard rebuilt in React + TypeScript, every page |
| `04c2129`, `a7e66df` | 09-23 | Copilot engine, API and panel; the design system |
| `38f56cd` | 09-23 | Old dashboard removed; static paths confined to the build |
| `c16d23d` | 09-23 | NLP mobile automation in CI: plan and ADR 0001 |
| `8d997d8` | 09-23 | README: quick start and what to watch on each page |
| `d43fe8a` | 09-23 | Each run records its device, device state and app build |
| `ff18ada` | 09-23 | One run in view: Run picker, run box, Run details |
| `7d36827` | 09-23 | Reset command, Version filter, sortable Run list |
| `7cddefc` | 09-23 | Tracker, product-manager agent and automatic run review |
| `2e6ce6e` | 09-23 | Flashlight and Perfetto on one device: tested and ruled out |
| `e9d7162` | 09-23 | Flashlight lane, the one-profiler guard, step and thread descriptions |
| `9ca753a` | 09-24 | Pages built only from the design system (T-003) |
| `1d6b4fb` | 09-24 | Run skill |
| `0083bc9` | 09-24 | Maestro screenshot testing parked; one product-manager skill for every agent |
