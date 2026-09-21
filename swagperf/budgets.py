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
