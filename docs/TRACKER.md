# Tracker

The live list of everything open on swagperf and on the performance of the app it measures. Bugs, features, tech debt and performance issues found in runs all live here, one row each. The product-manager skill (`.agents/skills/product-manager/SKILL.md`, shared by every coding agent; Claude Code runs it as the `product-manager` agent) keeps it current. After every recorded run it reviews the new data and opens or updates **performance issues for developer review** in `docs/issues/`. Any agent or person who finds, fixes, ships or defers something updates this file, or asks the product-manager agent to.

- Runs reviewed through: #81
- Last reconciled with git: 8d997d8 · 2026-09-23

**How to review a performance issue:**
1. Open the issue's file and check the evidence and initial observations.
2. Set its `Status:` line to `confirmed`, `dismissed` or `expected`. For `dismissed` or `expected`, add a Log line with the reason and the value at the time.
3. Or tell the product-manager agent your decision and let it make the change.

The agent never closes an issue on its own.

**Statuses:**
- open: `needs-review` → `confirmed` → `in-progress`
- closed: `done`, `dismissed`, `expected`
- tool items can also be `planned` or `backlog`

**Priorities:**

| Priority | Tool items | Performance issues |
|---|---|---|
| P0 | Wrong data shown as right, or a security hole | none |
| P1 | Blocks a workflow | A high-severity signal seen in 2 or more runs, or an ordering violation |
| P2 | Friction | One run only, or medium severity |
| P3 | Polish | none |

---

## Performance issues from runs

Problems in the app under test, opened from runs by the automatic review. Each has a file in `docs/issues/`.

| ID | Title | App · path | Priority | Status | Seen |
|---|---|---|---|---|---|
| [P-001](issues/P-001.md) | Janky frames over budget | Swag Pay · cold | P1 | needs-review | #72–#81 (5 of 10) |
| [P-002](issues/P-002.md) | Peak RAM usage over budget | Swag Pay · cold | P1 | needs-review | #72–#81 (10 of 10) |
| [P-003](issues/P-003.md) | RAM growth over budget | Swag Pay · cold | P1 | needs-review | #72–#81 (10 of 10) |
| [P-004](issues/P-004.md) | activity_create step regressed | Swag Pay · cold | P2 | needs-review | #72–#81 (1 of 10) |

## Tool bugs

