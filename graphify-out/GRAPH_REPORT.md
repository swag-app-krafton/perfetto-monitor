# Graph Report - perfetto-monitor  (2026-09-22)

## Corpus Check
- Corpus is ~29,198 words - fits in a single context window. You may not need a graph.

## Summary
- 371 nodes · 727 edges · 17 communities (11 shown, 6 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 18 edges (avg confidence: 0.87)
- Token cost: 67,523 input · 0 output

## Community Hubs (Navigation)
- Web Dashboard UI
- CLI & Job Orchestration
- Pipeline Integration Tests
- README Architecture Concepts
- Trace Capture Service
- Trace Derivation & App Detection
- Synthetic Trace Generation
- Metric Analysis & Model Backends
- Catalogue & Stress Test Fixtures
- App Catalogue Management
- Benchmark Metrics & Known Gaps
- HTTP Capture Server
- Known Gap: No Auth
- Known Gap: No Device Baselines
- Known Gap: Playwright Verification
- Known Gap: Synthetic Traces Only
- Test Directory Fixture

## God Nodes (most connected - your core abstractions)
1. `render()` - 36 edges
2. `main()` - 31 edges
3. `extract()` - 21 edges
4. `connect()` - 19 edges
5. `_trace()` - 19 edges
6. `extract_any()` - 17 edges
7. `esc()` - 15 edges
8. `gen_android_trace()` - 14 edges
9. `_analyse_run()` - 12 edges
10. `gen_trace()` - 12 edges

## Surprising Connections (you probably didn't know these)
- `web/ (dashboard, no build step)` --references--> `web/index.html (dashboard page shell)`  [INFERRED]
  README.md → web/index.html
- `_trace()` --calls--> `gen_trace()`  [EXTRACTED]
  tests/test_pipeline.py → swagperf/synth.py
- `#pathsel startup-path selector` --implements--> `Two startup paths, two budgets (--path-kind)`  [INFERRED]
  web/index.html → README.md
- `app.js (dashboard application script)` --implements--> `Dashboard (six tabs)`  [INFERRED]
  web/index.html → README.md
- `#vstrip verdict-per-run strip` --implements--> `Overview tab`  [INFERRED]
  web/index.html → README.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Dashboard tabs, each answering one architectural concern** — readme_dashboard, readme_tab_overview, readme_tab_startup, readme_tab_frame_pacing, readme_tab_memory, readme_tab_steps, readme_tab_compare, readme_tab_history, readme_tab_capture, readme_tab_stress [EXTRACTED 1.00]
- **Deterministic measurement to LLM judgement pipeline** — swagperf_extract, swagperf_store, swagperf_analyst, readme_measurement_judgement_split, swagperf_budgets [EXTRACTED 1.00]
- **Generic-app derivation scoping and budget-safety mechanism** — readme_derivation_concept, readme_app_catalogue, readme_derived_run_no_invented_budget, readme_scoping_app_path_device, readme_android_startup_startups_module [INFERRED 0.85]

## Communities (17 total, 6 thin omitted)

### Community 0 - "Web Dashboard UI"
Cohesion: 0.09
Nodes (57): appsInHistory(), benchOf(), CAP, clearBenchmark(), CMP, CRITICAL, el(), esc() (+49 more)

### Community 1 - "CLI & Job Orchestration"
Cohesion: 0.07
Nodes (49): datetime, re, sqlite3, statistics, _analyse_run(), main(), get(), _log() (+41 more)

### Community 2 - "Pipeline Integration Tests"
Cohesion: 0.07
Nodes (19): swagperf, extract(), sys, tempfile, Tests for the deterministic half of the pipeline. The LLM analyst is…, Direct children plus self-time must account for the whole step., A returning_user benchmark must not be used for a first_run trace., Thermal drift crosses zero, so a ratio would be nonsense. (+11 more)

### Community 3 - "README Architecture Concepts"
Cohesion: 0.06
Nodes (39): Perfetto android.startup.startups stdlib module, App catalogue (apps.json / apps.local.json), Benchmark (pinned reference run), capture_problems() empty-capture check, Compare (descriptive diff view), Dashboard (six tabs), dataviz skill CVD-safety and contrast gates, Derivation (analysing any app without instrumentation) (+31 more)

### Community 4 - "Trace Capture Service"
Cohesion: 0.09
Nodes (27): argparse, http_server, json, os, Perfetto --background-wait flag (launch race fix), Known gap: iOS not wired up, launching: slice width is not startup time, shlex (+19 more)

### Community 5 - "Trace Derivation & App Detection"
Cohesion: 0.10
Nodes (26): perfetto_trace_processor, Phase slices must be scoped to target process, derive_steps(), detect_app(), _like(), Derive steps from an *uninstrumented* trace. An instrumented app emits `step:`…, SQL OR-list matching a phase's slice names, prefix-aware., Package under test and startup classification, via the Perfetto stdlib. Returns… (+18 more)

### Community 6 - "Synthetic Trace Generation"
Cohesion: 0.18
Nodes (23): random, struct, gen_android_trace(), emit(), Synthetic *generic Android* trace generator. The Swag Pay generator in…, Build a trace that looks like an ordinary Android app launch + use. regress…, counter(), gen_trace() (+15 more)

### Community 7 - "Metric Analysis & Model Backends"
Cohesion: 0.12
Nodes (22): claude CLI backend, Deterministic rules backend, Direct API backend (ANTHROPIC_API_KEY), Measurement is deterministic, judgement is not, Per-step duration (trailing-baseline regression), Model backends (claude CLI, direct API, deterministic rules), RISK_MAP (architectural risk mapping), step: prefix convention (Trace.beginSection) (+14 more)

### Community 8 - "Catalogue & Stress Test Fixtures"
Cohesion: 0.14
Nodes (3): A stress test with some failures is still informative., TestCatalogue, TestStressTests

### Community 9 - "App Catalogue Management"
Cohesion: 0.23
Nodes (15): copy, add(), budgets_for(), display(), get(), is_instrumented(), load(), mark_verified() (+7 more)

### Community 10 - "Benchmark Metrics & Known Gaps"
Cohesion: 0.22
Nodes (9): Known gap: frame attribution is process-wide, Deferred-work ordering (hard fail), Peak RSS (320MB), RSS growth (60MB), Slow / janky frames (5% / 0.5%), Thermal drift (15%), Time to first usable camera frame (420ms budget), Swag Pay shell architecture (three runtimes in one process) (+1 more)

## Knowledge Gaps
- **34 isolated node(s):** `tip`, `RUNTIME`, `RC`, `RLABEL`, `PATH_LABEL` (+29 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 146 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Dashboard (six tabs)` connect `README Architecture Concepts` to `Trace Capture Service`, `Metric Analysis & Model Backends`?**
  _High betweenness centrality (0.063) - this node is a cross-community bridge._
- **Why does `extract()` connect `Pipeline Integration Tests` to `CLI & Job Orchestration`, `Trace Derivation & App Detection`?**
  _High betweenness centrality (0.055) - this node is a cross-community bridge._
- **What connects `tip`, `RUNTIME`, `RC` to the rest of the system?**
  _34 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Web Dashboard UI` be split into smaller, more focused modules?**
  _Cohesion score 0.08892921960072596 - nodes in this community are weakly interconnected._
- **Should `CLI & Job Orchestration` be split into smaller, more focused modules?**
  _Cohesion score 0.0726764500349406 - nodes in this community are weakly interconnected._
- **Should `Pipeline Integration Tests` be split into smaller, more focused modules?**
  _Cohesion score 0.07215541165587419 - nodes in this community are weakly interconnected._
- **Should `README Architecture Concepts` be split into smaller, more focused modules?**
  _Cohesion score 0.0553306342780027 - nodes in this community are weakly interconnected._