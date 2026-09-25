"""Performance budgets derived from the Swag Pay shell architecture.

Each budget encodes a constraint the architecture actually states, so a breach
can be reported against the decision it violates rather than as a bare number.
"""

FRAME_NS = 16_666_667

# A deferred step may legitimately begin at the first-frame boundary; only flag
# it as an ordering violation if it starts meaningfully earlier than that.
ORDERING_TOLERANCE_MS = 1.0

# Minimum trailing runs before regression detection is trusted at all.
MIN_BASELINE_RUNS = 5

# Steps on the critical path for a returning, authenticated, onboarded user.
# The architecture's strongest decision: nothing expensive before first camera frame.
CRITICAL_PATH_RETURNING = [
    "step:bootstrap", "step:session_read", "step:compose_shell",
    "step:camera_open", "step:first_qr_decode",
]
# For first-run the order inverts: onboarding is an RN surface.
CRITICAL_PATH_FIRST_RUN = [
    "step:bootstrap", "step:hermes_boot", "step:rn_onboarding_surface",
]
# Must NOT appear before first usable camera frame on the returning path.
DEFERRED_STEPS = ["step:hermes_boot", "step:cronet_init", "step:remote_config"]

STEP_BUDGETS_MS = {
    "step:bootstrap": 60,
    "step:session_read": 30,
    "step:compose_shell": 120,
    "step:camera_open": 180,
    "step:first_qr_decode": 120,
    "step:hermes_boot": 300,
    "step:cronet_init": 90,
    "step:remote_config": 60,
    "step:rn_onboarding_surface": 250,
}

GLOBAL_BUDGETS = {
    "time_to_first_camera_frame_ms": 420,
    "slow_frame_pct": 5.0,
    "janky_frame_pct": 0.5,
    "peak_rss_mb": 320,
    "rss_growth_mb": 60,
    "thermal_drift_pct": 15.0,
}

# The unit each targeted metric is shown in (breach keys, as extraction writes them).
METRIC_UNITS = {"peak_rss_mb": "MB", "rss_growth_mb": "MB", "time_to_first_camera_frame_ms": "ms",
                "slow_frame_pct": "%", "janky_frame_pct": "%", "thermal_drift_pct": "%"}


def with_unit(value, unit):
    """'493.3 MB', '0.84%', '357.31 ms'."""
    v = f"{value:g}" if isinstance(value, (int, float)) else str(value)
    return f"{v}{unit}" if unit == "%" else f"{v} {unit}".strip()


# Why a run's startup has no North Star target, in the reader's words.
STARTUP_TARGET_REASONS = {
    "simulator": "A simulator run is never judged against North Star targets: its numbers "
                 "come from the Mac's CPU.",
    # B-010: the catalogue's startup target is the camera-frame target, and a
    # startup derived from Android's launch slices ends at Android's first
    # frame, before the camera delivers one. Judging one by the other shows a
    # pass that was never measured.
    "derived_own": "This startup is time to initial display, derived from Android's launch "
                   "slices, and it ends before the camera frame. It isn't checked against the "
                   "camera-frame North Star target until B-010 is fixed.",
    "none": "No startup North Star target is set for this app.",
}


def startup_target(app, platform="android", *, derived, simulator):
    """(target_ms, reason): the North Star target a run's startup is judged
    against, or None and why not. The one rule for extraction, the dashboard,
    triage and the trend view.

    `app` is the run's catalogue entry (or None). An instrumented Android run
    is judged against the global camera-frame target; any other run only
    against a target its catalogue entry states, because inventing one for
    someone else's app would be making up a number. A derived run of our own
    instrumented app gets none (see STARTUP_TARGET_REASONS["derived_own"])."""
    if simulator:
        return None, STARTUP_TARGET_REASONS["simulator"]
    app = app or {}
    if (platform or "android") == "android" and not derived:
        return GLOBAL_BUDGETS["time_to_first_camera_frame_ms"], None
    if derived and app.get("instrumented") and app.get("role") == "own":
        return None, STARTUP_TARGET_REASONS["derived_own"]
    target = (app.get("budgets") or {}).get("ttid_ms")
    return (target, None) if target else (None, STARTUP_TARGET_REASONS["none"])


# Which architectural risk each metric speaks to.
RISK_MAP = {
    "time_to_first_camera_frame_ms": "startup-routing / deferred-work ordering",
    "deferred_leak": "startup-routing — deferred work ran on the critical path",
    "slow_frame_pct": "Frame pacing at interop (CMP x RN seam)",
    "janky_frame_pct": "Frame pacing at interop (CMP x RN seam)",
    "peak_rss_mb": "Peak RAM usage — three runtimes resident",
    "rss_growth_mb": "Surface teardown / orphaned RN surfaces",
    "thermal_drift_pct": "Sustained-scan thermal throttling",
}

# Which runtime owns each instrumented step. The dashboard labels steps with
# it; steps derived from Android's own launch slices belong to the framework.
STEP_RUNTIME = {
    "step:bootstrap": "Native", "step:session_read": "Native",
    "step:camera_open": "Native camera", "step:first_qr_decode": "Native camera",
    "step:compose_shell": "Compose",
    "step:hermes_boot": "React Native", "step:rn_onboarding_surface": "React Native",
    "step:cronet_init": "Native", "step:remote_config": "Native",
    "step:process_start": "Android framework", "step:bind_application": "Android framework",
    "step:activity_create": "Android framework", "step:layout_inflate": "Android framework",
    "step:activity_resume": "Android framework", "step:first_frame": "Android framework",
    "step:fully_drawn": "Android framework",
    "step:pre_main": "iOS framework", "step:main_to_first_frame": "iOS framework",
    "step:to_first_frame": "iOS framework", "step:first_frame_to_responsive": "iOS framework",
}

