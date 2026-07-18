# Demo Scenario: The Halcyon Release Manifest

Everything in this scenario is synthetic. Halcyon, its people, its documents, and
its release process are fictional and safe to publish.

## Canonical question

> Where should Halcyon publish its release metadata, and in which format?

The question remains byte-for-byte identical in the before-correction run, the
generated regression case, and the after-correction rerun.

## Synthetic project history

### Revision 1 — `DEC-001`: original decision

- **Date:** 2026-02-02
- **Source:** `architecture-note-07` (synthetic)
- **Decision:** Serve release metadata dynamically from
  `GET /api/release` as `halcyon-release/v1` JSON.
- **State when written:** Accepted and current.

This is a valid historical decision. It must remain visible even after it stops
being current.

### Revision 2 — `DEC-002`: superseding decision

- **Date:** 2026-03-11
- **Source:** `offline-deployment-review` (synthetic)
- **Decision:** Publish a static JSON manifest with format identifier
  `release-manifest/v2` at the “top level of the published web content.”
- **Relationship:** Explicitly `supersedes: DEC-001` because offline deployments
  cannot depend on the running API.
- **State when written:** Accepted and current.

After this event, `/api/release` is historical evidence, not a valid current
answer.

### Revision 3 — `INT-001`: unresolved interpretation

- **Date:** 2026-03-12
- **Source:** `packaging-handoff-note` (synthetic)
- **Observation:** The build archive contains both an archive root and a
  `public/` directory. “Top level of the published web content” could mean either
  `release.json` at the archive root or `public/release.json`.
- **Relationship:** `interprets: DEC-002`.
- **State:** Unresolved; no authoritative owner response is recorded yet.

The system may report both candidates, but it must not silently promote either
interpretation to a confirmed fact.

## Revision 4 — `ANS-001`: historical failure to reproduce

At revision 3, the agent is asked the canonical question. It correctly recognizes
the static `release-manifest/v2` format but answers that the file belongs at
archive-root `release.json`. It cites `DEC-002` while omitting `INT-001` and states
the location without qualification.

The observed answer is recorded as revision 4, `ANS-001`. Its error is not that
the evidence was absent; the error is that an unresolved interpretation was
treated as settled. The audit view should retain this failure as evidence of what
the correction is intended to prevent.

## Revision 5 — `COR-001`: human correction

- **Date:** 2026-04-05
- **Source:** `release-owner-correction` by fictional human owner Mira Chen.
- **Correction:** “Published web content” means the contents of the `public/`
  directory. The canonical manifest path is `public/release.json`. An
  archive-root `release.json` is not published and is incorrect.
- **Relationships:** `corrects: ANS-001`, `resolves: INT-001`, and
  `clarifies: DEC-002`.
- **Authority:** Explicit human owner correction.
- **State:** Current.

Applying this correction must append a new ledger revision. It must not edit
`DEC-001`, `DEC-002`, `INT-001`, or the recorded wrong answer.

## Revision 6 — `REG-001`: regression created by the correction

The correction workflow creates `REG-001` with:

- **Input:** the exact canonical question;
- **Expected location:** `public/release.json`;
- **Expected format:** `release-manifest/v2`;
- **Required evidence:** `DEC-001`, `DEC-002`, `INT-001`, and `COR-001`;
- **Required states:** `DEC-001` is superseded, `DEC-002` is current,
  `INT-001` is resolved, and `COR-001` is the authoritative correction; and
- **Forbidden current answer:** `/api/release` or archive-root `release.json`.

`REG-001` is durable, machine-readable memory evidence. The automated regression
runner must execute the same resolver used by the interactive question path.

## Currently valid answer

After revision 5, the correct response is:

> Halcyon should publish a static `release-manifest/v2` JSON file at
> `public/release.json`.

Its evidence chain is:

1. `DEC-001` proves the original API decision and is marked superseded.
2. `DEC-002` replaces it with a static v2 manifest and remains current.
3. `INT-001` proves that the path was ambiguous and is marked resolved rather
   than erased.
4. `COR-001` authoritatively resolves the path as `public/release.json` and
   corrects the prior answer.

The answer should be reported as current and supported, while the audit output
continues to show why an earlier answer differed.

## Demonstration sequence

1. Replay revisions 1–3 and display their relationships.
2. Ask the canonical question, append `ANS-001` as revision 4, and show its
   failure to honor unresolved uncertainty.
3. Apply `COR-001` as revision 5 and show it plus the generated `REG-001` at
   revision 6.
4. Ask the identical question again and display the current answer and evidence
   chain.
5. Run the regression suite and show `REG-001` passing.
6. Display the full ledger to prove no historical event was overwritten.
