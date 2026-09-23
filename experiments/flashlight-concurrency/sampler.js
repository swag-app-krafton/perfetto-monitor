// Flashlight's sampler, started exactly as `flashlight test` starts it, with a
// log line per event so run.py can place every measure on the device's clock.
//
//   node sampler.js <bundleId> <out.jsonl>
//
// Stops on SIGINT or SIGTERM. Flashlight runs plain `adb shell`, so it needs a
// single connected device or ANDROID_SERIAL set; run.py sets the variable.
"use strict";
const fs = require("fs");
const { profiler } = require("@perf-profiler/profiler");
const { FrameTimeParser } = require("@perf-profiler/android/dist/src/commands/atrace/pollFpsUsage");

const [bundleId, outPath] = process.argv.slice(2);
if (!bundleId || !outPath) {
  console.error("usage: node sampler.js <bundleId> <out.jsonl>");
  process.exit(2);
}

const out = fs.openSync(outPath, "w");
const log = (event, data = {}) =>
  fs.writeSync(out, JSON.stringify({ host_ms: Date.now(), event, ...data }) + "\n");

// Flashlight's FPS is computed from the atrace lines it reads off trace_pipe,
// but a measure does not say how many it got: with none at all it still
// reports an FPS, estimated from idle time. So the lines and parsed frames
// behind each measure are counted here. This observes; it changes nothing.
let lastAtrace = null;
const getFrameTimes = FrameTimeParser.prototype.getFrameTimes;
FrameTimeParser.prototype.getFrameTimes = function (output, pid) {
  const res = getFrameTimes.call(this, output, pid);
  const lines = output ? output.split(/\r\n|\n|\r/).filter(Boolean) : [];
  lastAtrace = {
    atrace_lines: lines.length,
    app_atrace_lines: lines.filter((l) => l.includes("-" + pid + " ")).length,
    frames: res.frameTimes.length,
  };
  return res;
};

log("start", { bundleId });
// Pushes the profiler binary, then runs `atrace --async_stop` and starts
// `atrace -c view -t 999`: the step most likely to disturb Perfetto.
profiler.installProfilerOnDevice();
log("installed");

const polling = profiler.pollPerformanceMeasures(bundleId, {
  onStartMeasuring: () => log("measuring"),
  onMeasure: (m) => {
    log("measure", { ...m, ...(lastAtrace || {}) });
    lastAtrace = null;
  },
});

let stopping = false;
const stop = (signal) => {
  if (stopping) return;
  stopping = true;
  log("stop", { signal });
  // Interrupts the on-device profiler and kills the atrace process.
  polling.stop();
  setTimeout(() => {
    log("stopped");
    fs.closeSync(out);
    process.exit(0);
  }, 1500);
};
process.on("SIGINT", () => stop("SIGINT"));
process.on("SIGTERM", () => stop("SIGTERM"));
