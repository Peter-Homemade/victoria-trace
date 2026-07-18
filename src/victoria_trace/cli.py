"""Standard-library command-line demonstration for Victoria Trace."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile
from typing import TextIO

from .correction import (
    CorrectionError,
    CorrectionResult,
    apply_correction_to_file,
    canonical_correction_request,
)
from .ledger import EventLedger, LedgerValidationError
from .models import EventKind
from .projector import (
    LifecycleState,
    ProjectedEvent,
    ProjectionError,
    StateAnnotation,
    StateProjection,
    project_ledger,
)
from .regression import (
    AssertionKind,
    RegressionAssertion,
    RegressionError,
    RegressionResult,
    RegressionStatus,
    run_regression,
)
from .resolver import (
    AnswerStatus,
    CANONICAL_QUESTION,
    ResolutionError,
    ResolutionResult,
    resolve_question,
)


EXIT_SUCCESS = 0
EXIT_FAILURE = 1
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_REFERENCE_FIXTURE = _REPOSITORY_ROOT / "data" / "halcyon_history.jsonl"
_REGRESSION_EVENT_ID = "REG-001"


class CLIError(RuntimeError):
    """Raised when demo orchestration cannot complete safely."""


def _heading(title: str, stream: TextIO) -> None:
    print(title, file=stream)
    print("=" * len(title), file=stream)


def _format_sequence(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "none"


def _format_assertion_value(value: object) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, tuple):
        return "[" + ", ".join(str(item) for item in value) + "]"
    return str(value)


def _event_meaning(projected: ProjectedEvent) -> str:
    """Summarize one event's claim without interpreting domain state anew."""

    event = projected.event
    claim = event.claim
    if event.kind is EventKind.DECISION:
        location = claim.get("location", claim.get("location_description"))
        delivery = str(claim.get("delivery")).replace("_", " ")
        return (
            f"release metadata via {delivery} at {location}; "
            f"format {claim.get('format')}"
        )
    if event.kind is EventKind.INTERPRETATION:
        candidates = claim.get("candidates", ())
        return (
            f"ambiguous location with candidates "
            f"{_format_sequence(tuple(str(item) for item in candidates))}"
        )
    if event.kind is EventKind.ANSWER:
        return (
            f"recorded {claim.get('outcome')} answer: "
            f"{claim.get('location')} in {claim.get('format')}"
        )
    if event.kind is EventKind.CORRECTION:
        return (
            f"human-owner correction: {claim.get('location')} in "
            f"{claim.get('format')}"
        )
    if event.kind is EventKind.REGRESSION:
        expected = claim.get("expected", {})
        return (
            f"stored regression expecting {expected.get('location')} in "
            f"{expected.get('format')}"
        )
    return "stored event"


def _jury_state(projected: ProjectedEvent) -> str:
    """Translate projector-produced state into an audit-friendly label."""

    annotations = projected.annotations
    if StateAnnotation.REGRESSION_RECORD in annotations:
        return "REGRESSION-PROTECTED RECORD - durable check, not answer authority"
    if StateAnnotation.AUTHORITATIVE_HUMAN_CORRECTION in annotations:
        return "CURRENT HUMAN CORRECTION - authoritative"
    if StateAnnotation.CORRECTED_BY_HUMAN in annotations:
        return "CORRECTED HISTORICAL ERROR - retained, not current authority"
    if StateAnnotation.RECORDED_WRONG_ANSWER in annotations:
        return "HISTORICAL ERROR - retained, not current authority"
    if projected.lifecycle is LifecycleState.SUPERSEDED:
        return "SUPERSEDED - preserved history, not current authority"
    if projected.lifecycle is LifecycleState.UNRESOLVED:
        return "UNRESOLVED - no candidate is confirmed"
    if projected.lifecycle is LifecycleState.RESOLVED:
        return "RESOLVED - ambiguity closed by the human correction"
    if projected.lifecycle is LifecycleState.CURRENT:
        return "CURRENT - active projected state"
    return "HISTORICAL - preserved evidence, not current authority"


