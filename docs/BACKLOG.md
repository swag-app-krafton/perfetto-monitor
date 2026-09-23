# Backlog

Deferred work on the swagperf tracing pipeline and the `swag-pay` instrumentation
it reads. Each entry records why the item matters, not just what it is, so it
stays actionable once the conversation that produced it is gone.

These are the long write-ups. The live list, with status and priority for
every item, is [TRACKER.md](TRACKER.md); each entry here carries its tracker ID.

---

## Widget-level trace metrics (widget TTI)

**Tracker:** F-003
**Status:** not started
**Raised:** 2026-09-22, while adding React Native screen and action tracing

### What

Screens should be able to emit per-**widget** trace metrics, the headline one
being widget time-to-interactive: how long after a screen opens before a given
widget on it is actually usable.

### Why

Screen-level attribution is now in place — each screen visit carries CPU, RAM,
frame and transition cost, and knows whether it was rendered by Compose, React
Native or a platform view. That answers "which screen is slow". It does not
answer "what on this screen is slow", and for a screen that is slow because of
one expensive component, the screen-level number points at the whole screen and
names no culprit.

Two concrete cases from this codebase motivate it:

- **Home** is tagged `native_view` because its cost is dominated by the camera
  preview rather than by Compose. The screen's time-to-first-usable-frame is
  already tracked as a startup step, but nothing separates the preview's
  readiness from the rest of the screen's.
- **Onboarding** now reports nine sub-screens, several of which are dominated by
  a single element: a numeric keypad, an OTP field, a bank-selection modal. A
  slow step currently gives no indication of which element caused it.

### Shape of the work

- A `widget:<Screen>.<Widget>` marker prefix, alongside the existing `screen:`,
  `action:`, `nav:` and `step:` prefixes in `SwagTrace.kt`.
- A TTI definition that is honest and consistent: most likely first composition
  through to the first frame in which the widget is both drawn and accepting
  input. "Rendered" alone is misleading for anything behind a loading state.
- A Compose helper that wraps a composable and emits the span, plus the
  equivalent for the React Native side through the existing `nativeTrace`
  bridge, so hybrid screens stay comparable.
- Extraction and a dashboard view in `swagperf/screens.py`, nested under the
  screen the widget belongs to, reusing the parent/step handling that the
  sub-screen work already established.

### Watch out for

- **Cardinality.** A marker per widget per visit is a much higher volume than a
  marker per screen. A list with fifty rows must not emit fifty markers; widgets
  should be named classes, not instances.
- **Privacy.** The rule the rest of the pipeline follows applies here too: names
  are fixed identifiers, never user data. Widgets in this app display payee
  names, amounts and masked phone numbers.
- **Double counting.** Widget spans sit inside screen spans exactly as
  sub-screens do, so any summary must not add them to the parent's total. See
  the `include_substeps` handling in `screen_summary`.

---

## Stack depth is reconstructed, not recorded

**Tracker:** T-002
**Status:** working, with a known limit
**Raised:** 2026-09-22, while adding the navigation stack view

The Screens tab reconstructs the navigation stack by replaying the coordinator's
`nav:open-` / `nav:back-` / `nav:tab-` markers. This is accurate for the app's
own navigation, and is the same back stack `AppCoordinator` holds.

Two cases it cannot see:

- **A trace that begins mid-session.** Markers before the capture window are not
  there, so a back with no matching push is clamped rather than popping the
  root. Depth is then a lower bound until the first tab reset resynchronises it.
- **Screens the coordinator does not own.** Anything pushed by the system or by
  a library — a permissions dialog, a third-party SDK activity — never emits a
  marker, so it does not appear in the stack even though it is holding memory.

Recording the depth directly as a counter (`SwagTrace.counter("nav_depth", n)`)
from `AppCoordinator` would make it a measured value rather than a replayed one,
and would survive a partial trace. That is a small change on the app side and
worth doing if depth ever becomes something budgets are asserted against.

---

## Onboarding modelled as one native route

**Tracker:** F-005
**Status:** partially addressed
**Raised:** 2026-09-22

`AppRoute.Onboarding` is a single route covering nine React Native steps. Trace
markers for those steps now exist as sub-screens, so a profile can attribute
cost to each one. The underlying product model is unchanged: the native side
still cannot express "the user is on the OTP step", so anything driven by route
state — deep links, analytics, back-stack restoration — remains coarse.

Splitting the route is a product-modelling decision rather than a tracing one,
which is why the tracing work did not do it.

---

## A/B measurement of graphify's token savings

**Tracker:** F-004
**Status:** not started
**Raised:** 2026-09-22

The token dashboard (`/tokens.html`) reports consumption only. It deliberately
shows no "tokens saved" figure, because savings require the cost of the path
not taken, and that counterfactual cannot be measured from a transcript — only
modelled.

`graphify benchmark` does model it, and its ratio should not be read as an
accounting result. Reviewing `benchmark.py` turned up three reasons to distrust
it:

- Both sides of the ratio are heuristics: the baseline is `words * 4/3` and the
  query cost is `len(text) / 4`. No tokenizer is involved.
- `corpus_words` comes from `.graphify_detect.json`, which Step 9 cleanup
  deletes. When it is missing the exception is swallowed and the code falls
  back to `nodes * 50` — so a run after cleanup silently benchmarks against a
  placeholder. This is what produced the "18,550 words" figure.
- Sample questions that match no node label are dropped from the average.
  Questions matching fewer nodes score *higher* reductions, so dropping misses
  biases the ratio upward. Only 3 of 5 questions scored on this repo.

The honest version answers one question twice — once via `graphify query`, once
by letting the agent read files — and compares real `usage` from both runs.
That is a measured delta rather than a counterfactual. It costs tokens to run
and is on-demand, not live, which is why it is not in the dashboard.

Answer quality has to be judged separately: a cheaper answer that is worse is
not a saving, and the token counts alone cannot see that.
