# swagperf

Perfetto trace regression monitor for the Swag Pay mobile shell.

Swag Pay runs **three runtimes in one process** — Compose/CMP, Hermes+Fabric, and the
native camera stack. This tool measures the performance constraints the shell
architecture actually states, tracks them per step across builds, and asks a model to
attribute any regression to a runtime and to a named architectural risk.

It is not a general trace viewer. Use the Perfetto UI for that.

- [Quick start](#quick-start)
- [The dashboard: what to monitor on each screen](#the-dashboard-what-to-monitor-on-each-screen)
- [Common workflows](#common-workflows)
- [Copilot](#copilot)
- [Command line](#command-line)
- [Frontend development](#frontend-development)

## Quick start

```bash
# 1. install (once)
cd ~/Documents/perfetto-monitor
python3 -m venv .venv && ./.venv/bin/pip install perfetto anthropic
ln -sf "$PWD/perfetto_init" ~/.local/bin/perfetto_init   # optional: puts the launcher on PATH

# 2. start the dashboard
perfetto_init                  # opens http://127.0.0.1:8787 (or: ./.venv/bin/python -m swagperf.cli dashboard)

# 3. connect an Android device with USB debugging on, then check it is seen
perfetto_init doctor
```

Then, in the dashboard:

1. **Capture** → pick the app → **Cold** → **Profile**. The run is traced, analysed
   and saved; **View results** opens it.
2. **Overview** shows its verdict against the budgets and the previous run.
3. When you have a run you trust, **History** → **Pin as benchmark**. Every later run
   of that app, path and device is judged against it.

No device? `./.venv/bin/python -m swagperf.cli seed -n 16 --regress-last` fills the
history with synthetic runs so every screen has something to show.

## Design

Measurement is deterministic; judgement is not. The split is deliberate:

```
trace ──▶ extract.py ──▶ metrics JSON ──▶ store.py (SQLite history)
          (SQL only)          │                    │
                              │                    ├──▶ regressions vs trailing baseline
                              │                    │
                              └──────▶ analyst.py ◀┘
                                       (LLM: attribution + verdict)
                                              │
                                              └──▶ dashboard / CI exit code
```

**The model never sees a raw trace.** It receives extracted metrics, trailing
baselines and the budget table. Measuring is SQL's job; the model's job is deciding
which runtime owns a regression and whether it deserves a human. A test asserts this
boundary holds.

## NLP automation architecture

- [Shareable architecture plan](docs/nlp-mobile-automation-ci-plan.html)
- [ADR 0001: NLP mobile automation in CI](docs/decisions/0001-nlp-mobile-automation-ci.md)
- [Flashlight + Perfetto observations and recommended path](docs/flashlight-perfetto-observations.html)
- [Reusable architecture skill](.cursor/skills/nlp-mobile-ci-architect/SKILL.md)

## What it measures

Each metric maps to a constraint or risk named in the shell architecture.

| Metric | Budget | Architectural basis |
|---|---|---|
| Time to initial display (TTID) — for Swag Pay, the first usable camera frame | 420 ms | *"Nothing before the first camera frame"* — the strongest decision on the board |
| Deferred-work ordering | hard fail | RN / Cronet / analytics / remote config must not run before the camera is usable |
| Slow / janky frames | 5% / 0.5% | Frame pacing at the CMP × RN interop seam |
| Thermal drift | 15% | Sustained-scan throttling on mid-range devices |
| Peak RAM usage | 320 MB | Three runtimes resident simultaneously |
| RAM growth | 60 MB | Orphaned RN surfaces — a Surface started and never stopped |
| Per-step duration | see `budgets.py` | Trailing-baseline regression per step |

**Two startup paths, two budgets.** A returning user puts the camera on the critical
path and defers Hermes. First-run inverts it — onboarding *is* an RN surface. Judging
one by the other's budget produces nonsense, so `--path-kind` is explicit and the
critical path differs per kind.

The startup, memory and thermal budgets are Swag Pay's own targets, so they apply
only to Swag Pay. Another app's run shows its numbers with no budget line (see
[Analysing any app](#analysing-any-app-and-the-competitor-catalogue)). The frame
budget (16.67 ms, 60 fps) applies to every app.

## The dashboard: what to monitor on each screen

### Finding your way around

- **Sidebar:** eleven screens in three groups. **Analyse** is for reading runs,
  **Run** is for making them, **Data** is for comparing and managing them. The
  `«` button collapses it to a rail of two-letter codes. It collapses by itself
  while the Copilot is open on a screen under 1400 px wide.
- **Top bar:** everything is filtered by **App** (package), **Path** (cold, warm,
  returning user, first run — whichever exist for that app) and **Range** (last 30
  runs, last 10 runs, last 7 days). The app, path and range are remembered.
- **Version** (top bar) narrows everything to one build of the app: its version
  name and build number (the Android `versionCode`), with how many runs each has.
  The Run list, the charts and the verdict strip then cover that build only;
  baselines still use every run, so a build is still compared with earlier ones.
  It appears once runs have recorded a version.
- **Run** (top bar) is the one place a run is chosen. It opens a table of the runs
  in scope (the selected version's, if one is picked): run, version, verdict,
  TTID, slow and janky frames, peak RAM and RAM growth, **sortable by any
  column**, so the slowest or heaviest run of a build is one click away. Pick a row
  and every screen shows that run; **Follow the latest run** goes back to
  following new runs as they land. Links that name a run (History's **Open**, a
  Copilot source, **View results** after a capture) set it here too. Changing the
  app, path or version goes back to that scope's latest run.
- **Run box** (top right of every screen): the run in view. It shows the run ID and
  verdict, whether it is the latest (**Older run · go to latest** when it is not),
  the device and Android version, and the app and its version and build number. It
  also shows when the run was recorded, its start path and what kind of run it
  was. **Run details** opens everything recorded about the run:
  - **App:** version, build number, git SHA, target/min SDK, debuggable, installer
    and install dates.
  - **Device:** manufacturer, model, Android and SDK, security patch, build ID and
    fingerprint, SoC, CPU cores, RAM, screen, refresh rate, kernel and serial.
  - **Device state:** battery, battery temperature, charging and thermal status,
    read before the capture.
  - **Trace:** file, size, length, Perfetto version.

  **Copy details** puts it on the clipboard for a bug report. A field that was not
  recorded says *not recorded*.
- **Page header:** the screen's name and what it is for.
- **Status is never colour alone.** ✓ pass, ! warn, ✕ fail. A metric warns within
  10% of its budget and fails over it. ▲ is worse, ▼ is better, = is unchanged.
  Moves under 5 ms on a step are treated as noise and are not coloured.
- **Links land on the thing they name.** A citation, "Inspect step" or a History
  row opens the screen, scrolls to the chart, row or finding, and rings it
  briefly.
- **Theme:** dark (the default) or light, from the top bar.

### At a glance

| Screen | Look here when… | The signal that matters |
|---|---|---|
| **Overview** | a new run lands | the verdict, any ✕ release gate, the worst regression |
| **Startup** | TTID moved, or deferred work is suspected | TTID trend against 420 ms; a step's share growing; ordering violations |
| **Frame pacing** | the app feels janky or hot | janky frames above 0.5%; thermal drift rising run over run |
| **Memory** | RAM is near 320 MB or growing | peak against budget; growth per run; Hermes heap |
| **Steps** | you need to know *which* step moved | Δ ms against the baseline; the child slice that moved inside it |
| **Screens** | the cost belongs to a screen or flow | RAM that steps up on the same screen and stays up; app jank per screen; slow transitions; deep stacks |
| **Capture** | you need a run | device health before profiling; the job log if it fails |
| **Stress** | one run is not proof | the spread of TTID; whether a shift is real or noise |
| **Manual** | the flow cannot be scripted | live markers arriving; the screen currently open |
| **Compare** | you need what changed between two builds | metrics and steps that got worse, and the child slices under them |
| **History** | managing runs and benchmarks | TTID over budget across runs; which benchmark is active |

### Overview

The latest run in scope, judged.

- **Verdict hero:** PASS, WARN or FAIL, the analyst's headline, and what the run
  was compared against: the pinned benchmark, or the previous run when none is
  pinned.
- **Worst regression:** the step that grew most (5 ms or more), its share of the
  TTID change, and three ways in: **Inspect step** (Steps, drill-down open),
  **Open in Compare**, **Ask Copilot why**.
- **Release gates:** every budgeted metric against its budget, as a bar.
- **KPI tiles:** TTID, slow frames, janky frames, peak RAM, RAM growth and
  thermal drift. Each shows its change against the baseline and a 12-run trend.
- **Verdict by run:** one cell per run in range, oldest to newest. The run in view
  is outlined and its numbers are shown under the strip. A "B" marks the benchmark.
- **Findings:** the analyst's findings, by severity, each with its evidence,
  recommendation and architectural risk. **Ask Copilot** explains one. Answers you
  pin from the Copilot appear here too, marked *Pinned from Copilot*.

**Watch for:** any ✕ gate, a high-severity finding, a worst regression that
accounts for most of the TTID change.

### Startup

How long launch took, and what it was spent on.

- **TTID over runs:** each run against the 420 ms budget, with this run's figure
  and its change.
- **Critical-path composition:** the last runs, each split into its startup steps.
  Time no step accounts for is left as a visible gap. It is not spread over the
  steps.
- **Ordering constraint:** deferred work (Hermes, Cronet, remote config…) against
  the first frame. Anything that starts before it is a violation. A derived run has
  no stated constraint and says so.
- **Startup findings:** the findings that concern launch.

**Watch for:** TTID creeping towards the budget over several runs, one step's
segment widening, any ordering violation.

### Frame pacing

- **Slow frames:** the share of frames over 16.67 ms, per run.
- **Janky frames:** the share over three frame budgets, the stutter a user sees.
- **Thermal drift:** mean frame time late in a run against early in it. It rises
  when the device throttles. A run that moved between screens shows a gap, because
  a change of screen, not heat, would move the number.

**Watch for:** janky frames above 0.5% (slow frames alone are often harmless),
thermal drift rising run after run on the same flow. To find *which* screen
stutters, go to **Screens**. Its per-screen *app jank* separates frames the app
was late with from compositor and display misses.

### Memory

- **Peak memory breakdown:** this run against the previous one, split by runtime
  when the trace records each runtime's own heap. When it does not, the screen shows
  the app total and says which counter is missing.
- **Peak RAM, RAM growth, Hermes heap:** one chart each, per run, with the 320 MB
  and 60 MB budgets for Swag Pay.
- **Where the growth happens:** links to Screens, which attributes growth to
  screens and to what was held open beneath them.

**Watch for:** peak over budget, RAM growth trending up, Hermes heap rising. Growth is
the orphaned-surface signature. Compare like with like: a long manual session peaks
higher than a 10 s capture simply because it runs longer.

### Steps

Every startup step of the latest run against its baseline: the pinned benchmark, or
the median of the previous 10 runs.

- **Table:** runtime, this run, baseline, Δ ms, Δ % and a 12-run trend. Sort by any
  column.
- **Drill-down** (select a row): P50 and P90 over recent runs, this run and the
  runtime, then every child slice as a bar for this run with a tick for its baseline.
  **Ask Copilot** from here names the step.

**Watch for:** a step with Δ ≥ 5 ms in the warn or fail colour, then the child
slice whose bar ends past its tick. That is the part of the step that moved.

### Screens

Per-screen cost for the run in view, read from the app's own `SwagTrace` markers
(see [Per-screen CPU and RAM](#per-screen-cpu-and-ram)). Only a run with a trace has
screens; for one without, the screen offers the latest run that has one. Manual
sessions are the richest.

**Screen usage** view:

- **Per-screen cost:** each screen's runtime (Compose, React Native, native view),
  stack depth, visits, CPU busy share, CPU time, peak RAM, RAM growth, app jank and
  time on screen. Select a screen to chart each visit separately.
- **Session timeline:** the app's RAM and CPU over the whole session, with each
  screen visit as a band behind it.
- **Navigation stack:** screens in visit order with how long each transition took
  to draw.
- **User actions:** every action the app marked, in order, with its screen.
- **Cost by stack depth:** peak RAM grouped by how many screens were open beneath.

**Launch metrics** view: TTID and the startup steps from the same trace.

**Watch for:** RAM that steps up on the same screen each visit and never comes back
down (look at the timeline first). Also a visit drawn in red, more than two standard
deviations from that screen's mean; high app jank on one screen; a slow transition;
a cheap screen with high RAM at depth 2+ (the memory belongs to the screens beneath).

### Capture

Profile an app on the connected device.

- **Device:** model, Android version, serial, battery, battery temperature and the
  on-device Perfetto version. A hot or low device skews results, so check this
  first.
- **Installed packages:** the device's apps, catalogue apps first, searchable.
- **Start** (cold force-stops the app first, warm does not) and **Duration**
  (5, 10 or 20 s), then **Profile**.
- **Job:** stages (Connect device → Launch → Record → Pull trace → Analyse), a
  progress bar and the live log. The result shows the new run's verdict and
  **View results**.

A capture that contains nothing from the target app fails loudly instead of saving a
flawless-looking empty run.

### Stress

One cold start is a noisy measurement. A stress test captures N cold starts back to
back.

- **Run:** pick the app and the number of cold starts (more is steadier: 10 or more
  for a decision).
- **Stress-test history:** every test with its sessions, median and spread. Select
  one to plot it.
- **TTID distribution:** the selected test against the previous completed test of
  the same app: each session as a dot, the box as the middle half, the median line
  and the budget. The shift between them is called **real** only when it is
  statistically significant (Mann–Whitney, p < 0.05) *and* larger than the earlier
  test's own spread; otherwise it is noise.

**Watch for:** a wide spread (a single capture of that app is not reproducible, so
compare medians), and whether a suspected regression survives as *real*.

### Manual

Drive the app by hand while it is traced: payments, biometrics, OTP onboarding.

- **Start** (cold or warm) → use the app → **Stop & analyse**, or **Abort** to
  discard. The clock shows elapsed time. Recording survives a page reload.
- **Live markers:** screens, actions, navigations and steps as the app emits them,
  newest first, filterable by kind. The screen on display now is marked open.
- The result links to the run. Its screens are on **Screens**, its launch on
  **Screens → Launch metrics**.

**Watch for:** markers arriving as you move through the app. If none arrive, the
build is not emitting them. Check it is the instrumented build, and remember that
a flow that never reached a screen emits nothing for it.

### Compare

- **Run A** is the run in view (change it with **Run** in the top bar). Compare it
  **against the benchmark** (default) or **with another run** (pick Run B: any run
  of the app, across paths).
- **Banners:** *Same run*, *Different devices* (compare with care), *Not comparable*
  (different app or path: different critical paths and budgets).
- **Top-line metrics:** each metric in both runs with Δ, Δ % and ▲ worse / ▼ better.
- **Steps diff:** every step with its child slices indented under it, including steps
  only one run has.

**Watch for:** the metrics and steps marked ▲ worse, and which child slices under
them moved.

### History

- **Runs:** every run of the app, searchable (run, label, device, build), filterable
  by verdict, sortable on any column. TTID over budget is shown in the fail colour.
- **Per row:** **Open** (puts the run in view on every screen, and opens Overview),
  **Compare** (with the run in view), **Pin as benchmark**. The run in view is
  highlighted.
- **Pinned benchmarks:** one per app, path and device. Regressions are measured
  against the active one. Unpin or compare from here.

## Common workflows

**Is this PR a regression?**
1. Install the PR build. **Capture** → cold → Profile.
2. **Overview:** read the verdict and the worst regression.
3. **Steps:** find the step and the child slice that moved.
4. **Stress:** run 10 cold starts on the benchmark build, then 10 on the PR build.
   The second test is plotted against the first. Treat it as a regression only if
   the shift is *real*.
5. **Copilot:** "Summarise this run for a PR comment" gives a paste-ready summary.

**RAM is high or growing**
1. **Memory:** is it the peak or the growth, and is Hermes heap part of it?
2. **Manual:** record the flow that grows. **Screens:** read the session timeline for
   a step up that never comes down, then the navigation stack for what was held open
   beneath it.

**The app stutters**
1. **Frame pacing:** janky frames, and whether thermal drift rises.
2. **Screens:** app jank per screen, and the transitions that were slow to draw.

**Benchmark a competitor**
1. **Capture** the competitor's package (cold, several runs or a **Stress** test).
2. Switch **App** in the top bar. Every screen scopes to it. No Swag Pay budget is
   applied to it.

**Look back at an older run**
1. Pick it in **Run** (top bar), or **Open** it from **History**. To find the worst
   run of a build, pick the build in **Version**, open **Run** and sort by TTID
   or Peak RAM.
2. Every screen now shows it. The run box says it is an older run, and
   **Run details** shows the device and app build it was measured on.

**Establish a baseline for a device**
1. Capture several cold starts of a known-good build on that device.
2. **History** → **Pin as benchmark** on a representative run. Later runs on that
   device and path are judged against it.

## Copilot

Press **⌘K** (Ctrl+K), or the **Ask** button, on any screen.

- **Ask** in plain words: why a run failed, which step grew, whether a regression is
  real (it reads the stress tests), how peak RAM moved across builds, when TTID first
  went over budget, which screen uses the most CPU or grows RAM, what changed
  between two runs, or a finding explained. **Suggested for {screen}** offers
  questions that fit the screen you are on.
- **Context** chips show what the question is about: the current screen, the run in
  view, its benchmark. Add runs, steps or findings with **+ Add**, or type **@** to
  reference one.
- **Answers** show the steps taken, a verdict, tables and charts, and **Sources**.
  Clicking a source opens that screen and rings the item.
- **Under each answer:** Copy (Markdown), Open in Compare, **Pin as finding** (it
  appears on Overview for that run), Export .md, and 👍 / 👎.
- **Deep analysis** also cross-checks the answer against the stress tests.
- **History** (clock icon) reopens past conversations. **New chat** starts over.
  **Stop** cancels an answer, and nothing half-finished is saved.
- Drag the panel's left edge to resize it, or maximise it. On a phone it takes the
  whole screen. Esc closes it.

**How it answers:** today the answers are computed by rules over the run history
(`swagperf/copilot.py`), not by a language model. Every number comes from the data,
and a run that is not in the history gets "no data", never a guess. A model-backed
engine can replace `answer()` there without the panel changing. Conversations,
feedback and pinned answers are stored in `history.db`.

## Install

```bash
cd ~/Documents/perfetto-monitor
python3 -m venv .venv && ./.venv/bin/pip install perfetto anthropic
ln -sf "$PWD/perfetto_init" ~/.local/bin/perfetto_init   # optional, puts it on PATH
ln -sf "$PWD/perfetto" ~/.local/bin/perfetto             # optional, shorter alias
```

`trace_processor_shell` downloads automatically on first run. The dashboard is
prebuilt in `web/dist`, so running it needs no Node. Node is only needed to change
the frontend (see [Frontend development](#frontend-development)).

### perfetto_init

A launcher so you do not have to remember the venv path or `cd` anywhere:

All three of these are the same command:

```bash
perfetto_init                  # start the dashboard on :8787
perfetto                       # shorter alias
perfetto init                  # also accepted
perfetto_init -p 9000          # another port
perfetto_init stop             # stop it
perfetto_init doctor           # device, deps, tracing state, history size
perfetto_init --help
```

Anything that is a swagperf subcommand passes straight through:

```bash
perfetto_init capture --pkg com.phonepe.app --cold --analyse
perfetto_init stress run --pkg com.swagpay -n 10
perfetto_init manual start --pkg com.swagpay --cold
perfetto_init screens traces/session.pftrace
```

It resolves the project root from the script's own location, following
symlinks, so it works from any working directory — without that the dashboard
cannot find `web/` or `history.db` and every relative trace path breaks. Known
subcommands are detected by asking the CLI's own parser rather than from a
hardcoded list, so a new swagperf subcommand works without editing the script.

After pulling changes to the Python side (`swagperf/`), restart the dashboard
(`perfetto_init stop && perfetto_init`): the server does not reload itself.

## Command line

```bash
# analyse a trace and record it
./.venv/bin/python -m swagperf.cli analyse traces/run.pftrace \
    --label "PR-4821" --git-sha $(git rev-parse --short HEAD) \
    --app-version 2.3.1 --device pixel7

# capture from a connected device, then analyse
./.venv/bin/python -m swagperf.cli capture --pkg com.swagpay --duration-ms 12000 --analyse

# first-run startup path
./.venv/bin/python -m swagperf.cli analyse traces/cold.pftrace --path-kind first_run

# dashboard
./.venv/bin/python -m swagperf.cli dashboard      # http://127.0.0.1:8787
./.venv/bin/python -m swagperf.cli dashboard -p 9000 --no-open

# compare two runs (base defaults to the pinned benchmark)
./.venv/bin/python -m swagperf.cli compare 19 11
./.venv/bin/python -m swagperf.cli compare 19            # vs benchmark

# pin a known-good run as the benchmark for its path + device
./.venv/bin/python -m swagperf.cli benchmark set 11 --note "known-good 2.2.0"
./.venv/bin/python -m swagperf.cli benchmark list
./.venv/bin/python -m swagperf.cli benchmark clear --run 11

# stress test, manual session, per-screen report (see their sections below)
./.venv/bin/python -m swagperf.cli stress run --pkg com.swagpay -n 10
./.venv/bin/python -m swagperf.cli manual start --pkg com.swagpay --cold
./.venv/bin/python -m swagperf.cli screens traces/session.pftrace

# delete every run, stress test, benchmark and Copilot conversation, and the
# trace files in traces/; run ids start again at #1. Asks you to type "delete".
# The app catalogue is kept, and so is any trace outside traces/.
./.venv/bin/python -m swagperf.cli reset            # or: perfetto_init reset
./.venv/bin/python -m swagperf.cli reset --keep-traces
./.venv/bin/python -m swagperf.cli reset --yes      # no prompt, for scripts

# recompute metrics for all runs whose traces still exist
# (run this after changing extract.py, or historical rows mix two formats)
./.venv/bin/python -m swagperf.cli reextract

# synthetic history, for development without a device
./.venv/bin/python -m swagperf.cli seed -n 16 --regress-last

# tests
./.venv/bin/python -m unittest discover -s tests
```

`analyse` exits non-zero on a `fail` verdict, so it drops into CI directly.
Use `--fail-on warn` to gate harder, `--fail-on never` to report only.

`SWAGPERF_DB=/path/to/other.db` points any command, including the dashboard, at a
different history, which is useful for experiments that should not touch the real one.

## Model backends

Tried in order, first one that works wins:

1. **`claude` CLI** — uses your Claude subscription. No API key. This is the default.
2. **Direct API** — set `ANTHROPIC_API_KEY` in `.env` (see `.env.example`). Useful on
   a CI machine where the CLI is not signed in.
3. **Deterministic rules** — no model at all. Always available, so the tool degrades
   rather than breaks.

Force one with `--backend cli|api|heuristic`.

## Benchmark and compare

These are deliberately different things:

**Compare** is a view. It diffs any two runs — top-line metrics, per-step durations,
and child slices under any step that got worse — and is purely descriptive. It does
not decide whether a change is a regression, because two runs have no variance to
reason about.

**Benchmark** is a pinned reference that changes what "regressed" means. Pin a
known-good run and every regression check for its scope compares against that run
instead of the trailing baseline, including the CLI exit code. One benchmark per
`(app, path_kind, device)` scope, so a returning-user benchmark is never applied to a
first-run trace and device classes stay apart.

Two consequences worth knowing:

- **A benchmark comparison has no variance**, so the z-score gate cannot apply and
  only a relative delta is used. That gate is therefore wider — `BENCH_MIN_DELTA_PCT`
  is 20% versus 8% for the trailing baseline — because a single clean run sits within
  roughly 15% of another clean run on the smaller steps. Without the wider gate,
  ordinary noise reads as a regression.
- **The benchmark run itself never regresses.** Pinning a run declares it the
  definition of acceptable for its scope, so its own regression list is empty and
  stays stable as later runs shift the trailing baseline.

Metrics that can legitimately be negative — thermal drift — report an absolute delta
only. A percentage change across zero is meaningless: −10.6% to +24.4% is not
"−330%", and the tool used to print exactly that.

A cross-path comparison is not blocked, but it is flagged prominently in both the CLI
and the dashboard, because the two startup paths have different critical paths and
different budgets so the numbers do not mean the same thing.

## Regression detection

A step is flagged only when it clears **both** gates against its own trailing
baseline (median of the last 20 runs):

- z-score ≥ 2.5, and
- relative delta ≥ 8%

Both are required because a step with very tight historical variance will produce a
large z-score from sub-millisecond noise. A baseline of fewer than 5 runs is not
trusted at all and nothing fires. A move under 5 ms never counts, whatever its
percentage.

A deferred step starting within 1 ms of the first-frame boundary is not an ordering
violation — it is a step legitimately starting *at* the boundary, and float rounding
can place it a hair early.

## Profiling from the dashboard

The **Capture** screen lists the apps installed on the connected device, merged with
the catalogue (known apps first). Pick one, choose cold or warm and a duration,
and press Profile. The capture runs server-side on a background thread; the page
polls and streams the log, then records the run and offers a link to it.

Two things this does not do, deliberately:

- **It does not assert Swag Pay's budgets against another app.** Startup and
  memory ceilings are our own product decisions. A derived run shows no budget
  line and no red breach unless the catalogue states a budget for that package.
  Frame budgets (16.67ms) are kept, since 60fps is an OS-level fact rather than
  a product target.
- **It does not report an empty capture as a pass.** A trace can pull and parse
  cleanly while containing nothing about the target app. `capture_problems()`
  checks whether the target package's own process contributed any slices at all;
  if not, the job fails loudly instead of recording a flawless-looking run of
  zero findings.

Runs are scoped by app throughout: the top bar's app selector filters every screen,
because plotting several different applications as one trend line is meaningless.

**What a run records about where it ran.** Each capture, stress session and manual
session reads the device over adb before it starts (at the end, for a manual
session): `getprop` for the device and its build, `/proc/meminfo`, `nproc`, `wm`
and `dumpsys display` for its hardware, `dumpsys battery` and `dumpsys
thermalservice` for its state, and `dumpsys package <pkg>` for the app's version
name, version code (the build number), SDK levels and install. Traces also record
the package list (`android.packages_list`), so a trace names the app build even
when analysed elsewhere. For a run recorded before this existed, the device's
build, SoC, kernel and Perfetto version are read from its trace the first time the
run is viewed, and kept (`GET /api/run/meta?id=N`).

### Known limits, found against a real device

Validated on a vivo V2514 (Android 16) against PhonePe, Google Pay, CRED and
others. Three things surfaced that are worth knowing:

- **The launch must not race the trace.** Perfetto is started with
  `--background-wait` so the trace is confirmed active before the app is
  force-stopped and launched. An earlier version ran both as concurrent `adb
  shell` sessions and consistently produced traces with zero slices for the
  target app, despite the app being confirmed in the foreground seconds later.
- **`launching:` slice width is not startup time.** For an app that never calls
  `reportFullyDrawn()`, that slice runs to a platform timeout — two captures
  both landed at almost exactly 3000ms. Startup is measured to the end of the
  last observed phase instead, which put the same app at 290ms.
- **Phase slices must be scoped to the target process.** On a busy device
  several apps launch at once; one real capture had `bindApplication` present
  simultaneously for the target app (255ms), another app (984ms) and a Google
  process (243ms). Matching on slice name alone would have measured whichever
  was slowest.

Apps with a lock or biometric prompt (payment apps especially) may still gate
their UI, but their startup phases remain measurable — PhonePe profiles fine.

## Stress tests

One cold start is a noisy measurement. Cache state, background work and thermal
condition all move it, so a single capture cannot tell a real regression from
ordinary variance. A stress test captures N cold starts back to back and reports
the **spread**, not an average:

```bash
./.venv/bin/python -m swagperf.cli stress run --pkg com.phonepe.app -n 10
./.venv/bin/python -m swagperf.cli stress list
./.venv/bin/python -m swagperf.cli stress show 3
```

Or from the dashboard's **Stress** screen: pick an app, choose a session count, run.

Three deliberate choices:

- **Each session is also an ordinary run.** Sessions are recorded in `runs` like
  any other capture, so the Steps, Memory and Compare screens work on them
  unchanged; `stress_tests` only groups them.
- **A failed session does not end the test.** Stopping would discard the
  sessions already captured, and a test with two failures out of ten is still
  informative. Failures are counted and shown; only an all-failed test errors.
- **Spread leads the summary.** `spread_pct` is max-over-min relative to the
  median. A wide spread means a single capture of that app is not reproducible
  and medians should be compared instead — the CLI says so explicitly above 25%.

Stress history is kept separate from run history, since a row there is a whole
test rather than one capture. A test left running when the server stopped is
marked interrupted at the next start rather than showing as running forever.

## Manual mode

Some flows cannot be scripted: a real payment, a biometric unlock, a specific
sequence of screens. Manual mode lets you drive the app by hand and control
tracing yourself.

```bash
./.venv/bin/python -m swagperf.cli manual start --pkg com.swagpay --cold
# ... use the app on the device ...
./.venv/bin/python -m swagperf.cli manual stop
./.venv/bin/python -m swagperf.cli manual status
./.venv/bin/python -m swagperf.cli manual abort    # discard without analysing
```

Or the dashboard's **Manual** screen: Start → use the app → Stop & analyse.

Tracing runs as a **detached** perfetto session (`--detach=KEY`, stopped with
`--attach=KEY --stop`), so it survives between HTTP requests and carries no
`duration_ms` at all. A long-but-finite duration would truncate a long session
and waste buffer on a short one. The buffer is a ring, so an over-long session
keeps the most recent data rather than failing.

A manual session may legitimately contain no launch — you might trace an
already-open app — so missing startup is reported as a note rather than treated
as a failed capture.

## Per-screen CPU and RAM

When the app emits `SwagTrace` markers (see the swag-pay repo), `screens.py`
attributes cost to named screens and actions:

```bash
./.venv/bin/python -m swagperf.cli screens traces/session.pftrace
```

Or the dashboard's **Screens** screen, which reads any recorded run's trace. It
has two views over the same run:

- **Screen usage** — per-screen attribution plus the navigation stack.
  Selecting a row charts every visit to that screen separately.
- **Launch metrics** — the startup steps from the same trace. A manual session
  records both halves at once, so both are readable from one run.

### Navigation stack

A per-screen number says what the screen on *top* cost. It cannot say what was
still held open underneath — and a screen pushed onto two others has not
replaced them: those are still alive, still holding their views and bitmaps, and
sometimes still doing work. That is usually the answer when a screen's own work
looks cheap but RAM is high while it is showing.

The stack cannot be read from slice nesting, because `ScreenTrace` keeps a
single slot: screen slices are strictly sequential and never overlap. It is
instead replayed from the coordinator's own markers, which *are* the stack
operations — `nav:open-` pushes, `nav:back-` pops, `nav:tab-` resets — so the
result is the same back stack the app held rather than an inference.

Each visit carries its `depth`, `stack` and what was `beneath` it, and the
Screens screen groups cost by depth. On a real session this surfaced a screen at
depth 3 running at 11% CPU while 485MB was resident: the screen itself was
nearly idle, and the memory belonged to the two screens held open below it.

Visits are charted individually because a per-screen total cannot distinguish
twelve even visits from eleven cheap ones and a pathological twelfth — and it is
usually the twelfth that is the bug. Bars are drawn in the order the visits
happened, so a screen that gets more expensive each time it is opened shows up
as a slope rather than disappearing into a sum. The dashed line is the mean;
a bar more than two standard deviations from it is drawn in red, and hovering
gives that visit's CPU and RAM against the mean and its deviation in standard
deviations.

| Marker | Meaning |
|---|---|
| `screen:<Route>` | async slice, open for the whole screen visit |
| `action:<name>` | a discrete user action |
| `nav:<From>-><To>` | the navigation transition itself |
| `step:<name>` | startup milestones, matching the existing step model |

Screen markers carry two extra pieces of structure:

| Form | Meaning |
|---|---|
| `screen:Home#compose` | what rendered it: `compose`, `rn`, `native_view` |
| `screen:Onboarding.otp#rn` | a step *inside* a route, as `Parent.Step` |

The kind matters because this app is a hybrid and the mix is not obvious from
the outside: Onboarding is a React Native surface, Home is Compose but dominated
by a camera preview, everything else is Compose. Without the tag, "is the React
Native screen slower than the native ones?" cannot be answered from a profile.

Sub-screens exist because a route can be one screen natively and several to the
user. Onboarding is the clear case: nine React Native steps under a single
`screen:Onboarding` slice, so the whole first-run experience used to profile as
one undifferentiated span. A sub-screen slice is open *inside* its parent's, so
`screen_summary` reports it as its own row and never adds it to the parent --
`include_substeps=False` gives the top-level view that sums correctly.

An untagged `screen:Home` from an older build still parses; its kind is reported
as unknown rather than the visit being dropped.

On the app side (swag-pay), the tag and the sub-screens are produced by:

- `ScreenKind`, an enum in `SwagTrace.kt` that each `AppRoute` declares via
  `traceKind`, on an exhaustive `when` -- a new route will not compile until
  it is classified.
- `SubScreenTrace`, a slot separate from `ScreenTrace` rather than a widening
  of its single-slot invariant, since a sub-screen slice is open *inside* its
  parent's and the two must not fight over which is "current".
- `onboardingReducer` in the React Native layer, instrumented the same way
  `PayFlow.reduce` already instruments the native pay funnel: one wrapper at
  the reducer's single choke point covers every step transition, so no call
  site can add a step without also tracing it. Markers cross to native
  through the existing `SwagPayNavigation` bridge (`nativeTrace.ts`); a
  missing bridge degrades to no markers rather than throwing, since tracing
  must never change app behaviour.

Only step names and outcome classes ever cross into a marker there. Onboarding
handles a mobile number, an OTP and a PIN, and a trace is pulled off the device
and shared -- the same rule the existing QR-validation and pay markers follow.

A screen that is still on display when tracing stops has no closing event, so
Perfetto records it as an unfinished slice (`dur = -1`). Those are reported as
visits, clamped to the end of the trace and flagged `open_ended`, because that
screen is usually the one the session was about — dropping it reported "0
visits" for a session that plainly had one. CPU, RAM and frames are all scoped
to the process that owns the slice; matching RAM counters across every process
once summed the whole device into a single screen's "peak".

Two things worth knowing about the numbers:

- **CPU is scheduled CPU time, not elapsed time.** It comes from `sched_slice`
  clipped to the visit window. A screen that is merely *open* while the device
  idles has not cost anything, and elapsed time cannot tell that apart from real
  work. The two are shown side by side so the difference is visible. This needs
  the `sched/sched_switch` ftrace event; a synthetic trace has none, and the
  screen says so rather than drawing zero bars.
- **RAM growth is min-to-peak within a single visit.** A screen that repeatedly
  leaves RAM higher than it found it is the orphaned-surface signature the shell
  architecture names.

### Live markers while recording

The Manual screen shows markers as they land, filterable by kind
(screens / actions / navigations / steps), with the currently-open screen
marked. It reads only the part of the trace written since the last read, so a
long session stays cheap to follow, and nothing about the recording is
disturbed:

```
GET /api/manual/live
```

If this stays empty while the app is being used, the build being traced is not
emitting markers — check the package is the instrumented one, and note that a
marker missing because the flow never reached that screen is not the same as a
marker that was never instrumented.

## Analysing any app, and the competitor catalogue

Not every app can be instrumented. A competitor's binary cannot emit `step:`
markers, so this tool reads a second way: **derivation** from the slice names
every Android app produces regardless of instrumentation (`bindApplication`,
`activityStart`, `inflate`, `Choreographer#doFrame`, ...). Perfetto's own
`android.startup.startups` stdlib module identifies the package and cold/warm
classification; explicit phase matching over slice names produces attributable
step durations, because a derived number that cannot be traced back to the
slices that produced it is not trustworthy.

```bash
# analyse any app -- instrumented or not, auto-detected from the catalogue
./.venv/bin/python -m swagperf.cli analyse trace.pftrace --app com.phonepe.app --device pixel7

# force derivation even for an app the catalogue marks instrumented
./.venv/bin/python -m swagperf.cli analyse trace.pftrace --app com.swagpay --derive

# capture a real cold start (force-stops the app, launches it just after
# tracing begins so the launch itself falls inside the trace window)
./.venv/bin/python -m swagperf.cli capture --pkg com.phonepe.app --cold --repeat 5 --analyse

# the app catalogue
./.venv/bin/python -m swagperf.cli apps list
./.venv/bin/python -m swagperf.cli apps add com.rival.app --name "Rival" --role competitor
./.venv/bin/python -m swagperf.cli apps discover     # verify package names against a connected device
```

**A derived run never gets an invented budget.** `budgets.py`'s numbers are Swag
Pay's own stated targets; asserting them against a competitor's app would be
making up a number for a product whose architecture is undocumented here. A
derived run's `budget_ms` is `None` unless the catalogue's `apps.json` (or a
local `apps.local.json` override) explicitly states one for that package, and
the dashboard does not draw a budget line or colour a breach when none exists.
This was a real bug during development, twice over: the dashboard first drew
Swag Pay's 420ms line against a competitor's trace, and separately the CLI's
`--path-kind` flag defaulted to `"returning_user"` and was silently applied to
a derived run regardless of app, mixing a competitor's trace into Swag Pay's
own bucket. Both are covered by regression tests now
(`TestGenericAppDerivation`, `TestCLIPathKindDefaulting`).

Regression detection, baselines and benchmarks are all scoped by
`(app_pkg, path_kind, device)`, so a PhonePe cold-start trend is compared
against its own history, never against Swag Pay's.

Steps derived this way carry no runtime attribution beyond "Android framework",
since only Swag Pay's own step names map to a runtime. The durations and
child-slice numbers are still fully attributable.

## Token consumption monitor

A second, unrelated page at `/tokens.html` (the *LLM token usage* link at the
bottom of the sidebar), answering a different question: not how the *app*
performs, but how much this Claude Code session has spent reading this
repository.

`tokens.py` reads the `usage` blocks Claude Code writes into its own session
transcripts under `~/.claude/projects/<this-project>/*.jsonl` and buckets them
by how the tokens got into context: `graphify` calls, `Read`/`NotebookRead`,
`Grep`/`Glob`, and read-only `Bash` (matched shallowly on the command's first
token -- `cat`, `head`, `sed`, `grep`, `find`, `ls`, `awk`, `less` -- because
guessing deeper misattributes more often than it helps).

Every figure is server-reported; nothing here is estimated. It deliberately
does **not** report "tokens saved", since that would need the cost of the path
not taken, which is a counterfactual and cannot be measured, only modelled --
that is what `graphify benchmark`'s words/chars ratio does instead, and the two
should not be confused for the same kind of number. Attribution is sound in
aggregate and fuzzy for any single call, since a tool result's cost lands on
the *next* API call rather than being labelled at the point it entered context.

Served at `/api/tokens`, aggregating the most recent sessions for the project
`server.py` is running in.

## Frontend development

The dashboard is a React 19 + TypeScript app in `frontend/`, built with Vite into
`web/dist`, which is committed so the tool runs without Node.

```bash
cd frontend
npm install
npm run dev        # Vite on :5173, proxying /api to the dashboard on :8787
npm run build      # typecheck + build into ../web/dist (commit the result)
npm test           # vitest
npm run lint       # oxlint
```

Every screen is built from the design system in `frontend/src/design/`: colour
tokens for both themes, a type and spacing scale, layout and text primitives, and
the shared components and charts. **`/design-system`** (the *Tokens* link in the top
bar) is its living reference. Typography follows [krafton.com](https://www.krafton.com/en/):
Zalando Sans Expanded for display, Poppins for UI text, Noto Sans KR as the Korean
fallback. The status colours are separate from the brand red. Fail is its own
crimson and always carries ✕, so brand and status never read as the same thing.
[`frontend/README.md`](frontend/README.md) has the layout and conventions.

## Layout

```
swagperf/
  budgets.py      architecture-derived budgets and risk map — start here
  extract.py      TraceProcessor SQL → metrics (no LLM)
  derive.py       steps from an uninstrumented app's own slices
  screens.py      per-screen and per-action cost from SwagTrace markers
  store.py        SQLite history, trailing baselines, regression detection,
                  benchmarks, stress tests, Copilot threads and pins
  analyst.py      model backends + deterministic fallback
  copilot.py      the Copilot's answers, computed from the run history
  capture.py      on-device capture via adb (one-shot, cold/warm, manual)
  live.py         incremental reads of a trace still being recorded
  jobs.py         background jobs for dashboard-started captures and stress tests
  catalogue.py    apps under test (apps.json, apps.local.json)
  server.py       dashboard server and JSON API
  tokens.py       token-consumption monitor
  synth*.py       synthetic trace generators for development
  cli.py          the swagperf command
frontend/         the dashboard's source (React + TypeScript)
web/dist/         the built dashboard, served by server.py
web/tokens.html   the token-consumption page
tests/            117 tests over the pipeline, the store, the server and the Copilot
docs/             backlog, decisions and plans
```

## Adapting it

Editing `budgets.py` is the main thing you will do — the step names, budgets and
`RISK_MAP` are what make the output specific to Swag Pay rather than generic.

Step names are matched by the `step:` prefix. Emit them from the app with
`Trace.beginSection("step:camera_open")` or from the automation harness; child slices
inside a step are attributed automatically and give the model what it needs to say
*which part* of a step moved.

## Known gaps

- **iOS is not wired up.** The extractor is schema-driven and should mostly work on an
  iOS trace, but `capture.py` is adb-only and nothing has been tested against a real
  iOS trace. The CMP × RN seam — the highest risk in the architecture — lives on iOS.
- **Frame attribution is per screen, not per surface.** Janky frames are attributed
  to the screen on display, but not yet to the CMP or RN surface within it, so the
  tool cannot currently prove the interop seam is the cause. The model correctly
  declines to claim it.
- **No device-model baselines.** `device` is recorded and benchmarks are per device,
  but the trailing baseline does not yet segment by device automatically. Mixing
  device classes in one history inflates variance and hides real regressions.
- **The Copilot is rule-based.** It answers the questions listed under
  [Copilot](#copilot) from the data and says so for anything else. A language model
  is not wired in yet.
- **The dashboard server has no auth and mutates local history** (pinning a
  benchmark, the Copilot's threads). It binds to loopback only, which is fine for a
  dev/CI tool — but do not expose it on a routable interface.
- **Dashboard verified with Playwright, not Chrome DevTools MCP.** Playwright drives
  real Chromium, so clicks, keyboard use, layout at phone width and console errors
  were checked against a live page. A DevTools pass would add performance-panel and
  network profiling.

Deferred work is tracked in [docs/BACKLOG.md](docs/BACKLOG.md).
