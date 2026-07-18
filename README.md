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
same resolver used for normal answering. The completed standard-library CLI makes
the entire proof visible through stable local terminal output.

## Requirements and installation

- Python 3.12.
- No package installation or external dependency.
- No OpenAI API key, paid service, network access, or LLM runtime.

Run commands from the repository root. The `src.victoria_trace` module path lets
the project run directly from a clean checkout without installation or a
`PYTHONPATH` change.

### Windows PowerShell

```powershell
python -m src.victoria_trace demo
python -m unittest discover -s tests
```

### macOS and Linux

```bash
python3 -m src.victoria_trace demo
python3 -m unittest discover -s tests
```

The first command runs the complete demonstration. The second runs the complete
test suite.

## CLI commands

```text
python -m src.victoria_trace show-history
python -m src.victoria_trace ask --revision 4
python -m src.victoria_trace correct --ledger path/to/revision-4-history.jsonl
python -m src.victoria_trace verify --ledger data/halcyon_history.jsonl
python -m src.victoria_trace demo
```

Use `python3` instead of `python` on macOS or Linux. `correct` deliberately
requires an explicit working-file path and refuses an already corrected ledger.
The `demo` command is the safest complete path: it creates revision-4 history in
a temporary directory, applies the correction there, verifies it, and removes
the disposable data automatically. It never modifies the reference fixture.

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

## Completed vertical slice

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
- a standard-library test suite and command-line demonstration (implemented).

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

The full demo sequence is:

1. Show all four pre-correction events and their projected states.
2. Ask the canonical question and display unresolved location uncertainty.
3. Apply Mira Chen's synthetic human-owner correction, creating `COR-001` and
   `REG-001` while preserving revisions 1–4.
4. Ask the identical question and display `public/release.json` with
   `release-manifest/v2`.
5. Execute `REG-001` through the normal resolver and show 12/12 assertions
   passing.
6. Show all six events to prove history was appended rather than overwritten.

All demonstration data is synthetic. The CLI is entirely local, deterministic,
and produces restrained ASCII output suitable for PowerShell, macOS Terminal,
and Linux shells.

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
