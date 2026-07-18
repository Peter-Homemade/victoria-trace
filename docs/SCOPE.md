# Scope: Smallest Viable Working Demonstration

## Objective

Before the Build Week deadline, deliver one deterministic, local Python workflow
that proves Victoria Trace can preserve changing memory, expose uncertainty,
accept a human correction, and prevent the corrected error from recurring.

The demonstration answers one fixed question about the synthetic software project
defined in `DEMO_SCENARIO.md`. Supporting arbitrary questions is not required.

## Required end-to-end behavior

The finished vertical slice must:

1. Load an append-only synthetic history containing an original decision, a
   superseding decision, and an unresolved interpretation.
2. Reproduce and record a historically wrong answer to the scenario's canonical
   question, including the evidence and uncertainty available at that revision.
3. Show that the original decision is historical rather than current, the newer
   decision supersedes it, and the interpretation remains unresolved at that
   point in time.
4. Accept the specified human correction through an explicit local command or
   domain operation.
5. Append the correction as a new, immutable memory revision. Earlier events must
   remain inspectable.
6. Create a durable regression case from the corrected question and expected
   answer as part of the same correction workflow.
7. Rerun the original question and return the corrected current answer, its state,
   and the complete supporting evidence chain.
8. Run the regression suite and show that the original error no longer occurs.
9. Produce stable, human-readable terminal output suitable for a short recorded
   demonstration.

## Architecture and implementation status

| Component | Smallest useful responsibility | Status |
| --- | --- | --- |
| Synthetic fixture | Provide the fixed events and canonical question without private data. | Implemented |
| Append-only ledger | Store ordered, versioned JSON records locally; never overwrite earlier memory. | Implemented |
| State projector | Replay events and classify claims as current, superseded, uncertain, corrected, or resolved. | Placeholder only |
| Question resolver | Match the canonical question, select the current claim, and return evidence identifiers. | Placeholder only |
| Correction service | Validate and append a human correction plus its regression case atomically. | Placeholder only |
| CLI | Expose `show-history`, `ask`, `correct`, and `verify`-style demo operations. | Not implemented |
| Tests | Check replay rules, evidence output, immutability, correction behavior, and the generated regression. | Ledger-focused coverage only |

The initial implementation uses newline-delimited JSON for reviewable fixtures and
Python 3.12 standard-library code for the event model, validation, persistence,
and tests. If atomic local updates become necessary beyond the single-process
demo, `sqlite3` is the preferred standard-library alternative; using both storage
approaches is out of scope for the first slice.

## Minimal memory model

Each stored event should have, at minimum:

- a stable event identifier and monotonically ordered revision;
- an event kind such as `decision`, `interpretation`, `correction`, or
  `regression`;
- synthetic provenance describing where the event came from;
- a structured claim or expected answer;
- an explicit relationship to affected events, such as `supersedes`,
  `interprets`, `corrects`, or `resolves`; and
- a timestamp from the fixed scenario, not the machine clock.

Current truth is a projection of the ledger and its relationships. It must not be
stored by destructively replacing old truth.

## Acceptance checks

The vertical slice is complete only when all of the following are true:

- The demo runs from a clean checkout with documented local Python commands.
- It requires no network, paid service, API key, secret, or non-synthetic input.
- Before correction, the audit view exposes the wrong answer and unresolved
  interpretation rather than hiding them.
- After correction, the exact same question returns `public/release.json` and the
  `release-manifest/v2` format.
- The returned evidence includes the original decision, superseding decision,
  uncertainty, and human correction with their correct states.
- A machine-readable regression created by the correction is executed and passes.
- Automated tests cover ordering and relationship rules, not just presentation.
- The complete test suite passes deterministically on repeated runs.

## Explicit non-goals

- LLM calls, embeddings, semantic search, or general natural-language answering.
- A web UI, API server, cloud service, authentication, or multi-user support.
- Importing real chats, repositories, tickets, documents, or personal data.
- Performance or scale work beyond the tiny synthetic fixture.
- Autonomous conflict resolution when two authoritative human corrections disagree.
- Integration with Victoria-Framework or any other private repository.

## Principal risks and containment

- **Overbuilding:** Keep one question, one correction, and one evidence chain until
  every acceptance check passes.
- **False confidence:** Model uncertainty and unresolved relationships explicitly;
  do not infer authority from recency alone.
- **History mutation:** Test that correction appends records and leaves prior bytes
  or rows inspectable.
- **Demo-only hard-coding:** The scenario may be narrow, but state transitions and
  evidence traversal must be implemented as domain rules rather than printed
  canned output.
- **Regression theater:** The post-correction test must invoke the same resolver as
  the original question, not a separate expected-output shortcut.
- **Scope contamination:** Use only the documented synthetic fixture and keep the
  separate Victoria-Framework repository untouched.
