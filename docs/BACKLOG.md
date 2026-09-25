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

---

## iOS lane beyond the simulator

**Tracker:** F-013
**Status:** simulator lane shipped; the rest not started
**Raised:** 2026-09-24, while building the iOS lane ([ADR 0002](decisions/0002-ios-via-xctrace-normalised-to-perfetto.md))

### What

The iOS lane records Swag Pay on an iOS Simulator today. These are the parts it doesn't
have yet.

1. **A physical iPhone.**
   - devicectl for discovery, launch, terminate and lock state, plus the display's refresh
     rate (`devicectl device info displays`).
   - `xctrace record --device <udid>` with Hitches and Frame Lifetimes for frames, and
     Thermal State for heat.
   - Activity Monitor for RAM usage, in place of sampling from the Mac.
   - Battery needs a helper, because devicectl doesn't report it.
2. **Frame deadlines per frame.** On a 120 Hz ProMotion screen a frame is due every
   8.3 ms, not 16.67 ms. Hitches carry each frame's own expected interval; use it (T-004).
3. **iOS budgets.** Set them from physical-device runs, not carried over from Android.
   Until then, iOS runs have none.
4. **A true cold start.** iOS keeps an app's files cached between launches.
   - Offer a reboot-first mode (`devicectl device reboot`; on the simulator, shutdown and
     boot).
   - Mark a stress test's first session as its warm-up. The spike's first launch after an
     install took 1.83 s, the next two 0.51 s.
5. **Manual sessions and live markers.**
   - An unbounded `xctrace record`, stopped with SIGINT, with the process handle held in
     `jobs.py`.
   - Live markers from `log stream --predicate 'subsystem == "com.swag.pay.trace"'`.
6. **Per-screen CPU.** An iOS trace has no scheduler data. Time Profiler samples could
   give a sampled estimate; System Trace an exact one, at a far larger trace size.
7. **Competitor apps.** Spike first. App Store builds lack `get-task-allow`, so test what
   an all-processes recording can attribute to them (launch signposts, footprint).
8. **Hermes heap on iOS.** The JS side must emit `mem.hermes_heap` on both platforms; the
   converter already turns `counter` signposts into process counters.

### Why

The simulator runs the app on the Mac's CPU. It is good for checking the pipeline and for
comparing one simulator run with another. It says nothing about how the app performs on a
phone, and frames can't be measured on it at all.

### Watch out for

- Keep physical and simulator runs apart everywhere. The `simulator` column already does
  this; don't key anything on the device name alone.
- The bundle id is still the prototype's placeholder, `com.cambench.compose.ios`. Change
  it in `apps.json` and `iosApp.xcodeproj` together, and before recording runs that should
  be kept.

---

## Killcam on the swagperf design system

**Tracker:** F-015 (Killcam F-001)
**Status:** Killcam's half possibly shipped in Killcam `44ec8e0` (2026-09-24, "Rebuild the
dashboard on the swagperf design system"); a developer or the user confirms. What's left
here is step 11 of the joint plan under "One tool": taking `kit/`'s generic parts upstream.
**Raised:** 2026-09-24, when the user asked for Killcam to look and behave like swagperf
**Killcam:** `~/Documents/killcam`. The dashboard is in `dashboard/`, the wire contract in
`dashboard/src/api/types.ts` and the API in `docs/API.md`.

### What

Rebuild Killcam's web dashboard from swagperf's design system (`frontend/src/design`), so
its pages look and behave like swagperf's: the same tokens, type, components, shell
(sidebar, top bar, page header) and conventions. The panels stay the same, and so do the
API and what Killcam captures. This is step 1 of F-016.

### Why

The user wants the two tools to become one product (F-016). Today they share nothing on
screen:
- Killcam's dashboard is one hand-written stylesheet (`dashboard/src/styles.css`) with its
  own amber accent and system fonts.
- It has a hash router and its own stores, and no tests or lint.
- swagperf's pages are built only from the design system, and a lint rule and a showcase
  test enforce it (T-003).

If the UI is done first, on the same parts swagperf uses, the merge is wiring rather than
a second redesign.

### Decisions already taken