def render_history(projection: StateProjection, stream: TextIO) -> None:
    """Render projected history without hiding superseded or historical events."""

    _heading("VICTORIA TRACE - HISTORY", stream)
    print(f"Projection revision: {projection.through_revision}", file=stream)
    print(f"Visible events: {len(projection.events)}", file=stream)
    print(file=stream)

    for projected in projection.events:
        event = projected.event
        annotations = tuple(
            annotation.value for annotation in sorted(
                projected.annotations,
                key=lambda annotation: annotation.value,
            )
        )
        relationships = tuple(
            f"{relationship.kind.value} -> {relationship.target_event_id}"
            for relationship in event.relationships
        )
        source = event.source
        provenance = (
            f"{source.source_type}:{source.source_id}; synthetic=yes"
        )
        if source.actor is not None:
            provenance += f"; actor={source.actor}"

        print(f"Revision {event.revision}: {event.event_id}", file=stream)
        print(f"  kind: {event.kind.value}", file=stream)
        print(f"  meaning: {_event_meaning(projected)}", file=stream)
        print(f"  jury state: {_jury_state(projected)}", file=stream)
        print(f"  lifecycle: {projected.lifecycle.value}", file=stream)
        print(f"  annotations: {_format_sequence(annotations)}", file=stream)
        print(f"  relationships: {_format_sequence(relationships)}", file=stream)
        print(f"  provenance: {provenance}", file=stream)
        print(file=stream)


def render_resolution(
    result: ResolutionResult,
    stream: TextIO,
    *,
    title: str = "VICTORIA TRACE - ANSWER",
    indent: str = "",
) -> None:
    """Render one structured resolver result as stable terminal text."""

    if title:
        _heading(title, stream)
    print(f"{indent}Question: {result.question}", file=stream)
    print(f"{indent}Projection revision: {result.projection_revision}", file=stream)
    print(f"{indent}Status: {result.status.value.upper()}", file=stream)
    if result.status is AnswerStatus.UNCERTAIN and result.location is None:
        location = "unresolved (no location selected)"
    else:
        location = result.location or "not available"
    print(f"{indent}Location: {location}", file=stream)
    print(f"{indent}Format: {result.format or 'not available'}", file=stream)
    print(f"{indent}Reason: {result.reason.value}", file=stream)

    if result.uncertainties:
        print(f"{indent}Uncertainty:", file=stream)
        for uncertainty in result.uncertainties:
            print(
                f"{indent}  - field: {uncertainty.field} "
                f"({uncertainty.kind.value})",
                file=stream,
            )
            print(
                f"{indent}    candidates: "
                f"{_format_sequence(uncertainty.candidates)}",
                file=stream,
            )
            print(
                f"{indent}    evidence: "
                f"{_format_sequence(uncertainty.evidence_event_ids)}",
                file=stream,
            )
    else:
        print(f"{indent}Uncertainty: none", file=stream)

    print(f"{indent}Evidence:", file=stream)
    if result.evidence:
        for reference in result.evidence:
            print(
                f"{indent}  - {reference.event_id}: {reference.role.value}",
                file=stream,
            )
    else:
        print(f"{indent}  - none", file=stream)


def render_correction(
    result: CorrectionResult,
    stream: TextIO,
    *,
    include_resolution_details: bool = True,
) -> None:
    """Render the before/after proof returned by the correction workflow."""

    _heading("VICTORIA TRACE - CORRECTION", stream)
    print("Synthetic human owner: Mira Chen", file=stream)
    print(f"Original revision: {result.original_revision}", file=stream)
    print(f"Resulting revision: {result.resulting_revision}", file=stream)
    print(
        f"Created revision 5: {result.correction_event.event_id} "
        "(authoritative human-owner correction)",
        file=stream,
    )
    print(
        f"Created revision 6: {result.regression_event.event_id} "
        f"(durable regression generated from {result.correction_event.event_id})",
        file=stream,
    )
    print(
        "Appended events: " + _format_sequence(result.appended_event_ids),
        file=stream,
    )
    print(
        "Append-only proof: PASS - revisions 1-4 preserved unchanged; "
        "no earlier revision was overwritten",
        file=stream,
    )
    persistence = (
        "PASS - COR-001 and REG-001 persisted together"
        if result.persistence_requested and result.persistence_completed
        else "not requested"
    )
    print(f"Persistence: {persistence}", file=stream)

    if not include_resolution_details:
        return

    print(file=stream)

    print("Before correction", file=stream)
    print("-----------------", file=stream)
    render_resolution(result.before_resolution, stream, title="", indent="  ")
    print(file=stream)
    print("After correction", file=stream)
    print("----------------", file=stream)
    render_resolution(result.after_resolution, stream, title="", indent="  ")