| ID | Title | Area | Priority | Status | Raised | Evidence |
|---|---|---|---|---|---|---|
| B-001 | Verdict headline has no units and doubled brackets | Analyst / Overview | P2 | needs-review | 2026-09-23 | Overview, run #81 reads "Peak RAM usage over budget: 493.3 vs budget 320 (+54.2%) (+1 more)". The value and budget have no "MB", and "(+54.2%) (+1 more)" stacks two bracket groups. Built by `analyst.heuristic`: evidence `f"{value} vs budget {budget} (+{pct}%)"` plus `" (+N more)"`. Source: `.claude/issues/image.png` |
| B-002 | Peak RAM tile shows a green improvement while the Peak RAM gate fails | Overview | P2 | needs-review | 2026-09-23 | Overview, run #81: the Peak RAM tile shows "493 MB ▼ −5 MB vs 498 MB" in the good colour, because it compares against run #80. Beside it, the release gate shows Peak RAM 493 MB failing against its 320 MB limit. A reader sees "better" and "failing" for the same number. Source: `.claude/issues/image.png` |
| B-003 | A run's trailing baseline includes runs recorded after it, and mixes start paths | Regression detection (`store.baseline`) | P1 | needs-review | 2026-09-23 | `store.baseline()` takes the newest 20 runs of a step, excluding only the run being judged. It has no `id <` bound and no `path_kind` filter. At capture time, only earlier runs exist, so the verdict is right. Anything that recomputes an older run's regressions later (`swagperf reextract`, `swagperf triage` over an old range) judges it partly against runs that came after it, and cold and warm runs can share a baseline. Needs a developer to confirm the intended window before changing verdict logic. |
| B-004 | A trace recorded while Flashlight profiles the same phone is broken, and can be recorded as a normal run | Capture (`capture.py`, `jobs.py`) | P0 | in-progress | 2026-09-23 | Measured in the concurrency experiment ([result](flashlight-perfetto-observations.html), `experiments/flashlight-concurrency/`, 3 of 3 repetitions each way). If Flashlight's sampler starts during a Perfetto session, scheduler events, app slices, screen markers and RAM samples all stop at that moment and never resume. If Flashlight is already running, Perfetto starts without error but records no scheduler events, counters or process names. Perfetto logs no error either way. A manual stop records the run regardless (problems are only notes), so a partial or empty trace can reach history as a normal run. Fix: refuse to start a capture while `BAMPerfProfiler` or `atrace` is running on the device, and fail any trace whose scheduler events stop before it ends. That also catches Flashlight joining partway through, where the first part of the trace is still fine. Untested: whether the atrace settings Flashlight leaves behind after it exits also break the next capture. The raw experiment traces stay local (`results/` is git-ignored); the note has the numbers. P0 under the wrong-data rule. Must land before F-006. Implemented 2026-09-23, not yet committed: `capture.require_no_other_profiler` before every capture and manual start, `extract.tracing_lost` on every device trace before it is recorded (jobs and CLI), and the dashboard's manual start respects the capture lock; checked against every Phase 0 trace. |
| B-005 | Seeded runs are recorded without an app, so they show as "Unknown app" but are judged against Swag Pay's budgets | CLI `seed` (`swagperf/cli.py`) | P3 | needs-review | 2026-09-24 | Found while building the run-perfetto-monitor skill (`.claude/skills/run-perfetto-monitor/`), which seeds a scratch history with `swagperf seed`. Repro: seed a history with `swagperf seed` and open the dashboard. Shown: the App picker lists the seeded runs as "unknown" and the run box reads "Unknown app 2.3.0", yet Startup draws "Budget 420 ms" and the Overview release gates judge them against Swag Pay's TTID budget (≤ 420 ms). Expected: the runs are labelled Swag Pay (`com.swag.pay`), because `synth.gen_trace` makes Swag Pay-shaped traces with `step:` markers, read through the instrumented `ex.extract()`. Cause: the `seed` branch of `swagperf/cli.py` calls `store.record(...)` (line 445) with no `app_pkg`. A run labelled as an unknown app is asserted against Swag Pay's budget, the "never assert our budgets on another app" pattern, although here the runs really are Swag Pay builds. Second effect: the App picker prefers `com.swag.pay`, so any real or synthetic `com.swag.pay` Perfetto run in the same history becomes the default view and hides the seeded series. Fix: record seed runs with `app_pkg="com.swag.pay"`, then update the Gotchas in the run-perfetto-monitor skill, which documents the current behaviour. Scope: `seed` and synthetic/demo data only; captured runs are not affected. P3 (polish): demo data only, the budget and verdicts are right for what the runs are, and the seeded runs stay reachable under "unknown" in the App picker. |

## Tool features