Taken in Killcam on 2026-09-24 (Killcam's BACKLOG, "The dashboard rebuilt on swagperf's
design system"). The user's answers to Q2 and Q7 are still open.
- **Vendor, don't import.** swagperf's `frontend/src/design` is copied exactly into Killcam's
  `dashboard/src/design/` by `scripts/sync-design-system.sh` and pinned in
  `dashboard/design-system.lock` (at `d007f5a`). Killcam wraps its own parts in
  `dashboard/src/kit/` and never edits `design/`, so "the later merge is a deletion". This
  replaces the recommendation under Shape of the work to build inside swagperf's
  `frontend/`. Both product managers now recommend keeping the vendored copy until Q7 is
  answered.
- **Fonts are bundled** (Poppins and Zalando Sans Expanded, about 140 KB), because the phone
  may be offline.
- **The shell follows swagperf's:** Analyse, Run and Data groups; a session picker with
  "Follow live"; a Session details dialog in place of the Device page; a phone layout for
  the in-app window (`?embed=1`).
- **Wording follows swagperf's rules:** no playful copy, status never by colour alone, a unit
  on every number.
- **Two copies, one guard.** swagperf's T-003 lint rule and showcase test guard only
  swagperf's copy. Killcam T-008 adds a check that flags local edits and drift from the
  locked commit; swagperf takes `kit/`'s generic parts upstream into `frontend/src/design`,
  each meeting T-003 (step 11 of the joint plan).

### Shape of the work

- **Where the code lives.** Decide this first (see Open questions).
  - Recommended: build Killcam's pages inside swagperf's `frontend/` as a lane, with a
    second build that outputs only the Killcam lane into
    `killcam-core/src/main/resources/killcam-web`. The phone, Rozenite and
    `adb forward` keep getting their dashboard from the device.
  - Copying the design system into the Killcam repo makes two copies that drift, and
    T-003's lint rule and showcase test would guard only one of them.
- **Map Killcam's shell onto swagperf's:**

  | Killcam today | swagperf's convention |
  |---|---|
  | KILLCAM wordmark, app name, version, build type and device in the top bar | Top-bar title and subtitle, and a session box in the page header, like the run box |
  | Session selector: Live, saved and crash sessions | One picker, like Run: the one place a session is chosen, with "Follow live" in place of "Follow the latest run" |
  | "Viewing saved session (read-only)" banner | The run box's "Older run · go to latest" |
  | Sidebar groups "Session" and "Live app", with icons and count badges | Sidebar groups Analyse, Run and Data, numbered items, two-letter rail codes |
  | Device panel | A "Session details" dialog like Run details, with "not recorded" gaps and Copy details |
  | "Watch killcam" from a crash into Replay | Links land on the thing they name: Replay opens at that moment and rings it |

- **Components the design system lacks.** Each goes into `frontend/src/design` as a
  generic component and onto `/design-system`, as T-003 requires:
  - a screenshot frame and a replay player (F-012's plan already names `ImageFrame`);
  - a JSON tree and an HTTP body viewer;
  - a split view: a list with a detail pane;
  - a virtualised list, because logs run to thousands of rows;
  - a stack trace view that highlights the app's own frames;
  - a key-value editor for prefs, flags and MMKV, and a SQL query box;
  - a PIN screen and a connection indicator.
- **Three layouts.** Killcam is shown in a laptop browser, in the phone's in-app window
  (`?embed=1`) and in the React Native DevTools panel (`?embed=devtools`). swagperf is
  laptop-first. The design system needs a compact density and a phone layout for the
  in-app window.
- **Fonts.** swagperf loads its fonts from Google Fonts when the page opens
  (`frontend/index.html`). Killcam is served from the phone and has to work without
  internet, so the fonts must be bundled. That adds to the debug APK's size.
- **Keep the API unchanged.** `dashboard/src/api/types.ts` stays the wire contract. This
  step changes only the UI, so `./gradlew :killcam-core:demo` and `npm run mock` still
  work as test data.
- **Tests.** Add Killcam's pages to the run skill's `tour`
  (`.claude/skills/run-perfetto-monitor/`), against Killcam's mock or demo server.

### Watch out for

- **Wording.** swagperf's rules apply to every page Killcam brings:
  - status is never colour alone (✓ ! ✕);
  - every number has its unit (B-001);
  - unmeasured reads "not measured", and missing metadata reads "not recorded";
  - two signals on one screen never contradict each other (B-002).

  Killcam's playful strings need a decision: "No crashes. GG.", the upper-case "CRASH"
  and "FATAL" badges, and "killcam" used as a verb.
- **Colour.** Killcam's accent is amber and its errors are red. In swagperf, KRAFTON red
  is only for titles and fail has its own crimson, so red can't also be Killcam's brand
  colour.
- **The phone window.** It's a WebView on a small screen. Check touch targets, and check
  load time on a mid-range phone, not only on a laptop.

### Open questions

Merged with Killcam's questions under "One tool", in Killcam's numbering: Q2 and Q7 (where
the code and the repository live) and Q5 (the name and brand).

---

## One tool: Killcam and swagperf combined

**Tracker:** F-016 (Killcam F-003)
**Status:** planned jointly with Killcam's product manager on 2026-09-24 (the joint plan
below); no code yet. Waits on the user's answers to the open questions at the end.
**Raised:** 2026-09-24, when the user asked to "club" the two tools
**Killcam:** `~/Documents/killcam`. It is integrated into Swag Pay on an uncommitted
branch in `~/Documents/swag-pay-killcam`
(`apps/mobile/composeApp/src/androidMain/kotlin/com/swag/pay/debugtools/KillcamSetup.kt`).

### What

One product for Swag Pay's performance and debugging. swagperf's lanes (Perfetto ·
Android, Instruments · iOS, Flashlight · Android) and Killcam's panels share one shell,
with links between them where they describe the same screen or error. This is step 2,
after F-015.

### Why

Both tools look at the same app through the same markers:
- Killcam's replay gets its screens from the `SwagTrace` markers that swagperf reads.
- Killcam's Crashes panel lists the same `SwagErrors` JS error records that swagperf's
  Stability page reads.

They answer different questions, though:
- swagperf: is this build slower or heavier than the last? It measures and judges across
  builds.
- Killcam: what exactly happened in this session, live or in the moments before a crash?

A developer who sees a JS error on Stability has no way to see what the user did before
it. A tester who marks a slow screen in Killcam has no way to see what that screen costs.

### Who uses each

| | swagperf | Killcam |
|---|---|---|
| Who | A developer on a Mac, with an Android phone over USB or a booted iOS Simulator; the product-manager agent after every run; later CI (`analyse --fail-on`, ADR 0001) | QA on the phone alone (the bubble, a shake, the notification); developers over `adb forward`, Wi-Fi with a PIN, or React Native DevTools; PMs and backend engineers |
| Build | Whatever is installed. The iOS lane refuses Debug builds. | Debug builds only. Release builds link the no-op. |
| Unit | A run, kept in `history.db` and compared across builds | A session: live, saved, or saved at a crash, and kept on the phone |
| Output | A verdict against budgets, a tracker issue, a PR summary | Evidence: a replay, a HAR file, a bug bundle zip |

### Overlap

| Area | swagperf | Killcam | In one tool |
|---|---|---|---|
| Crashes | Per run, from the crash log or a fatal signal, on both platforms (F-014) | Fatal and non-fatal JVM crashes with their stacks, and the session saved at the crash, with its replay | Keep both, linked by app version and error name |
| JS errors | `error:js:` markers and `SwagErrors` records from the trace. Hermes stacks resolved against the build's source map, a fingerprint per crash site, fatal or non-fatal. | The same records, put back together in the app (`KillcamTraceBridge.errorLine`) and recorded with `Killcam.recordError(…, fatal)`, so the fatal flag is kept (fixed about 15:20 on 2026-09-24). The raw stack is kept verbatim and isn't resolved. | One record format tested on both sides (T-005, Killcam T-014). Linked by the `error:js:<source>:<Name>` identity and app version, labelled "same error", not by fingerprint: a debug build's JS comes from Metro, so a release source map never fits it |
| Hangs | Microhangs and hangs (F-014) | None | swagperf only |
| Screens and markers | Every screen visit with its duration, sub-screens, the navigation stack, timed `step:` and `action:` spans, counters | Screen starts, instant markers and async action starts only. The bridge skips `nav:` markers and doesn't forward timed spans (`platformTraceBegin`). | Screen names are the key that joins the two |
| RAM usage per screen | Peak RAM usage and RAM growth per visit | None: its wire contract has no RAM, CPU, frame or hang data | swagperf only; Killcam's screen events link to it |
| Screenshots | None. F-012 (parked) is a visual regression lane. | On screen changes, around taps and when the screen settles, as evidence | Kept apart. Screenshots cost CPU, so they must never run during a measured trace (F-012's own decision). None of F-012's revisit triggers has fired. |
| Device and build | Run details: device, device state and app build, with "not recorded" gaps | Device panel: app, device, runtime, and rows the app adds | One details dialog |
| Live feed | Manual: live markers while recording | Replay and Logs, live | Keep both: Manual traces, Killcam doesn't |
| Copilot | Rule-based answers over the run history (F-001 adds a local model) | None | Open question Q6. Joint recommendation: nothing from Killcam in v1 |
| Security | Loopback only. Since T-001 (2026-09-25): a loopback `Host` allow-list, a loopback `Origin` when one is sent, and `X-Swagperf: 1` on every write | Loopback by default, a `Host` allow-list, `X-Killcam: 1` on every write, and a PIN for Wi-Fi sharing | No combined server. The Killcam lane embeds Killcam's own dashboard, so Killcam's rules stay in charge of the phone. swagperf's server only reads link keys; T-001 copied Killcam's rules |

### Shape of the work

- **Navigation.**
  - Killcam becomes a lane in the top bar's first control, next to Perfetto · Android,
    Instruments · iOS and Flashlight · Android. swagperf's rule stays: everything to the
    right of that control follows the lane.
  - This follows the user's decision on F-008: lanes stay separate behind a switch, not
    mixed in one view.
  - In the Killcam lane, the sidebar keeps swagperf's three groups:
    - **Analyse** (read the session in view): Replay, Network, Logs, Crashes.
    - **Run** (act on the live app): Mocks, Flags, Remote Config, Actions.
    - **Data:** Sessions (saved and crash sessions, like History) and Storage.
    - Device moves into the session details dialog.
- **Links between lanes.** These are the reason to combine:
  - Stability → the Killcam sessions with the same JS error, matched by the
    `error:js:<source>:<Name>` identity and app version.
  - A Killcam screen event → the Screens page of the latest run that has that screen.
  - A Screens row → "open a Killcam session on this screen".

  Swag Pay can't be profiled and debugged in the same process (see Watch out for), so
  links match by screen name, JS-error identity and app version, never by timestamp.
- **Servers.** Two, and swagperf's never forwards to the phone (see "Agreed with
  Killcam's product manager").
  - The on-device server stays, because the phone window, Wi-Fi sharing and Rozenite
    need it.
  - The laptop reaches it through `adb forward`, and the Killcam lane embeds Killcam's
    own dashboard from `127.0.0.1:8090`. Its writes stay on its own origin, so they keep
    `X-Killcam`, and Killcam's server never has to approve a cross-origin write.
  - swagperf's server only reads link keys (F-018).
- **One launcher.** `perfetto_init` sets up the port forward, and `doctor` reports
  whether Killcam is running in the app on the device by asking its `/api/status` (F-017).

### Agreed with Killcam's product manager

Agreed on 2026-09-24. These are recommendations to the user, not decisions: each waits on
the open question it names.
- **Debug builds (Q3, B-009).** swagperf never judges a debuggable build, or a build whose
  trace carries Killcam's marker, so a build with Killcam's `allowNonDebuggable` is caught
  too. Every capture refuses such a build unless the capture opts in. An opted-in run is its
  own kind, *debug build*, and names Killcam when the marker is there. It follows ADR 0002's
  simulator rules (no budgets, verdict capped at warn, no benchmark, skipped by triage) and
  never shares a baseline with other runs. The kind is read from the build details recorded
  at capture and from the trace, so `reextract` keeps it. Killcam's release no-op writes no
  marker.
- **Killcam's trace marker (Killcam F-016).** One fixed name, carrying Killcam's version,
  the pause state, the capture switches, and network conditions as a preset name or
  `custom`.
  - It is written at install (`KillcamRuntime.start()`), on every foreground
    (`onForeground()`), and on every change to pause or network conditions, so warm starts
    and manual sessions carry it too.
  - Pause and network conditions change in pure-JVM `killcam-core`, which can't call
    `android.os.Trace`. So core gets an internal state-change callback that the Android
    runtime registers. It isn't a `LiveListener`, which would encode every event (Killcam
    T-005), and the same callback fixes Killcam B-005.
  - It is a zero-length `beginSection`, with names under 127 characters. There is no public
    API change.
  - swagperf reads rule 13 (markers carry only fixed names and outcome classes) as allowing
    this: build constants and states from a fixed set, never app data. If a developer reads
    the rule strictly, the version comes out.
- **Two servers: embed, never forward (Q1).** The Killcam lane shows Killcam's own dashboard
  (F-017, Killcam F-017). A forwarder would hand Killcam's loopback trust (Killcam T-001) to
  anything that reaches `:8787`, and forwarding `/api/live` would route payment bodies
  through swagperf's server.
- **Link keys (F-018).**
  - swagperf's server may GET `/api/sessions`, `/api/crashes` and `/api/info` only, when a
    page is viewed.
  - It keeps session ids, screen names (`SessionSummary.screens`, added by Killcam F-018),
    the JS-error identity and the app version, and drops the rest.
  - It never calls `/api/timeline` or `/api/sessions/{id}`, which hold bodies, logs and tap
    text. It never writes, stores nothing in `history.db`, and gives the Copilot nothing.
- **Errors join on identity, not fingerprint.** The join is on `error:js:<source>:<Name>`
  plus the app version, and the link reads "same error", never "same crash site". A debug
  build loads its JS from Metro, so a release source map never fits it, and F-014 refuses a
  map from another build.
- **Killcam's cost (Killcam F-004).** It is measured as two states, without and with
  Killcam, as opted-in stress tests (`-n 10`) that record network conditions from the
  marker. Pausing isn't "off": it keeps starting logcat every 1 s, waking the main thread
  every 2.5 s and serialising request bodies. So swagperf gets no pause switch (Q9).

### Joint plan

⛔ = must land before `killcam-integration` merges into Swag Pay. Killcam's IDs share
numbers with swagperf's, so they are always prefixed "Killcam".

| # | Owner | swagperf | Killcam | Title | Priority | Depends on | Notes |
|---|---|---|---|---|---|---|---|
| 1 ⛔ | swagperf | B-009 | Other trackers (F-004) | A debuggable or Killcam build is never judged: refused unless the capture opts in, then labelled | P1; P0 once `killcam-integration` merges | Q3 | Refusing needs only the debuggable flag (d43fe8a). Naming Killcam needs step 3. Its own baseline. |
| 2 ⛔ | swag-pay-killcam | — | T-007 | Swag Pay's `KillcamTraceBridge` out of release builds | P1 | — | **Killcam.** Whether it blocks the merge is the developer's call. |
| 3 | Killcam | — | F-016 | Killcam names itself in every trace of its build | P1 | — | **No-op:** none. **Contract:** none. See "Killcam's trace marker" above. |
| 4 | swag-pay | T-005 | T-014 | One `SwagTrace` and `SwagErrors` definition, one shared fixture | P2 | — | Pins the `error:js:` identity. Land it before the bridge is committed. |
| 5 | Killcam | — | F-004 | What Killcam costs Swag Pay: without and with it, as stress tests (`-n 10`) | P1 | 1, 3 | Each run records network conditions. The pause half is dropped (Q9). |
| 6 | swagperf | T-001 | — | Origin and Host checks, copying Killcam's rules | P0 | — | Before step 9. |
| 7 | Killcam | — | F-017 | Killcam's dashboard can be embedded in swagperf | P2 | Q1 | **Security:** `frame-ancestors` loopback only. |
| 8 | swagperf | F-017 | Other trackers (F-003) | Killcam lane: the embed, `perfetto_init`'s port forward, and `doctor` via `/api/status` | P2 | 7; the lane-switch bug (TESTING-PLAN IOS-D7, S-09) | A fourth lane in the top bar's first control. |
| 9 | swagperf | F-018 | Other trackers (F-003) | Links by screen name, JS-error identity and app version | P2 | 4, 6, 8, 10; Killcam T-001 | Read-only GET of three endpoints; nothing stored. |
| 10 | Killcam | — | F-018 | Crashes and screens link out to swagperf; sessions list their screens | P2 | 4, 8 | **Contract:** `SessionSummary.screens`, empty for older sessions; `types.ts`, `Models.kt`, API.md and the mock server change together. |
| 11 | both | F-015 | T-008 | One design system: a lock check in Killcam, and `kit/`'s generic parts upstream in swagperf | P2 | Q2, Q7 | Parts taken upstream meet T-003. |
| 12 | swagperf | F-016 | F-003 | One tool | P2 | 1–11; Q5, Q7 | The umbrella. |

### Watch out for

- **T-001 before F-018.** swagperf's server reads Killcam's link keys. Until T-001 lands,
  any website open in the browser could read them back through it. Forwarding was dropped
  for a stronger form of the same reason: through a forwarder, any website could change
  the phone (mocks, flags, prefs, SQL writes, file deletes and actions). Killcam blocks
  this today. T-001 should copy Killcam's rules. Done 2026-09-25: T-001 copied them (a loopback
  `Host`, a loopback `Origin` when sent, and `X-Swagperf: 1` on every write).