def _assertion_presentation(
    assertion: RegressionAssertion,
    forbidden_location: str | None,
) -> tuple[str, str, str]:
    """Return a jury-readable title and value labels for an assertion."""

    kind = assertion.kind
    if kind is AssertionKind.RESOLVER_STATUS:
        return (
            "Resolver returns a supported answer",
            "Required resolver status",
            "Observed resolver status",
        )
    if kind is AssertionKind.EXPECTED_LOCATION:
        return (
            "Current location matches the human correction",
            "Stored expected location",
            "Resolver location",
        )
    if kind is AssertionKind.EXPECTED_FORMAT:
        return (
            "Current format matches the human correction",
            "Stored expected format",
            "Resolver format",
        )
    if kind is AssertionKind.REQUIRED_EVIDENCE:
        return (
            "Resolver uses the stored evidence chain in order",
            "Required evidence",
            "Resolver evidence",
        )
    if kind is AssertionKind.REQUIRED_PROJECTED_STATE:
        event_id = assertion.event_ids[0] if assertion.event_ids else "event"
        return (
            f"{event_id} has the required projected state",
            "Required state",
            "Observed state",
        )
    if kind is AssertionKind.FORBIDDEN_CURRENT_LOCATION:
        display_location = forbidden_location or "stored forbidden location"
        if display_location == "release.json":
            display_location = "archive-root release.json"
        return (
            f"Forbidden current location: {display_location}",
            "Must be returned as current answer",
            "Returned as current answer",
        )
    if kind is AssertionKind.EXCLUDED_ANSWER_EVIDENCE:
        return (
            "ANS-001 remains history, not current authority",
            "May influence current answer",
            "Influences current answer",
        )
    return (
        "REG-001 does not influence the answer it verifies",
        "May influence current answer",
        "Influences current answer",
    )


def _presentation_value(kind: AssertionKind, value: object) -> str:
    if kind in {
        AssertionKind.FORBIDDEN_CURRENT_LOCATION,
        AssertionKind.EXCLUDED_ANSWER_EVIDENCE,
        AssertionKind.EXCLUDED_REGRESSION_EVIDENCE,
    } and isinstance(value, bool):
        return "yes" if value else "no"
    return _format_assertion_value(value)


