# Backlog

Deferred work on the swagperf tracing pipeline and the `swag-pay` instrumentation
it reads. Each entry records why the item matters, not just what it is, so it
stays actionable once the conversation that produced it is gone.

These are the long write-ups. The live list, with status and priority for
every item, is [TRACKER.md](TRACKER.md); each entry here carries its tracker ID.

---

## Widget-level trace metrics (widget TTI)

**Tracker:** F-003
**Status:** not started
**Raised:** 2026-09-22, while adding React Native screen and action tracing

### What

Screens should be able to emit per-**widget** trace metrics, the headline one
being widget time-to-interactive: how long after a screen opens before a given
widget on it is actually usable.

### Why

Screen-level attribution is now in place — each screen visit carries CPU, RAM,
frame and transition cost, and knows whether it was rendered by Compose, React
Native or a platform view. That answers "which screen is slow". It does not
answer "what on this screen is slow", and for a screen that is slow because of
one expensive component, the screen-level number points at the whole screen and
names no culprit.

Two concrete cases from this codebase motivate it:

- **Home** is tagged `native_view` because its cost is dominated by the camera
  preview rather than by Compose. The screen's time-to-first-usable-frame is
  already tracked as a startup step, but nothing separates the preview's
  readiness from the rest of the screen's.
- **Onboarding** now reports nine sub-screens, several of which are dominated by
  a single element: a numeric keypad, an OTP field, a bank-selection modal. A
  slow step currently gives no indication of which element caused it.

### Shape of the work

- A `widget:<Screen>.<Widget>` marker prefix, alongside the existing `screen:`,
  `action:`, `nav:` and `step:` prefixes in `SwagTrace.kt`.
- A TTI definition that is honest and consistent: most likely first composition
  through to the first frame in which the widget is both drawn and accepting
  input. "Rendered" alone is misleading for anything behind a loading state.
- A Compose helper that wraps a composable and emits the span, plus the
  equivalent for the React Native side through the existing `nativeTrace`
  bridge, so hybrid screens stay comparable.
- Extraction and a dashboard view in `swagperf/screens.py`, nested under the
  screen the widget belongs to, reusing the parent/step handling that the
  sub-screen work already established.

### Watch out for

- **Cardinality.** A marker per widget per visit is a much higher volume than a
  marker per screen. A list with fifty rows must not emit fifty markers; widgets
  should be named classes, not instances.
- **Privacy.** The rule the rest of the pipeline follows applies here too: names
  are fixed identifiers, never user data. Widgets in this app display payee
  names, amounts and masked phone numbers.
- **Double counting.** Widget spans sit inside screen spans exactly as
  sub-screens do, so any summary must not add them to the parent's total. See
  the `include_substeps` handling in `screen_summary`.

---

## Stack depth is reconstructed, not recorded

**Tracker:** T-002
**Status:** working, with a known limit
**Raised:** 2026-09-22, while adding the navigation stack view

The Screens tab reconstructs the navigation stack by replaying the coordinator's
`nav:open-` / `nav:back-` / `nav:tab-` markers. This is accurate for the app's
own navigation, and is the same back stack `AppCoordinator` holds.

Two cases it cannot see:

- **A trace that begins mid-session.** Markers before the capture window are not
  there, so a back with no matching push is clamped rather than popping the
  root. Depth is then a lower bound until the first tab reset resynchronises it.
- **Screens the coordinator does not own.** Anything pushed by the system or by
  a library — a permissions dialog, a third-party SDK activity — never emits a
  marker, so it does not appear in the stack even though it is holding memory.

Recording the depth directly as a counter (`SwagTrace.counter("nav_depth", n)`)
from `AppCoordinator` would make it a measured value rather than a replayed one,
and would survive a partial trace. That is a small change on the app side and
worth doing if depth ever becomes something budgets are asserted against.

---

## Onboarding modelled as one native route

**Tracker:** F-005
**Status:** partially addressed
**Raised:** 2026-09-22

`AppRoute.Onboarding` is a single route covering nine React Native steps. Trace
markers for those steps now exist as sub-screens, so a profile can attribute
cost to each one. The underlying product model is unchanged: the native side
still cannot express "the user is on the OTP step", so anything driven by route
state — deep links, analytics, back-stack restoration — remains coarse.

Splitting the route is a product-modelling decision rather than a tracing one,
which is why the tracing work did not do it.

---

## A/B measurement of graphify's token savings

**Tracker:** F-004
**Status:** not started
**Raised:** 2026-09-22

The token dashboard (`/tokens.html`) reports consumption only. It deliberately
shows no "tokens saved" figure, because savings require the cost of the path
not taken, and that counterfactual cannot be measured from a transcript — only
modelled.

`graphify benchmark` does model it, and its ratio should not be read as an
accounting result. Reviewing `benchmark.py` turned up three reasons to distrust
it:

- Both sides of the ratio are heuristics: the baseline is `words * 4/3` and the
  query cost is `len(text) / 4`. No tokenizer is involved.
- `corpus_words` comes from `.graphify_detect.json`, which Step 9 cleanup
  deletes. When it is missing the exception is swallowed and the code falls
  back to `nodes * 50` — so a run after cleanup silently benchmarks against a
  placeholder. This is what produced the "18,550 words" figure.
- Sample questions that match no node label are dropped from the average.
  Questions matching fewer nodes score *higher* reductions, so dropping misses
  biases the ratio upward. Only 3 of 5 questions scored on this repo.

The honest version answers one question twice — once via `graphify query`, once
by letting the agent read files — and compares real `usage` from both runs.
That is a measured delta rather than a counterfactual. It costs tokens to run
and is on-demand, not live, which is why it is not in the dashboard.

Answer quality has to be judged separately: a cheaper answer that is worse is
not a saving, and the token counts alone cannot see that.

---

## Screenshot testing with Maestro (visual regression lane)

**Tracker:** F-012
**Status:** not started. Designed, then parked by the user on 2026-09-24.
**Raised:** 2026-09-24
**Shareable plan:** [screenshot-testing-plan.html](screenshot-testing-plan.html)

### What

Maestro flows kept in this repo (`flows/<app_pkg>/<flow>.yaml`) take a
`takeScreenshot` at named checkpoints. swagperf compares each screenshot with an
approved baseline for that app, cohort, device class, flow and checkpoint, and
fails the run on an unexpected change. A person reviews the diff in the dashboard
and approves it, and the approved image becomes the new baseline.

### Why

swagperf sees timings, frames and RAM usage, but not how a screen looks, so a
build that renders a broken layout quickly passes every gate. The Maestro POC
(`~/Documents/app-automation-poc/maestro`) keeps ADB screenshots as evidence but
never compares them: its report only says "Review screenshots for visual
regression if needed" (`runners/maestro_worker/evidence.py`). ADR 0001 already
names Maestro as the executor for repeatable CI plans. This is the first lane
that would use it.

### Decisions already taken

- **A regression gate, not only a gallery:** baselines, diffs, approval, and a
  non-zero exit code.
- **A separate lane from Perfetto runs:** never inside a measured trace window,
  because screencaps cost CPU and would skew frames and TTID. Visual runs link to
  perf runs by app build and device.
- **Flows live in swagperf**, not in the POC catalog. Importing POC flows can
  come later.
- **Android first.** The comparison doesn't depend on the platform. The iOS
  simulator lane comes later.
- **swagperf does the comparison, not Maestro.** Maestro 2.10 has
  `assertScreenshot` (`path`, `thresholdPercentage`, `cropOn`, `optional`,
  checked in the installed jar). It stops the flow at the first mismatch and has
  no region masks, per-device baselines or approval step. Flows only take
  screenshots; swagperf compares them.

### Shape of the work

- **Run.** Command:
  `maestro --device <serial> test <flow> --test-output-dir <dir> --format junit --output <dir>/junit.xml -e APP_ID=<pkg> --no-ansi`.
  - Screenshots are collected from the flow's `manifest.json` (artifact kind
    `TAKE_SCREENSHOT`), never from guessed paths.
  - The first failed step comes from `commands.json`.
- **Compare.** With Pillow:
  - mask the status bar and fractional regions from an optional
    `<flow>.visual.json`;
  - count pixels over a per-pixel tolerance;
  - find changed regions on a grid, and write a diff overlay.
- **Statuses:**

  | Status | Meaning |
  |---|---|
  | `pass` | Within tolerance |
  | `changed` | Split into `layout_changed` / `render_changed` once layout hashes exist |
  | `new` | No baseline for this key |
  | `missing` | A baseline exists but this run didn't capture it |
  | `size_changed` | Different dimensions; never resized to force a match |
  | `error` | No screenshots, a failed Maestro step, or a cohort mismatch. Never counts as a pass. |

- **Exit codes:** 0 all pass, 1 any failure, 2 only `new` checkpoints waiting
  for approval.
- **Modules:**
  - `swagperf/maestro.py`: the adapter, on the same subprocess and watchdog
    pattern as `flashlight.run_audit`. It finds the binary through
    `SWAGPERF_MAESTRO`, then PATH, then `~/.maestro/bin`, and checks for JDK 17
    or 21 first.
  - `swagperf/visual.py`: comparison, baselines and approval.
  - `capture.py`: display info and device prep (SystemUI demo mode and
    animations off, always restored).
  - `store.py`: `visual_runs`, `visual_checks`, `visual_baselines`, with
    approval history.
  - `jobs.start_visual`, under the capture lock.
  - CLI `swagperf visual run|list|show|approve`.
  - `/api/visual*` routes that serve images by database id.
  - Design-system `ImageFrame` and `ImageCompare`.
  - A Visual page, and an Overview line: "Visual: n/m pass on this build".