| ID | Title | Area | Priority | Status | Raised | Notes |
|---|---|---|---|---|---|---|
| F-001 | Copilot answers from a local Claude or Codex session | Copilot | P2 | planned | 2026-09-23 | An "Answer with" switch: Rules / Claude / Codex. It uses the logged-in CLI session, so no API key is needed. The rules engine still supplies every number, the model writes the answer, and numbers not found in the data are flagged. If the session fails, the rules answer is shown under a banner. Needs T-001 first. |
| F-003 | Widget-level trace metrics (widget TTI) | Instrumentation / Screens | P3 | backlog | 2026-09-22 | [BACKLOG: widget TTI](BACKLOG.md#widget-level-trace-metrics-widget-tti) |
| F-004 | Measured A/B of graphify's token savings | Token monitor | P3 | backlog | 2026-09-22 | [BACKLOG: graphify A/B](BACKLOG.md#ab-measurement-of-graphifys-token-savings) |
| F-005 | Split the onboarding route into its nine steps | Swag Pay app model | P3 | backlog | 2026-09-22 | Partly addressed: trace markers exist per step. [BACKLOG: onboarding route](BACKLOG.md#onboarding-modelled-as-one-native-route) |
| F-006 | Flashlight audit lane: separate runs, results imported beside Perfetto runs | Capture / new `flashlight.py` | P2 | in-progress | 2026-09-23 | Step 3 of the [Flashlight note](flashlight-perfetto-observations.html), and its step 1: Perfetto owns every time-aligned metric; Flashlight owns only its score, report and thread summary. Flashlight never runs at the same time as Perfetto (step 2 of the note, the concurrency experiment, ruled it out). Runs `flashlight test` on its own, keeps `results.json` unchanged, stores a summary per audit. It must hold the capture lock, refuse while a manual session records, and reset atrace when it finishes, because Flashlight leaves its atrace settings behind. The standalone `flashlight` binary is Intel-only and will not run on Apple Silicon without Rosetta; the npm packages (`@perf-profiler/*`, last released 2024) run natively. Needs B-004 first. Implemented 2026-09-23, not yet committed: `flashlight/` (pinned npm packages, `audit.js`, `summary.js`), `swagperf/flashlight.py`, `jobs.start_audit`, `/api/audits` and `/api/audit/start`, `swagperf audit run|list|show`, and a Profiler switch in the dashboard with Audit, Run audit and Audits pages. Not yet run end to end on the device. |
| F-007 | Per-thread CPU from the Perfetto trace, including the React Native JS thread | Extraction / Screens | P2 | planned | 2026-09-23 | Step 5 of the [Flashlight note](flashlight-perfetto-observations.html): Flashlight-style thread CPU (UI thread, RenderThread, `mqt_js`/`mqt_v_js`) computed from the trace's own scheduler data, so it lines up with screens. In a manual-mode trace on the V2514 the JS thread is named `mqt_v_js` (bridgeless) and resolves; still unchecked in a cold capture, whose config has no `task_newtask`/`task_rename`. Needs a React Native workload: Onboarding (`#rn`, first run only) or the offers screens (F-009). |
| F-008 | Flashlight audits and Perfetto runs in one view, labelled by provenance | Dashboard | P3 | dismissed | 2026-09-23 | Step 4 of the [Flashlight note](flashlight-perfetto-observations.html). Each audit is labelled `same_cohort` (same app build, device and flow) or `unrelated`, computed rather than typed in, and never drawn on the Perfetto timeline. Needs F-006. Dismissed 2026-09-23 by the user: the two profilers stay separate. The dashboard separates them with a Profiler switch instead of showing them in one view. |
| F-009 | React Native offer screens after Home in Swag Pay | Swag Pay app (`swag-pay` repo) | P2 | in-progress | 2026-09-23 | Home's banner cards open a React Native `Offers` surface: a collection page (Action games) and a gift card page per card (amounts with cashback, how to redeem, FAQs, related cards), modelled on swag.gg's gift card pages. Traced as `screen:Offers#rn` with sub-screens `Offers.collection` and `Offers.card`, and `offers_*` actions. Gives F-007 a React Native workload reachable without a first-run reset. Built and checked on the V2514 on 2026-09-23 (every marker present in a trace); not yet committed. Known limits: a page returned to by back starts from its first amount, and a rotation resets the app to Home (existing behaviour: navigation state is not saved across activity recreation). Card art now uses pictures already in the app for the Action games page, BGMI and Forza Horizon; the other four cards keep gradients because the repo has no pictures of those games. The Forza card reuses the picture from Home's "Forza Horizon" card, which is not Forza artwork (Home has the same mismatch). |
| F-010 | A 5,000-contact list built twice, React Native (FlashList) and Compose, for comparing scrolling | Swag Pay app (`swag-pay` repo) | P2 | in-progress | 2026-09-23 | The same deterministic contacts (grouped A–Z with sticky letter headers) on a React Native screen with Shopify's FlashList and a Compose `LazyColumn` screen, each its own route (`screen:ContactsRN#rn`, `screen:ContactsCompose#compose`) with a list-ready step marker, so Perfetto and Flashlight can compare the two runtimes on identical content. |
| F-011 | Plain-language descriptions for step names and thread names | Dashboard / `budgets.py` / `threads.py` | P2 | in-progress | 2026-09-23 | Startup steps and Flashlight's thread list showed raw names (`bind_application`, `mqt_v_js`, `DefaultDispatch (3)`) with nothing saying what they are. Steps: `STEP_DESCRIPTIONS` next to `STEP_RUNTIME` in `budgets.py`, published as `startup_model.step_descriptions`, with a test that every step in `derive.PHASES` and `STEP_RUNTIME` has one. Threads: `swagperf/threads.py` matches names by pattern (15-character truncation, numbered threads, Flashlight's ` (N)` suffix) and `/api/audits` adds a `description` to each thread; unknown names get none. Shown with new design-system components `Term` (a ? beside the name) and `TermList` (a second line): Screens' Startup steps, Steps (row and drill-down), Startup (legend, ordering list), Compare's steps diff, and the Audit page's CPU by thread. Swag Pay's own steps (`bootstrap`, `session_read`, `camera_open`…) are described from the startup model in `budgets.py`, because the app emits only instant `step:` milestones today; tighten them when it wraps real work. Implemented 2026-09-23, not yet committed. |
| F-012 | Screenshot testing with Maestro: a visual regression lane | Maestro / new lane | P3 | backlog | 2026-09-24 | Designed, then parked by the user on 2026-09-24 before any code. Maestro flows kept in swagperf take a screenshot at named checkpoints. swagperf compares each one with an approved baseline for that app, cohort and device class, fails the run on an unexpected change, and takes approvals in the dashboard. It's a separate lane from Perfetto runs, Android first. The product-manager skill's revisit queue says when to raise it again. [BACKLOG: screenshot testing](BACKLOG.md#screenshot-testing-with-maestro-visual-regression-lane) · [plan](screenshot-testing-plan.html) |

## Tech debt & security

| ID | Title | Area | Priority | Status | Raised | Notes |
|---|---|---|---|---|---|---|
| T-001 | Dashboard server accepts POSTs from any website | Server | P0 | planned | 2026-09-23 | `do_POST` checks neither `Origin` nor `Host`. Any page open in the browser can start captures and stress tests on `127.0.0.1:8787`, and a DNS-rebinding page can also read the history. With F-001, it could also spend the user's Claude or Codex quota. Fix: reject requests whose `Origin` or `Host` isn't `127.0.0.1` or `localhost`. |
| T-002 | Navigation stack depth is replayed, not recorded | Screens | P3 | backlog | 2026-09-22 | [BACKLOG: stack depth](BACKLOG.md#stack-depth-is-reconstructed-not-recorded) |

## Done (last 30 days)

| ID | Title | Commit | Date |
|---|---|---|---|
| T-003 | Dashboard pages built only from the design system: the three hand-drawn charts (Stress box plot, Startup ordering, Memory breakdown) and the two hand-built expandable tables now use `DotBoxPlot`, `SpanTimeline`, `StackedBars` lg and `ExpandableTable`; pickers use `Table`/`SortTh`/`RowAction`; no inline styles or raw controls in pages, enforced by oxlint; every component on `/design-system`, enforced by a test | not yet committed | 2026-09-24 |
| — | Flashlight + Perfetto on one device (step 2 of the note): tested and ruled out, harness in `experiments/flashlight-concurrency/` | not yet committed | 2026-09-23 |
| F-002 | Tracker, product-manager agent and automatic run review | added with this file | 2026-09-23 |
| — | README: quick start, full instructions, what to monitor per screen | 8d997d8 | 2026-09-23 |
| — | NLP mobile automation in CI: architecture plan, ADR 0001, skill | c16d23d | 2026-09-23 |
| — | Old dashboard removed; every static path kept inside the build | 38f56cd | 2026-09-23 |
| — | Dashboard design system and the Copilot panel | a7e66df | 2026-09-23 |
| — | Copilot engine and API: streamed answers, threads, feedback, pins | 04c2129 | 2026-09-23 |
| — | Dashboard redesign in React + TypeScript (all screens) | 51f403f…b46f5fe | 2026-09-23 |
| — | Device-trace accuracy: RAM and frames scoped to the app | a792525 | 2026-09-23 |
| — | Manual trace config slimmed from ~230 MB/min to ~53 MB/min | feb61cc | 2026-09-23 |
| — | Live markers read incrementally | f190cda | 2026-09-23 |
| — | Screens: session timeline, per-screen app jank, transition costs | db78f77 | 2026-09-23 |
| — | Live token-consumption monitor | 0aabe16 | 2026-09-22 |
| — | Manual tracing mode and per-screen CPU/RAM attribution | d4b18b3 | 2026-09-22 |
| — | Stress tests: repeated cold starts, per-session view | 7ddf1b9 | 2026-09-22 |
| — | Any Android app via step derivation, plus a competitor catalogue | 377aa0d | 2026-09-22 |
| — | Run comparison and pinned benchmark runs | 88ba98d | 2026-09-22 |

## Archive

Done items older than 30 days, as `ID · title · commit`.