- **Measuring Killcam by mistake (B-009).** Killcam installs first in
  `Application.onCreate` and takes screenshots on screen changes and taps. A swagperf run
  of that debug build would measure that work too.
- **Two readers of one format.** `SwagTrace` and `SwagErrors` now have two readers.
  Killcam's bridge sees only some of the markers, and until T-005 the `error:js:` identity
  it passes to Killcam is whatever the uncommitted bridge sends. Keep one definition in
  `swag-pay` and test both readers against it (T-005, Killcam T-014).
- **Payment data.** Killcam captures request and response bodies, up to 128 KB each and
  24 MB in total. Don't copy them into `history.db`. The Copilot, and any model, must
  never see bodies or screenshots: the same boundary swagperf keeps for traces. swagperf
  never calls `/api/timeline` or `/api/sessions/{id}`, which hold bodies, logs and tap
  text (Killcam B-003).
- **Nothing to show yet.** Swag Pay runs on `FakeMobileRepository`, and the integration
  adds no `KillcamInterceptor`. Network and Mocks stay empty until the app makes real
  HTTP calls through a client that has the interceptor. React Native `fetch` needs its
  own client factory.
- **Lane switching.** Switching lanes is suspected of losing the Android app filter
  (TESTING-PLAN IOS-D7, S-09). A fourth lane would make that worse, so settle it first.

### Open questions (the user's call)

These are merged with Killcam's open questions and use Killcam's numbering. Killcam's Q8,
the package name, is Killcam's alone. Both product managers agree on every recommendation
below. When the user answers one, record the answer and its date in the items it blocks,
in both trackers, and remove it here.

