# swagperf

Perfetto trace regression monitor for the Swag Pay mobile shell.

Swag Pay runs **three runtimes in one process** — Compose/CMP, Hermes+Fabric, and the
native camera stack. This tool measures the performance constraints the shell
architecture actually states, tracks them per step across builds, and asks a model to
attribute any regression to a runtime and to a named architectural risk.

It is not a general trace viewer. Use the Perfetto UI for that.

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

## What it measures

Each metric maps to a constraint or risk named in the shell architecture.

| Metric | Budget | Architectural basis |
|---|---|---|
| Time to first usable camera frame | 420 ms | *"Nothing before the first camera frame"* — the strongest decision on the board |
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

## Install

```bash
cd ~/Documents/perfetto-monitor
python3 -m venv .venv && ./.venv/bin/pip install perfetto anthropic
ln -sf "$PWD/perfetto_init" ~/.local/bin/perfetto_init   # optional, puts it on PATH
ln -sf "$PWD/perfetto" ~/.local/bin/perfetto             # optional, shorter alias
```

`trace_processor_shell` downloads automatically on first run.

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

## Use

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

# compare two runs (base defaults to the pinned benchmark)
./.venv/bin/python -m swagperf.cli compare 19 11
./.venv/bin/python -m swagperf.cli compare 19            # vs benchmark

# pin a known-good run as the benchmark for its path + device
./.venv/bin/python -m swagperf.cli benchmark set 11 --note "known-good 2.2.0"
./.venv/bin/python -m swagperf.cli benchmark list
./.venv/bin/python -m swagperf.cli benchmark clear --run 11

# recompute metrics for all runs whose traces still exist
# (run this after changing extract.py, or historical rows mix two formats)
./.venv/bin/python -m swagperf.cli reextract

