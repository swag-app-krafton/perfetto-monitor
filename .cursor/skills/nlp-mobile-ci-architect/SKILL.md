---
name: nlp-mobile-ci-architect
description: Design or review natural-language Android test automation, screen/widget/action contracts, Maestro execution, ARTEMIS exploration, CI lanes, and Perfetto correlation. Use for NLP-driven mobile test architecture and implementation planning; not for ordinary static UI test edits.
---

# NLP mobile CI architect

Design a system where language understanding is flexible but CI execution and performance measurement remain reproducible.

## Core boundary

- The model produces typed intent and plan IR referencing known contract IDs.
- A deterministic validator checks schema, reachability, inputs, environment, risk, secrets, and approvals.
- Maestro executes the frozen plan.
- One Perfetto session surrounds that execution and is the canonical performance timeline.
- Keep LLM/device exploration and self-heal outside the measured window.

## Contract model

Treat these as versioned first-class records:

- screen: stable ID, route/page key, ready condition, widgets, backend operations
- widget: stable ID, role, description, states, test selector, data binding
- action: purpose, inputs, outputs, preconditions, side effects, risk, next states
- transition: source screen, action, destination screen, guards
- backend operation: operation ID, endpoint, request/response semantics, sensitive fields
- assertion: observable condition and evidence source
- trace marker: screen/action/API marker names and correlation fields
- run manifest: build, contract version, plan hash, device, environment and artifacts

Text, OCR, XPath, and coordinates are fallbacks; do not use them as canonical identity when stable app IDs can exist.

## Tool roles

- Use Maestro for approved deterministic execution.
- Use ARTEMIS for exploration, unknown-path discovery, failure reproduction, and suggested repairs. Its proposals require validation and promotion.
- Use Perfetto for correlated screen/action timing, frames, CPU and RAM. Give models only extracted summaries, never raw traces.

## CI routing

- PR: contract/schema, policy, compiler, reachability and golden-prompt tests.
- Device smoke: approved frozen plans only.
- Nightly/release: repeated Perfetto runs with scoped baselines and variance checks.
- Exploration: ARTEMIS, non-blocking until its output is reviewed and promoted.

## Guardrails

- Unknown intent must return `unsupported` or a proposal, not default to a risky flow.
- Planning must be read-only; catalog mutation is an explicit reviewed operation.
- Never allow generated free-form commands for protected financial/destructive actions.
- Store secret handles, not secret values, in prompts, plans, logs or reports.
- Enforce one active capture/execution per device.
- Record model, prompt, contract and plan versions for replayability.

## Deliverables

For an architecture or review request, keep the output concise and include:

1. recommendation and boundaries
2. current-state findings
3. target data/control flow
4. CI lanes and gates
5. risks and rejected alternatives
6. phased rollout and unresolved decisions

When a durable artifact is requested, create a self-contained HTML document under `docs/` and keep the decision source in `docs/decisions/`.