| # | Question | Blocks | Joint recommendation |
|---|---|---|---|
| Q1 | One server or two? | F-016, F-017, F-018; Killcam F-003, F-017 | Two. The Killcam lane embeds Killcam's own dashboard; swagperf's server only reads link keys and never forwards. |
| Q2 | Where does the shared dashboard code live? | F-015; Killcam F-001, F-003, T-008 | Keep Killcam's vendored copy until Q7 is answered. `kit/`'s generic parts go upstream into swagperf's design system. |
| Q3 | May swagperf capture debug builds at all? | B-009; Killcam F-004 | Only when the capture opts in, as its own labelled kind that is never judged (see "Agreed with Killcam's product manager"). |
| Q4 | Does the in-app window stay Killcam-only? | F-016; Killcam F-003 | Yes. The phone can't reach the laptop, so it can show only what the phone holds. |
| Q5 | What is the combined product called, and whose brand does it wear? | F-016; Killcam F-003 | Decide once the links (F-018, Killcam F-018) are in use. |
| Q6 | May the Copilot read Killcam sessions, and what may it see? | F-001, F-016; Killcam F-003 | Nothing in v1. Later, link keys only: never bodies, headers, logs or screenshots. |
| Q7 | Does Killcam stay in its own repository? | F-015, F-016; Killcam F-003 | Decide once the links are in use. Until then it stays. |
| Q9 | Drop "let swagperf pause Killcam during a capture" from Killcam F-004? | Killcam F-004 | Yes. Pausing isn't "off", and a pause switch would treat a Killcam build as a performance run. |

For a developer, not the user:
- Does Killcam T-007 (the bridge runs in release builds) block the `killcam-integration`
  merge? Both product managers propose that it does.
- How does Killcam T-001 close loopback trust? If it adds a per-install secret, F-018's
  read must carry it.
- Were the Android runs behind P-001–P-004 debuggable builds? Their Run details would say
  (B-009).

---

## Camera performance: Swag Pay's scanner

**Tracker:** B-010, F-019, F-020, F-021, F-022, and the `camera:` family in T-005. Killcam's
side: Killcam F-019, Killcam F-020, Killcam T-015, and the `camera:` family in Killcam T-014.
**Status:** planned jointly with Killcam's product manager on 2026-09-25; no code yet. The
user answered Killcam Q10, Killcam Q11 and Q-D on 2026-09-25 (see "Answered by the user");
the open questions at the end still wait on the user. **Parked by the user on 2026-09-25**
(F-019–F-022 and the camera part of T-005 are `backlog`): "Just keep those as backlog tasks,
to be done after we have another app which will be the focus". See "Decisions already
taken" and "Revisit when". B-010 is not parked (see Joint order).
**Raised:** 2026-09-25, when the user asked for camera-specific performance logs for Swag
Pay's scanner, in Killcam and in swagperf: "camera first frame, time to process each frame,
time to resolve a QR, memory consumption during camera, any memeory leaks".
**App code:** `~/Documents/swag-pay/apps/mobile/composeApp/src/`: `commonMain/.../camera/`
(`CameraHomeScreen.kt`, `CameraModels.kt`), `androidMain/.../camera/CameraPlatformSurface.android.kt`
and `iosMain/.../camera/CameraPlatformSurface.ios.kt`.

### What

Five measurements of the QR scanner on Swag Pay's Home screen, on each lane where the
platform allows them:

| Metric | Android | iOS |
|---|---|---|
| Camera first frame | Each open, from Home's mount (the scanner's first composition) to the first analysed frame (`camera:open`), on every mount, as the user asked on 2026-09-25. At startup, see B-010. | Not measured on the Simulator, which has no camera (`extract.py:516`). On a physical iPhone, once that lane exists: `configureAndStart` to the first sample buffer. |
| Time to process each frame | ML Kit's decode time per analysed frame (`camera:decode`): count, first decode, p50, p90 and max in ms. | Not measurable. `AVCaptureMetadataOutput` decodes inside AVFoundation, and the app sees only a detection. Changing the decoder is the user's call, not instrumentation. |
| QR resolve time | Code found → validated (`camera:qr_found` → `action:qr_validate_*`), and found → Pay screen shown (→ `screen:Pay#compose`). Also, for every QR registered, as the user asked on 2026-09-25: first frame → QR found and Home's mount → QR found (`camera:open` end or start → `camera:qr_found`). Those two measure the tester's aim unless a test QR is in view from the start (Q-E). | The first two, on a physical iPhone, from the metadata callback. |
| RAM usage while the camera is open | `mem.rss`, `mem.rss.anon` and `mem.rss.file` before `camera:open`, the peak while open, and after `camera:close`. | Not measured on the Simulator. On a physical iPhone, Activity Monitor ("iOS lane beyond the simulator", item 1). |
| Leaks | A signal from RAM usage across N open/close cycles in one process (F-021); proof from Java heap dumps (F-022). | Not planned. Instruments' Leaks would be a later spike. |

Killcam shows the scanner's events (camera states, failures, scan outcome classes) in its
sessions and links to swagperf's Camera page. Every judged number and every RAM figure is
swagperf's. Killcam also shows a timing summary per camera open and per QR registered,
labelled as a debug-build figure, with no RAM usage figures and no budgets; swagperf never
reads it. That is the user's answer to Killcam Q10 on 2026-09-25.

### Why

- **Home is the scanner, and startup ends on it, yet no real run has measured it.**
  - The startup model ends at `step:camera_open` → `step:first_qr_decode` (`budgets.py:18-21`,
    budgets of 180 ms and 120 ms at `:33-34`).
  - The app emits only instant milestones, so every device run falls back to Android's
    launch phases and is judged against the 420 ms camera-frame budget with a number that
    ends before the camera frame (B-010).
- **How the scanner works today** (read from the code on 2026-09-25):
  - **Android.** CameraX 1.6.1 Preview and ImageAnalysis at 1280×720, 15–30 fps
    (`CameraPlatformSurface.android.kt:203-229`), and ML Kit barcode scanning 17.3.0.
    - The analyser decodes at most one frame per 250 ms and closes the rest unread
      (`:240-246`, `:337`).
    - A repeated value is ignored for 1,500 ms (`:262`, `:338`).
    - The value is posted to the main thread (`:265`), where `QrValidator.validate` emits
      `action:qr_validate_<class>` without the value (`CameraModels.kt:26-43`).
  - **iOS.** `AVCaptureMetadataOutput` decodes QR codes (`CameraPlatformSurface.ios.kt:212-218`).
    The video output is used only for the first frame and then unhooked (`:269-277`).
  - **The 10 s "closed" scanner state is visual only.** The camera and the decoder stay on
    (`CameraHomeScreen.kt:112-116`; `enabled = true` at `:239`).
- **A trace already shows the camera without new markers.** Run #1 was recorded with the
  manual config, which has no `camera` atrace category, yet CameraX's own slices arrive
  through `atrace_apps`. Across 5 Home visits it has:
  - 5 × `CameraId-0#openCamera` (average 32.59 ms);
  - 5 × `CameraDevice-0#createCaptureSession` (average 143.35 ms);
  - 5 × `CX:bindToLifecycle`;
  - 242 `android.media.ImageReader#postEventFromNative` frame events.
- **Perfetto has no camera module in the version swagperf uses.** In the trace processor
  swagperf uses (v49), `INCLUDE PERFETTO MODULE android.camera` fails. It has
  `android.memory.heap_graph.*`, `android.memory.dmabuf`, `android.memory.process` and
  `android.gpu.memory`.

### Shape of the work