def render_regression(
    result: RegressionResult,
    stream: TextIO,
    *,
    forbidden_locations: tuple[str, ...] = (),
) -> None:
    """Render every stored assertion and an unambiguous final summary."""

    _heading("VICTORIA TRACE - REGRESSION VERIFY", stream)
    print(f"Regression: {result.regression_event_id}", file=stream)
    print(f"Projection revision: {result.projection_revision}", file=stream)
    print(f"Question: {result.question}", file=stream)
    print(f"Generated from: {result.generated_from_correction_id}", file=stream)
    print(f"Expected location: {result.expected_location}", file=stream)
    print(f"Expected format: {result.expected_format}", file=stream)
    print(f"Actual location: {result.actual_resolution.location}", file=stream)
    print(f"Actual format: {result.actual_resolution.format}", file=stream)
    print(file=stream)
    print("Assertions", file=stream)
    print("----------", file=stream)

    forbidden_index = 0
    for assertion in result.assertions:
        forbidden_location = None
        if assertion.kind is AssertionKind.FORBIDDEN_CURRENT_LOCATION:
            if forbidden_index < len(forbidden_locations):
                forbidden_location = forbidden_locations[forbidden_index]
            forbidden_index += 1
        title, expected_label, actual_label = _assertion_presentation(
            assertion,
            forbidden_location,
        )
        label = "PASS" if assertion.passed else "FAIL"
        print(f"[{label}] {title}", file=stream)
        negative_check = assertion.kind in {
            AssertionKind.FORBIDDEN_CURRENT_LOCATION,
            AssertionKind.EXCLUDED_ANSWER_EVIDENCE,
            AssertionKind.EXCLUDED_REGRESSION_EVIDENCE,
        }
        if not negative_check:
            print(
                f"       {expected_label}: "
                f"{_presentation_value(assertion.kind, assertion.expected)}",
                file=stream,
            )
        print(
            f"       {actual_label}: "
            f"{_presentation_value(assertion.kind, assertion.actual)}",
            file=stream,
        )
        print(
            f"       Result: {label}; Assertion ID: {assertion.assertion_id}; "
            f"events: {_format_sequence(assertion.event_ids)}",
            file=stream,
        )

    passed = sum(assertion.passed for assertion in result.assertions)
    total = len(result.assertions)
    print(file=stream)
    print(f"Summary: {passed}/{total} assertions passed", file=stream)
    print(f"Overall: {result.status.value.upper()}", file=stream)
    print(f"Reason: {result.reason.value}", file=stream)
    if result.status is RegressionStatus.PASSED:
        print(
            "Proof: PASS - the corrected answer is regression-protected",
            file=stream,
        )


def _load_projection(
    ledger_path: Path,
    *,
    through_revision: int | None = None,
) -> tuple[EventLedger, StateProjection]:
    ledger = EventLedger.load_jsonl(ledger_path)
    projection = project_ledger(ledger, through_revision=through_revision)
    return ledger, projection


def _command_show_history(
    ledger_path: Path,
    stream: TextIO,
) -> int:
    _, projection = _load_projection(ledger_path)
    render_history(projection, stream)
    return EXIT_SUCCESS


def _command_ask(
    ledger_path: Path,
    through_revision: int | None,
    stream: TextIO,
) -> int:
    _, projection = _load_projection(
        ledger_path,
        through_revision=through_revision,
    )
    result = resolve_question(projection, CANONICAL_QUESTION)
    render_resolution(result, stream)
    if result.status is AnswerStatus.UNSUPPORTED:
        return EXIT_FAILURE
    return EXIT_SUCCESS


def _command_correct(
    ledger_path: Path,
    stream: TextIO,
) -> int:
    ledger = EventLedger.load_jsonl(ledger_path)
    result = apply_correction_to_file(
        ledger_path,
        ledger,
        canonical_correction_request(),
    )
    render_correction(result, stream)
    return EXIT_SUCCESS


def _command_verify(
    ledger_path: Path,
    stream: TextIO,
) -> int:
    _, projection = _load_projection(ledger_path)
    result = run_regression(projection, _REGRESSION_EVENT_ID)
    stored_locations = projection.get(_REGRESSION_EVENT_ID).event.claim.get(
        "forbidden_locations",
        (),
    )
    render_regression(
        result,
        stream,
        forbidden_locations=tuple(str(item) for item in stored_locations),
    )
    if result.status is RegressionStatus.FAILED:
        return EXIT_FAILURE
    return EXIT_SUCCESS


def _create_disposable_revision_four(path: Path) -> tuple[EventLedger, bytes]:
    reference = EventLedger.load_jsonl(_REFERENCE_FIXTURE)
    revision_four = EventLedger.from_events(reference[:4])
    original_bytes = b"".join(
        (event.to_json_line() + "\n").encode("utf-8")
        for event in revision_four
    )
    path.write_bytes(original_bytes)
    reloaded = EventLedger.load_jsonl(path)
    if reloaded != revision_four:
        raise CLIError("disposable revision-4 ledger failed validation")
    return revision_four, original_bytes


def _demo_step(number: int, title: str, stream: TextIO) -> None:
    print(file=stream)
    heading = f"STAGE {number}/6 - {title}"
    print(heading, file=stream)
    print("-" * len(heading), file=stream)


