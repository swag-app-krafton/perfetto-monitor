// node summary.test.js -- checks the audit summary against real measurements:
// three Swag Pay cold starts that Flashlight sampled on a Vivo V2514.
"use strict";
const assert = require("assert");
const {summarise} = require("./summary");
const results = require("./fixtures/results.json");

const s = summarise(results, null);
assert.strictEqual(s.successful, 3);
assert.strictEqual(s.failed, 0);
assert.ok(s.score >= 0 && s.score <= 100, `score ${s.score}`);
for (const k of ["cpu_pct", "fps", "ram_mb"]) {
  assert.ok(typeof s.metrics[k] === "number", `metrics.${k}`);
}
assert.strictEqual(s.key_threads.ui.name, "UI Thread");
assert.strictEqual(s.key_threads.js.name, "mqt_v_js");
assert.strictEqual(s.iterations.length, 3);
assert.strictEqual(s.series.length, results.iterations[0].measures.length);
assert.deepStrictEqual(s.series.slice(0, 3).map(p => p.t_ms), [500, 1000, 1500]);
assert.deepStrictEqual(Object.keys(s.stats).sort(), ["cpu", "fps", "ram", "runtime"]);

// An audit where nothing succeeded still says so, with no numbers invented.
const failed = summarise(
  {...results, status: "FAILURE", iterations: results.iterations.map(it => ({...it, status: "FAILURE"}))},
  new Error("Max number of retries reached."),
);
assert.strictEqual(failed.successful, 0);
assert.strictEqual(failed.score, null);
assert.strictEqual(failed.metrics, null);
assert.strictEqual(failed.failure, "Max number of retries reached.");

console.log("summary.test.js: ok");