- **Markers (F-019, built by Swag Pay).** Fixed names and outcome classes only.

  | Marker | Shape | Notes |
  |---|---|---|
  | `camera:open` | Async, new cookie | From Home's mount, on every mount, to the first analysed frame, as the user asked on 2026-09-25. The mount is the scanner's first composition, where `session.start()` is called from the `AndroidView` update block (`:123-128`); that block is composed only once camera permission is granted (`:123`), so a permission prompt is never inside an open. Also from CameraX's restart after background, where Home doesn't remount (agreed earlier). Async because it runs from the main thread to the analysis executor. `start()` returns early while `binding` is true (`:184`), and `firstFrameDelivered` never resets today (`:156`, `:236-239`), so both need handling. |
  | `camera:decode` | Async, its own cookie | From `scanner.process` to `addOnCompleteListener` (`:258-274`). At most one in flight (`STRATEGY_KEEP_ONLY_LATEST`, closed on complete) and at most one per 250 ms. |
  | `camera:qr_found` | Instant, no value | When a value is accepted (`:262-265`). |
  | `camera:open_failed#denied\|unavailable\|closed` | Instant | `denied` and `unavailable`: `:72`, `:108`, `:196`. `closed`: the camera closed before its first frame; the app ends `camera:open` at close and emits this, and both tools read that open as "no first frame", never as a duration. Proposed by swagperf and agreed with Killcam's product manager on 2026-09-25: an unfinished `camera:open` followed by the next open, with the same name and cookie, can't be paired reliably. |
  | `camera:close#dispose\|background\|permission` | Instant, once per open | From `stop()`/`close()` and on ON_STOP / `applicationWillResignActive`. Added by Killcam's product manager: Killcam's bridge needs an end to summarise an open, and swagperf reads "RAM usage after" from it, because the camera stops on background while Home stays the screen. |
  | Existing `action:qr_validate_<class>`, `screen:Pay#compose`, `step:first_usable_camera_frame` | Unchanged | |

  - **Why a new prefix.**
    - `_extract` reads every `step:%` slice as a budgeted startup step (`extract.py:461-507`).
    - `action:` feeds the Screens action table and its 200-row action timeline
      (`screens.py:344-395`), and Killcam's bridge forwards action starts.
    - Four decodes a second would flood both tools.
  - **iOS later.** `camera:open` needs a new async signpost family in `swagsignpost.def`
    and `convert_ios.ASYNC_FAMILIES` (`convert_ios.py:39`). Instants and counters already
    convert (`:271-279`).
- **Metrics (F-020, swagperf).** A module like `stability.py`, stored with the run.
  - **Opens and decodes:** `select s.ts, s.dur from slice s join process_track pt on
    s.track_id = pt.id where s.name = 'camera:open' and pt.upid in (<app upids>)`.
    - Async slices sit on process tracks, as screen visits do (`screens.py:95-107`).
    - A slice that never closed (`dur = -1`) counts as "no first frame", never as a
      duration.
    - So does a `camera:open` that ends with a `camera:open_failed#closed` instant.
    - Percentiles are computed in Python, as `store.stress_stats` does.
  - **RAM usage:** the `mem.rss` and `mem.rss.anon`/`.file` counters from
    `process_counter_track`, scoped to the app's process as `screens.py:156-162` does, over
    `camera:open` → `camera:close`.
  - **Frames delivered:** `ImageReader#postEventFromNative` in the app's threads, set
    against `camera:decode`.
  - **Per scan.** The user asked on 2026-09-25: "when it registers a QR, it should log the
    metrics". For swagperf, that is one row per `camera:qr_found` in the run's camera data,
    shown on the Camera page and printed by the CLI. Each row has:
    - Home's mount → first frame for its open;
    - first frame → QR found;
    - Home's mount → QR found;
    - QR found → validated;
    - QR found → Pay screen shown;
    - decodes so far in the open, and decode p50, p90 and max so far, in ms;
    - the outcome class.
  - **Dashboard:** a Camera page in both lanes, plus Compare rows and the CLI.
- **Cycle test (F-021, swagperf).** One trace across N open/close cycles in one process.
  - The phone is driven over adb: raw taps, as the Maestro proof of concept does on the
    vivo, or background/foreground (Q-C).
  - RAM usage is read at the same point in every cycle, the first cycle is skipped as a
    warm-up, and the result is a trend in MB per cycle.
  - A sustained-scan mode on Home only reuses thermal drift (`extract.py:383-409`: 1 s
    skipped, at least 120 frames, one screen). It also records decodes and RAM usage while
    the scanner looks closed, since the camera stays on then.