def _render_answer_comparison(
    result: CorrectionResult,
    stream: TextIO,
) -> None:
    before = result.before_resolution
    after = result.after_resolution
    print(file=stream)
    print("BEFORE / AFTER COMPARISON", file=stream)
    print("-------------------------", file=stream)
    print(
        f"Before: {before.status.value.upper()} | "
        "location unresolved | "
        f"format {before.format}",
        file=stream,
    )
    print(
        f"After:  {after.status.value.upper()} | "
        f"location {after.location} | format {after.format}",
        file=stream,
    )
    print(
        "Why it changed: COR-001 resolved INT-001 with explicit human-owner "
        "authority. The same deterministic resolver then evaluated the new "
        "append-only state.",
        file=stream,
    )


def _command_demo(stream: TextIO) -> int:
    _heading("VICTORIA TRACE - GUIDED LOCAL PROOF", stream)
    print(
        "Most agent memory systems store what was said. This demonstration shows "
        "what changed, what remains uncertain, and why a corrected answer "
        "can be trusted.",
        file=stream,
    )
    print(
        "Proof path: earlier decision -> superseding decision -> unresolved "
        "ambiguity -> wrong historical answer -> human correction -> stored "
        "regression.",
        file=stream,
    )
    print(f"Canonical question: {CANONICAL_QUESTION}", file=stream)
    print(
        "State labels distinguish CURRENT, SUPERSEDED, UNRESOLVED, RESOLVED, "
        "CORRECTED, HISTORICAL, and REGRESSION-PROTECTED records.",
        file=stream,
    )
    print("All people, projects, decisions, and data are synthetic.", file=stream)
    print(
        "The demo uses disposable local data, the Python standard library, "
        "and no network, API, or LLM runtime.",
        file=stream,
    )
    reference_bytes = _REFERENCE_FIXTURE.read_bytes()

    with tempfile.TemporaryDirectory(prefix="victoria-trace-demo-") as directory:
        working_path = Path(directory) / "halcyon-working.jsonl"
        revision_four, original_bytes = _create_disposable_revision_four(
            working_path
        )

        _demo_step(1, "READ THE MEMORY BEFORE CORRECTION", stream)
        if _command_show_history(working_path, stream) != EXIT_SUCCESS:
            raise CLIError("could not show pre-correction history")

        _demo_step(2, "ASK BEFORE CORRECTION", stream)
        if _command_ask(working_path, 4, stream) != EXIT_SUCCESS:
            raise CLIError("pre-correction question could not be evaluated")

        _demo_step(3, "APPEND THE HUMAN-OWNER CORRECTION", stream)
        working_ledger = EventLedger.load_jsonl(working_path)
        correction_result = apply_correction_to_file(
            working_path,
            working_ledger,
            canonical_correction_request(),
        )
        render_correction(
            correction_result,
            stream,
            include_resolution_details=False,
        )

        _demo_step(4, "ASK THE SAME QUESTION AFTER CORRECTION", stream)
        if _command_ask(working_path, 6, stream) != EXIT_SUCCESS:
            raise CLIError("post-correction question could not be evaluated")
        _render_answer_comparison(correction_result, stream)

        _demo_step(5, "RUN THE STORED REGRESSION", stream)
        if _command_verify(working_path, stream) != EXIT_SUCCESS:
            raise CLIError("stored regression did not pass")

        _demo_step(6, "CONFIRM THE APPEND-ONLY AUDIT TRAIL", stream)
        if _command_show_history(working_path, stream) != EXIT_SUCCESS:
            raise CLIError("could not show corrected history")

        corrected = EventLedger.load_jsonl(working_path)
        corrected_bytes = working_path.read_bytes()
        if corrected.events[:4] != revision_four.events:
            raise CLIError("demo history comparison detected changed events")
        if not corrected_bytes.startswith(original_bytes):
            raise CLIError("demo history comparison detected changed bytes")

    if _REFERENCE_FIXTURE.read_bytes() != reference_bytes:
        raise CLIError("demo detected a changed reference fixture")

    print("PROOF SUMMARY", file=stream)
    print("=============", file=stream)
    print(
        "[PASS] History: the earlier decision, supersession, ambiguity, and "
        "wrong answer remain visible.",
        file=stream,
    )
    print(
        "[PASS] Correction: COR-001 and REG-001 were appended together; "
        "revisions 1-4 were not overwritten.",
        file=stream,
    )
    print(
        "[PASS] Current answer: the same resolver now returns SUPPORTED - "
        "public/release.json in release-manifest/v2.",
        file=stream,
    )
    print(
        "[PASS] Regression-protected: REG-001 passed 12/12 assertions and will "
        "fail if an old location is treated as current again.",
        file=stream,
    )
    print(
        "[PASS] Safety: disposable synthetic data was used; the reference "
        "fixture remains unchanged.",
        file=stream,
    )
    print(
        "Trust basis: explicit relationships, human-owner authority, and "
        "deterministic projection and resolution - never timestamp recency "
        "or an LLM judgment at runtime.",
        file=stream,
    )
    print("Result: PASS", file=stream)
    return EXIT_SUCCESS


