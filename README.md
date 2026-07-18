# Victoria Trace

> Memory that knows when it may be wrong.

Victoria Trace is a local-first, auditable continuity layer for long-running AI
agents. Its purpose is to preserve not just remembered statements, but also the
relationships that determine whether a statement is current, superseded,
uncertain, or corrected.

This repository is the primary OpenAI Build Week 2026 implementation of that
idea. It currently contains the project foundation, demo specification, immutable
event model, append-only ledger, synthetic history fixture, and deterministic
state projector. It also includes a deterministic resolver for the single
canonical Halcyon question and a human-correction workflow that generates and
can atomically persist the correction plus its durable regression record. A
deterministic local regression runner now executes that stored record through the
same resolver used for normal answering. Command-line behavior and polished
terminal presentation have not yet been implemented.

## The demo promise

The first vertical slice will answer one question about a fully synthetic
software project. It will show, with inspectable evidence:

1. the original decision;
2. the decision that superseded it;
3. an unresolved interpretation of the newer decision;
4. a human correction of a wrong answer;
5. the currently valid answer and the evidence chain supporting it; and
6. a rerun of the original question through a regression test proving the same
   error no longer occurs.

The correction will be stored as a versioned memory event. It will not silently
overwrite history.

## Planned vertical slice

The vertical slice is deliberately small:

- a synthetic, append-only event ledger stored locally (implemented);
- a deterministic projector that derives auditable state from complete or
  revision-prefix ledger history (implemented);
- a narrow question resolver that returns an answer, confidence state, and
  evidence chain (implemented for the canonical synthetic question);
- a correction workflow that appends a new revision and records a regression
  case (implemented from the revision-4 history);
- a deterministic regression runner that validates stored assertions and invokes
  the canonical resolver (implemented); and
- a standard-library test suite and command-line demonstration.

The implementation targets Python 3.12 and its standard library only. No paid
service, API key, private data, or network dependency is required. See
[the scoped acceptance criteria](docs/SCOPE.md) and
[the synthetic scenario](docs/DEMO_SCENARIO.md).

Before the human correction, the resolver returns explicit structured location
uncertainty and does not choose between candidate paths. After the correction, it
returns the supported location and format with ordered projected evidence.

The correction workflow generates `COR-001` at revision 5 and `REG-001` at
revision 6 without rewriting revisions 1–4. The regression record is durable,
machine-readable, and executes locally against the same projected state and
resolver as a normal question. The correction-generated case passes
deterministically after correction.

## How Codex and GPT-5.6 were used

The project owner defined the Victoria concepts, objectives, and constraints and
reviewed each implementation phase. Codex with GPT-5.6 translated that scope into
repository documentation, architecture, Python implementation, and tests. Work
was implemented only in explicitly approved phases, with Codex reporting design
decisions, risks, and test results after each phase.

No application runtime depends on an OpenAI API, an API key, or a paid service.
All demonstration data is synthetic, and human approval is required before any
commit or push.

## Repository boundaries

- All demonstration content must be synthetic and safe to publish.
- Runtime code must be local Python, using the standard library where practical.
- The project must not require an OpenAI API key or paid API usage.
- Private conversations, chat backups, family or medical information,
  credentials, and secrets are out of scope.
- The separate Victoria-Framework repository is out of scope and must not be
  accessed or modified.
- A polished, testable vertical slice takes priority over broad feature coverage.

## Build Week record

- [Pre-existing concepts versus Build Week work](PREEXISTING_WORK.md)
- [Build Week changelog](BUILD_WEEK_CHANGELOG.md)
- [Contributor and agent instructions](AGENTS.md)

Repository: <https://github.com/Peter-Homemade/victoria-trace>
