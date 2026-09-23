# Tracker

The live list of everything open on swagperf and on the performance of the app it measures. Bugs, features, tech debt and performance issues found in runs all live here, one row each. The product-manager agent (`.claude/agents/product-manager.md`) keeps it current. After every recorded run it reviews the new data and opens or updates **performance issues for developer review** in `docs/issues/`. Any agent or person who finds, fixes, ships or defers something updates this file, or asks the product-manager agent to.

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

## Tool features

| ID | Title | Area | Priority | Status | Raised | Notes |
|---|---|---|---|---|---|---|
| F-001 | Copilot answers from a local Claude or Codex session | Copilot | P2 | planned | 2026-09-23 | An "Answer with" switch: Rules / Claude / Codex. It uses the logged-in CLI session, so no API key is needed. The rules engine still supplies every number, the model writes the answer, and numbers not found in the data are flagged. If the session fails, the rules answer is shown under a banner. Needs T-001 first. |
| F-003 | Widget-level trace metrics (widget TTI) | Instrumentation / Screens | P3 | backlog | 2026-09-22 | [BACKLOG: widget TTI](BACKLOG.md#widget-level-trace-metrics-widget-tti) |
| F-004 | Measured A/B of graphify's token savings | Token monitor | P3 | backlog | 2026-09-22 | [BACKLOG: graphify A/B](BACKLOG.md#ab-measurement-of-graphifys-token-savings) |
| F-005 | Split the onboarding route into its nine steps | Swag Pay app model | P3 | backlog | 2026-09-22 | Partly addressed: trace markers exist per step. [BACKLOG: onboarding route](BACKLOG.md#onboarding-modelled-as-one-native-route) |

## Tech debt & security

| ID | Title | Area | Priority | Status | Raised | Notes |
|---|---|---|---|---|---|---|
| T-001 | Dashboard server accepts POSTs from any website | Server | P0 | planned | 2026-09-23 | `do_POST` checks neither `Origin` nor `Host`. Any page open in the browser can start captures and stress tests on `127.0.0.1:8787`, and a DNS-rebinding page can also read the history. With F-001, it could also spend the user's Claude or Codex quota. Fix: reject requests whose `Origin` or `Host` isn't `127.0.0.1` or `localhost`. |
| T-002 | Navigation stack depth is replayed, not recorded | Screens | P3 | backlog | 2026-09-22 | [BACKLOG: stack depth](BACKLOG.md#stack-depth-is-reconstructed-not-recorded) |

## Done (last 30 days)

| ID | Title | Commit | Date |
|---|---|---|---|
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
