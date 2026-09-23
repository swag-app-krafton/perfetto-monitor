# ADR 0001: NLP mobile automation in CI

- Status: Proposed
- Date: 2026-09-23
- Scope: Android native + React Native hybrid application
- Shareable view: [NLP automation CI plan](../nlp-mobile-automation-ci-plan.html)

## Context

The existing Maestro POC converts natural language into intent, matches approved scenarios, generates guarded drafts, executes on Android, and stores evidence. It has useful safety controls, but planning is hard-coded to two funnels, catalog writes are not concurrency-safe, and there is no CI or automated test suite.

The target app is backend-driven. Screens are populated by `/page/fetch`; user actions use `action/view`; durable data uses `/datasync`. Performance results must correlate with exact screens and actions in one Perfetto run.

## Decision

Adopt a two-plane architecture:

1. The probabilistic control plane converts natural language into a typed intent and then a plan containing only versioned contract IDs.
2. The deterministic execution plane validates, freezes, and executes that plan with Maestro while one Perfetto session captures the run.

The canonical knowledge model will contain versioned screen, widget, action, transition, backend-operation, assertion, and trace-marker contracts. Text, OCR, and coordinates are fallback evidence, not stable identity.

Every run will record the build, contract version, plan hash, device, environment, model/prompt version, test-data handles, and artifact locations.

## Tool roles

- Maestro: primary executor for approved, repeatable CI plans.
- Perfetto: canonical timing and resource evidence for the same execution.
- ARTEMIS: exploration, failure reproduction, and proposed contract/test updates. It is excluded from measured regression runs because model latency and decisions are non-deterministic.
- LLM: intent and plan compiler. It cannot issue unrestricted device commands or approve its own contract changes.

## Safety and correctness rules

- Unknown or unreachable requests return `unsupported` or a reviewable proposal; they do not silently map to a payment flow.
- Planning is read-only. Contract promotion and catalog mutation are explicit operations.
- Financial or destructive actions require approved adapters, mock/staging policy, secret handles, and review where configured.
- Execution uses a frozen plan; no LLM or self-heal decision runs inside the measured Perfetto window.
- The model receives extracted metrics and summaries, never raw traces or unrestricted backend payloads.
- Device execution is mutually exclusive per device.

## CI lanes

- Every PR: schema, reference, reachability, policy, compiler, and golden-prompt checks.
- Selected PRs: approved Maestro smoke plans on a leased device.
- Nightly/release: repeated deterministic plans with Perfetto regression analysis.
- Nightly/manual: ARTEMIS discovery and repair proposals; non-blocking until reviewed.
- Model or prompt changes: offline intent/plan/refusal evaluation with token and latency tracking.

## Consequences

Benefits:

- Natural language stays flexible without making CI outcomes model-dependent.
- Functional and performance evidence can be correlated within one execution.
- Backend-driven UI changes become versioned contract diffs.
- New paths can be discovered without silently becoming trusted automation.

Costs:

- The application and backend must expose stable semantic IDs and operation metadata.
- A contract registry, planner IR, plan validator, device scheduler, and promotion workflow must be built.
- Device fleets need controlled state, test data, and repeated-run performance baselines.

## Rejected alternatives

- LLM/ARTEMIS as the default CI executor: too non-deterministic and too slow for performance correlation.
- Separate Flashlight and Perfetto runs as one timeline: run variance prevents event-level correlation.
- Screenshot-only screen inventory: insufficient for backend semantics, stable identity, and state validation.
- Free-form generated Maestro/ADB commands: bypasses reachability, policy, and action safety controls.

## Next decision

Define the contract schemas and lifecycle for screens, widgets, actions, transitions, backend operations, assertions, trace markers, and run manifests. Validate them first against one native → React Native → backend-heavy reference funnel.
