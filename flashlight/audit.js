// A Flashlight cold-start audit, run by swagperf (see swagperf/flashlight.py).
//
//   node audit.js --bundle-id com.swag.pay --iterations 5 --duration 10000 \
//     --out /abs/path/audit3.json [--title "Swag Pay cold start"]
//
// Each iteration is what `flashlight test` does by default: Flashlight's own
// force-stop and settle, a launch, then measurement for --duration ms. The
// results file at --out is Flashlight's standard one (`flashlight report` opens
// it). Beside it, <out without .json>.summary.json holds the numbers swagperf
// stores, all computed by Flashlight's reporter so they mean what they mean in
// Flashlight's own report.
//
// Flashlight runs plain `adb shell`, so the caller sets ANDROID_SERIAL.
"use strict";
const fs = require("fs");
const path = require("path");
const {execFile} = require("child_process");
const {profiler} = require("@perf-profiler/profiler");
const {PerformanceTester} = require("@perf-profiler/e2e/dist/PerformanceTester");
const {getScore} = require("@perf-profiler/reporter");
const {summarise} = require("./summary");

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 2) {
    out[argv[i].replace(/^--/, "")] = argv[i + 1];
  }
  return out;
}

const args = parseArgs(process.argv.slice(2));
const bundleId = args["bundle-id"];
const iterationCount = parseInt(args.iterations || "5", 10);
const duration = parseInt(args.duration || "10000", 10);
const out = args.out && path.resolve(args.out);
if (!bundleId || !out || !out.endsWith(".json")) {
  console.error("usage: node audit.js --bundle-id <pkg> --iterations N --duration MS --out <file.json>");
  process.exit(2);
}
const summaryPath = out.replace(/\.json$/, ".summary.json");

const launch = () =>
  new Promise((resolve, reject) =>
    execFile(
      "adb",
      ["shell", "monkey", "-p", bundleId, "-c", "android.intent.category.LAUNCHER", "1"],
      (err, stdout, stderr) => {
        if (err || /No activities found/.test(`${stdout}${stderr}`)) {
          reject(new Error(`could not launch ${bundleId}`));
        } else {
          resolve();
        }
      },
    ),
  );

async function main() {
  fs.mkdirSync(path.dirname(out), {recursive: true});
  const testCase = {
    beforeTest: () => profiler.stopApp(bundleId),
    run: launch,
    duration,
    getScore,
  };
  const tester = new PerformanceTester(bundleId, testCase, {
    iterationCount,
    maxRetries: 2,
    resultsFileOptions: {path: out, title: args.title || `${bundleId} cold start`},
  });
  let failure = null;
  try {
    await tester.iterate();
  } catch (e) {
    failure = e instanceof Error ? e : new Error(String(e));
    console.error(`Flashlight audit failed: ${failure.message}`);
  }
  if (tester.measures.length) {
    tester.writeResults();
    const result = JSON.parse(fs.readFileSync(out, "utf8"));
    fs.writeFileSync(summaryPath, JSON.stringify(summarise(result, failure)));
  }
  profiler.cleanup();
  process.exit(failure || !tester.measures.length ? 1 : 0);
}

main().catch(e => {
  console.error(e && e.stack ? e.stack : String(e));
  process.exit(1);
});
