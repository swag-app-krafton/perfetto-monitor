"""What a thread is, from its name, in plain words.

A CPU-by-thread list (Flashlight's, or one read from a trace) names threads,
and most of those names mean nothing to a developer who is not an Android
performance expert. This module is the one place that says what a name means,
and the dashboard shows it beside the name.

Names are partly dynamic, so they are matched by pattern:

- Android cuts a thread's name to 15 characters (`DefaultDispatcher-worker-3`
  reads `DefaultDispatch`, `glide-disk-cache-thread-0` reads `glide-disk-cach`).
- Numbered threads (`Thread-22`, `binder:4242_3`, `hwuiTask1`).
- Flashlight labels the app's main thread `UI Thread`, renames
  `Binder:<pid>_<n>` to `Binder #<n>`, and suffixes a repeated name with the
  count so far: the third thread called `DefaultDispatch` is
  `DefaultDispatch (3)`. That suffix is ignored when matching.

Only names whose meaning is reliable are described. A name that could be
anyone's thread gets None rather than a guess.
"""
import re

# Flashlight's " (3)" for the third thread with the same name.
_REPEAT_SUFFIX = re.compile(r" \(\d+\)$")

_UNNAMED = ("The name gives no clue which code runs here; naming the thread "
            "where it is created would make its CPU attributable.")

# (pattern, description), first match wins, so specific names come before the
# generic ones that would also match them. Patterns are matched against the
# whole name (re.fullmatch), with any repeat suffix removed.
THREAD_DESCRIPTIONS = [(re.compile(p), d) for p, d in [
    # The app's own threads that matter most in a hybrid app.
    (r"UI Thread", (
        "The app's main thread (Flashlight calls it UI Thread). It runs lifecycle "
        "callbacks, input, layout and Compose or View drawing. Work here that takes "
        "longer than a frame causes jank.")),
    (r"RenderThread", (
        "Android's render thread for this app: it turns each frame's drawing commands "
        "into GPU work. Busy with large images, shadows, blurs or a lot of overdraw.")),
    (r"mqt_(v_)?js", (
        "React Native's JavaScript thread, where Hermes runs the app's JS: React "
        "rendering, state updates and business logic. It is mqt_v_js in bridgeless "
        "mode and mqt_js with the bridge.")),
    (r"mqt_(v_native|native_modu\w*)", (
        "React Native's native-modules thread: asynchronous calls from JavaScript into "
        "native modules run here. It is mqt_v_native in bridgeless mode and "
        "mqt_native_modules with the bridge.")),
    (r"hades", (
        "Hermes's garbage collector (Hades), freeing JavaScript memory in the "
        "background while the JS thread runs. Busy when the app's JavaScript "
        "allocates a lot.")),
    # ART, the runtime for Java and Kotlin code.
    (r"HeapTaskDaemon", (
        "ART's background garbage collector for Java and Kotlin objects. High CPU "
        "here means the app allocates many short-lived objects, so memory is "
        "reclaimed often.")),
    (r"FinalizerDaemon", (
        "ART thread that runs the finalize() methods of objects the garbage collector "
        "found unreachable. Normally near idle; busy when many objects need finalizing.")),
    (r"FinalizerWatchd\w*", (
        "ART thread that watches FinalizerDaemon and ends the app if one finalize() "
        "method runs too long. Normally idle.")),
    (r"ReferenceQueueD\w*", (
        "ART thread that hands cleared weak, soft and phantom references to the "
        "queues code registered for them. Normally near idle.")),
    (r"Signal Catcher", (
        "ART thread that handles signals sent to the app, such as the request to "
        "dump every thread's stack when Android reports the app not responding "
        "(ANR). Normally idle.")),
    (r"Jit thread pool", (
        "ART's just-in-time compiler, turning often-run Java and Kotlin methods into "
        "machine code while the app runs. High at startup when code wasn't compiled "
        "ahead of time, e.g. without a baseline profile.")),
    (r"Profile Saver", (
        "ART thread that records which methods ran, so Android can compile them "
        "ahead of time later. Brief activity a few seconds after launch is normal.")),
    (r"ADB-JDWP Connec.*", (
        "ART thread that lets a debugger or profiler attach over adb (JDWP). Idle "
        "unless one connects.")),
    # Android framework threads inside the app's process.
    (r"Binder #\d+|(Hw)?[Bb]inder:\d+_[0-9A-Fa-f]*", (
        "A binder thread: it handles calls into this app from other processes, such "
        "as the system delivering lifecycle events, broadcasts or content-provider "
        "queries.")),
    (r"hwuiTask\d*", (
        "A helper thread of Android's graphics library (hwui) that takes background "
        "drawing work off RenderThread.")),
    (r"GrallocUploadTh\w*", (
        "Android graphics thread that copies bitmaps into memory the GPU can read "
        "(hardware bitmaps) before they are drawn.")),
    (r"queued-work-loo\w*", (
        "Android's thread that writes SharedPreferences changes made with apply() "
        "to disk.")),
    # Libraries.
    (r"DefaultDispatch(er-worker-\d+)?", (
        "A Kotlin coroutines worker (Dispatchers.Default and Dispatchers.IO share "
        "them). Coroutine code moved off the main thread runs here; the name alone "
        "doesn't say which code.")),
    (r"arch_disk_io_\d+", (
        "AndroidX's shared background thread for disk work; Room database queries "
        "often run here.")),
    (r"OkHttp.*", (
        "A thread of OkHttp, the HTTP client many Android apps and React Native use: "
        "it runs network calls and manages connections.")),
    (r"Okio Watchdog", (
        "Okio's timeout watchdog, which OkHttp uses to cancel network reads and "
        "writes that take too long. Normally near idle.")),
    (r"glide-source.*", "Glide image loading: fetches images from the network or from files and decodes them."),
    (r"glide-disk-cach.*", "Glide image loading: reads images from Glide's on-disk cache and decodes them."),
    (r"glide-animation.*", "Glide image loading: decodes the frames of animated images such as GIFs."),
    (r"glide-.+", "A thread of Glide, an image-loading library."),
    (r"Fresco.+", (
        "A thread of Fresco, the image library React Native uses on Android: it "
        "downloads, decodes and caches images.")),
    (r"CameraX-.+", (
        "A thread of CameraX, Android's camera library: it opens the camera and runs "
        "its setup and callbacks here.")),
    (r"CXCP-.+", (
        "A thread of CameraX's camera-pipe layer (CXCP), which drives Android's "
        "camera API: opening the camera, sending capture requests and receiving "
        "results.")),
    (r"mali-.+", (
        "A thread of the Arm Mali GPU driver, running inside the app to manage its "
        "GPU work and memory. Busy when the app draws a lot.")),
    (r"Chrome_.+|Cr(Gpu|Renderer|Utility|Browser)Main", (
        "A thread of Chromium, the engine behind Android's WebView and the Cronet "
        "network library.")),
    # Threads nobody named.
    (r"Thread-\d+", f"An unnamed Java or Kotlin thread. {_UNNAMED}"),
    (r"pool-\d+-thread-?\d*", f"A worker of a Java thread pool created without thread names. {_UNNAMED}"),
    (r"AsyncTask #\d+", (
        "A worker of Android's AsyncTask pool, a deprecated API older libraries "
        "still use. The name doesn't say which task runs here.")),
]]


