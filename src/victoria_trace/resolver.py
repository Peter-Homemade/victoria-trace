"""Deterministic resolution of the single synthetic Halcyon question."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import EventKind, RelationshipKind
from .projector import (
    DerivedEffect,
    LifecycleState,
    ProjectedEvent,
    StateAnnotation,
    StateProjection,
)


CANONICAL_QUESTION = (
    "Where should Halcyon publish its release metadata, and in which format?"
)


class ResolutionError(ValueError):
    """Raised when projected state cannot support a consistent resolution."""


class AnswerStatus(StrEnum):
    """Whether the requested answer is supported by projected evidence."""

    SUPPORTED = "supported"
    UNCERTAIN = "uncertain"
    UNSUPPORTED = "unsupported"


class ResolutionReason(StrEnum):
    """Machine-readable explanation for the result status."""

    AUTHORITATIVE_CORRECTION = "authoritative_correction"
    LOCATION_UNRESOLVED = "location_unresolved"
    UNSUPPORTED_QUESTION = "unsupported_question"
    INSUFFICIENT_DECISION_EVIDENCE = "insufficient_decision_evidence"
    MISSING_INTERPRETATION_EVIDENCE = "missing_interpretation_evidence"


class UncertaintyKind(StrEnum):
    """Structured uncertainty currently understood by the resolver."""

    UNRESOLVED_INTERPRETATION = "unresolved_interpretation"


class EvidenceRole(StrEnum):
    """The resolution role played by one projected event."""

    HISTORICAL_DECISION = "historical_decision"
    CURRENT_DECISION = "current_decision"
    UNRESOLVED_INTERPRETATION = "unresolved_interpretation"
    RESOLVED_INTERPRETATION = "resolved_interpretation"
    HISTORICAL_WRONG_ANSWER = "historical_wrong_answer"
    AUTHORITATIVE_CORRECTION = "authoritative_correction"


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    """An ordered projected event identifier and its resolution role."""

    event_id: str
    role: EvidenceRole


@dataclass(frozen=True, slots=True)
class ResolutionUncertainty:
    """Structured ambiguity affecting one requested answer field."""

    kind: UncertaintyKind
    field: str
    candidates: tuple[str, ...]
    evidence_event_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        candidates = tuple(self.candidates)
        evidence_event_ids = tuple(self.evidence_event_ids)
        if not self.field:
            raise ResolutionError("uncertainty field must be non-empty")
        if len(candidates) < 2 or not all(
            isinstance(candidate, str) and candidate for candidate in candidates
        ):
            raise ResolutionError(
                "unresolved interpretation must contain at least two candidates"
            )
        if not evidence_event_ids or not all(evidence_event_ids):
            raise ResolutionError("uncertainty must identify supporting evidence")
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "evidence_event_ids", evidence_event_ids)


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    """Immutable resolution suitable for later CLI and regression consumers."""

    question: str
    projection_revision: int
    status: AnswerStatus
    location: str | None
    format: str | None
    uncertainties: tuple[ResolutionUncertainty, ...]
    evidence: tuple[EvidenceReference, ...]
    reason: ResolutionReason

    def __post_init__(self) -> None:
        uncertainties = tuple(self.uncertainties)
        evidence = tuple(self.evidence)
        if not isinstance(self.question, str):
            raise ResolutionError("question must be a string")
        if isinstance(self.projection_revision, bool) or not isinstance(
            self.projection_revision, int
        ):
            raise ResolutionError("projection_revision must be an integer")
        if self.projection_revision < 0:
            raise ResolutionError("projection_revision cannot be negative")
        if len({reference.event_id for reference in evidence}) != len(evidence):
            raise ResolutionError("resolution evidence IDs must be unique")
        if self.status is AnswerStatus.SUPPORTED:
            if not self.location or not self.format:
                raise ResolutionError(
                    "supported resolution requires location and format"
                )
            if uncertainties:
                raise ResolutionError(
                    "supported resolution cannot retain unresolved uncertainty"
                )
        elif self.status is AnswerStatus.UNCERTAIN:
            if not uncertainties:
                raise ResolutionError(
                    "uncertain resolution requires structured uncertainty"
                )
        elif self.status is not AnswerStatus.UNSUPPORTED:
            raise ResolutionError(f"unsupported answer status: {self.status!r}")
        object.__setattr__(self, "uncertainties", uncertainties)
        object.__setattr__(self, "evidence", evidence)

    @property
    def evidence_event_ids(self) -> tuple[str, ...]:
        return tuple(reference.event_id for reference in self.evidence)


def _ordered_evidence(
    projection: StateProjection,
    roles: dict[str, EvidenceRole],
) -> tuple[EvidenceReference, ...]:
    return tuple(
        EvidenceReference(projected.event_id, roles[projected.event_id])
        for projected in projection.events
        if projected.event_id in roles
    )


def _unsupported(
    projection: StateProjection,
    question: str,
    reason: ResolutionReason,
) -> ResolutionResult:
    return ResolutionResult(
        question=question,
        projection_revision=projection.through_revision,
        status=AnswerStatus.UNSUPPORTED,
        location=None,
        format=None,
        uncertainties=(),
        evidence=(),
        reason=reason,
    )


def _require_decision_state(
    original: ProjectedEvent,
    replacement: ProjectedEvent,
) -> str:
    if original.event.kind is not EventKind.DECISION:
        raise ResolutionError("DEC-001 is not projected as a decision")
    if replacement.event.kind is not EventKind.DECISION:
        raise ResolutionError("DEC-002 is not projected as a decision")
    if original.lifecycle is not LifecycleState.SUPERSEDED:
        raise ResolutionError("DEC-001 is not projected as superseded")
    if replacement.lifecycle is not LifecycleState.CURRENT:
        raise ResolutionError("DEC-002 is not the projected current decision")

    supersession_causes = tuple(
        cause
        for cause in original.causes
        if cause.effect is DerivedEffect.SUPERSEDED
        and cause.relationship is RelationshipKind.SUPERSEDES
    )
    if len(supersession_causes) != 1:
        raise ResolutionError(
            "DEC-001 does not have one auditable supersession cause"
        )
    cause = supersession_causes[0]
    if cause.source_event_id != "DEC-002" or cause.target_event_id != "DEC-001":
        raise ResolutionError("DEC-001 supersession is not caused by DEC-002")

    if replacement.event.claim.get("delivery") != "static_file":
        raise ResolutionError("DEC-002 does not establish static file delivery")
    answer_format = replacement.event.claim.get("format")
    if not isinstance(answer_format, str) or not answer_format:
        raise ResolutionError("DEC-002 has no usable manifest format")
    return answer_format


def _historical_answer_role(
    projection: StateProjection,
    roles: dict[str, EvidenceRole],
) -> None:
    answer = projection.by_event_id.get("ANS-001")
    if answer is None:
        return
    if answer.event.kind is not EventKind.ANSWER:
        raise ResolutionError("ANS-001 is not projected as an answer")
    if answer.lifecycle is not LifecycleState.HISTORICAL:
        raise ResolutionError("ANS-001 must remain historical")
    if StateAnnotation.RECORDED_WRONG_ANSWER not in answer.annotations:
        raise ResolutionError("ANS-001 is not marked as a recorded wrong answer")
    roles["ANS-001"] = EvidenceRole.HISTORICAL_WRONG_ANSWER


def _authoritative_corrections(
    projection: StateProjection,
) -> tuple[ProjectedEvent, ...]:
    return tuple(
        projected
        for projected in projection.events
        if projected.event.kind is EventKind.CORRECTION
        and projected.lifecycle is LifecycleState.CURRENT
        and StateAnnotation.AUTHORITATIVE_HUMAN_CORRECTION
        in projected.annotations
        and StateAnnotation.CORRECTED_ANSWER in projected.annotations
    )


def _resolution_cause(
    interpretation: ProjectedEvent,
) -> tuple[str, ...]:
    return tuple(
        cause.source_event_id
        for cause in interpretation.causes
        if cause.effect is DerivedEffect.RESOLVED
        and cause.relationship is RelationshipKind.RESOLVES
        and cause.target_event_id == interpretation.event_id
    )


def _resolve_uncertain(
    projection: StateProjection,
    question: str,
    answer_format: str,
    interpretation: ProjectedEvent,
) -> ResolutionResult:
    if _authoritative_corrections(projection):
        raise ResolutionError(
            "unresolved interpretation cannot coexist with current authoritative "
            "correction state"
        )
    raw_candidates = interpretation.event.claim.get("candidates")
    if not isinstance(raw_candidates, tuple):
        raise ResolutionError("INT-001 has no immutable candidate list")
    candidates = tuple(raw_candidates)
    if not all(isinstance(candidate, str) for candidate in candidates):
        raise ResolutionError("INT-001 candidates must be strings")

    roles = {
        "DEC-001": EvidenceRole.HISTORICAL_DECISION,
        "DEC-002": EvidenceRole.CURRENT_DECISION,
        "INT-001": EvidenceRole.UNRESOLVED_INTERPRETATION,
    }
    _historical_answer_role(projection, roles)
    uncertainty = ResolutionUncertainty(
        kind=UncertaintyKind.UNRESOLVED_INTERPRETATION,
        field="location",
        candidates=candidates,
        evidence_event_ids=("DEC-002", "INT-001"),
    )
    return ResolutionResult(
        question=question,
        projection_revision=projection.through_revision,
        status=AnswerStatus.UNCERTAIN,
        location=None,
        format=answer_format,
        uncertainties=(uncertainty,),
        evidence=_ordered_evidence(projection, roles),
        reason=ResolutionReason.LOCATION_UNRESOLVED,
    )


def _resolve_supported(
    projection: StateProjection,
    question: str,
    decision_format: str,
    decision: ProjectedEvent,
    interpretation: ProjectedEvent,
) -> ResolutionResult:
    corrections = _authoritative_corrections(projection)
    if not corrections:
        raise ResolutionError(
            "resolved interpretation has no current authoritative correction"
        )
    if len(corrections) != 1:
        raise ResolutionError(
            "multiple current authoritative corrections have no conflict policy"
        )
    correction = corrections[0]

    resolution_sources = _resolution_cause(interpretation)
    if resolution_sources != (correction.event_id,):
        raise ResolutionError(
            "INT-001 is not resolved by the authoritative correction"
        )
    if StateAnnotation.CLARIFIED_BY_HUMAN not in decision.annotations:
        raise ResolutionError(
            "DEC-002 lacks an authoritative clarification annotation"
        )
    clarification_sources = tuple(
        cause.source_event_id
        for cause in decision.causes
        if cause.effect is DerivedEffect.CLARIFIED
        and cause.relationship is RelationshipKind.CLARIFIES
        and cause.target_event_id == "DEC-002"
    )
    if clarification_sources != (correction.event_id,):
        raise ResolutionError(
            "DEC-002 is not clarified by the authoritative correction"
        )

    location = correction.event.claim.get("location")
    corrected_format = correction.event.claim.get("format")
    if not isinstance(location, str) or not location:
        raise ResolutionError("authoritative correction has no usable location")
    if not isinstance(corrected_format, str) or not corrected_format:
        raise ResolutionError("authoritative correction has no usable format")
    if corrected_format != decision_format:
        raise ResolutionError(
            "authoritative correction conflicts with the current decision format"
        )

    answer = projection.by_event_id.get("ANS-001")
    if answer is not None:
        if answer.lifecycle is not LifecycleState.HISTORICAL:
            raise ResolutionError("ANS-001 cannot be current authority")
        if StateAnnotation.RECORDED_WRONG_ANSWER not in answer.annotations:
            raise ResolutionError("ANS-001 is not a recorded wrong answer")

    roles = {
        "DEC-001": EvidenceRole.HISTORICAL_DECISION,
        "DEC-002": EvidenceRole.CURRENT_DECISION,
        "INT-001": EvidenceRole.RESOLVED_INTERPRETATION,
        correction.event_id: EvidenceRole.AUTHORITATIVE_CORRECTION,
    }
    return ResolutionResult(
        question=question,
        projection_revision=projection.through_revision,
        status=AnswerStatus.SUPPORTED,
        location=location,
        format=corrected_format,
        uncertainties=(),
        evidence=_ordered_evidence(projection, roles),
        reason=ResolutionReason.AUTHORITATIVE_CORRECTION,
    )


def resolve_question(
    projection: StateProjection,
    question: str,
) -> ResolutionResult:
    """Resolve the canonical Halcyon question from already-projected state."""

    if not isinstance(projection, StateProjection):
        raise TypeError("projection must be a StateProjection")
    if not isinstance(question, str):
        raise TypeError("question must be a string")
    if question.strip() != CANONICAL_QUESTION:
        return _unsupported(
            projection,
            question,
            ResolutionReason.UNSUPPORTED_QUESTION,
        )

    original = projection.by_event_id.get("DEC-001")
    replacement = projection.by_event_id.get("DEC-002")
    if original is None or replacement is None:
        return _unsupported(
            projection,
            question,
            ResolutionReason.INSUFFICIENT_DECISION_EVIDENCE,
        )
    answer_format = _require_decision_state(original, replacement)

    interpretation = projection.by_event_id.get("INT-001")
    if interpretation is None:
        return _unsupported(
            projection,
            question,
            ResolutionReason.MISSING_INTERPRETATION_EVIDENCE,
        )
    if interpretation.event.kind is not EventKind.INTERPRETATION:
        raise ResolutionError("INT-001 is not projected as an interpretation")

    if interpretation.lifecycle is LifecycleState.UNRESOLVED:
        return _resolve_uncertain(
            projection,
            question,
            answer_format,
            interpretation,
        )
    if interpretation.lifecycle is LifecycleState.RESOLVED:
        return _resolve_supported(
            projection,
            question,
            answer_format,
            replacement,
            interpretation,
        )
    raise ResolutionError(
        f"INT-001 has unsupported lifecycle {interpretation.lifecycle.value}"
    )
