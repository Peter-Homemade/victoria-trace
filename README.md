# Victoria Trace

> Memory that knows when it may be wrong.

Victoria Trace is a local-first, auditable memory layer that preserves how an
answer changed and the evidence that makes its current state trustworthy.

> Most agent memory systems store what was said. Victoria Trace stores what
> changed, what was corrected, what remains uncertain, and why the current
> answer should be trusted.

## The problem

Ordinary agent memory often preserves what was said without reliably preserving
what changed, what a human corrected, what remains unresolved, or why one claim
is current while another is only history. That makes continuity difficult to
audit and old mistakes easy to repeat.

## Current Build Week implementation

This repository implements one narrow, deterministic, auditable vertical slice:
the fully synthetic Halcyon release-manifest scenario. An append-only event
ledger records an earlier decision, its supersession, unresolved ambiguity, an
incorrect answer, a human-owner correction, and a durable regression case. The
guided proof makes that complete evidence chain visible automatically, while the
interactive audit mode lets a judge inspect the same chain in their own order.

This is the working Build Week proof, not the full broader Victoria architecture.

## 60-second quick start

- Python 3.12 or newer is required.
- No project or package installation and no virtual environment are required.
- No third-party Python dependencies are required; the standard library is
  sufficient.
- No API key, paid service, LLM runtime, or network connection is required after
  cloning. Runtime data is local and synthetic.

Run commands from the repository root. The `src.victoria_trace` module path lets
the project run directly from a clean checkout without installing Victoria Trace
or changing `PYTHONPATH`.

### Windows PowerShell

Guided proof:

```powershell
python -m src.victoria_trace demo
```

Interactive audit:

```powershell
python -m src.victoria_trace chat
```

All tests:

```powershell
python -m unittest discover -s tests
```

If the `python` command is unavailable, use the common Windows Python launcher:

```powershell
py -3.12 -m src.victoria_trace demo
py -3.12 -m src.victoria_trace chat
py -3.12 -m unittest discover -s tests
```

If neither `python` nor `py -3.12` is available, first install or otherwise
provide Python 3.12 or newer.

### macOS and Linux

Guided proof:

```bash
python3 -m src.victoria_trace demo
```

Interactive audit:

```bash
python3 -m src.victoria_trace chat
```

All tests:

```bash
python3 -m unittest discover -s tests
```

The guided proof runs the complete evidence line automatically. The interactive
audit lets a judge investigate supported Halcyon topics in any order, starting at
revision 4 before correction. It is deterministic and deliberately limited: it
is not an LLM or general chatbot. Once Python is available, neither mode requires
installing Victoria Trace or any package, creating a virtual environment, using
an API key, connecting to a network after cloning, or paying for a service.

### Example interactive audit

```text
audit> What is the current answer?
State: UNCERTAIN
Location: unresolved (no candidate selected)

audit> correct
Apply this correction? Type yes or no.

audit> yes
After state: SUPPORTED
Appended: COR-001 -> REG-001

audit> verify
Assertions: 12/12 passed
REG-001 verifies the resolver result; it is not answer authority.
```

## What to look for

- Before correction, the location is explicitly `UNCERTAIN`; the resolver does
  not guess between two candidate paths.
- The old incorrect answer remains visible as historical evidence, never current
  authority.
- The human-owner correction is appended as `COR-001`; it does not rewrite an
  earlier revision.
- The same resolver then returns the supported answer
  `public/release.json` in `release-manifest/v2`.
- The correction workflow also appends the durable regression record `REG-001`.
- `REG-001` reruns the question through that same resolver and verifies the old
  locations are not treated as current again.

## Architecture of the proof

```text
Synthetic JSONL event ledger
           |
           v
Deterministic state projector
           |
           v
Question resolver
           |
           v
Human correction workflow
           |
           v
Stored regression runner
           |
           v
Guided proof or interactive audit
```

## CLI commands

```text
python -m src.victoria_trace show-history
python -m src.victoria_trace ask --revision 4
python -m src.victoria_trace correct --ledger path/to/revision-4-history.jsonl
python -m src.victoria_trace verify --ledger data/halcyon_history.jsonl
python -m src.victoria_trace demo
python -m src.victoria_trace chat
```

Use `python3` instead of `python` on macOS or Linux. `correct` deliberately
requires an explicit working-file path and refuses an already corrected ledger.
The `demo` command is the safest complete path: it creates revision-4 history in
a temporary directory, applies the correction there, verifies it, and removes
the disposable data automatically. The `chat` command keeps its revision-4 or
revision-6 session ledger only in memory and discards it on reset or exit. Neither
command modifies the reference fixture.

## What the implementation proves

The vertical slice answers one question about a fully synthetic software project
and shows, with inspectable evidence:

1. the original decision;
2. the decision that superseded it;
3. an unresolved interpretation of the newer decision;
4. a human correction of a wrong answer;
5. the currently valid answer and the evidence chain supporting it; and
6. a rerun of the original question through a regression test proving the same
   error no longer occurs.

The correction is stored as a versioned memory event. It does not silently
overwrite history.

## What is implemented now

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
- a standard-library test suite, guided command-line proof, and bounded
  interactive audit mode (implemented).

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

## Broader direction

The broader Victoria direction is continuity for long-running AI agents, with
bridge and retrieval layers that can supply relevant versioned memory to future
agent runtimes. Those broader layers, general-purpose retrieval, and
general-purpose chat are not implemented in this repository. The current proof
deliberately focuses on the smallest complete, testable chain from stored history
to corrected and regression-protected answer.

## Human, ChatGPT, and Codex collaboration

Peter originated the broader Victoria concepts and remained the project owner and
decision-maker. He defined the problem, product direction, safety boundaries,
scope, and acceptance criteria.

During Build Week, Peter collaborated with ChatGPT powered by GPT-5.6 Thinking,
informally called "Victor" within their long-running design conversation.
ChatGPT helped translate the concepts into narrow implementation phases,
challenge assumptions, formulate specifications for Codex, and review completion
reports. "Victor" is an informal conversational name, not a separate OpenAI
model, human contributor, or autonomous legal or team identity.

Codex using GPT-5.6 inspected the repository and implemented only the explicitly
approved phases, reporting design decisions, risks, and test results for human
review. The final runtime is local and deterministic: GPT-5.6 does not decide
which historical claim is current or authoritative at runtime.

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