- **After v1:**
  - the iOS simulator lane;
  - running a flow inside a Perfetto session;
  - automatic tracker issues for visual regressions (a `visual:` signal kind in
    `triage.signals_of`);
  - importing POC catalog flows;
  - the CI lane.

### Several cohorts with different layouts

Pixel diffing on its own isn't robust across cohorts. It only knows "different
from the baseline", so cohort B compared with cohort A's baseline reads as a
regression. Four additions make it robust:

1. **Cohort goes into the baseline key:**
   `(app, cohort, device class, flow, checkpoint)`.
2. **The cohort is pinned, not inferred:** a fixed test account per cohort (the
   POC has `config/test-data/`) or a forced-cohort override in debug builds.
3. **The cohort is checked at run time.** The app reports it, for example as a
   `cohort:<id>` trace marker or a test tag the flow asserts. A mismatch is an
   `error`, never a `changed` diff.
4. **The data is frozen, and the layout recorded.**
   - Runs use the mock environment, with recorded `/page/fetch` responses per
     cohort.
   - Each checkpoint stores a hash of its layout response, or its layout-contract
     version. A diff can then say `layout_changed` (the backend sent a new layout:
     expected) or `render_changed` (same layout, different pixels: likely an app
     regression).

Baselines multiply as cohorts × device classes × checkpoints (5 × 3 × 20 is 300
images). Keep pixel baselines for a handful of key screens per cohort, and cover
the rest with the layout checks under "Device sizes".

### Keeping baselines current

- **An intentional UI change is approved, not re-recorded.** It arrives as
  `changed` with a diff. A reviewer approves it per checkpoint, or in bulk per
  flow, cohort or device class, with a note. Every approval is kept (who, when,
  which build, why), so one can be rolled back.
- **The whole matrix in one pass.** A rebaseline run covers every cohort and
  device class, and identical changes across device classes are grouped for one
  approval.
- **Housekeeping shows up as statuses:**
  - backend layout changes arrive labelled `layout_changed`;
  - checkpoints no longer captured read `missing`;
  - baselines with no run in 30 days are flagged as possibly dead.
- **Flows stay stable by targeting ids** (Compose `testTag`, `resource-id`),
  never on-screen text.
- **Where baselines live.** Once a CI lane exists, baselines should live where
  the UI change is reviewed: committed to the app repo with Git LFS, so new
  images show up in the pull request.

### Device sizes

A pixel baseline never carries across screen sizes, so there are two layers:

- **Pixel baselines on a fixed matrix of device classes, not phone models.**
  - About three classes: a small phone, the common 393–412 dp width, and a large
    or foldable screen.
  - Plus font scale 1.3 and dark mode where supported.
  - Emulators with fixed profiles in CI; the Vivo stays for smoke runs, because
    vendor skins change fonts and system bars.
  - The key is resolution + density + font scale + theme. An unknown class reads
    `new`.
- **Layout checks at any size, with no baseline.** These are read from the view
  hierarchy:
  - key elements are visible and fully on screen;
  - interactive elements don't overlap;
  - touch targets are at least 48 dp;
  - key labels aren't cut off with an ellipsis;
  - nothing sits under the system bars.

  They run on every device and cohort.

One experiment comes first. Maestro 2.10 saves a view hierarchy only for failed
or warned steps. Try three ways to get one at each checkpoint: an intentionally
optional assert, `maestro hierarchy` between flow segments, and
`uiautomator dump` (checking it doesn't clash with Maestro's driver).

### Watch out for

- **Home shows a live camera preview.** Mask it, or the Home checkpoint always
  fails.
- **Maestro's device server hangs on the Vivo after Store→Rewards** (POC
  README). The POC drives its two real scenarios with raw ADB taps for this
  reason.
- **Use JDK 17 or 21.** Java 25 hangs Maestro's Android driver.
- **Restore the device.** Device prep (animations off, demo mode) must always be
  undone. A perf capture should warn if animations are still off.
- **Keep the model away.** No screenshot is ever sent to it, the same boundary
  swagperf keeps for traces.

### Revisit when

- work starts on ADR 0001's Maestro CI lane or its contract registry;
- a UI regression reaches a build that a screenshot would have caught;
- a phone where Maestro drives Swag Pay without the Vivo hang is attached, or an
  emulator lane exists;
- Swag Pay has cohort test accounts or a forced-cohort override;
- the user asks.

### Open questions

- Which is the source of truth for cohorts: test accounts, a forced override, or
  both?
- Where do baselines live once CI exists: the local store, or the app repo with
  Git LFS?
- Which device classes make up the matrix?
- How is a view hierarchy captured at each checkpoint?
