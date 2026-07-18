# Build Week Changelog

This file records material work performed specifically for the Victoria Trace
OpenAI Build Week 2026 project.

## 2026-07-18 — Complete local CLI demonstration

### Added

- Added the standard-library `show-history`, `ask`, `correct`, `verify`, and
  `demo` commands with deterministic ASCII presentation and meaningful exit
  codes.
- Added the `python -m src.victoria_trace` module entry point, runnable directly
  from a clean checkout without installation or a `PYTHONPATH` change.
- Kept command handlers thin by delegating ledger loading, projection, answering,
  correction persistence, and regression execution to the existing public
  domain APIs.
- Added a repeatable complete demo that creates revision-4 history in a temporary
  directory, applies the correction there, executes the generated regression,
  proves byte and event preservation, and checks that the reference fixture is
  unchanged.
- Added focused CLI tests for output, revision-specific answers, correction
  safety, regression exit codes, repeatability, deterministic presentation, API
  delegation, and a real subprocess invocation from the repository root.
- Documented exact Windows PowerShell, macOS/Linux, demo, test, and individual
  command invocations without requiring package installation.

### Boundaries preserved

- Made no event-schema, ledger, projector, resolver, correction, regression,
  synthetic-fixture, scenario, or earlier-test changes.
- Did not add a web UI, API server, network access, LLM calls, embeddings,
  semantic search, external dependencies, packaging, or publishing behavior.
- Performed no commit or push.

### Verified

- All 141 domain, persistence, regression, CLI, and end-to-end tests pass on
  Python 3.12.13 using `unittest`.
- The real `python -m src.victoria_trace demo` subprocess completes with exit
  code 0, reports 12/12 assertions passing, and leaves the reference fixture
  unchanged.
- Confirmed by SHA-256 comparison that all existing core files, the synthetic
  fixture, and all 119 earlier tests remained unchanged.

## 2026-07-18 — Deterministic stored-regression runner

### Added

- Added immutable regression-status, reason, assertion, and result models with
  stable assertion ordering and machine-readable failures.
- Implemented projected regression discovery and strict validation of stored
  questions, expected answers, evidence, projected states, forbidden current
  locations, and `generated_from` correction authority.
- Executed stored questions exclusively through the existing
  `resolve_question()` function and compared its `ResolutionResult` with the
  `REG-001` claim.
- Distinguished missing records and invalid definitions with domain-specific
  errors from valid regressions that execute and return failed assertions.
- Added deterministic revision-ordered `run_all_regressions()` discovery and
  execution for later CLI use.
- Added an end-to-end test proving that `REG-001` created by
  `apply_correction()` is directly executable and passes after correction.

### Boundaries preserved

- Made no event-schema, ledger, projector, resolver, correction-workflow,
  synthetic-fixture, or earlier-test changes.
- Did not implement CLI commands, terminal presentation, file-based runner
  shortcuts, network access, APIs, semantic search, external dependencies, or
  LLM calls.
- Performed no commit or push.

### Verified

- All 119 model, ledger, projector, resolver, correction-workflow, and
  regression-runner tests pass on Python 3.12.13 using `unittest`.
- Confirmed by SHA-256 comparison that all core files, the completed synthetic
  fixture, and all 79 earlier tests remained unchanged.
- Confirmed end to end that the correction workflow's newly generated `REG-001`
  executes the normal resolver and passes from the resulting revision-6
  projection.

## 2026-07-18 — Human correction and regression-record creation

### Added

- Implemented an immutable human-correction request and structured workflow
  result for the canonical synthetic correction.
- Validated the revision-4 projection and uncertain resolver result before
  generating `COR-001` as revision 5 and `REG-001` as revision 6.
- Verified post-correction projection and resolution while preserving revisions
  1–4 and excluding `REG-001` from answer authority.
- Added optional all-or-nothing JSON Lines persistence using a validated
  same-directory temporary file, flush, `fsync`, and one atomic replacement.
- Added focused tests for event construction, reference equivalence, preconditions,
  postconditions, immutability, determinism, duplicate rejection, exact byte
  preservation, file/ledger matching, reload, and handled persistence failures.

### Boundaries preserved

- Made no event-schema, ledger, projector, resolver, synthetic-fixture, or
  earlier-test changes.
- Created the durable regression record but did not implement or invoke a
  regression runner.
- Did not implement CLI commands, presentation, network access, APIs, semantic
  search, external dependencies, or LLM calls.
- Performed no commit or push.

### Verified

- All 79 model, ledger, projector, resolver, and correction-workflow tests pass
  on Python 3.12.13 using `unittest`.
- Confirmed by SHA-256 comparison that the event model, ledger, projector,
  resolver, completed synthetic fixture, and all 52 earlier tests remained
  unchanged.
- Confirmed that the generated `COR-001` and `REG-001` events are semantically
  equivalent to the corresponding completed reference-fixture events.

## 2026-07-18 — Deterministic canonical-question resolver

