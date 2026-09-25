# Testing plan: changes of 2026-09-24

This plan covers everything that changed in swagperf on 2026-09-24: three commits, plus the iOS and stability work that is built but not yet committed. What each change does is described in [FEATURES.md](FEATURES.md). Record bugs you find in [TRACKER.md](TRACKER.md).

- **Written.** 2026-09-24, about 13:30 IST. Other sessions were still editing the iOS and stability code. Check `git status` before you start, and re-read a section if its files changed.
- **Filling it in.** Each test has an ID, a check, how to run it, the expected result, the environment it needs and a priority. Write ✓ or ✗ in the Result column, with a note when something fails.
- **Priority.** **Must** blocks the change from shipping. **Should** needs fixing or a tracker row before sign-off.

## 1. Scope

| Change | State | Risk | Environments | Section |
|---|---|---|---|---|
| T-003: pages built only from the design system | committed `1be77cc` | Medium. Every page was touched, and the charts were redrawn. | E0 | [4.1](#41-t-003-pages-built-only-from-the-design-system-1be77cc) |
| Run skill | committed `b6e429d` | Low. Agent tooling only. | E0 | [4.2](#42-run-skill-b6e429d) |
| F-012 parked; one product-manager skill | committed `8b27552` (local) | Low. Docs and agent setup only. | E0 | [4.3](#43-shared-product-manager-skill-and-f-012-8b27552) |
| F-013: iOS lane | uncommitted | **High.** It touches extraction, storage, triage, Copilot, the server and every dashboard page, and changes Android behaviour too. | E0, E2, E1 | [4.4](#44-f-013-ios-lane-uncommitted) |
| B-006: per-screen CPU "not measured" | uncommitted | Medium | E0 | [4.5](#45-b-006-per-screen-cpu-not-measured-uncommitted) |
| F-014: hangs, JS errors, crashes | uncommitted, still being written | **High.** It adds a new store schema, a new page and new triage signals. | E0, E1, E2 | [4.6](#46-f-014-stability-uncommitted-still-being-written) |
| T-004: 60 Hz frame deadline | planned, no code | none | — | [4.7](#47-t-004-no-code-change) |
| Tracker: review after the reset, B-007, B-008 | docs | Low | E0 | [4.8](#48-tracker-and-the-automatic-review) |
| Existing features, because shared code changed | — | Medium | E1 | [5](#5-regression-pass-on-existing-android-features) |

## 2. Environments and ground rules

| Env | What it is | Needed for |
|---|---|---|
| **E0** | This repo on a Mac with no phone and no Xcode. Uses made-up traces and a scratch history. | Most tests |
| **E1** | An Android phone with USB debugging on (the V2514 has been used so far). It needs Swag Pay built with its trace markers; for F-014, the build must also emit `error:js:` markers and SwagPerfError log records (app side, in the `swag-pay` repo). Also `npm ci --prefix flashlight` for audits. | Real captures, the regression pass, and Android stability |
| **E2** | A Mac with Xcode (`xcrun xctrace`) and a booted "iPhone 17" simulator. It needs a **Release** build of Swag Pay iOS (`com.cambench.compose.ios`, with the os_signpost wrapper) installed with `xcrun simctl install booted …`, plus a **Debug** build to test the refusal. | Real iOS captures |

**Ground rules:**
1. **Never test against the real `history.db`.** Use the run skill's scratch workspace, or set `SWAGPERF_DB` to a scratch file. The only exception is the migration test (IOS-M1), which uses **a copy**.
2. **Switch off the automatic review.** Export `SWAGPERF_PM_AUTOTRIAGE=0` and `SWAGPERF_BACKEND=heuristic` for everything except PM-02.
3. **Run the CLI from a scratch folder.** Traces written by `seed` land in the current folder, and `reset` always empties the repo's `traces/`. Don't run `reset` outside a scratch copy of the repo.
4. **Make sure the dashboard shows current code.** `web/dist` can lag behind `frontend/src`. Rebuild with `cd frontend && npm run build`, or use the run skill's `up --dev`. `driver.py up` warns when the build is stale.
5. **Wait for the code to settle.** Start when the other sessions have finished editing F-013 and F-014, or test a snapshot with `git stash` or a worktree. Several earlier suite failures were caused by files being edited mid-run.

Shortcut used below: `D` means `./.venv/bin/python .claude/skills/run-perfetto-monitor/driver.py`. Run it from the repo root.

## 3. Entry gate: automated checks

All of these must pass before manual testing starts.

| ID | Check | How | Expected | Priority | Result |
|---|---|---|---|---|---|
| G-01 | Python suite | `./.venv/bin/python -m unittest discover -s tests` | OK. There were 263 tests in the working tree at the time of writing, including `test_ios`, `test_stability` and `test_symbolicate`; the last clean run at `b6e429d` had 167. It takes about 3 minutes. Two `test_symbolicate` tests skip unless local release builds of Swag Pay exist. | Must | |
| G-02 | Frontend tests | `cd frontend && npm test` | All pass, including `routes.test.ts` and the iOS cases in `runMeta`, `metrics` and `scope`. | Must | |
| G-03 | Types and lint | `cd frontend && npm run typecheck && npm run lint` | Both exit 0. The lint rules forbid raw controls and inline styles in pages. | Must | |
| G-04 | Flashlight summary | `cd flashlight && node summary.test.js` | Prints `summary.test.js: ok` | Must | |
| G-05 | Build is current | `cd frontend && npm run build`, then `D up --fresh` | `up` prints no "web/dist is older" warning. | Must | |
| G-06 | Every Android and Flashlight page loads | `D tour` | "N/N pages clean", with no console, page or HTTP errors. **Read the PNGs** in `$TMPDIR/swagperf-run/shots/`. `tour` doesn't visit `/ios/*` (see RS-04). | Must | |

## 4. Test cases by change

### 4.1 T-003: pages built only from the design system (`1be77cc`)

This was a refactor: nothing should look or behave differently. Compare the pages against the previous build, or against the screenshots in `.claude/handoffs/design_handoff_swag_pay_performance/screenshots/`.

| ID | Check | How | Expected | Env | Priority | Result |
|---|---|---|---|---|---|---|
| DS-01 | Stress box plot (`DotBoxPlot`) | Needs a stress test in the history (E1 `stress run -n 10`, or seed through the store). Open `/stress`. | Dots, quartile box, median and outliers match the numbers in `stress show ID`. Compared with the previous test of the same app. | E0/E1 | Must | |
| DS-02 | Startup ordering timeline (`SpanTimeline`) | `D shot /startup --full` on the seeded regressed run, and on a run with an ordering violation (seed a first_run trace judged as returning_user). | Overlapping spans stay readable. The first-frame line is in the right place. A violation is marked. | E0 | Must | |
| DS-03 | Memory breakdown (`StackedBars` lg) | `D shot /memory` | Two bars (run in view against the benchmark or previous run), a runtime legend, and totals that match the tiles. | E0 | Must | |
| DS-04 | Expandable tables | `/screens?run=1` and `/steps`: open a row with the mouse and with the keyboard, sort by each column. | The row opens and closes, and the toggle says so. Sorting marks the column header. A cell's own control doesn't toggle the row. | E0 | Must | |
| DS-05 | Top-bar Run and Audit pickers | Open the picker, sort by every column, pick a run from the keyboard, and use "Follow the latest run". | The run in view changes on every page, and sorting keeps missing values last. | E0 | Must | |
| DS-06 | Capture app list (`ChoiceList`) | `/capture` with a phone connected, or check the list's behaviour on `/design-system`. | One Tab stop, arrow keys move the choice, a click picks. | E0/E1 | Should | |
| DS-07 | Navigation stack (`FlowList`) and Overview verdict strip (`StatusStrip`) | `/screens?run=1` and `/overview` | Stack order and transition times are unchanged. The strip outlines the run in view and marks the benchmark "B". | E0 | Should | |
| DS-08 | Both themes | `D tour` and `D tour --light` | No unreadable text, missing colours or invisible borders in either theme. Status colours differ from the KRAFTON red. | E0 | Must | |
| DS-09 | Design-system page | `D shot /design-system --full` | Every component renders with no console error. | E0 | Should | |
| DS-10 | Copilot highlight on the redrawn tables | Ask Copilot "which screen costs the most CPU?" on run 1, then click a Screens source. | The Screens page opens and rings the named row. | E0 | Should | |

### 4.2 Run skill (`b6e429d`)

| ID | Check | How | Expected | Env | Priority | Result |
|---|---|---|---|---|---|---|
| RS-01 | Isolation | Note the time `history.db` was last modified, and list `traces/` and `docs/issues/`. Run `D up --fresh`, `D tour`, the Copilot flow from SKILL.md, then `D down`. Check again. | `history.db`, `traces/` and `docs/` are unchanged. | E0 | Must | |
| RS-02 | Every command in SKILL.md | Follow SKILL.md line by line in a fresh shell. | Every block works as written. | E0 | Must | |
| RS-03 | Dev mode | `D down; D up --dev; D tour; D down` | Tour is clean against live source, and both ports are free afterwards. | E0 | Should | |
| RS-04 | Known gap: iOS pages | `D tour` | Doesn't visit `/ios/*`, because those routes are built in code, and seeds no iOS data. Until that's fixed, cover them with IOS-D*. Since `4e7ff5c` the demo session (#1) carries JS exceptions, an ANR and two crashes, so Crashes & ANRs and Frame pacing's hangs have data (`--run 1`). | E0 | Should | |

### 4.3 Shared product-manager skill and F-012 (`8b27552`)

| ID | Check | How | Expected | Env | Priority | Result |
|---|---|---|---|---|---|---|
| PM-01 | "What's next" uses the fixed template | Ask Claude Code, and separately Cursor, "what's next?" | A top five with open items only, then "Parked, revisit?" with exactly one F-012 line. | E0 | Should | |
| PM-02 | Automatic review still starts the agent | On a **scratch copy of the repo**, where the history file is the copy's own `history.db`: turn on `SWAGPERF_PM_AUTOTRIAGE`, then `analyse` a failing made-up run. | `swagperf pm status` shows a review. The agent reads `.agents/skills/product-manager/SKILL.md` and edits only the copy's `docs/`. | E0 | Should | |
| PM-03 | Pointers stay pointers | Read `.claude/agents/product-manager.md`, `.claude/skills/product-manager/SKILL.md` and `.cursor/skills/product-manager/SKILL.md`. | Each only points to `.agents/skills/product-manager/SKILL.md`. | E0 | Should | |

### 4.4 F-013: iOS lane (uncommitted)

**Made-up iOS data for E0.** Run this from a scratch folder, or use `D cli` so it lands in the run skill's history. The signature is as of writing; check `swagperf/synth_ios.py` if it changed.

```bash
./.venv/bin/python -c "from swagperf.synth_ios import gen_ios_trace; open('ios.pftrace','wb').write(gen_ios_trace(bundle_id='com.cambench.compose.ios')[0])"
D cli analyse <abs path>/ios.pftrace --app com.cambench.compose.ios --no-llm --no-review
```

Record it five or more times, so baselines exist.

#### Conversion, extraction and simulator rules (E0)

| ID | Check | How | Expected | Priority | Result |
|---|---|---|---|---|---|
| IOS-01 | Platform read from the trace | `analyse` a made-up iOS trace | The run is stored with `platform=ios` and `simulator=1`. The startup steps are pre_main, main_to_first_frame and first_frame_to_responsive, with dyld work nested under pre_main. | Must | |
| IOS-02 | Simulator verdict never FAIL | `analyse` a made-up simulator trace with a regression injected | The verdict is at most WARN, and the headline starts "Simulator run, indicative only". A clean run prints STEADY and "(simulator run: no budget applies)". | Must | |
| IOS-03 | No budgets on a simulator | `D shot /ios/startup` and `/ios/memory` | No budget line and no release gates. | Must | |
| IOS-04 | Frames not measured | `D shot /ios/frames` | "Not measured on the iOS Simulator", never 0%. | Must | |
| IOS-05 | Can't pin a simulator run | CLI `benchmark set <ios id>`; History page Pin; `POST /api/benchmark/set` (with `-H 'X-Swagperf: 1'`, which every POST needs since T-001) | The CLI prints an error and exits 2. The Pin button is disabled with a tooltip. The API returns 400. | Must | |
| IOS-06 | Triage skips simulator runs | `swagperf triage --json` (scratch history) | The simulator runs are listed in `skipped` with the reason "simulator run: indicative only, never judged". | Must | |
| IOS-07 | Instruments bundle converted by `analyse` | E2 recording: `analyse x.trace --app com.cambench.compose.ios`, and the same without `--app` | Converts, then records. Without `--app` it refuses clearly. | Should (E2) | |
| IOS-08 | `swagperf ios devices\|toc\|convert` | E2 | Lists simulators. `toc` prints the device, process and end reason. `convert -o` writes a `.pftrace` that `analyse` accepts. | Should (E2) | |

#### Keeping platforms apart (E0)

| ID | Check | How | Expected | Priority | Result |
|---|---|---|---|---|---|
| IOS-P1 | Lanes show only their own platform | History holds Android seed runs and iOS runs. Open each lane's App, Path, Version and Run pickers. | No iOS run appears in the Android lane, and the reverse. | Must | |
| IOS-P2 | Compare across platforms | `/compare?mode=run&a=<android>&b=<ios>` and `swagperf compare <android> <ios> --json` | Shows "Not comparable", with `same_platform: false`. | Must | |
| IOS-P3 | Baselines never mix | Record 5 Android and 5 iOS runs of the same step name, then regress one. | Regressions use only same-platform, same-simulator runs. | Must | |
| IOS-P4 | Same id on both platforms | `swagperf apps add com.swag.pay --platform ios --name "Test"` | The Android entry is unchanged, with its budgets. Removing the iOS entry doesn't touch Android. | Should | |
| IOS-P5 | Existing Android benchmarks still resolve | Pin an Android benchmark with the old code, switch to the new code, and open Overview. | The same benchmark is used, because Android scope keys are unchanged. | Must | |

#### Upgrading an existing history (E0, with a copy)

| ID | Check | How | Expected | Priority | Result |
|---|---|---|---|---|---|
| IOS-M1 | Old history opens and upgrades | `cp history.db /tmp/h-copy.db`, then `SWAGPERF_DB=/tmp/h-copy.db swagperf list` and the dashboard | Old runs read `platform=android`, `simulator=0`, `crashed=0`, with null stability columns. Nothing is lost, and ids are unchanged. | Must | |
| IOS-M2 | Upgrade is idempotent | Open the copy twice, and with two processes at once. | No error, no duplicate columns. | Should | |

#### Dashboard iOS lane (E0; rebuild first or use `up --dev`)

| ID | Check | How | Expected | Priority | Result |
|---|---|---|---|---|---|
| IOS-D1 | Every iOS page loads | `D shot` each of `/ios/overview`, `/ios/startup`, `/ios/frames`, `/ios/memory`, `/ios/steps`, `/ios/screens`, `/ios/capture`, `/ios/stress`, `/ios/compare`, `/ios/history`, `/ios/stability` | No console or HTTP errors. There's no `/ios/manual`. | Must | |
| IOS-D2 | Switching lanes keeps the page | From `/memory`, switch to Instruments · iOS. From `/manual`, switch to iOS. From Flashlight, switch to iOS. | Lands on `/ios/memory`, then `/ios/overview` (no manual page on iOS), then the iOS home. | Must | |
| IOS-D3 | A link to a run in the other lane | Open `/overview?run=<ios id>` | Redirects into the iOS lane with that run in view. | Must | |
| IOS-D4 | Simulator banner and STEADY | Open an iOS simulator run on Overview, History and the run box. | "Simulator run: indicative only" banner. A pass shows STEADY in the neutral colour. | Must | |
| IOS-D5 | Capture page without a simulator | `/ios/capture` with no simulator booted | "No iOS Simulator booted", a Retry detection button, and no Cold/Warm toggle. | Must | |
| IOS-D6 | Run details for an iOS run | Open Run details | The device reads "iPhone 17 · iOS … · Simulator on <chip>". There's a Mac section, and Build, JS bundle, iOS, Simulator, UDID and Instruments rows. Anything missing reads "not recorded". | Should | |
| IOS-D7 | Filters after switching lanes | Pick an Android app, visit iOS, then come back. | Note what happens. The App, Path and Version filters are shared, so the Android choice may be lost. Log it if that's confusing. | Should | |
| IOS-D8 | Copilot in the iOS lane | Ask "why did this run warn?" on an iOS run, and click a source. | The answer uses iOS runs only, and the source opens inside `/ios/*`. | Should | |

#### Server API (E0)

| ID | Check | How | Expected | Priority | Result |
|---|---|---|---|---|---|
| IOS-A1 | Device query by platform | `curl '…/api/device?platform=ios'`, `?platform=android`, `?platform=x` | iOS lists simulators, apps with their Release or Debug build, and the Mac's state. `x` returns 400. | Must | |
| IOS-A2 | Manual sessions and audits refused on iOS | `POST /api/manual/start` and `/api/audit/start` with `{"platform":"ios"}` and `-H 'X-Swagperf: 1'` | 409 with a clear message | Must | |
| IOS-A3 | Budgets per run in `/api/history` | `curl …/api/history` | Simulator runs have `ttid_budget_ms: null`. iOS runs take budgets only from the catalogue. | Must | |

#### Real capture on the simulator (E2)

| ID | Check | How | Expected | Priority | Result |
|---|---|---|---|---|---|
| IOS-C1 | Doctor | `./perfetto_init doctor` | Finds xctrace, the booted simulator, and each iOS app's build type. | Must | |
| IOS-C2 | Cold capture from the CLI | `./perfetto_init capture --platform ios --pkg com.cambench.compose.ios --analyse` | Writes `.trace`, `.pftrace` and `.convert.json` under `traces/ios/`, and records a run with steps, RAM usage and screens. | Must | |
| IOS-C3 | Capture from the dashboard | Instruments · iOS, then Capture, pick Swag Pay, then Profile. | The progress bar shows "Convert trace". The log streams xctrace progress. **View results** opens the run. | Must | |
| IOS-C4 | Debug build refused | Install the Debug build, then capture. | Refused with "Debug build, cannot be profiled". The Profile button is disabled in the dashboard. | Must | |
| IOS-C5 | Refused while Instruments is open | Open Instruments or run another `xctrace record`, then capture. | Refused, naming what is running. | Must | |
| IOS-C6 | Warm capture refused | CLI `--platform ios` without cold, and the stress API with `cold: false` | Refused clearly, or cold is implied (the CLI implies `--cold`). | Should | |
| IOS-C7 | iOS stress test | `./perfetto_init stress run --platform ios --pkg com.cambench.compose.ios -n 5` | Five sessions. The Stress page in the iOS lane shows it. The first launch after install is slower (about 1.8 s against about 0.5 s, from warm caches), so compare medians. | Should | |
| IOS-C8 | One lock for both platforms | Start an iOS capture, then try an Android capture or stress run (E1+E2). | The second is refused while the first runs. | Should | |
| IOS-C9 | Default package on iOS | `capture --platform ios` without `--pkg` | Note what happens. It defaults to `com.swag.pay`, which isn't installed on the simulator. The error should say so; if it's confusing, log it. | Should | |
| IOS-C10 | App crashes during launch | Use a build or flag that crashes at launch. | The crash should be a result: a run recorded with `crashed` set. **Suspected defect S-04:** the run may be rejected as having no slices instead. | Must | |
| IOS-C11 | Reset deletes iOS traces | On a scratch copy of the repo with iOS captures: `swagperf reset --yes` | `traces/ios/`, including the `.trace` folders, is gone, and the catalogue is kept. | Should | |

#### Android side effects of shared code (E0, then E1)

| ID | Check | How | Expected | Priority | Result |
|---|---|---|---|---|---|
| AND-01 | Incomplete critical path | Made-up Swag Pay trace missing `camera_open`: `analyse` it. On E1, capture with the camera permission denied. | TTID "not measured", with a note saying which steps are missing; not a shorter number. The run falls back to derived steps, and since B-010's interim guard (2026-09-25) its startup has no North Star target: Startup and Overview show the reason instead of a 420 ms line. | Must | |
| AND-02 | Zero frames | A trace with no frames (e.g. a trace with the app backgrounded) | Average and longest frame time are "not measured". Frames page, Compare and Copilot show "–" or "not measured", never 0 ms, and nothing crashes. | Must | |
| AND-03 | First-run path unchanged | `seed` first-run traces, or E1 onboarding | TTID is as before, and ordering violations are still caught. | Must | |
| AND-04 | Baselines scoped | `analyse` two apps with the same step names | Each app's regressions use only its own runs (the B-003 note). | Should | |

### 4.5 B-006: per-screen CPU "not measured" (uncommitted)

| ID | Check | How | Expected | Env | Priority | Result |
|---|---|---|---|---|---|---|
| SCR-01 | No scheduler data | `swagperf screens ios.pftrace` | The CPU column shows `-`. | E0 | Must | |
| SCR-02 | Screens page with no scheduler data | `D shot /ios/screens --full` | The CPU busy and CPU time columns show "–". The timeline shows only its RAM panel, and the stack-depth tiles don't show "0%". | E0 | Must | |
| SCR-03 | Android with scheduler data | `D shot /screens --run 1 --full` | CPU is still measured and shown, exactly as before. | E0 | Must | |
| SCR-04 | Sort by CPU with missing values | Sort the per-screen table by CPU busy, both ways. | Missing values stay last, and nothing throws. | E0 | Should | |
| SCR-05 | Old cache not reused | Open Screens for a run cached before the change. | It is recomputed (cache version 6), with no stale zeros. | E0 | Should | |
| SCR-06 | Copilot on CPU without scheduler data | On an iOS run, ask "which screen costs the most CPU?" | Says the trace has no scheduler data. It doesn't rank screens by zero. | E0 | Should | |
| SCR-07 | Android trace without `sched_switch` | Record on E1 with a config that has no sched, or build one by hand. | Same as SCR-01 and SCR-02. | E1 | Should | |

### 4.6 F-014: stability (uncommitted, still being written)

**Made-up data with a hang, a JS error and a crash (E0).** Check the `Recording` API in `swagperf/synth_ios.py` first; it was changing while this plan was written.

```bash
./.venv/bin/python -c "from swagperf.synth_ios import Recording; r=Recording(); r.launch(); r.async_slice('screen','screen:Home#compose',1300); r.hang(2000,300); r.js_error(2500, fatal=True); open('st.pftrace','wb').write(r.convert(end_ms=70000, crashed='SIGABRT')[0])"
```

| ID | Check | How | Expected | Env | Priority | Result |
|---|---|---|---|---|---|---|
| STB-01 | Findings from a made-up run | `analyse st.pftrace --app com.example.ios --no-llm --no-review` | Findings for the crash (high), the fatal JS error (high) and the hang. On the simulator the verdict is capped at WARN. | E0 | Must | |
| STB-02 | Hang classes | Made-up hangs of 90, 150, 260 and 1200 ms, after the first frame | Microhangs = 1 (150 ms), hangs = 2. The one under 100 ms is ignored. The longest is 1200 ms, which is high severity (≥ 1 s). | E0 | Must | |
| STB-03 | Stalls before the first frame | A hang before the first frame | Counted under startup, not in the post-launch hang count. | E0 | Must | |
| STB-04 | Hang rate only for long sessions | A 10 s session and a 70 s session | The 10 s session shows no rate. The 70 s session shows a rate per hour. | E0 | Should | |
| STB-05 | JS error record reassembly | A long stack split into chunks; one record with a chunk dropped | The complete record shows the full stack. The broken one shows "Only the marker arrived", and the incomplete count goes up. | E0 | Must | |
| STB-06 | Stack resolved with the right map | `swagperf maps add <map> --app <id> --platform ios --bundle <main.jsbundle>`, then open the error | The resolved frames match `metro-symbolicate`. The hint names the map. | E0/E2 | Must | |
| STB-07 | A map from another build | Register a map from a different build. | Nothing is resolved and it says why. Never wrong frames. | E0 | Must | |
| STB-08 | Stability API | `curl '…/api/stability?run=N'`, `?run=abc`, `?run=99999`, and a run recorded before F-014 | 200 with data; 400; 404; `{stability: null}`. | E0 | Must | |
| STB-09 | Stability page (superseded by CR-01–CR-03: the page is Crashes & ANRs since `5811c2c`, and hangs are on Frame pacing) | `D shot /stability --full` and `/ios/stability` on runs with and without stability data | Tiles with the change against the previous run, the chart per run, the hangs table, and the expandable JS error rows (resolved, raw and component stacks). An old run says "Not measured… run `swagperf reextract`". | E0 | Must | |
| STB-10 | Compare shows stability | `/compare` between a clean run and a crashed one | Rows for hangs, longest hang, JS errors and crashed, with the right direction arrows. | E0 | Should | |
| STB-11 | Triage signals | `triage --json` on a scratch history with an Android (not simulator) crash and a JS error | `crash:<exception or signal>:<app>:<path>` (since F-028; `crash:app:…` for runs recorded before), `anr:<type>:<app>:<path>` and `js_error:<Name>:<app>:<path>` keys. Their context links to Crashes & ANRs (S-02, fixed in `f1793f4`). | E0 | Must | |
| STB-12 | `reextract` fills stability | On a copy of an older history: `swagperf reextract` | Old runs gain stability data where their traces exist. | E0 | Should | |
| STB-13 | Real Android JS error | E1 with the instrumented build: trigger a fatal and a non-fatal JS error during a manual session. | Both appear, with screen, message and stack, and the fatal one is high severity. | E1 | Must | |
| STB-14 | Real Android crash | E1: force a Java crash, and a native crash. | `crashed` is set. **Check tombstone lines:** they come from `crash_dump`, whose process isn't the app's. Since F-028 (`1d51c1b`) a tombstone is read by its header (`>>> <pkg> <<<`), not by process, and joined to the app's `Fatal signal` line; CR-07 checks it on the phone. | E1 | Must | |
| STB-15 | Android hangs are real hangs | E1 cold capture of Swag Pay; compare the hang list with the trace in Perfetto UI. | Each "hang" is a real main-thread stall. **Suspected defect S-07:** the app's own long `step:` spans may be counted as hangs. | E1 | Must | |
| STB-16 | Log source cost | E1: capture size and stop time with and without the new Android log source | Size grows only slightly. `tracing_lost` still passes on a full capture. | E1 | Should | |
| STB-17 | History payload size | `curl -s …/api/history \| wc -c` on a history with 100 runs that have stability data | Note the size and the page load time. If Overview is slow to load, log it. | E0 | Should | |
| STB-18 | Real iOS crash and hang | E2: a build that hangs the main thread for 1 s, and one that crashes after launch | The hang is attributed to its screen. The crash is recorded (see IOS-C10). | E2 | Must | |

### 4.7 T-004: no code change

| ID | Check | How | Expected | Env | Priority | Result |
|---|---|---|---|---|---|---|
| T4-01 | Frames still judged at 60 Hz | Any Android run | The slow and janky thresholds are 16.67 ms and 50 ms, as before. The 90/120 Hz problem remains until T-004 is built. | E0 | Should | |

### 4.8 Tracker and the automatic review

| ID | Check | How | Expected | Env | Priority | Result |
|---|---|---|---|---|---|---|
| TRK-01 | B-007 repro | Scratch copy of the repo: `reset --yes`, record 2 runs, `triage --json`, `triage --mark 2` | Today: prints "reviewed through #81" and doesn't move the marker. After a fix: it moves to #2. | E0 | Should | |
| TRK-02 | B-008 repro | History where P-004's app and path ran without firing P-004 | Today: P-004 is missing from `quiet`. After a fix: it's listed. Note that a regression can't fire until the step has 5 runs of baseline, so right after a reset, "quiet" doesn't mean "fixed". | E0 | Should | |
| TRK-03 | Review after a reset | Scratch copy: reset, record a failing run with the automatic review on | The agent adds one reset note to each open issue, and the marker moves back to the new run. | E0 | Should | |

### 4.9 F-028: Crashes & ANRs (`a3428b4`…`4e7ff5c`)

JS exceptions, ANRs and crashes on one tab, and hangs on Frame pacing. Spec: `docs/superpowers/specs/2026-09-25-crashes-anrs-tab-design.md`. `D` is the run skill's driver. CR-01–CR-06 were run headless on 2026-09-25 against the seeded scratch data.

| ID | Check | How | Expected | Env | Priority | Result |
|---|---|---|---|---|---|---|
| CR-01 | Crashes & ANRs page | `D shot /crashes --run 1 --full` | Tiles: 2 JS exceptions ("1 fatal"), 1 ANR, 2 crashes (the first crash's exception as the note). One list of 5 events in time order: TypeError (Send), ANR (Store), RangeError, the JavascriptException crash and SIGSEGV (History), with Fatal pills. The source-map hint below. | E0 | Must | Pass, 2026-09-25 |
| CR-02 | A row opens to its detail | `D do "/crashes?run=1" "click:role=button[name*='A touch or key']" "shot:open"`, and the same for a crash row | The ANR shows its plain-words type, Android's timeout, the system's reason line and "The main thread was in binder transaction for 5,000 ms". A crash shows its crash log. | E0 | Must | Pass (ANR), 2026-09-25 |
| CR-03 | Hangs on Frame pacing | `D shot /frames --run 1 --full`, and a simulator run on `/ios/frames` | The hang tiles, the hangs table and (with more than one run) a hangs-per-run chart below the frame charts. On the simulator, frames read "not measured" and the hangs still show. | E0 | Must | Pass on Android, 2026-09-25; simulator not run. Note: the demo generator draws screen slices on the main thread, so #1 lists them as hangs; real traces don't (see S-07). |
| CR-04 | Old links land | `D eval "/stability?run=1" "location.pathname"`, and `/ios/stability` | `/crashes`, with the run kept; `/ios/crashes`. | E0 | Must | Pass (Android), 2026-09-25 |
| CR-05 | Compare rows | `D eval /compare` for rows named ANRs and Crashes | Rows for Hangs, JS exceptions, ANRs and Crashes. | E0 | Should | Pass, 2026-09-25 |
| CR-06 | Old runs and unmeasured traces | A run recorded before F-028 (no `anrs` in its stability), and a trace whose config has no `android.log` source (run #1's) | ANRs and crashes read "not measured", never 0. A pre-F-028 crash still shows one crash row. | E0 | Must | Covered by `incidents.test.ts` and `test_a_trace_without_the_log_source_measures_no_crashes`; not yet on a real old history. |
| CR-07 | Phone check | E1, one manual session of a debuggable Swag Pay on the V2514: freeze the main thread with `run-as com.swag.pay kill -STOP <pid>` and tap twice (ANR), `am crash com.swag.pay` (Kotlin/Java crash), `run-as com.swag.pay kill -SEGV <pid>` (native crash). Script and queries: Task 0 of `docs/superpowers/plans/2026-09-25-crashes-anrs-tab.md`. | One ANR with its type and reason; two crashes, one `java` and one `native` with the tombstone in its log. If `android_anrs` is empty after a real ANR, add the event-log fallback (the plan's Task 4). | E1 | Must | Not run: the phone was disconnected on 2026-09-25. |

## 5. Regression pass on existing Android features

Extraction, storage, triage, Copilot, the server and every page changed today, so run the main Android flows end to end once on a real phone (E1), against a scratch history. For a scratch history with the real dashboard: `SWAGPERF_DB=/tmp/h.db ./perfetto_init`.

| ID | Flow | Expected | Priority | Result |
|---|---|---|---|---|
| REG-01 | Cold capture of Swag Pay from the dashboard | Steps, TTID, frames, RAM usage and screens are all present, and Run details shows device, state and build. | Must | |
| REG-02 | Warm capture | Recorded as warm. No process_start step. | Must | |
| REG-03 | Competitor capture, e.g. PhonePe | Derived steps. No Swag Pay budgets on the Startup or Memory pages. | Must | |
| REG-04 | Manual session with live markers | The feed updates. Stop & analyse lands on Screens with the visits. | Must | |
| REG-05 | Stress test, 10 sessions | Spread, box plot, and a comparison with the previous test. | Must | |
| REG-06 | Flashlight audit | Audit A-n recorded. A Perfetto capture during the audit is refused. atrace is reset afterwards. | Must | |
| REG-07 | Capture while Flashlight runs (B-004) | Refused, naming the profiler. | Must | |
| REG-08 | Compare and benchmark | Pin, compare, unpin. Regressions follow the benchmark. | Must | |
| REG-09 | Copilot flows | Why, step, PR summary, stress noise, screens and frames questions; pin a finding. | Should | |
| REG-10 | CLI `analyse --fail-on` exit codes | 0 for pass, 1 for fail, 2 for an instrumented app without steps. | Should | |
| REG-11 | `reextract` on a copy of the real history | Completes. Verdicts are recomputed with rules, and model-analysed runs are listed as out of date. | Should | |

## 6. Suspected defects found while writing this plan

These come from reading the code, not from running it, except S-01. Confirm each with the test named. Then log it in the tracker, or ask the product-manager agent to.

| ID | Suspected defect | Confirm with | Status |
|---|---|---|---|
| S-01 | `triage` never reports a step-based issue (`regression:step:…`, `ordering:step:…`) as quiet. The uncommitted change compares `parts[2:-1]` of the key with the app. | TRK-02 | **Confirmed:** today's review returned `quiet: []` although P-004 didn't fire in run #1. Logged as **B-008**. |
| S-02 | Crash and JS error signals get the ordering-violation context: the wrong risk, the wrong next check, and a link to `/startup#order`. `triage._context` only knows budgets and regressions. | STB-11 | **Fixed** in `f1793f4` (F-028): crash, ANR and JS-error signals get their own next check and a Crashes & ANRs link; pinned by `test_android_anrs_and_crashes_are_stored_found_and_signalled`. |
| S-03 | An iOS run that isn't on the simulator is judged against Android's global budgets (320 MB peak RAM usage, 60 MB RAM growth, frames), in both `extract_any` and the frontend `METRICS`. This contradicts "no iOS budgets until iOS budgets exist". | Made-up `gen_ios_trace(simulator=False)` run, then check Overview gates | to confirm |
| S-04 | An iOS crash during launch may be rejected: `verify()` accepts it, but `capture_problems` treats "no slices from own process" as fatal. | IOS-C10 | to confirm |
| S-05 | "Longest hang" includes microhangs, so a run with 0 hangs can show a longest hang of 150 ms. | STB-02 | to confirm |
| S-06 | The Stability page labels any hang without a screen as "startup", even after the first frame. On an app without screen markers, every hang reads "startup". | STB-03 with no screen markers | to confirm |
| S-07 | On Android, any top-level main-thread slice of 100 ms or more counts as a hang, including the app's own `step:` spans. | STB-15 | Not seen in two real traces (2026-09-25): in run #1's manual trace and `com.swag.pay_cold_51eb344b38d5.pftrace`, `screen:`, `step:` and `action:` markers sit on async tracks, and neither has a false hang. The synthetic `gen_device_session` does draw screen slices on the main thread (CR-03). STB-15 still to run. |
| S-08 | `capture --platform ios` defaults `--pkg` to `com.swag.pay`. | IOS-C9 | to confirm |
| S-09 | Switching lanes loses the Android app filter. | IOS-D7 | to confirm |
| S-10 | `sourcemaps/` wasn't in `.gitignore`, so registered maps would show up in `git status`. | STB-06, then `git status` | **Fixed** in the working tree while this plan was written: `.gitignore` now lists `sourcemaps/`. |
| S-11 | An iOS stress test doesn't stream xctrace progress into its job log (`start_stress` passes no log callback). | IOS-C7 | to confirm |
| S-12 | `derive_ios_steps` looks up the app's process without the platform. It works only because the converter names the process after the bundle id. | code review | to confirm |
| S-13 | The run skill's `tour` skips `/ios/*` and seeds no iOS or stability data. | RS-04 | confirmed by reading; tooling gap. Stability data seeded since `4e7ff5c`; iOS still not. |
| S-14 | README says "154 tests". `tests/test_pipeline.py` has `unittest.main()` partway through, so running that file directly skips 56 tests; `discover` is unaffected. | read | confirmed by reading; docs and tooling |

## 7. Automated tests worth adding

The biggest gaps, ordered by how much risk they would remove:
1. **HTTP-level server tests.** No test sends a request today. Cover:
   - `/api/history`, `/api/stability`, `/api/device?platform=`
   - the 400, 404, 409 and 503 answers
   - benchmark set on a simulator run
   - the 409 for manual sessions on iOS
2. **`extract.tracing_lost` on real broken traces.** The experiment's traces in `experiments/flashlight-concurrency/results/` are ready-made cases.
3. **Jobs with a stubbed backend:**
   - `start_capture` and `start_stress` for both platforms
   - the iOS warm refusal
   - lock contention
4. **A render smoke test for each page.** vitest renders no page or shell today. A test that mounts each route with a fixed `/api/history` would catch most refactor breaks, the kind T-003 could cause.
5. **Stability page and lane switching,** in the frontend: TopBar lane switching, the AppShell `?run=` redirect, the simulator banner, and the Pin button disabled.
6. **Triage context for the new signal kinds, and the quiet check for step signals:** S-01 and S-02.
7. **Run skill:** tour the `/ios/*` routes and seed one iOS run and one run with stability data, so `tour` covers today's pages.
8. **Visual regression.** A screenshot baseline for each page would have covered DS-01 to DS-08 automatically. That's F-012, which is parked; this plan is evidence for its "Revisit when".
9. **CI.** There is none. The four commands in section 3 are the whole suite and run only when someone remembers.

## 8. Order of work and sign-off

1. Wait until the F-013 and F-014 edits settle, or test a snapshot.
2. Entry gate, section 3. Stop and fix anything red.
3. All E0 cases: 4.1–4.8 and the E0 rows of section 6.
4. E2: the IOS-C cases and STB-18.
5. E1: the section 5 regression pass, and STB-13 to STB-16.
6. Log every ✗ and every confirmed suspected defect in the tracker.

**Sign-off for each change:**
- Every **Must** row is ✓.
- Every **Should** row is ✓ or has a tracker row.
- The entry gate passes on the exact commit being shipped.

F-013 and F-014 should be committed only after their E0 Must rows pass. Their E1 and E2 Must rows decide when they move from in-progress to done.
