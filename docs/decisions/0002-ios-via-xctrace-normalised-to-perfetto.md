# ADR 0002: iOS through xctrace, normalised into Perfetto traces

- Status: Accepted
- Date: 2026-09-24
- Scope: swagperf's iOS lane (tracker F-013), simulator first
- Spike: iPhone 17 simulator, iOS 27.0, Xcode 27.0 (xctrace 27.0), Swag Pay 1.0.0 Release build

## Context

swagperf measured Android only: `capture.py` drives adb and Perfetto, and every metric is
Perfetto SQL (`extract.py`, `derive.py`, `screens.py`). Swag Pay ships on iOS too, and the
Compose Multiplatform × React Native seam, the highest risk in its architecture, lives
there. The iOS app's trace markers were `println` stubs.

iOS has no Perfetto. Its recorder is Instruments, driven from the command line by
`xcrun xctrace`. A recording is a `.trace` bundle that `xctrace export` turns into XML.

## Decision

1. **Record with xctrace and convert each recording into a Perfetto trace.** Don't write
   a second extractor. The converter (`swagperf/convert_ios.py`) writes the same slice
   and counter shapes the Android markers produce. Everything that reads a run's trace
   then works unchanged: extraction, screens, reextract, Copilot, triage and the Perfetto
   UI. The `.trace` bundle is kept beside the `.pftrace` for Instruments.
2. **The platform travels inside the trace.** The converter writes one instant,
   `swagperf.source:platform=ios;simulator=1;...`, which `extract.trace_source` reads.
3. **iOS is a lane of its own.** Runs carry `platform` and `simulator` columns.
   Baselines, regressions, benchmarks, compare and triage never mix platforms, and never
   mix simulator runs with device runs. The dashboard shows iOS as the "Instruments · iOS"
   choice in the first top-bar control.
4. **Simulator runs are indicative only.** They are recorded and regression-checked
   against other simulator runs. They carry no budgets and no breaches, their verdict is
   capped at warn, they can't be pinned as a benchmark, and triage skips them.
5. **The app marks work with `os_signpost`.** Kotlin can't call the macro, so C wrappers
   live in `composeApp/src/nativeInterop/cinterop/swagsignpost.def` in the app repo:
   - A fixed signpost name per marker family: `span`, `screen`, `sub`, `nav`, `event`,
     `counter`.
   - The full marker string goes in `%{public}s`.
   - Sync spans pair through a per-thread id stack.
   - Async slots use fixed ids, like the Android cookies.

## What the spike found

Each point was checked on a real recording, not taken from documentation. Trimmed exports
are in `tests/fixtures/ios/`.

- **Launch:** `--launch` needs the `.app` path. Given a bare bundle id, xctrace looks for
  a Mac executable of that name, records the Mac for 2 s, and reports no error.
- **Weight:** the App Launch template's Time Profiler and Thread Activity make a 10 s
  recording 140–180 MB. The chosen set (`os_signpost`, `os_log`, `Hangs`, `dyld Activity`)
  makes about 3 MB. A 10 s capture takes about 25 s end to end, export and conversion
  included.
- **Launch phases:**
  - The App Launch template's `life-cycle-period` table is empty on the simulator.
  - The launch is rebuilt from dyld's "Launch Executable" intervals (process start;
    pre-main ends with the inner one) and Apple's `com.apple.app_launch_measurement`
    signposts (`ApplicationFirstFramePresentation`, then `...Responsive`). These are the
    signposts XCTest's launch metric and Xcode Organizer read.
  - Startup time runs from process start to the first frame.
- **Frames:** the simulator refuses Hitches ("not supported on this platform"), and Frame
  Lifetimes and Core Animation FPS ("graphics instruments do not support the current
  device"). Frames are unmeasured there, never 0%.
- **Memory:**
  - VM Tracker records nothing on the simulator, and Activity Monitor is "not available
    on this device".
  - A simulator app is a Mac process, so its physical footprint is sampled from the Mac
    every 100 ms (`proc_pid_rusage`). This matches Apple's `footprint` tool: 77.4 MB
    against 74 MiB.
  - Samples go on the trace's clock through the recording's start time. They can't go
    through the process start: Instruments spawns the app suspended, and dyld begins
    about 0.58 s after spawn.
  - Only samples from the first frame on are kept, so RAM growth means the same thing as
    on Android.
- **Hangs:** the Hangs instrument works on the simulator. The App Launch template sets it
  to >500 ms; the capture sets 100 ms through `--recording-options`, so microhangs are
  recorded too.
- **Markers:** they arrive with their text intact, for example `step:returning_bootstrap`
  and `screen:Home#native_view` on the fixed 0x5747 slot. The React Native bridge's trace
  methods are verified by build only: no React Native screen was opened in the spike.
- **Warm cache:** the first launch after an install measured 1.83 s; the next two measured
  0.51 s. A single simulator capture isn't reproducible, so compare stress-test medians.
  Apple's launch metric discards its first iteration for the same reason.
- **Mixing tools:** another xctrace recording or Instruments running at the same time is
  refused, as Flashlight is on Android.

## Consequences

- One extractor serves both platforms. New Android analysis reaches iOS for free, provided
  the converter writes the shapes it reads.
- **B-006:** an iOS trace has no scheduler data, which exposed a bug that also hit Android.
  Per-screen CPU read 0 ms instead of unmeasured. It is fixed.
- **T-004:** the 60 Hz frame deadline (`FRAME_NS`) is still hard-coded. It is wrong on
  120 Hz iPhones and on 90/120 Hz Android devices.
- **Still to come:** a physical iPhone (devicectl, Hitches, Thermal State), iOS budgets,
  manual sessions and competitor apps. See [BACKLOG: iOS lane](../BACKLOG.md#ios-lane-beyond-the-simulator).
- **Bundle id:** Swag Pay iOS still uses the prototype's `com.cambench.compose.ios`, and
  history is keyed by it. Change it in `apps.json` and `iosApp.xcodeproj` together.