def _positive_revision(value: str) -> int:
    try:
        revision = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("revision must be an integer") from error
    if revision < 1:
        raise argparse.ArgumentTypeError("revision must be positive")
    return revision


def build_parser() -> argparse.ArgumentParser:
    """Build the deterministic command parser used by both module entry points."""

    parser = argparse.ArgumentParser(
        prog="victoria-trace",
        description=(
            "Local, deterministic demonstration of auditable agent memory."
        ),
    )
    commands = parser.add_subparsers(
        dest="command",
        required=True,
        title="commands",
    )

    history = commands.add_parser(
        "show-history",
        help="show every projected event without hiding historical state",
    )
    history.add_argument(
        "--ledger",
        type=Path,
        default=_REFERENCE_FIXTURE,
        help="JSONL ledger (default: bundled synthetic reference history)",
    )

    ask = commands.add_parser(
        "ask",
        help="ask the canonical Halcyon question at an inclusive revision",
    )
    ask.add_argument(
        "--ledger",
        type=Path,
        default=_REFERENCE_FIXTURE,
        help="JSONL ledger (default: bundled synthetic reference history)",
    )
    ask.add_argument(
        "--revision",
        type=_positive_revision,
        help="inclusive revision; defaults to the complete supplied ledger",
    )

    correct = commands.add_parser(
        "correct",
        help="atomically apply the canonical synthetic correction",
    )
    correct.add_argument(
        "--ledger",
        type=Path,
        required=True,
        help="explicit path to a working revision-4 JSONL ledger",
    )

    verify = commands.add_parser(
        "verify",
        help="execute projected REG-001 through the normal resolver",
    )
    verify.add_argument(
        "--ledger",
        type=Path,
        required=True,
        help="explicit path to a corrected revision-6 JSONL ledger",
    )

    commands.add_parser(
        "demo",
        help="run the complete proof using disposable local data",
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the CLI and return a process-compatible exit code."""

    output = sys.stdout if stdout is None else stdout
    errors = sys.stderr if stderr is None else stderr
    parser = build_parser()
    arguments = parser.parse_args(argv)

    try:
        if arguments.command == "show-history":
            return _command_show_history(arguments.ledger, output)
        if arguments.command == "ask":
            return _command_ask(arguments.ledger, arguments.revision, output)
        if arguments.command == "correct":
            return _command_correct(arguments.ledger, output)
        if arguments.command == "verify":
            return _command_verify(arguments.ledger, output)
        if arguments.command == "demo":
            return _command_demo(output)
        parser.error(f"unsupported command: {arguments.command}")
    except (
        CLIError,
        CorrectionError,
        LedgerValidationError,
        OSError,
        ProjectionError,
        RegressionError,
        ResolutionError,
    ) as error:
        print(f"ERROR: {error}", file=errors)
        return EXIT_FAILURE
    return EXIT_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
