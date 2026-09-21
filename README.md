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
| Peak RSS | 320 MB | Three runtimes resident simultaneously |
| RSS growth | 60 MB | Orphaned RN surfaces — a Surface started and never stopped |
| Per-step duration | see `budgets.py` | Trailing-baseline regression per step |

**Two startup paths, two budgets.** A returning user puts the camera on the critical
path and defers Hermes. First-run inverts it — onboarding *is* an RN surface. Judging
one by the other's budget produces nonsense, so `--path-kind` is explicit and the
critical path differs per kind.

## Install

```bash
cd ~/Documents/perfetto-monitor
python3 -m venv .venv && ./.venv/bin/pip install perfetto anthropic
```

`trace_processor_shell` downloads automatically on first run.

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
| **Memory** | Peak RSS and Hermes heap on one axis, session growth, JS share of growth |
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