- **Heap dumps (F-022, swagperf, with Swag Pay's manifest change).**
  - A separate config with `android.java_hprof` for `com.swag.pay`.
  - After the first and last cycle, count reachable camera classes: `select c.name,
    o.graph_sample_ts, count(*), sum(o.self_size) from heap_graph_object o join
    heap_graph_class c on o.type_id = c.id where o.upid in (…) and o.reachable group by 1, 2`.
  - The class summary tree comes from `android.memory.heap_graph.class_summary_tree`.
  - **The build (Q-D, answered 2026-09-25).** Swag Pay builds a separate profileable
    variant of the release build (`<profileable android:shell="true"/>`); the store release
    stays unchanged. Killcam's constraints on it, also recorded in Killcam T-007:
    - it depends on `killcam-no-op` like release. `releaseImplementation` doesn't apply to
      a new build type, so the variant needs its own no-op dependency or it won't compile;
    - it gets T-007's release stub of the bridge;
    - it carries no LeakCanary.
  - swagperf tells the variant apart from the trace: `package_list.profileable_from_shell`
    (in trace processor v49; run #1's `com.swag.pay` reads 0). A heap-dump run refuses a
    build that isn't profileable. Whether every other run also uses the variant is Q-H.
- **Capture config.**
  - **Cold capture** (`capture.py:9-32`): unchanged. It already has the `camera` category
    and a 131,072 KB buffer.
  - **Manual capture:** don't add `camera` back. It produced 2.2M camera-hardware slices in
    a 4-minute session, and removing it along with other unused sources cut the file from
    ~230 to ~53 MB a minute (`capture.py:388-395`).
  - **Spike before adopting either:** event-driven RAM usage (`kmem/rss_stat`) and the
    dmabuf events for camera buffers. Measure each on the V2514 first: MB per minute, and
    `tracing_lost` still passing.
- **Derived runs (competitors).** Run #2 (`money.super.payments`, cold, 5.0 s, V2514) shows:
  - the app's own CameraX slices (`CX:bindToLifecycle-internal`, `CX:unbindAll`) and 53
    `ImageReader` events, but none of Swag Pay's `CXCP#…` or `CameraId-0#…` names;
  - camera service and vendor HAL slices (`CameraHal::openSession` 8.85 ms,
    `CameraHal::configureStreams` 2 × 79.5 ms average), and vivo-only QR modules in
    `camerahalserver`.

  What that gives a derived run:
  - **Derived, labelled so:** camera open, from `CX:bindToLifecycle*` to the first
    `ImageReader` event in the app's own threads, and RAM usage over it. `ImageReader`
    isn't camera-only, so the figure is an estimate. An app on raw Camera2 or its own
    camera stack gets "not measured".
  - **Not measured:** decode time and QR resolve, because the decoder's work isn't named
    in the trace. Leak proof isn't possible either, because another app can't be
    heap-dumped.
  - **Never attributed:** camera service slices can't be tied to a client app by name.
  - **Budgets:** Swag Pay's budgets are never applied to another app (design rule 2;
    `extract.py:213-225`).
- **Budgets.** Existing, never checked on a device: time to first camera frame 420 ms,
  `step:camera_open` 180 ms and `step:first_qr_decode` 120 ms. Candidates, for the user to
  set (Q-B):
  - first frame when the camera reopens on a visit;
  - decode p90 per frame;
  - QR found → Pay screen shown;
  - RAM added while the camera is open;
  - RAM kept per cycle.

  None until a 10-session baseline exists on the V2514. Until then, camera metrics show
  values and raise no triage signals.

### Agreed with Killcam's product manager

Agreed on 2026-09-25. These are recommendations to the user, not decisions.

1. **The `camera:` family**, built by Swag Pay (F-019), including Killcam's
   `camera:close#dispose|background|permission`.
2. **Ownership.** B-010 (P0), F-020, F-021 and F-022 are swagperf's. There are no camera
   budgets until a 10-session baseline exists.
3. **The decoded QR value is never recorded** in markers, in Killcam or in swagperf. Only
   the outcome class is.
4. **Killcam shows no RAM usage figures for the camera.** Its Java and native heap row is
   never camera evidence, because it includes Killcam's own buffers.
5. **`camera:decode` is never forwarded to Killcam as one event per frame.** T-005 (Killcam
   T-014) gains the `camera:` family and its fixture, and says so.
6. **Links.** Camera events in Killcam link to swagperf's Camera page by screen and app
   version, never by timestamp. This is a later extension of F-018 and Killcam F-018, not
   a new item.

Killcam's own items:
- **Killcam F-019.** The bridge forwards the `camera:` family to Killcam's timeline, plus a
  per-open summary if Q10 is yes. It also flags "camera still delivering frames after
  `camera:close`". Confirmed on 2026-09-25 (Killcam Q10 answered): for every QR
  registered, a timeline summary and a Logs line (tag `camera`), and a final summary at
  `camera:close`, labelled as a debug-build figure, with no RAM usage figures.
- **Killcam F-020.** Confirmed on 2026-09-25 (Killcam Q11 answered yes). LeakCanary in Swag Pay's debug build only (Killcam Q11), shown as a
  non-fatal `leak:<class>` with class and field names only. It never touches swagperf's
  runs.
- **Killcam T-015.** Whether Home's replay frames contain the live preview.

None of these clashes with swagperf's items.

### Joint order

Nothing here has to land before `killcam-integration` merges. Killcam's IDs share numbers
with swagperf's (F-019 and F-020 exist in both), so they are always prefixed "Killcam".

| # | Owner | swagperf | Killcam | Title | Depends on |
|---|---|---|---|---|---|
| 1 | swagperf | B-010 | — | Startup judged against the camera-frame budget with a number that ends before the camera frame (P0) | Q-A for the fix; independent |
| 2 | swag-pay | T-005 | T-014 | The `camera:` family and fixture in the one `SwagTrace` definition | — |
| 3 | swag-pay | F-019 | — | Camera markers, Android first; the iOS `camera:open` signpost family later | 2 |
| 4 | swagperf | F-020 | — | Camera metrics and the Camera page | 3, B-009, B-010 |
| 5 | Killcam | — | F-019 | The bridge forwards the `camera:` family, with a summary per open and per QR registered (Q10 answered 2026-09-25) | 2, 3, Killcam T-007 |
| 6 | swagperf | F-021 | — | Camera cycle test and the leak signal | 4, Q-C |
| 7 | Killcam | — | F-020 | Leaks in debug builds through LeakCanary | Killcam Q11 answered yes on 2026-09-25; independent of 4–6 |
| 8 | swagperf | F-022 | — | Heap-dump runs in a profileable release variant | 6; Swag Pay's profileable variant (Q-D answered 2026-09-25) |

Killcam T-015 is independent.

Parked on 2026-09-25: steps 2 (the camera part only) to 8 wait for the user to bring the
camera work back. Step 1, B-010, stays open: it is wrong data shown as right today, not
camera work the user set aside. Killcam T-015 also stays open on Killcam's side.

### Decisions already taken

Settled before the work was parked, so it doesn't restart from zero:
- **Prefix and markers.** The `camera:` prefix, not `action:` or `step:`, with the markers
  in the table above:
  - `camera:open` from Home's mount on every mount, and from CameraX's restart after
    background, to the first analysed frame;
  - `camera:decode`, `camera:qr_found` and `camera:open_failed#denied|unavailable|closed`;
  - `camera:close#dispose|background|permission`, once per open.
- **Payment data.** The decoded QR value is never recorded anywhere; only its outcome
  class is.
- **Killcam's side** (the user's answers to Killcam Q10 and Q11):
  - Killcam shows timing summaries per open and per QR registered, labelled as debug-build
    figures. It shows no RAM usage figures and no budgets, and swagperf never reads them.
  - LeakCanary goes in the debug build only.
  - `camera:decode` is never forwarded to Killcam as one event per frame.
- **Links.** Camera events link between the tools by screen and app version, never by
  timestamp.
- **Heap dumps.** They run on a separate profileable variant of the release build (Q-D),
  with Killcam's three constraints on it.
- **Per-scan metrics.** swagperf gives one row per QR registered (F-020).
- **Budgets.** None until a 10-session baseline exists.

### Revisit when

- another app is integrated with Killcam and the user makes it the focus (the trigger
  agreed with Killcam's product manager, who parked Killcam F-019 and Killcam F-020 on
  the same trigger). The user then decides which app the camera work targets (Swag Pay's
  scanner, the new app's, or both), and the scanner code is read again first: the line
  references here are from 2026-09-25;
- the user asks.

### Watch out for

- **A leak is never claimed from one trace.**
  - Run #1's RAM growth (414.4 MB) covers startup and every screen of a manual session.
  - Per-visit growth on the Screens page is the highest reading minus the lowest inside
    one visit, not what the visit left behind (`screens.py:171-176`).
  - One cycle's before and after moves with garbage collection, ML Kit's first load,
    CameraX's process-wide provider and the file cache.
  - Stress tests can't show a leak, because each session is a new cold process.
- **RAM sampling is coarse.** process_stats polls every 1,000 ms on cold captures and
  500 ms on manual ones (`capture.py:27`, `:429`); run #1 has 39 `mem.rss` samples over
  19.0 s. RAM usage for the open itself is "not measured" at that resolution. Camera
  buffers (gralloc/dmabuf) may not show in the app's RSS at all.
- **Preview smoothness isn't measured.** The camera preview (PreviewView in PERFORMANCE
  mode, `:164`) is drawn outside `Choreographer#doFrame`. Frame metrics cover the Compose
  UI around it.
- **Heap dumps need the right build.**
  - The V2514 runs a user build (`user/release-keys`), so a dump needs a profileable or
    debuggable app. Swag Pay's manifest has neither, and a debuggable build is never
    judged (Q3).
  - Class names are readable only while release keeps `isMinifyEnabled = false`
    (`composeApp/build.gradle.kts:102`).
  - LeakCanary (Killcam F-020) must stay in the debug build only, so it is never in a
    measured build.
- **The profileable variant's application id.** swagperf keys the catalogue, budgets,
  baselines and the instrumented flag on the package name. Keeping `com.swag.pay` puts the
  variant's runs in Swag Pay's series; a new id needs a catalogue entry, and its runs form
  a series of their own.
- **Run #1 was a debuggable build.** Its trace's `package_list` has `debuggable = 1` for
  `com.swag.pay` (Run details had not recorded it). So the only Swag Pay run in the history
  is a debug build's numbers (B-009). The B-010 fault is in the extraction logic and holds
  for any build.
- **Payment data.** A decoded QR is a UPI payload (payee VPA, name, amount). Markers carry
  none of it (`CameraModels.kt:31-32`), and route names must stay fixed, like `Pay`
  (`AppRoute.kt:91`). `onPayScanned` opens a hard-coded payee today (`AppShell.kt:233`);
  keep the trace name fixed when it's wired to the scanned value.
- **Killcam builds.** A camera run of a Killcam build would include Killcam's screenshots
  on screen changes and its logcat polling. F-021 and F-022 inherit B-009's refusal.

### Answered by the user

On 2026-09-25, to Killcam's product manager. The user's words, verbatim: "With Q10: I agree
with your recommendation / Q11: Yes, do it / Create a flavor for the release build that
remains profilable / On home page mount/render, the camera should auto start, and the time
to first frame should be captured / Also when it registers a QR, it should log the metrics"
(line breaks shown as " / ").

