# Phase 0: Flashlight and Perfetto on one device

Answers one question with evidence: **does Flashlight's sampler damage a Perfetto
trace recorded at the same time?** See
[the observations note](../../docs/flashlight-perfetto-observations.html) for why
it matters.

## Why we suspect it does

Flashlight's own source (profiler 0.10.11, the version pinned here) shows that
when it starts measuring it:

1. runs `adb shell atrace --async_stop`, which switches kernel tracing off, then
   `atrace -c view -t 999`;
2. starts an on-device binary that reads `/sys/kernel/tracing/trace_pipe` for
   frame timing. Reading that file removes events from the kernel buffer.

Perfetto's `linux.ftrace` data source uses the same buffer, and it is how
`sched_switch` and the app's `screen:`/`action:`/`step:` markers reach the trace.

## Run it

Needs one Android device with USB debugging and the app installed, left unlocked.
Flashlight's CLI is not needed: the sampler calls the same library `flashlight
test` uses.

```bash
npm ci --prefix experiments/flashlight-concurrency        # once
./.venv/bin/python experiments/flashlight-concurrency/run.py --pkg com.swag.pay
./.venv/bin/python experiments/flashlight-concurrency/analyse.py experiments/flashlight-concurrency/results/<timestamp>
```

The default is 3 repetitions of 4 modes, about 15 minutes. `--reps`, `--taps` and
`--modes` shorten it. If the tab positions cannot be read off the screen (Home's
camera preview can stop `uiautomator` reading it), pass them with `--tap-coords`.

## What it does

| Mode | Perfetto | Flashlight sampler | Tests |
|---|---|---|---|
| `perfetto_only` | whole run | — | the control every trace number is compared with |
| `perfetto_then_flashlight` | whole run | middle window only | damage while it starts, runs, and after it stops |
| `flashlight_then_perfetto` | whole run | already running | whether Perfetto starts cleanly next to it |
| `flashlight_only` | — | whole run | the control for Flashlight's own numbers |

Each run taps the bottom tabs at a fixed pace in three windows. The taps run on
the device and log their boot-clock time, the clock the trace uses, so each
window's expected number of screen markers is known. Perfetto is started through
swagperf's manual-session code, so the session tested is the one the dashboard
uses. Tracing state (`tracing_on`, atrace properties, live profiler processes) is
recorded at every boundary.

## Reading the result

For each window, `analyse.py` compares against the control for the same window:

- **Fed by ftrace, so at risk:** scheduler events per second, seconds with none,
  the longest gap in scheduler coverage, the app's `Choreographer#doFrame`
  slices, and screen markers seen against taps made.
- **Not fed by ftrace, the check that the app kept running:** frame timeline and
  RAM samples. If these hold steady while the first group drops, the loss is in
  tracing, not in the app.
- **Flashlight's side:** the atrace lines and frames its sampler received per
  500 ms, against `flashlight_only`.

A window is marked damaged when scheduler events or doFrame slices fall below
80% of the control, when any second has no scheduler events, or when it holds
10 points fewer of its expected screen markers than the control does.

`results/` (traces and logs) is git-ignored. The conclusion and its numbers go
into the observations note.
