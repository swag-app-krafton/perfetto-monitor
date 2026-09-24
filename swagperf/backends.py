"""Capture backends: one module per platform, chosen in one place.

capture.py (Android: adb + Perfetto) and capture_ios.py (iOS: simctl +
xctrace) expose the same functions, so jobs.py, the CLI and the server drive
either platform the same way and never branch on it themselves. Both write a
Perfetto trace, so analysis needs no backend at all.
"""
import re

PLATFORMS = ("android", "ios")

# What every backend module provides (a test holds them to it).
SURFACE = ("devices", "device_info", "run_metadata", "other_profilers",
           "installed_packages", "capture", "verify")

ANDROID_PKG_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$")
# Bundle ids allow hyphens, and segments that start with a digit.
IOS_BUNDLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*(\.[A-Za-z0-9-]+)+$")

ID_NAMES = {"android": "an Android package name", "ios": "an iOS bundle id"}
NO_DEVICE = {
    "android": "No adb device connected.",
    "ios": "No booted iOS Simulator. Boot one (xcrun simctl boot \"iPhone 17\") or open Simulator.app.",
}


def check_platform(platform):
    if platform not in PLATFORMS:
        raise ValueError(f"platform must be one of {', '.join(PLATFORMS)}, not {platform!r}")
    return platform


def get(platform):
    """The capture module for a platform."""
    if check_platform(platform) == "ios":
        from . import capture_ios
        return capture_ios
    from . import capture
    return capture


def validate_id(platform, app_id):
    """Refuse an app id that cannot be one on this platform (and anything a
    shell or a path could misread)."""
    rx = IOS_BUNDLE_RE if check_platform(platform) == "ios" else ANDROID_PKG_RE
    if not rx.match(app_id or ""):
        raise ValueError(f"'{app_id}' does not look like {ID_NAMES[platform]}")
    return app_id
