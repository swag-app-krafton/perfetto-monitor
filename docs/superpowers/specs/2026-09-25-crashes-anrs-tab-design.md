# Crashes & ANRs: ANR detection, a full crash list, and one tab for JS exceptions, ANRs and crashes

- **Tracker:** F-028 (this spec). Serves F-025 (test-flow runs), which gets its own spec afterwards.
- **Status:** implemented 2026-09-25 in `58fe6fa`…`d21da60` (plan: `docs/superpowers/plans/2026-09-25-crashes-anrs-tab.md`). The phone check (Order of work, step 1; TESTING-PLAN CR-07) is still open: the V2514 was disconnected all day.
- **Builds on:** F-014 (`swagperf/stability.py`, the Stability page, commit `d007f5a`).

## What the user asked for

> "in the perfetto dashboard there should be a dedicated option for the JS exceptions, ANRs and Crashes, we can club all these three metrics into one tab only"

The user's context is F-025: test suites that run custom flows, not only cold and warm starts, with the whole Perfetto trace, screen markers and action markers captured. Those runs are long, so JS exceptions, ANRs and crashes need to be readable per event, not only as counts.

## Decisions taken with the user

1. **Tab layout.** The Stability tab becomes **Crashes & ANRs**, holding JS exceptions, ANRs and crashes only. Hangs move into a section on **Frame pacing**, beside jank, because both measure responsiveness. The sidebar stays the same length.
2. **ANR source.** ANRs come from the trace: the trace processor's `android.anrs` module. The Android event log (`am_anr`) is added only if a real ANR on the V2514 doesn't show up in that module. Android's exit records (`dumpsys activity exit-info`) are not used: they live outside the trace, so `reextract` can't rebuild them, and they miss an ANR the user waited out.
3. **Severity.** An ANR is high severity, like a crash, so any ANR fails the run (simulator runs stay capped at warn).
4. **Triage keys.** One issue per kind of ANR and per kind of crash, not one issue for "the app crashed".
5. **No commits** until the user asks. Other sessions are editing the same files (F-023, F-026, F-027); only this work's hunks are staged.

## Where things stand (F-014)

- `stability.extract_stability(tp, pkg, platform)` returns `{hangs, errors, crash}` and runs on every extraction path (`extract.extract`, `extract.extract_any`, both platforms).
- Both Android configs (`capture.CONFIG`, `capture.MANUAL_CONFIG`) record `capture.LOG_SOURCE`: the `android.log` source, main and crash buffers, filtered to `SwagPerfError`, `AndroidRuntime`, `DEBUG` and `libc`. Both record the `am` atrace category.
- `stability.crash()` returns `{crashed, reason}`: the first matching crash line (`limit 1`), read only from threads of the app's processes. A native crash's tombstone lines are written by `crash_dump`, a different process, so they are never read (TESTING-PLAN STB-14).
- ANRs are not recorded at all.
- Run rows store `hang_count`, `longest_hang_ms`, `js_errors`, `crashed` and `stability_json` (`store.MIGRATIONS`). Compare shows hangs, longest hang and JS errors (`store.METRIC_DIRECTION`, `ComparePage.STABILITY_LABELS`), but not crashes.
- Triage raises `crash:app:<app>:<path>` and `js_error:<fingerprint>:<app>:<path>` (`triage.signals_of`). No tracker issue has been opened under a `crash:` key.

## 1. Measurement (`swagperf/stability.py`)

### ANRs (Android)

The system, not the app, declares an ANR. When it does, ActivityManager writes two counters into the trace under the `am` atrace category:

- `ErrorId:<process_name> <pid>#<error_id>`
- `Subject(for ErrorId <error_id>):<subject>`

The trace processor's `android.anrs` module joins them into `android_anrs` (`process_name`, `pid`, `upid`, `error_id`, `ts`, `subject`, `anr_type`, `dur`, and more). On 2026-09-25 the module loaded on run #1's trace and returned no rows; run #1 had no ANR.

New `anrs(tp, pkg, upids, wins)`:

- `include perfetto module android.anrs`, then the rows whose `process_name` is the package (or whose `upid` is one of the app's). A trace processor without the module, or a trace without the counters, gives an empty result, never an error.
- For each ANR:
  - `start_ms`, the `anr_type` (e.g. `INPUT_DISPATCHING_TIMEOUT`), the system's `subject` line, and `dur_ms` when the module gives one;
  - the screen on display, through the existing `_screen_at`;
  - `main_thread`: the longest top-level slice on the app's main thread overlapping the window `[ts - dur, ts]` (5 s before `ts` when `dur` is unknown), as `{name, dur_ms}`, or `None` when nothing was traced. This is attribution from the trace only; when it's `None` the page says the trace doesn't show what the main thread was doing.
- Returns `{count, by_type, per_screen, events}`, with events capped at `MAX_EVENTS` like the others.
- iOS: `{count: None, ...}` with `measured: False`. iOS has no ANR; a watchdog kill arrives as a crash.

If the phone check (see "Order of work") shows `android_anrs` empty after a real ANR, `LOG_SOURCE` gains `log_ids: LID_EVENTS` with `filter_tags: "am_anr"`, and `anrs()` also reads `am_anr` rows for the package. The design of everything downstream doesn't change.

### Crashes (Android)

`crash()` becomes a list of crashes. Each crash has `start_ms`, `kind` (`java`, `native`, `ios`), `signature`, `message`, `log` (the crash log text), `screen` and `pid`.

- **Kotlin/Java.** `AndroidRuntime` writes the report as consecutive lines from the crashing process: `FATAL EXCEPTION: <thread>`, `Process: <pkg>, PID: <pid>`, the exception line, then one line per stack frame and `Caused by:` block. Lines from the same pid are grouped into one crash until a gap of more than 1 s or the next `FATAL EXCEPTION`. `signature` is the exception class (`java.lang.IllegalStateException`); `message` is the whole exception line, which reads on its own.
- **Native.** The app's `libc` line `Fatal signal <n> (<SIG>), code … in tid … pid <pid> (<name>)` starts the crash; `signature` is the signal name (`SIGSEGV`). The tombstone comes from `crash_dump` under tag `DEBUG`: its header `pid: <pid>, tid: <tid>, name: <thread>  >>> <pkg> <<<` names the app, so `DEBUG` lines are read unscoped and kept only from the header that names this package and pid until the tombstone's end. Their text becomes `log` (abort message, registers, backtrace).
- A fatal signal with no tombstone in the trace is still a crash, with `log` holding the one line.
- **iOS.** Unchanged in substance: one crash when the provenance says the process crashed, `signature` from the termination reason.

The returned dict keeps `crashed` and `reason` (the first crash's line) so the history's existing JSON, the analyst and the API keep reading it. It adds `measured`, `count` and `events`.

### Measured or not

A trace records its own config (`metadata.trace_config_pbtxt`). When the config has no `name: "android.log"` source, crashes are `measured: False` with `count: None`; when it has no `atrace_categories: "am"`, ANRs are. The page shows "not measured", never 0. Run #1's trace (`traces/manual_b073b3b4500c.pftrace`) has no log source, checked 2026-09-25. A trace without a recorded config (synthetic, or converted from iOS) counts as measured.

### JS exceptions

Unchanged (F-014).

### Hangs

Unchanged in measurement. Only where they are shown moves (section 3).

## 2. Run data (`swagperf/store.py`, `server.py`)

- New migrations: `runs.anr_count int` and `runs.crash_count int`. `_stability_cols` fills them. `crashed` stays and is still set.
- `record()` and `reextract` write them. `reextract` fills ANRs and crash lists for older runs whose traces exist. A trace recorded before `LOG_SOURCE` existed (run #1, `traces/manual_b073b3b4500c.pftrace`, has no log rows) stays without crash detail; its ANR count comes from the trace's counters if it has any.
- `METRIC_DIRECTION` gains `anr_count` and `crash_count`, both lower-is-better, so Compare shows them.
- `/api/stability` is unchanged in shape; the new fields ride in `stability`. `frontend/src/api/types.ts` gains the ANR and crash event types and `anr_count`, `crash_count` on `Run`.

Old `stability_json` without `anrs` or `crash.events` must still render: the page treats missing fields as "not measured", never as zero.

## 3. Dashboard

Everything is built from the existing design system (`frontend/src/design`); T-003's lint rule (no raw controls, no inline styles) applies. No new design-system component is needed.

### The Crashes & ANRs tab

- **Routes** (`frontend/src/app/routes.ts`, `router.tsx`): the `stability` screen becomes `{ id: 'crashes', path: '/crashes', label: 'Crashes & ANRs', code: 'CR', hint: 'JS exceptions, ANRs and crashes: when, on which screen, with the stack or crash log.' }`. The iOS lane gets `/ios/crashes` through the existing mapping. `/stability` and `/ios/stability` redirect to the new paths, because Copilot answers, analyst recommendations and issue files link to them.
- **Tiles** (`KpiTile`), each with its change against the previous run:
  - **JS exceptions**, with "n fatal";
  - **ANRs**, reading "Android only" on the iOS lane;
  - **Crashes**, with the first crash's signature as the note.
- **Chart** (`LineChart`): the three counts per run, shown when more than one run is in range.
- **One event list** (`ExpandableTable`), in time order, so cause and effect read in sequence (a fatal JS error just before a crash):
  - columns: At; What (`StatusPill`: JS EXCEPTION, ANR, CRASH); Name (the error name, the ANR type, or the exception class or signal); Screen; Fatal;
  - a `Segmented` filter above it: All, JS exceptions, ANRs, Crashes;
  - expanded rows:
    - JS exception: as today (message, resolved stack, component stack; the source-map hint stays in the card's hint);
    - ANR: the system's subject line, the ANR type in plain words, and what the main thread was doing (or that the trace doesn't show it);
    - crash: the crash log in a `CodeBlock`.
- **Empty states:** "No JS exception, ANR or crash in this run." When the run has no stability data: the existing "Not measured … run `swagperf reextract`" message.
- Merging the three kinds into one sorted, filterable list is a pure function in `frontend/src/domain/`, tested on its own.
- `StabilityPage.tsx` becomes `CrashesPage.tsx` in `features/crashes/`; its `HangTable` moves to Frame pacing.

### Hangs on Frame pacing

- A **Hangs** section at the bottom of `FramesPage`: the four hang tiles (Hangs, Microhangs, Longest hang, Hang rate), a hangs-per-run chart, and the hangs table, moved from Stability unchanged.
- `FramesPage` today returns early on the iOS Simulator ("Not measured on the iOS Simulator") and when a run has no frames. Those early returns become a card at the top, so the Hangs section still renders: the simulator measures hangs through the Hangs instrument even though it measures no frames.

### Elsewhere

- Compare: rows for ANRs and Crashes beside Hangs, Longest hang and JS errors (`STABILITY_LABELS`).
- Analyst recommendations name the right tab: crashes, ANRs and JS errors → "Crashes & ANRs"; hangs → "Frame pacing".

## 4. Verdict, triage and the analyst

- `analyst.stability_findings`:
  - a crash finding per run, titled with the count ("The app crashed 2 times during the run"), evidence the first signatures;
  - a new ANR finding, high severity, evidence the types and screens;
  - `_stability_summary` (the model's payload) gains `anr_count`, `crash_count` and the crash signatures.
- `triage.signals_of`:
  - `anr:<anr_type>:<app>:<path>`, high severity, value the count, detail the first subject line;
  - `crash:<signature>:<app>:<path>` replaces `crash:app:<app>:<path>`, high severity, value the count;
  - `triage._key_scope` reads keys from the end, so both fit. A test covers them.
- The product-manager skill's issue template needs no change: new keys are ordinary signals.

## 5. Testing

- **Python** (`tests/test_stability.py`, extending its `_android_trace()` builder with counter tracks and more log lines):
  - an ANR from the two counters: type, subject, screen, and the main-thread slice; a trace without the counters gives `count 0`;
  - a Kotlin/Java crash split across `AndroidRuntime` lines reassembles into one crash with its class, message and stack;
  - a native crash: the app's `Fatal signal` line plus `DEBUG` tombstone lines from another pid, read by the header's pid and package; a tombstone for another package is ignored;
  - two crashes in one trace count as two;
  - old `stability_json` without the new fields still reads (store, analyst, triage);
  - the new columns, `reextract`, the Compare metrics, the ANR finding and the `anr:` and `crash:` keys.
- **Frontend** (vitest): the event-list merge, sort and filter; the `/stability` redirect and the sidebar entry (`routes.test.ts`); lint.
- **In the running dashboard** (the run-perfetto-monitor skill): screenshots of `/crashes` and `/frames` on scratch data. The seed data gains JS errors, ANRs and crashes; this also closes TESTING-PLAN RS-04's "seeds no … stability data".
- **On the phone:** the phone check below, kept as TESTING-PLAN rows.

## Order of work

1. **Phone check first** (the project's rule: verify instrumentation in a real trace before changing extraction). On the V2514, in one manual session of Swag Pay:
   - an ANR: freeze the app's main thread (`run-as com.swag.pay kill -STOP <pid>`), tap twice, wait past 5 s;
   - a Kotlin/Java crash: `am crash com.swag.pay`;
   - a native crash: `run-as com.swag.pay kill -SEGV <pid>`.

   `run-as` needs a debuggable build. If the installed build isn't one, ask the user before installing anything. Record what the trace holds (`android_anrs` rows, the `AndroidRuntime`, `libc` and `DEBUG` lines and their pids) in this spec. It decides the event-log fallback, and the real line formats become the synthetic fixtures.
2. `stability.py`, tests first.
3. Run data: columns, `reextract`, API types.
4. Analyst, triage, Compare.
5. Dashboard: the tab, the redirects, the Hangs section on Frame pacing.
6. Seed data and screenshots; FEATURES.md, TESTING-PLAN rows; tracker (F-028 to done with its commit, TESTING-PLAN STB-14's note).

## Out of scope

- Test-flow runs (F-025): their own spec, next.
- Non-fatal Kotlin/Java exceptions the app catches (F-029).
- Budgets (North Star targets) for crash or ANR counts.
- Symbolicating native backtraces.
- Android's exit records (`dumpsys activity exit-info`).

## Risks

- **The V2514 may not write the ANR counters.** Vendors change ActivityManager. The phone check finds out before any code; the event-log fallback covers it.
- **Tombstone format varies by Android version.** The header line (`pid: …, tid: …, name: …  >>> <pkg> <<<`) has been stable for years, but the parser keeps the raw lines, so a change loses structure, not the log.
- **Trace size.** The ANR counters are a handful of events; crash logs are kilobytes. If the `am_anr` fallback is needed, the events buffer is filtered to one tag.