### Added

- Implemented deterministic resolution of the single canonical Halcyon question
  from `StateProjection` rather than raw ledger or fixture data.
- Added immutable answer status, machine-readable reason, structured uncertainty,
  evidence-role, evidence-reference, and resolution-result models.
- Returned explicit location ambiguity through revisions 3 and 4 without choosing
  a candidate or treating `ANS-001` as authority.
- Returned the supported `public/release.json` and `release-manifest/v2` answer
  through revisions 5 and 6 from the authoritative projected correction.
- Added focused tests for matching, normalization, unsupported questions,
  revision-specific behavior, evidence semantics, structured uncertainty,
  immutability, deterministic results, missing evidence, inconsistent state,
  conflicting authority, and timestamp independence.

### Boundaries preserved

- Made no event-schema, ledger, projector, synthetic-fixture, or earlier-test
  changes.
- Did not implement correction creation or persistence, regression-case creation
  or execution, CLI commands, network access, APIs, semantic search, or LLM calls.
- Performed no commit or push.

### Verified

- All 52 model, ledger, projector, and resolver tests pass on Python 3.12.13
  using `unittest`.
- Confirmed by SHA-256 comparison that the event model, ledger, projector,
  synthetic fixture, and all 31 earlier tests remained unchanged.

## 2026-07-18 — Deterministic state projector

### Added

- Implemented immutable state projection for complete ledgers and inclusive
  revision prefixes.
- Separated lifecycle state, semantic annotations, and causal relationship edges
  so superseded, unresolved, resolved, historical, corrected, and authoritative
  evidence remain independently inspectable.
- Added explicit transition handling for `supersedes`, `interprets`, `cites`,
  `corrects`, `resolves`, `clarifies`, and `generated_from` relationships.
- Added focused projector tests for Halcyon history snapshots, causal evidence,
  immutability, deterministic replay, invalid prefixes, conflicting terminal
  transitions, human authority, history preservation, and timestamp independence.

### Boundaries preserved

- Made no event-schema, ledger, synthetic-fixture, or existing-test changes.
- Did not implement resolver behavior, correction creation or persistence,
  regression execution, CLI commands, network access, APIs, or LLM calls.
- Performed no commit or push.

### Verified

- All 31 model, ledger, and projector tests pass on Python 3.12.13 using
  `unittest`.
- Confirmed by SHA-256 comparison that the event model, ledger, synthetic
  fixture, and their existing tests remained unchanged.

## 2026-07-18 — Codex and GPT-5.6 attribution clarification

### Documented

- Clarified that the project owner defined the Victoria concepts, objectives,
  constraints, and reviewed each implementation phase.
- Recorded that Codex with GPT-5.6 translated the approved scope into repository
  documentation, architecture, Python implementation, and tests while reporting
  design decisions, risks, and test results.
- Reaffirmed that the application runtime uses no OpenAI API, API key, or paid
  service; all demonstration data is synthetic; and commits and pushes require
  human approval.

## 2026-07-18 — Initial append-only ledger

### Added

- Added immutable Python 3.12 event, provenance, and relationship models.
- Added an immutable in-memory ledger with JSON Lines loading, relationship
  validation, and append-only file persistence.
- Encoded the complete synthetic Halcyon history as a reviewable JSON Lines
  fixture.
- Added standard-library tests for model immutability, serialization, ordered
  revisions, relationship integrity, and append-only persistence.
- Added placeholder modules that mark projection, resolving, and correction
  behavior as intentionally deferred.

### Changed

- Assigned the recorded wrong answer `ANS-001` its own ledger revision and moved
  the correction and regression revisions accordingly.
- Updated project status and Python constraints to match this implementation
  phase.

### Verified

- The repository is initialized on `main` with `origin` set to
  `https://github.com/Peter-Homemade/victoria-trace.git`.
- All 14 ledger and model tests pass on Python 3.12.13 using `unittest`.
- No commit or push was performed.

## 2026-07-18 — Project foundation

### Added

- Defined the project mission, constraints, and demo promise in `README.md`.
- Added repository-wide contributor and agent boundaries in `AGENTS.md`.
- Documented the boundary between pre-existing Victoria concepts and new Build
  Week implementation work in `PREEXISTING_WORK.md`.
- Scoped the smallest viable local vertical slice in `docs/SCOPE.md`.
- Designed one synthetic software-project decision history in
  `docs/DEMO_SCENARIO.md`.
- Added a Python-oriented `.gitignore`.
- Started this Build Week change record.

### Environment and repository status

- Confirmed that `D:\Victoria-trace` was empty before these foundation files were
  created.
- At foundation time, Git was not available on the active shell `PATH` or in the
  checked standard Windows installation locations. Workspace tooling later
  exposed empty `.git/` and `.agents/` directories; at that point `.git/` had no
  `HEAD`, config, or refs. Repository initialization was completed afterward and
  is recorded in the entry above.
- No application code was implemented.
- No commit or push was performed.
