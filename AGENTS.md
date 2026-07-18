# AGENTS.md

These instructions apply to the entire `victoria-trace` repository.

## Mission

Build one polished, local-first demonstration of versioned and auditable agent
memory. The demonstration must make provenance and memory state visible instead
of presenting every stored statement as equally current or certain.

## Non-negotiable constraints

- Use zero paid API calls and require no OpenAI API key.
- Use Python 3.12 standard-library components only. Add no external runtime or
  test dependencies for the vertical slice.
- Use synthetic demonstration data only.
- Never add private conversations, exported chats, family information, medical
  information, credentials, tokens, keys, or other secrets.
- Do not access, copy from, or modify the separate Victoria-Framework repository.
- Keep this repository self-contained and safe for immediate public release.
- Ask before deleting files, rewriting history, force-pushing, or performing any
  other destructive action.
- Do not commit or push changes unless the user explicitly asks.

## Delivery priorities

1. Preserve an immutable history of decisions, uncertainty, corrections, and
   their relationships.
2. Make the currently valid answer derivable and explainable from that history.
3. Turn each accepted human correction into both a new memory revision and a
   durable regression case.
4. Demonstrate the failing question before correction and the passing rerun after
   correction.
5. Favor a narrow end-to-end workflow with reliable tests over extra features.

## Engineering expectations

- Keep domain logic separate from command-line presentation and persistence.
- Make ordering, supersession, correction, and unresolved uncertainty explicit
  data rather than implicit text conventions.
- Preserve old events; derive current state instead of editing historical facts in
  place.
- Return evidence identifiers with every answer so a human can audit it.
- Keep test fixtures obviously fictional and deterministic.
- Avoid network access in the application and test suite. No LLM runtime or API
  calls belong in this vertical slice.
- Run the full relevant test suite before reporting implementation work complete.
- Update `BUILD_WEEK_CHANGELOG.md` for material Build Week changes.
- Update `PREEXISTING_WORK.md` if project provenance boundaries change.

## Scope control

The acceptance criteria in `docs/SCOPE.md` define the current target. Do not add
general-purpose retrieval, embeddings, a web service, a graphical interface,
multi-user support, cloud synchronization, or LLM inference until the vertical
slice is complete and reviewed.
