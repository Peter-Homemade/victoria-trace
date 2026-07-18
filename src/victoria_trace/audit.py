"""Deterministic interactive audit controller for the Halcyon proof."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .correction import (
    CorrectionResult,
    apply_correction,
    canonical_correction_request,
)
from .ledger import EventLedger
from .models import EventKind
from .projector import (
    DerivedEffect,
    StateAnnotation,
    StateProjection,
    project_ledger,
)
from .regression import run_regression
from .resolver import (
    AnswerStatus,
    CANONICAL_QUESTION,
    EvidenceRole,
    ResolutionResult,
    resolve_question,
)


class AuditError(ValueError):
    """Raised when an interactive audit session cannot be constructed."""


class AuditIntent(StrEnum):
    """The deliberately small set of locally recognized audit intentions."""

    CURRENT_ANSWER = "current_answer"
    UNCERTAINTY = "uncertainty"
    SUPERSEDED_DECISION = "superseded_decision"
    WRONG_ANSWER = "wrong_answer"
    EVIDENCE = "evidence"
    HISTORY_PRESERVATION = "history_preservation"
    APPLY_CORRECTION = "apply_correction"
    DIFFERENCE = "difference"
    VERIFY_REGRESSION = "verify_regression"
    FULL_HISTORY = "full_history"
    HELP = "help"
    RESET = "reset"
    EXIT = "exit"
    CONFIRM_YES = "confirm_yes"
    CONFIRM_NO = "confirm_no"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class AuditTurn:
    """One immutable, structured response from the audit controller."""

    intent: AuditIntent
    message: str
    revision: int
    awaiting_confirmation: bool = False
    should_exit: bool = False


def _normalize_input(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("audit input must be a string")
    normalized = " ".join(text.casefold().strip().split())
    if normalized == "?":
        return normalized
    return normalized.rstrip(".?!")


def recognize_intent(text: str) -> AuditIntent:
    """Map supported phrasing to an intent without generating domain facts."""

    normalized = _normalize_input(text)
    exact = {
        "?": AuditIntent.HELP,
        "help": AuditIntent.HELP,
        "reset": AuditIntent.RESET,
        "exit": AuditIntent.EXIT,
        "quit": AuditIntent.EXIT,
        "yes": AuditIntent.CONFIRM_YES,
        "y": AuditIntent.CONFIRM_YES,
        "no": AuditIntent.CONFIRM_NO,
        "n": AuditIntent.CONFIRM_NO,
        "ask": AuditIntent.CURRENT_ANSWER,
        "uncertainty": AuditIntent.UNCERTAINTY,
        "superseded": AuditIntent.SUPERSEDED_DECISION,
        "error": AuditIntent.WRONG_ANSWER,
        "evidence": AuditIntent.EVIDENCE,
        "history": AuditIntent.HISTORY_PRESERVATION,
        "correct": AuditIntent.APPLY_CORRECTION,
        "difference": AuditIntent.DIFFERENCE,
        "verify": AuditIntent.VERIFY_REGRESSION,
        "audit trail": AuditIntent.FULL_HISTORY,
    }
    if normalized in exact:
        return exact[normalized]
    if (
        "full history" in normalized
        or "full audit" in normalized
        or "audit trail" in normalized
    ):
        return AuditIntent.FULL_HISTORY
    if (
        "run the regression" in normalized
        or "regression" in normalized
        or "will not recur" in normalized
        or "will not repeat" in normalized
    ):
        return AuditIntent.VERIFY_REGRESSION
    if (
        "what changed" in normalized
        or "compare before and after" in normalized
        or "before and after" in normalized
    ):
        return AuditIntent.DIFFERENCE
    if "apply" in normalized and "correction" in normalized:
        return AuditIntent.APPLY_CORRECTION
    if (
        "overwritten" in normalized
        or "overwrite" in normalized
        or "deleted" in normalized
        or "history preserved" in normalized
    ):
        return AuditIntent.HISTORY_PRESERVATION
    if (
        "/api/release" in normalized
        or "original decision" in normalized
        or "superseded" in normalized
    ):
        return AuditIntent.SUPERSEDED_DECISION
    if (
        "wrong answer" in normalized
        or "mistake" in normalized
        or "historical error" in normalized
    ):
        return AuditIntent.WRONG_ANSWER
    if "uncertain" in normalized or "uncertainty" in normalized:
        return AuditIntent.UNCERTAINTY
    if "evidence" in normalized or "trust this answer" in normalized:
        return AuditIntent.EVIDENCE
    if (
        "current answer" in normalized
        or ("halcyon" in normalized and "publish" in normalized)
    ):
        return AuditIntent.CURRENT_ANSWER
    return AuditIntent.UNSUPPORTED


def render_audit_opening(revision: int) -> str:
    """Return the fixed local-session introduction."""

    return "\n".join(
        (
            "VICTORIA TRACE - INTERACTIVE AUDIT",
            "==================================",
            (
                "This is a deterministic audit of the synthetic Halcyon "
                "evidence chain, not a general chatbot."
            ),
            f"The disposable session starts before correction at revision {revision}.",
            "Ask questions in your own words within this supported scenario.",
            'Type "help" for examples and "exit" to end the session.',
            "No API key, network, LLM, installation, or paid service is used.",
            (
                "The repository fixture is read-only; session changes are "
                "discarded on exit."
            ),
        )
    )


def render_audit_help() -> str:
    """List the intentionally bounded audit topics and example phrasing."""

    return "\n".join(
        (
            "SUPPORTED HALCYON AUDIT TOPICS",
            "- ask | What is the current answer?",
            "- uncertainty | Why are you uncertain?",
            "- superseded | Why not /api/release?",
            "- error | Show the wrong answer.",
            "- evidence | Why should I trust this answer?",
            "- history | Was anything overwritten?",
            "- correct | Apply the correction. (requires yes/no confirmation)",
            "- difference | Compare before and after.",
            "- verify | Run the stored regression.",
            "- audit trail | Show the full history.",
            "- reset | Return this disposable session to revision 4.",
            "- exit | End the session and discard its state.",
        )
    )


def _chain(event_ids: tuple[str, ...]) -> str:
    return " -> ".join(event_ids) if event_ids else "none"


def _answer_evidence(result: ResolutionResult) -> tuple[str, ...]:
    return tuple(
        reference.event_id
        for reference in result.evidence
        if reference.role is not EvidenceRole.HISTORICAL_WRONG_ANSWER
    )


def _historical_errors(result: ResolutionResult) -> tuple[str, ...]:
    return tuple(
        reference.event_id
        for reference in result.evidence
        if reference.role is EvidenceRole.HISTORICAL_WRONG_ANSWER
    )


def _render_resolution(
    projection: StateProjection,
    result: ResolutionResult,
) -> str:
    location = result.location or "unresolved (no candidate selected)"
    lines = [
        "VICTORIA TRACE",
        f"State: {result.status.value.upper()}",
        f"Revision: {result.projection_revision}",
        f"Location: {location}",
        f"Format: {result.format or 'unavailable'}",
        f"Evidence: {_chain(_answer_evidence(result))}",
    ]
    historical = _historical_errors(result)
    if historical:
        lines.append(
            f"Historical error: {_chain(historical)} (retained, not authority)"
        )
    for uncertainty in result.uncertainties:
        lines.append(f"Uncertain field: {uncertainty.field}")
        lines.append(f"Candidates: {', '.join(uncertainty.candidates)}")
    authority = tuple(
        reference.event_id
        for reference in result.evidence
        if reference.role is EvidenceRole.AUTHORITATIVE_CORRECTION
    )
    if authority:
        correction = projection.get(authority[0]).event
        lines.append(
            "Authority: human-owner correction "
            f"{correction.event_id} ({correction.source.actor})"
        )
    regression_is_evidence = "REG-001" in result.evidence_event_ids
    lines.append(
        "REG-001 answer authority: "
        f"{'yes' if regression_is_evidence else 'no'}"
    )
    return "\n".join(lines)


def _render_uncertainty(
    projection: StateProjection,
    result: ResolutionResult,
) -> str:
    interpretation = projection.get("INT-001")
    if result.uncertainties:
        uncertainty = result.uncertainties[0]
        return "\n".join(
            (
                "VICTORIA TRACE - UNCERTAINTY",
                f"Revision: {result.projection_revision}",
                f"State: {interpretation.lifecycle.value.upper()}",
                f"Field: {uncertainty.field}",
                f"Candidates: {', '.join(uncertainty.candidates)}",
                f"Evidence: {_chain(uncertainty.evidence_event_ids)}",
                "Resolver choice: none; no candidate is confirmed.",
            )
        )
    resolution_causes = tuple(
        cause.source_event_id
        for cause in interpretation.causes
        if cause.effect is DerivedEffect.RESOLVED
    )
    return "\n".join(
        (
            "VICTORIA TRACE - UNCERTAINTY",
            f"Revision: {result.projection_revision}",
            f"State: {interpretation.lifecycle.value.upper()}",
            "Remaining uncertainty: none",
            f"Resolved by: {_chain(resolution_causes)}",
            "The interpretation remains visible; only its lifecycle changed.",
        )
    )


def _render_supersession(projection: StateProjection) -> str:
    original = projection.get("DEC-001")
    replacement = projection.get("DEC-002")
    causes = tuple(
        cause.source_event_id
        for cause in original.causes
        if cause.effect is DerivedEffect.SUPERSEDED
    )
    historical_location = original.event.claim.get("location")
    return "\n".join(
        (
            "VICTORIA TRACE - SUPERSEDED DECISION",
            f"Revision: {projection.through_revision}",
            f"DEC-001 state: {original.lifecycle.value.upper()}",
            f"Historical location: {historical_location}",
            f"Historical format: {original.event.claim.get('format')}",
            f"Superseded by: {_chain(causes)}",
            f"DEC-002 state: {replacement.lifecycle.value.upper()}",
            (
                f"Why not {historical_location}: the explicit supersedes "
                "relationship makes it historical, not current authority."
            ),
        )
    )


def _render_wrong_answer(projection: StateProjection) -> str:
    answer = projection.get("ANS-001")
    corrected = StateAnnotation.CORRECTED_BY_HUMAN in answer.annotations
    causes = tuple(
        cause.source_event_id
        for cause in answer.causes
        if cause.effect is DerivedEffect.CORRECTED
    )
    state = "CORRECTED HISTORICAL ERROR" if corrected else "HISTORICAL ERROR"
    omitted = tuple(str(item) for item in answer.event.claim.get("omitted_evidence", ()))
    lines = [
        "VICTORIA TRACE - HISTORICAL WRONG ANSWER",
        f"Revision: {projection.through_revision}",
        f"Event: {answer.event_id}",
        f"State: {state}",
        f"Recorded location: {answer.event.claim.get('location')}",
        f"Recorded format: {answer.event.claim.get('format')}",
        f"Omitted evidence: {_chain(omitted)}",
        "Current answer authority: no",
    ]
    if causes:
        lines.append(f"Corrected by: {_chain(causes)}")
    lines.append("The wrong answer remains inspectable and was not deleted.")
    return "\n".join(lines)


def _render_evidence(
    projection: StateProjection,
    result: ResolutionResult,
) -> str:
    lines = [
        "VICTORIA TRACE - ANSWER EVIDENCE",
        f"Revision: {result.projection_revision}",
        f"Resolver state: {result.status.value.upper()}",
    ]
    for reference in result.evidence:
        projected = projection.get(reference.event_id)
        lines.append(
            f"- {reference.event_id}: role={reference.role.value}; "
            f"lifecycle={projected.lifecycle.value}"
        )
    if "REG-001" in projection.by_event_id:
        lines.append("- REG-001: stored verifier; not used as answer evidence")
    lines.append(f"Answer evidence order: {_chain(_answer_evidence(result))}")
    return "\n".join(lines)


def _render_history_preservation(
    baseline: EventLedger,
    current: EventLedger,
) -> str:
    preserved = current.events[:4] == baseline.events
    appended = tuple(event.event_id for event in current[4:])
    old_answer_present = "ANS-001" in tuple(
        event.event_id for event in current
    )
    return "\n".join(
        (
            "VICTORIA TRACE - HISTORY PRESERVATION",
            f"Revision: {current.last_revision}",
            f"Revisions 1-4 unchanged: {'yes' if preserved else 'no'}",
            f"Old answer deleted: {'no' if old_answer_present else 'yes'}",
            f"Preserved events: {_chain(tuple(e.event_id for e in baseline))}",
            f"Appended events: {_chain(appended)}",
            (
                "History is projected into current state; earlier records are "
                "never overwritten in this session."
            ),
        )
    )


def _event_summary(projection: StateProjection, event_id: str) -> str:
    projected = projection.get(event_id)
    event = projected.event
    if event.kind is EventKind.DECISION:
        detail = event.claim.get("location", event.claim.get("location_description"))
    elif event.kind is EventKind.INTERPRETATION:
        detail = ", ".join(str(item) for item in event.claim.get("candidates", ()))
    elif event.kind in {EventKind.ANSWER, EventKind.CORRECTION}:
        detail = event.claim.get("location")
    else:
        expected = event.claim.get("expected", {})
        detail = f"expects {expected.get('location')}"
    relationships = ", ".join(
        f"{relationship.kind.value}->{relationship.target_event_id}"
        for relationship in event.relationships
    ) or "none"
    return (
        f"r{event.revision} {event.event_id} | {event.kind.value} | "
        f"{projected.lifecycle.value} | {detail} | relations: {relationships}"
    )


def _render_full_history(projection: StateProjection) -> str:
    lines = [
        "VICTORIA TRACE - FULL AUDIT TRAIL",
        f"Projection revision: {projection.through_revision}",
    ]
    lines.extend(
        _event_summary(projection, projected.event_id)
        for projected in projection.events
    )
    lines.append("All visible events are preserved in revision order.")
    return "\n".join(lines)


def _render_correction_proposal(result: CorrectionResult) -> str:
    correction = result.correction_event
    regression = result.regression_event
    relationships = ", ".join(
        f"{relationship.kind.value} {relationship.target_event_id}"
        for relationship in correction.relationships
    )
    return "\n".join(
        (
            "PROPOSED SYNTHETIC HUMAN CORRECTION",
            f"Human owner: {correction.source.actor}",
            f"Location: {correction.claim.get('location')}",
            f"Format: {correction.claim.get('format')}",
            f"Relationships: {relationships}",
            f"Will append: {correction.event_id} and {regression.event_id}",
            "No existing revision will be overwritten.",
            "Apply this correction? Type yes or no.",
        )
    )


def _render_correction_applied(result: CorrectionResult) -> str:
    correction_id = result.correction_event.event_id
    regression_id = result.regression_event.event_id
    regression_is_evidence = regression_id in (
        result.after_resolution.evidence_event_ids
    )
    return "\n".join(
        (
            "VICTORIA TRACE - CORRECTION APPLIED",
            f"Before state: {result.before_resolution.status.value.upper()}",
            f"After state: {result.after_resolution.status.value.upper()}",
            f"Revision: {result.resulting_revision}",
            f"Location: {result.after_resolution.location}",
            f"Format: {result.after_resolution.format}",
            f"Appended: {_chain(result.appended_event_ids)}",
            "Revisions 1-4 unchanged: yes",
            f"{correction_id} is answer authority; {regression_id} is a stored "
            f"verifier only (answer evidence: "
            f"{'yes' if regression_is_evidence else 'no'}).",
        )
    )


def _render_difference(result: CorrectionResult | None, revision: int) -> str:
    if result is None:
        return "\n".join(
            (
                "VICTORIA TRACE - BEFORE / AFTER",
                f"Revision: {revision}",
                "No correction has been applied in this session.",
                (
                    "Current state remains UNCERTAIN. Type \"correct\" to "
                    "review the proposed human-owner correction."
                ),
            )
        )
    before = result.before_resolution
    after = result.after_resolution
    correction = result.correction_event
    resolution_target = next(
        relationship.target_event_id
        for relationship in correction.relationships
        if relationship.kind.value == "resolves"
    )
    return "\n".join(
        (
            "VICTORIA TRACE - BEFORE / AFTER",
            f"Before: {before.status.value.upper()} | location unresolved | "
            f"format {before.format}",
            f"After: {after.status.value.upper()} | location {after.location} | "
            f"format {after.format}",
            f"Appended: {_chain(result.appended_event_ids)}",
            f"Why: {correction.event_id} resolved {resolution_target} with "
            "human-owner authority.",
            "The same deterministic resolver produced both results.",
        )
    )


def _render_regression(projection: StateProjection) -> str:
    if "REG-001" not in projection.by_event_id:
        return "\n".join(
            (
                "VICTORIA TRACE - REGRESSION",
                f"Revision: {projection.through_revision}",
                "REG-001 is unavailable before the correction.",
                "Nothing was fabricated or executed. Type \"correct\" first.",
            )
        )
    result = run_regression(projection, "REG-001")
    passed = sum(assertion.passed for assertion in result.assertions)
    lines = [
        "VICTORIA TRACE - STORED REGRESSION",
        f"Regression: {result.regression_event_id}",
        f"Generated from: {result.generated_from_correction_id}",
        f"Resolver state: {result.actual_resolution.status.value.upper()}",
        f"Actual location: {result.actual_resolution.location}",
        f"Actual format: {result.actual_resolution.format}",
        f"Assertions: {passed}/{len(result.assertions)} passed",
    ]
    lines.extend(
        f"- {'PASS' if assertion.passed else 'FAIL'}: {assertion.assertion_id}"
        for assertion in result.assertions
    )
    lines.extend(
        (
            f"Overall: {result.status.value.upper()}",
            "REG-001 verifies the resolver result; it is not answer authority.",
        )
    )
    return "\n".join(lines)


class AuditSession:
    """Mutable session shell around immutable Victoria Trace domain values."""

    def __init__(self, baseline: EventLedger) -> None:
        if not isinstance(baseline, EventLedger):
            raise TypeError("baseline must be an EventLedger")
        if baseline.last_revision != 4:
            raise AuditError("interactive audit must start at revision 4")
        projection = project_ledger(baseline)
        resolution = resolve_question(projection, CANONICAL_QUESTION)
        if resolution.status is not AnswerStatus.UNCERTAIN:
            raise AuditError("revision-4 audit baseline must be uncertain")
        self._baseline = baseline
        self._ledger = baseline
        self._pending_correction: CorrectionResult | None = None
        self._applied_correction: CorrectionResult | None = None

    @classmethod
    def from_reference_ledger(cls, reference: EventLedger) -> AuditSession:
        """Create a disposable revision-4 session from a validated fixture."""

        if not isinstance(reference, EventLedger):
            raise TypeError("reference must be an EventLedger")
        if reference.last_revision < 4:
            raise AuditError("reference ledger must contain revision 4")
        return cls(EventLedger.from_events(reference[:4]))

    @property
    def revision(self) -> int:
        return self._ledger.last_revision

    @property
    def ledger(self) -> EventLedger:
        return self._ledger

    @property
    def projection(self) -> StateProjection:
        return project_ledger(self._ledger)

    @property
    def awaiting_confirmation(self) -> bool:
        return self._pending_correction is not None

    def _turn(
        self,
        intent: AuditIntent,
        message: str,
        *,
        should_exit: bool = False,
    ) -> AuditTurn:
        return AuditTurn(
            intent=intent,
            message=message,
            revision=self.revision,
            awaiting_confirmation=self.awaiting_confirmation,
            should_exit=should_exit,
        )

    def _resolve(self) -> tuple[StateProjection, ResolutionResult]:
        projection = self.projection
        return projection, resolve_question(projection, CANONICAL_QUESTION)

    def _request_correction(self) -> AuditTurn:
        if self.revision == 6:
            return self._turn(
                AuditIntent.APPLY_CORRECTION,
                "The correction is already applied at revision 6. "
                "COR-001 and REG-001 were not duplicated.",
            )
        self._pending_correction = apply_correction(
            self._ledger,
            canonical_correction_request(),
        )
        return self._turn(
            AuditIntent.APPLY_CORRECTION,
            _render_correction_proposal(self._pending_correction),
        )

    def _confirm_correction(self, accepted: bool) -> AuditTurn:
        pending = self._pending_correction
        if pending is None:
            return self._turn(
                AuditIntent.UNSUPPORTED,
                "No correction is awaiting confirmation. Type \"correct\" to "
                "review it first.",
            )
        if not accepted:
            self._pending_correction = None
            return self._turn(
                AuditIntent.CONFIRM_NO,
                "Correction declined. No events were appended; the session "
                "remains at revision 4.",
            )
        self._ledger = pending.resulting_ledger
        self._applied_correction = pending
        self._pending_correction = None
        return self._turn(
            AuditIntent.CONFIRM_YES,
            _render_correction_applied(pending),
        )

    def reset(self) -> AuditTurn:
        self._ledger = self._baseline
        self._pending_correction = None
        self._applied_correction = None
        return self._turn(
            AuditIntent.RESET,
            "Session reset to revision 4. Disposable correction state was "
            "discarded; the repository fixture was never modified.",
        )

    def _exit(self) -> AuditTurn:
        self._ledger = self._baseline
        self._pending_correction = None
        self._applied_correction = None
        return self._turn(
            AuditIntent.EXIT,
            "Audit session ended. Disposable state was discarded.",
            should_exit=True,
        )

    def handle(self, text: str) -> AuditTurn:
        """Recognize one bounded intent and return an auditable response."""

        intent = recognize_intent(text)
        if self.awaiting_confirmation:
            if intent is AuditIntent.CONFIRM_YES:
                return self._confirm_correction(True)
            if intent is AuditIntent.CONFIRM_NO:
                return self._confirm_correction(False)
            if intent is AuditIntent.EXIT:
                return self._exit()
            if intent is AuditIntent.RESET:
                return self.reset()
            return self._turn(
                intent,
                "Confirmation required: type yes or no. No events were appended.",
            )

        if intent is AuditIntent.HELP:
            return self._turn(intent, render_audit_help())
        if intent is AuditIntent.EXIT:
            return self._exit()
        if intent is AuditIntent.RESET:
            return self.reset()
        if intent in {AuditIntent.CONFIRM_YES, AuditIntent.CONFIRM_NO}:
            return self._confirm_correction(intent is AuditIntent.CONFIRM_YES)
        if intent is AuditIntent.APPLY_CORRECTION:
            return self._request_correction()

        projection, result = self._resolve()
        if intent is AuditIntent.CURRENT_ANSWER:
            return self._turn(intent, _render_resolution(projection, result))
        if intent is AuditIntent.UNCERTAINTY:
            return self._turn(intent, _render_uncertainty(projection, result))
        if intent is AuditIntent.SUPERSEDED_DECISION:
            return self._turn(intent, _render_supersession(projection))
        if intent is AuditIntent.WRONG_ANSWER:
            return self._turn(intent, _render_wrong_answer(projection))
        if intent is AuditIntent.EVIDENCE:
            return self._turn(intent, _render_evidence(projection, result))
        if intent is AuditIntent.HISTORY_PRESERVATION:
            return self._turn(
                intent,
                _render_history_preservation(self._baseline, self._ledger),
            )
        if intent is AuditIntent.DIFFERENCE:
            return self._turn(
                intent,
                _render_difference(self._applied_correction, self.revision),
            )
        if intent is AuditIntent.VERIFY_REGRESSION:
            return self._turn(intent, _render_regression(projection))
        if intent is AuditIntent.FULL_HISTORY:
            return self._turn(intent, _render_full_history(projection))
        return self._turn(
            AuditIntent.UNSUPPORTED,
            "This local audit mode only supports questions about the synthetic "
            "Halcyon evidence chain. Type \"help\" to see the available audit "
            "topics.",
        )