def describe_thread(name):
    """A plain-language description of the thread called `name`, or None."""
    if not name:
        return None
    base = _REPEAT_SUFFIX.sub("", name.strip())
    for pattern, description in THREAD_DESCRIPTIONS:
        if pattern.fullmatch(base):
            return description
    return None


def _described(t):
    """A copy of one {name, cpu_pct} entry with its description, if any."""
    if not isinstance(t, dict):
        return t
    d = describe_thread(t.get("name"))
    return {**t, "description": d} if d else t


def describe_summary(summary):
    """An audit summary with a description on every thread it names.

    Returns a new dict and leaves the stored one alone: descriptions are
    delivered with the data, never written into history.
    """
    if not isinstance(summary, dict):
        return summary
    out = dict(summary)
    if isinstance(out.get("threads"), list):
        out["threads"] = [_described(t) for t in out["threads"]]

    def keyed(kt):
        return {k: _described(v) for k, v in kt.items()} if isinstance(kt, dict) else kt
    if "key_threads" in out:
        out["key_threads"] = keyed(out["key_threads"])
    if isinstance(out.get("iterations"), list):
        out["iterations"] = [{**it, "key_threads": keyed(it.get("key_threads"))}
                             if isinstance(it, dict) and "key_threads" in it else it
                             for it in out["iterations"]]
    return out
