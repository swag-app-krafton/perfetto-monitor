// The numbers swagperf stores for a Flashlight audit, computed from
// Flashlight's standard results by Flashlight's own reporter. Kept apart from
// audit.js so it can be checked without a device (summary.test.js).
"use strict";
const {Report} = require("@perf-profiler/reporter");
const {POLLING_INTERVAL} = require("@perf-profiler/types");

// Threads worth naming in a hybrid Compose + React Native app. Flashlight
// reports every thread by name; these are the ones the dashboard picks out.
const KEY_THREADS = {
  ui: ["UI Thread"],
  render: ["RenderThread"],
  js: ["mqt_v_js", "mqt_js"],
  native_modules: ["mqt_v_native", "mqt_native_modu"],
};

const round = (x, d = 1) => (x == null || Number.isNaN(x) ? null : Math.round(x * 10 ** d) / 10 ** d);
const sum = obj => Object.values(obj || {}).reduce((a, b) => a + b, 0);

function keyThreads(perProcess) {
  const byName = Object.fromEntries(perProcess.map(p => [p.processName, p.cpuUsage]));
  const outThreads = {};
  for (const [key, names] of Object.entries(KEY_THREADS)) {
    const hit = names.find(n => byName[n] != null);
    outThreads[key] = hit ? {name: hit, cpu_pct: round(byName[hit])} : null;
  }
  return outThreads;
}

function metricsOf(report) {
  const m = report.getAverageMetrics();
  return {
    cpu_pct: round(m.cpu),
    fps: round(m.fps),
    ram_mb: round(m.ram),
    runtime_ms: round(m.runtime, 0),
    high_cpu_s: round(m.totalHighCpuTime),
  };
}

function summarise(result, failure) {
  const versions = ["e2e", "profiler", "reporter"].map(
    p => `${p} ${require(`@perf-profiler/${p}/package.json`).version}`,
  );
  const successful = result.iterations.filter(it => it.status === "SUCCESS" && !it.isRetriedIteration);
  const summary = {
    flashlight_version: versions.join(", "),
    title: result.name,
    status: result.status,
    iterations_run: result.iterations.length,
    successful: successful.length,
    failed: result.iterations.length - successful.length,
    failure: failure ? failure.message : null,
    refresh_rate: result.specs ? result.specs.refreshRate : null,
    score: null,
    metrics: null,
    key_threads: null,
    threads: [],
    stats: null,
    iterations: [],
    series: [],
  };
  if (!successful.length) {
    return summary;
  }
  const report = new Report({...result, iterations: successful, status: "SUCCESS"});
  const perProcess = report.getAverageMetrics().averageCpuUsagePerProcess;
  summary.score = round(report.score, 0);
  summary.metrics = metricsOf(report);
  summary.key_threads = keyThreads(perProcess);
  summary.threads = perProcess.slice(0, 12).map(p => ({name: p.processName, cpu_pct: round(p.cpuUsage)}));
  // Spread across iterations for the headline numbers. Flashlight also has it
  // per thread, for every thread; that is dozens of rows nobody reads.
  const {cpu, fps, ram, runtime} = report.getStats();
  summary.stats = {cpu, fps, ram, runtime};
  summary.iterations = result.iterations.map((it, i) => {
    const one = it.measures.length
      ? new Report({...result, iterations: [it], status: "SUCCESS"})
      : null;
    return {
      index: i + 1,
      status: it.status,
      retried: !!it.isRetriedIteration,
      ...(one ? metricsOf(one) : {}),
      key_threads: one ? keyThreads(one.getAverageMetrics().averageCpuUsagePerProcess) : null,
    };
  });
  // The average iteration, one point per Flashlight measure. Flashlight gives
  // every averaged measure time = POLLING_INTERVAL, so a point's time is its
  // position: measures are POLLING_INTERVAL apart, the first one after it.
  summary.series = report.getAveragedResult().average.measures.map((m, i) => {
    const js = KEY_THREADS.js.map(n => m.cpu.perName[n]).find(v => v != null);
    return {
      t_ms: (i + 1) * POLLING_INTERVAL,
      cpu_pct: round(sum(m.cpu.perName)),
      ui_pct: round(m.cpu.perName["UI Thread"]),
      js_pct: round(js),
      ram_mb: round(m.ram),
      fps: round(m.fps),
    };
  });
  return summary;
}

module.exports = {summarise, KEY_THREADS};