# What each step covers, in plain words, for a developer who is not an Android
# performance expert. The dashboard shows it wherever a step is named. A test
# requires one for every step in derive.PHASES and in STEP_RUNTIME, so a new
# step cannot ship without one.
#
# The Android steps are derived from the framework's own launch slices (see
# derive.PHASES), so they describe what those slices are. The Swag Pay steps
# below them are the startup model this file states: its paths, owners and
# deferred work. The app itself emits only instant `step:` milestones today
# (SwagTrace.stepInstant), so these descriptions say what each step stands
# for in that model and no more; tighten them when the app wraps real work.
STEP_DESCRIPTIONS = {
    # Android's own launch phases, for any app.
    "step:process_start": (
        "Android creating the app's process by forking Zygote, a pre-started process "
        "with the framework already loaded. Only a cold start has it. Mostly outside "
        "the app's control; a busy or low-memory device slows it."),
    "step:bind_application": (
        "The new process loading the app: ART, the Java/Kotlin runtime, opens its dex "
        "(code) files, content providers start, then Application.onCreate runs. SDKs "
        "initialised in onCreate or providers usually make it slow."),
    "step:activity_create": (
        "Android creating the first screen (an Activity) and running its onCreate. "
        "Slow when onCreate does real work before returning, such as reading storage "
        "or setting up dependencies on the main thread."),
    "step:layout_inflate": (
        "Building the first screen's UI: inflating XML layouts into views "
        "(setContentView), or composing the first Compose frame. Deep or complex "
        "layouts and heavy work inside composables make it slow."),
    "step:activity_resume": (
        "The first screen becoming ready for input: Android runs the Activity's "
        "onResume. Slow when onResume starts work on the main thread, such as opening "
        "the camera or registering listeners."),
    "step:first_frame": (
        "The app's first frame (the first Choreographer#doFrame): measuring, laying "
        "out and drawing the first screen on the main thread. A complex first screen "
        "or work queued ahead of drawing makes it slow."),
    "step:fully_drawn": (
        "The app telling Android its first screen is complete, content included, by "
        "calling reportFullyDrawn(). Only apps that call it have this step; it marks "
        "time to full display (TTFD)."),
    # iOS's own launch phases, for any app (derive.IOS_PHASES).
    "step:pre_main": (
        "iOS loading the app before any of its code runs: dyld maps the app and its "
        "frameworks, fixes up pointers and runs static initializers. Many frameworks "
        "or heavy static initializers make it slow."),
    "step:main_to_first_frame": (
        "From main() to the first frame on screen: UIKit starts, the app delegate and "
        "scene are set up, and the first screen is built and drawn. Work done before "
        "the first screen shows makes it slow."),
    "step:to_first_frame": (
        "The whole launch, process start to the first frame on screen, when the trace "
        "could not split it at main(). It covers loading frameworks, static "
        "initializers and building the first screen."),
    "step:first_frame_to_responsive": (
        "From the first frame to the app accepting touches, as Apple's launch "
        "measurement defines it. Work queued on the main thread just after the first "
        "frame makes it slow."),
    # Swag Pay's startup model (CRITICAL_PATH_*, DEFERRED_STEPS above).
    "step:bootstrap": (
        "Swag Pay's native start-up work before its first screen. It comes first on "
        "both the returning-user and first-run paths, so every later step waits for "
        "it; work the first screen doesn't need belongs later."),
    "step:session_read": (
        "Reading the saved user session from on-device storage, on the returning-user "
        "path; it decides whether the app opens the camera home or onboarding. "
        "Blocking disk reads make it slow."),
    "step:compose_shell": (
        "Swag Pay's Compose shell composed and drawn for the first time: the shared "
        "UI, such as the bottom navigation, that every screen sits in. Heavy work "
        "during the first composition makes it slow."),
    "step:camera_open": (
        "Opening the camera and starting its preview, on the returning-user path. "
        "Most of its time is usually the camera hardware and driver setting up "
        "streams, so starting it earlier helps more than faster code."),
    "step:first_qr_decode": (
        "Decoding the first QR code from the camera's frames. The last step on the "
        "returning-user path: startup time (TTID) ends when it does. Large frames or "
        "a slow decoder make it slow."),
    "step:hermes_boot": (
        "Starting Hermes, the JavaScript engine React Native runs on. On first run, "
        "onboarding waits for it; for a returning user it must not start before the "
        "first usable camera frame. JS bundle size usually drives its cost."),
    "step:rn_onboarding_surface": (
        "Showing the React Native onboarding screen on first run, after Hermes has "
        "started: creating the surface and rendering its first view tree. Heavy "
        "JavaScript work before the first render makes it slow."),
    "step:cronet_init": (
        "Starting Cronet, Chromium's networking library, for the app's HTTP requests. "
        "Deferred work: for a returning user it must not start before the first usable "
        "camera frame. Loading its native library and building the engine are the cost."),
    "step:remote_config": (
        "Fetching or applying remote configuration: settings and feature flags served "
        "by a backend. Deferred work: for a returning user it must not start before "
        "the first usable camera frame. Network waits slow it."),
}