- **Killcam Q10** (does Killcam show camera timings from debug builds?): Killcam's
  recommendation. Killcam shows a summary per camera open and per QR registered,
  labelled as a debug-build figure, with no RAM usage figures and no budgets, and swagperf
  never reads it. swagperf's recommendation (events only) was not taken. Killcam F-019 is
  confirmed.
- **Killcam Q11** (LeakCanary in Swag Pay's debug build?): yes. Killcam F-020 is confirmed.
- **Q-D** (a profileable build for heap dumps?): yes, as a separate profileable variant
  of the release build, built by Swag Pay; the store release stays unchanged. It unblocks
  F-022.
- **Home's mount → first frame, on every mount, and metrics on every QR registered:**
  new requirements, recorded in F-019 and F-020 and above.
- **Q-A stays open.** The words ask for time to first frame on every Home mount. They
  don't say where swagperf's startup ends, and the product-manager skill doesn't let a
  question be answered by inference.

### Open questions (the user's call)

Q-F from swagperf's draft became Killcam Q10. When the user answers one, record the answer and
its date in the items it blocks, in both trackers, and remove it here.

Parked with the camera work on 2026-09-25: Q-B, Q-C, Q-E, Q-G and Q-H stay recorded but wait
until the user brings the work back. Q-A stays live, because B-010's full fix needs it.

| # | Question | Blocks | Recommendation |
|---|---|---|---|
| Q-A | Should Swag Pay's startup end at the first usable camera frame, which is what the 420 ms metric is named after? Or at the first QR decode, as `budgets.py:18-21` says? The second can't be measured on a cold start without a QR in view. The user's 2026-09-25 words ask for Home's mount → first frame on every mount, but don't say where startup ends. | B-010 | The first usable camera frame. First QR decode becomes a camera metric (F-020). |
| Q-B | What budget numbers do the camera candidates get? Do 180 ms (`camera_open`) and 120 ms (`first_qr_decode`) stay, and do they apply when the camera reopens? | F-020 | Set after a 10-session baseline on the V2514; none before. |
| Q-C | What is one cycle? Tab away from Home and back (runs `close()`, the path most likely to leak) or background and foreground (the session is kept)? How many cycles? Raw adb taps per device, or Maestro (F-012, parked)? | F-021 | Both kinds of cycle, raw adb taps, as the Maestro proof of concept does on the vivo. F-012 stays parked unless the user brings it back. |
| Q-E | Should there be a fixed rig with a printed test UPI QR (a fake VPA) for QR-resolve runs? | F-020, F-021 | Yes, for camera ready → first code found. Hand-held, that figure measures the tester's aim. |
| Q-G | Is "not measured" on iOS acceptable until the physical-iPhone lane exists, with no per-frame decode timing on iOS unless the app changes its decoder? | F-019 (iOS half), F-020 | Yes. |
| Q-H | Should every swagperf run of Swag Pay use the profileable release variant, or only heap-dump runs (F-022)? | F-020, F-021, F-022 | Heap-dump runs only, until a 10-session stress test of each build on the V2514 shows the variant starts and runs like the store release. Then the user decides. |

For a developer, not the user:
- Is the scanner meant to keep the camera and decoder running while it looks closed
  (`CameraHomeScreen.kt:112-116`, `:239`)? F-021's sustained-scan mode measures it; neither
  tracker owns Swag Pay's own bugs.
- Was run #1's build debuggable? Run details doesn't record it (B-009). Answered from the
  trace on 2026-09-25: yes (`package_list.debuggable = 1`).

---

## AI run summary, and a benchmark comparison

**Tracker:** F-023, F-024
**Status:** implemented 2026-09-25, after T-001 (see F-023 and F-024 in TRACKER.md for what was built). The user answered Q-S1 and Q-S2 on 2026-09-25 (see "Answered by the user").
**Raised:** 2026-09-25, when the user asked: "I want for each run an AI generated summary
view to be available, or maybe give one toggle while capturing a run to auto-generate RUN
summary. And compare against some benchmark as well"

### What

1. **A summary for every run (F-023).** The run's model-written analysis in the dashboard:
   verdict, headline, each finding with its evidence, runtime, architectural risk and
   recommendation, and the signals it looked at and dismissed. The summary also says who
   wrote it (which model and when, or "rules").
2. **Generate on demand (F-023).** A run analysed by the rules only gets a **Generate
   summary** action. It runs the analyst on the run's stored metrics and adds a row to
   `analyses`, and the rules row stays.
3. **Auto-generate at capture (F-023).** A switch on Capture, Stress and manual sessions:
   write an AI summary when the run is recorded. Off by default, because it spends the
   user's Claude quota.
4. **Benchmark comparison (F-024).** The summary says how the run compares with a
   benchmark: per metric and per step, the run's value, the benchmark's value, the
   difference, and the model's reading of it. The benchmark is the pinned benchmark run (Q-S1).

### What exists today

- **The model analyst.** `analyst.run_analysis` tries the local `claude` CLI first (the
  user's subscription, so no API key), then the Anthropic API, then rules. It returns a
  verdict, headline, findings and dismissed signals. `cli._analyse_run` stores each result
  in `analyses` with the model's name. The analyst sees only extracted metrics and
  baselines, never a trace.
- **The CLI uses it; the dashboard doesn't.** `swagperf analyze` uses the model by default
  (`--no-llm`, `--backend`). Dashboard runs are rules only: the server's
  `/api/capture/start`, `/api/stress/start` and `/api/manual/stop` already accept
  `use_llm` and pass it to `jobs.py`, but the dashboard never sends it. So most of item 3
  is a switch.
- **The view mostly exists.** Overview shows the newest analysis's headline, "Run #N vs
  Benchmark #M" (or the recent median) and its findings as `FindingCard`s, and Startup
  shows its own findings. Nothing shows the dismissed signals, or whether a model or the
  rules wrote the analysis.
- **Benchmarks.** One run is pinned per app, path and device (`swagperf benchmark set`,
  History's **Pin as benchmark**). A pinned benchmark replaces the trailing baseline in
  `store.regressions`. It is never taken from another app, and a simulator run can't be
  pinned. The analyst's payload (`analyst.build_payload`) gets the regressions judged
  against it, but not the benchmark run's own numbers or its id.
- **Competitors.** The catalogue lists competitor apps, which are captured as derived runs.
  Compare diffs any two runs.

### Shape of the work

- **F-023, server.**
  - A `POST /api/analysis/generate` that runs `_analyse_run(..., use_llm=True)` on a
    recorded run from its stored metrics, as a job, so the page follows it the way it
    follows a capture.
  - Returns the new analysis, or the rules result under a banner when no model backend
    worked. `run_analysis` already falls back to the rules.
- **F-023, dashboard.**
  - A Summary section on Overview, built from the design system (T-003's lint rule and
    showcase test apply). It shows the author and time, the findings, the dismissed signals
    and the Generate summary action.
  - The capture switch on Capture, Stress and manual sessions sends `use_llm`.
- **F-024.**
  - `build_payload` gains the benchmark: its run id, its top-line metrics and its step
    durations, taken from `store.get_benchmark` for the run's scope.
  - The prompt asks for a comparison section.
  - The summary shows the comparison as a table built from the payload, not from the
    model's text. The model's words sit beside the table.

### Watch out for

- **T-001 first.** The server accepted POSTs from any website, so a Generate summary endpoint
  would have let one request spend the user's Claude quota with no phone connected. T-001
  landed first, on 2026-09-25.
- **Numbers.** Measurement is deterministic and judgement isn't. Every number in the summary
  must come from the payload. Flag any number the model writes that isn't in the payload,
  as F-001 plans for the Copilot.
- **Wrong data read aloud.** A summary of a derived Swag Pay startup repeats B-010's wrong
  pass in confident prose. Land B-010's interim guard first. Also apply B-009's debug-build
  kind and the simulator rules to the summary: verdict capped at warn, and no benchmark.
- **Stress tests.** `jobs.py` analyses each session inside the capture loop, and each model
  call can take up to 180 s (`analyse_via_cli`'s timeout). With the switch on, a 10-session
  stress test makes 10 model calls between its cold starts. That changes the spacing
  between sessions, and each session's recorded thermal state depends on that spacing.
  Write summaries after the last capture, or write one summary for the whole stress test.
- **Verdicts changing after the fact.** The dashboard shows each run's newest `analyses`
  row, so a summary generated later can change a run's pass, warn or fail (Q-S2).
- **Re-extraction.** `swagperf reextract` recomputes verdicts with the rules and lists
  runs that a model analysed as out of date. The summary should say when it is out of date.
- **Backend choice.** F-001 plans a Rules / Claude / Codex switch for the Copilot. Use one
  choice for both features, not two.

### Answered by the user

- **Q-S1, which benchmark a summary compares against** (2026-09-25): "Yes the same pinned
  benchmark". The summary compares the run with the pinned benchmark run for its app, path
  and device. Competitor runs and published thresholds are not part of F-024.
- **Q-S2, whether a later summary may change the run's verdict** (2026-09-25): "No, summary is
  text only". The verdict stays the rules' verdict recorded at capture. A summary is stored as
  its own kind of analysis row, and when the model reads the run differently the page says so
  beside the recorded verdict. CLI `analyse` and `capture --analyse` keep writing model verdicts,
  as before.

### Open questions (the user's call)

None open.

---

## Release archive: bundles and source maps per build

**Tracker:** F-030
**Status:** in progress since 2026-09-25. The swag-pay half is draft PR [swag-pay#2](https://github.com/swag-app-krafton/swag-pay/pull/2) (branch `release-archive`); its CI dry run is the pull request's check. The swagperf half is in the working tree.
**Raised:** 2026-09-25, when the user asked where JS exceptions should be resolved to "the
exact site", then set the flow: "build generation (input versionNumber + versionCode) -> git
tag -> store hbc file"

### What

- **One command per release in swag-pay:** `apps/mobile/scripts/release_build.py
  --version-name 1.2.0 --version-code 42`.
  - It builds Android (the release APK) and iOS (the Release simulator app).
  - It tags the commit `v1.2.0-42` and pushes the tag.
  - It attaches each platform's Hermes bundle, composed source map and a `manifest.json`
    to a GitHub Release on that tag.
- **swagperf fetches from the archive:** `swagperf maps fetch --tag v1.2.0-42` (or `--all`)
  downloads a Release and registers each map under its bundle's hash and under
  `build-<versionCode>`. The Stability page then resolves that build's JS errors.

### Why

- **Only that build's map fits.** A release build's JS error reads
  `at fn (address at index.android.bundle:1:4974)`, and only that exact build's composed map
  turns the offset back into a file and line. On 2026-09-25, four real errors in Swag Pay's
  Android release build resolved to their exact throwing lines this way (see F-014).
- **The build number can't find the map.** Every local build is versionCode 1 / 1.0.0 on
  Android and 2026090403 on iOS. The test fixtures' build and the 2026-09-25 build are both
  versionCode 1, yet Metro's module ids differ between them (520 became 517).
- **Nothing kept the maps.** Each build overwrote the last one's.

### Decisions already taken

The user decided these on 2026-09-25:
- **Where the archive lives:** a GitHub Release on the tag, in `swag-app-krafton/swag-pay`,
  which is private. The maps carry the full source (`sourcesContent`), so they must never go
  anywhere public.
- **How the version gets in:** at build time, as `-Pswag.versionCode/-Pswag.versionName` for
  Gradle and `MARKETING_VERSION/CURRENT_PROJECT_VERSION` for xcodebuild. There are no version
  commits, so the tagged commit is exactly what was built. Without the properties a build is
  1 / 1.0.0, which marks a local dev build.
- **Platforms:** Android and iOS, under one tag.

Settled in the plan the user approved:
- **Tag format:** `v<name>-<code>`. `+` is avoided because GitHub URLs have mishandled it.
- **Version rules:** the code is 2 or more, and above every earlier tag's.
- **Where it builds:** a dedicated worktree (`~/Documents/swag-pay-release`), detached at the
  commit, never the tree other sessions share.
- **Checks before archiving:**
  - The APK's own bundle has the same sha256 as the archived one.
  - The APK's version and package match.
  - The app's Info.plist version matches.
- **Asking first:** the script asks before it tags and pushes.
- **Dry runs** build as `<name>-dryrun` / code 1 and never tag.

Decided by the user on 2026-09-25, second round:
- **Yarn classic 1.22 instead of npm.**
  - `yarn.lock` pins exactly package-lock.json's versions (all 809 packages).
  - `yarn import` can't read lockfile v3, so it was generated from an npm install, and 12 re-resolved entries were pinned back.
  - The Hermes bundles built with yarn are byte-identical to npm's.
- **Bash scripts instead of Python**, run through yarn (`yarn release`, `release:dry-run`, `release:resume`, `release:test`).
- **GitHub Actions runs the pipeline** (`.github/workflows/release.yml`).
  - `preflight` tests the scripts and checks the version.
  - `android` runs on Ubuntu and `ios` on macOS, in parallel.
  - `publish` tags, pushes and creates the Release.
  - A pull request touching the pipeline runs it as a dry run.
- **The demo error is a hidden gesture in every build.** A long-press on the Contacts title throws a non-fatal `TypeError` that SurfaceBoundary catches.
  - On 2026-09-25 it was driven by Maestro in the dry-run release build on an iOS simulator.
  - The os_log record resolved with `swagperf maps resolve` to `src/contactsDirectory.ts:166:27 buildContactList`, then `ContactsScreen.tsx:50`.
- **`swagperf maps resolve`** reads a pasted stack, logcat, or the simulator's `log show` output (whose backslashes arrive as `\134`).

### Watch out for

- **`workflow_dispatch` only runs from `main`,** so the first real release waits for swag-pay#2 to merge.
- **Release APKs:** `main` signs release builds with the debug key since cb4a2cf. That's enough for the demo to install, but it isn't a store signing.
- **Cost:** the iOS job runs on a macOS runner, which counts 10× against the Team plan's Actions minutes. Pull requests run it only when the release tooling changes.
- **Xcode:** the `macos-26` runner's Xcode may lag this Mac's Xcode 27. The project's settings (Swift 5, iOS 15.5) build on older Xcode.
- **The first real release has to wait for the merge.** `--ref origin/main` needs the
  `build.gradle.kts` hunk, and until `release-archive` is merged the script refuses to build
  a commit without it.
- **Killcam must sit next to the build worktree.** origin/main resolves Killcam from a
  sibling checkout (`../killcam`), so the build worktree has to be next to it. The script
  checks this.
- **Lint errors that don't fail the build.** The Android release build logs Kotlin metadata
  errors from `killcam-no-op` (compiled with Kotlin 2.4, while the app uses 2.2), but it
  completes. That's Killcam's to fix, not this item's.
- **Build numbers aren't unique on iOS runs.** A run that recorded its bundle's hash (iOS
  does) is now matched by the hash alone: a local build shares a build number with other
  builds, and falling back to it could pick the wrong map. Android runs record only the
  version code, so they rely on `build-<n>`, which is safe only for tagged builds.

### Follow-ups, not in this item

- **JS error records carry the bundle hash.** An error pasted or uploaded on its own can then
  find its map. Today the record has name, message, stack, component stack, fatal and source.
- **Android capture reads the bundle hash from the installed APK**, as iOS capture already
  does (`capture_ios.py`).
- **The crash reporter gets its upload from the same step**, once Datadog or Sentry is
  chosen.
- **A "Resolve" page**, where you paste a stack or upload a trace, after T-001.