# synthetic history, for development without a device
./.venv/bin/python -m swagperf.cli seed -n 16 --regress-last
```

`analyse` exits non-zero on a `fail` verdict, so it drops into CI directly.
Use `--fail-on warn` to gate harder, `--fail-on never` to report only.

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
`(path_kind, device)` scope, so a returning-user benchmark is never applied to a
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
trusted at all and nothing fires.

A deferred step starting within 1 ms of the first-frame boundary is not an ordering
violation — it is a step legitimately starting *at* the boundary, and float rounding
can place it a hair early.

## Dashboard

Six tabs, one per concern the architecture names:

| Tab | Answers |
|---|---|
| **Overview** | Verdict, all six budgets, every finding, verdict-per-run strip |
| **Startup** | Time to first camera frame, ordering violations, critical-path composition |
| **Frame pacing** | Slow/janky frames and thermal drift — kept apart because progressive drift means throttling while scattered spikes mean the interop seam |
| **Memory** | Peak RAM usage and Hermes heap on one axis, session growth, JS share of growth |
| **Steps** | Per-step table with trailing-baseline deltas; click a step for its history and child breakdown |
| **Compare** | Diff any two runs, defaulting to the pinned benchmark; child slices expand under any step that got worse |
| **History** | Every run, sortable on any column, filterable by verdict/device/text; pin a benchmark or jump to a comparison per row |

The step chart has three views. **Critical path** is the default and sums only the
steps a user waits through on the selected path — the bar height is a number they
experience. **All steps** adds deferred work, hatched at 45° so "off the critical
path" is not carried by position alone. **Per step** is small multiples, each step on
its own scale, so a 40ms step's movement is as readable as a 200ms step's.

The legend doubles as a show/hide control. In critical-path mode a runtime with no
steps in view (Hermes, for a returning user) is marked *not in view* rather than
appearing broken when toggling it changes nothing, and the last visible runtime is
disabled so the chart can never be emptied.

Clicking a step row opens a breakdown below the table: this run versus its trailing
median, z-score, stdev, min/max, the step's own history against its budget, and every
direct child slice with its own trend. Untraced self-time is shown explicitly, so the
breakdown sums to the step duration — "24ms unaccounted for in compose_shell" is
itself a finding rather than a rounding gap.

## Token consumption monitor

A second, unrelated dashboard at `/tokens.html` (linked from the main page),
answering a different question: not how the *app* performs, but how much this
Claude Code session has spent reading this repository.

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

## Layout

```
swagperf/
  budgets.py    architecture-derived budgets and risk map — start here
  extract.py    TraceProcessor SQL → metrics (no LLM)
  store.py      SQLite history, trailing baselines, regression detection
  analyst.py    model backends + deterministic fallback
  capture.py    optional adb capture
  server.py     dashboard server + /api/history, /api/compare, /api/benchmark/*
  synth.py      synthetic trace generator for development
web/            dashboard (no build step, no dependencies)
tests/          24 tests over the deterministic pipeline
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
- **Frame attribution is process-wide.** Slow frames are not yet attributed to a
  specific surface, so the tool cannot currently prove the interop seam is the cause.
  The model correctly declines to claim it. Emitting surface-boundary markers would
  close this.
- **No device-model baselines.** `device` is recorded and baselines can filter on it,
  but the CLI does not yet segment automatically. Mixing device classes in one history
  will inflate variance and hide real regressions.
- **Dashboard verified with Playwright, not Chrome DevTools MCP.** That MCP server is
  not installed in this environment. Playwright drives real Chromium over CDP, so
  click/sort/filter/keyboard behaviour and console errors were checked against a live
  page, but if you have the DevTools MCP configured it is worth a second pass for
  performance-panel and network profiling that Playwright assertions do not cover.
- **The dashboard server has no auth and mutates local history** (pinning a benchmark
  is a POST). It binds to loopback only, which is fine for a dev/CI tool — but do not
  expose it on a routable interface.
- All development used synthetic traces. The SQL is written against the real
  TraceProcessor schema, but validate step extraction against one real capture before
  trusting it in CI.

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

Steps derived this way carry no runtime attribution beyond "native" (the
`RUNTIME` map in the dashboard only knows Swag Pay's own step names), so the
step chart's colour-by-runtime legend is uninformative for a derived run --
the duration and child-slice numbers are still fully attributable, only the
colour coding is not meaningful.

## Theme

Typography follows [krafton.com](https://www.krafton.com/en/)'s own stack --
Zalando Sans Expanded for display numbers and headings, Poppins for UI text,
Noto Sans KR as the CJK fallback their stylesheet declares -- loaded from
Google Fonts. Their proprietary "KRAFTON" display face is not licensable here;
Zalando Sans Expanded stands in for it on hero numbers, matching its bold,
geometric, wide-set shape. Surfaces follow their stark black/white/grey
editorial treatment in both themes. The categorical and status colors
(`--s1`..`--s4`, `--good`/`--warn`/`--crit`) are untouched -- they are
validated against the dataviz skill's CVD-safety and contrast gates, and
swapping them for brand colors would need re-validation against those gates.

## Profiling from the dashboard

The **Capture** tab lists the apps installed on the connected device, merged with
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

Runs are scoped by app throughout: the header's app selector filters every tab,
because plotting several different applications as one trend line is meaningless.

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

Or from the dashboard's **Stress** tab: pick an app, choose a session count, run.

Three deliberate choices:

- **Each session is also an ordinary run.** Sessions are recorded in `runs` like
  any other capture, so the Steps, Memory and Compare tabs work on them
  unchanged; `stress_tests` only groups them. The per-session table links
  straight through to each run.
- **A failed session does not end the test.** Stopping would discard the
  sessions already captured, and a test with two failures out of ten is still
  informative. Failures are counted and shown; only an all-failed test errors.
- **Spread leads the summary.** `spread_pct` is max-over-min relative to the
  median. A wide spread means a single capture of that app is not reproducible
  and medians should be compared instead — the CLI says so explicitly above 25%.

Stress history is kept separate from run history, since a row there is a whole
test rather than one capture.

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

Or the dashboard's **Manual** tab: Start tracing → use the app → Stop and analyse.

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

Or the dashboard's **Screens** tab, which reads any recorded run's trace. That
tab has two views over the same run:

- **Screen usage** — per-screen attribution plus the navigation stack.
  Selecting a row charts every visit to that screen separately.
- **Launch metrics** — the startup steps from the same trace. A manual session
  records both halves at once, and this view exists because the **Startup** tab
  reads the *globally* selected run: after a manual capture the launch numbers
  were a tab switch and a re-pick away, which read as them not being recorded.

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
Screens tab groups cost by depth. On a real session this surfaced a screen at
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
to the process that owns the slice; matching RSS counters across every process
once summed the whole device into a single screen's "peak".

### Live markers while recording

The Manual tab shows markers as they land, filterable by kind
(screens / actions / navigations / steps), with the currently-open screen
marked. It reads the partial trace the manual config is already draining to
the device, so nothing about the recording session is disturbed:

```
GET /api/manual/live
```

The response is cached briefly server-side, since each refresh costs an adb
pull and a parse. If this stays empty while the app is being used, the build
being traced is not emitting markers — check the package is the instrumented
one, and note that a marker missing because the flow never reached that screen
is not the same as a marker that was never instrumented.

Two things worth knowing about the numbers:

- **CPU is scheduled CPU time, not wall time.** It comes from `sched_slice`
  clipped to the visit window. A screen that is merely *open* while the device
  idles has not cost anything, and wall time cannot tell that apart from real
  work. The two are shown side by side so the difference is visible. This needs
  the `sched/sched_switch` ftrace event; a synthetic trace has none, and the tab
  says so rather than drawing zero bars.
- **RAM growth is min-to-peak within a single visit.** A screen that repeatedly
  leaves RAM higher than it found it is the orphaned-surface signature the shell
  architecture names.
