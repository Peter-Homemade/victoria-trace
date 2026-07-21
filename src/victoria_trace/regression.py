# Copyright (C) 2026 Peter Van Geldorp
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Deterministic execution of projected Victoria Trace regression records."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias

from .models import EventKind, RelationshipKind
from .projector import (
    DerivedEffect,
    LifecycleState,
    ProjectedEvent,
    StateAnnotation,
    StateProjection,
)
from .resolver import (
    AnswerStatus,
    ResolutionError,
    ResolutionResult,
    resolve_question,
)


AssertionValue: TypeAlias = str | bool | None | tuple[str, ...]

_REGRESSION_CLAIM_FIELDS = frozenset(
    {
        "expected",
        "forbidden_locations",
        "question",
        "required_evidence",
        "required_states",
    }
)
_EXPECTED_FIELDS = frozenset({"format", "location"})
_STATE_EVENT_KINDS: dict[str, frozenset[EventKind]] = {
    "authoritative_correction": frozenset({EventKind.CORRECTION}),
    "current": frozenset({EventKind.DECISION, EventKind.CORRECTION}),
    "resolved": frozenset({EventKind.INTERPRETATION}),
    "superseded": frozenset({EventKind.DECISION}),
}


class RegressionError(ValueError):
    """Base error for regression discovery, validation, and execution."""


class RegressionNotFoundError(RegressionError):
    """Raised when the requested regression is absent from the projection."""


class RegressionDefinitionError(RegressionError):
    """Raised when a stored regression cannot be executed safely."""


class RegressionExecutionError(RegressionError):
    """Raised when the resolver cannot execute against the supplied projection."""


class RegressionStatus(StrEnum):
    """Outcome of executing a structurally valid stored regression."""

    PASSED = "passed"
    FAILED = "failed"


class RegressionReason(StrEnum):
    """Machine-readable reason for the overall regression status."""

    ALL_ASSERTIONS_PASSED = "all_assertions_passed"
    ASSERTIONS_FAILED = "assertions_failed"


class AssertionStatus(StrEnum):
    """Outcome of one deterministic regression assertion."""

    PASSED = "passed"
    FAILED = "failed"


class AssertionKind(StrEnum):
    """Supported assertion semantics in their execution-order categories."""

    RESOLVER_STATUS = "resolver_status"
    EXPECTED_LOCATION = "expected_location"
    EXPECTED_FORMAT = "expected_format"
    REQUIRED_EVIDENCE = "required_evidence"
    REQUIRED_PROJECTED_STATE = "required_projected_state"
    FORBIDDEN_CURRENT_LOCATION = "forbidden_current_location"
    EXCLUDED_ANSWER_EVIDENCE = "excluded_answer_evidence"
    EXCLUDED_REGRESSION_EVIDENCE = "excluded_regression_evidence"


def _freeze_assertion_value(value: object, field_name: str) -> AssertionValue:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (list, tuple)) and all(
        isinstance(item, str) for item in value
    ):
        return tuple(value)
    raise RegressionError(
        f"{field_name} must be a string, boolean, null, or string tuple"
    )


def _event_ids(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise RegressionError(f"{field_name} must be an ordered string sequence")
    result = tuple(value)
    if not all(isinstance(event_id, str) and event_id for event_id in result):
        raise RegressionError(f"{field_name} must contain non-empty event IDs")
    if len(set(result)) != len(result):
        raise RegressionError(f"{field_name} must contain unique event IDs")
    return result


@dataclass(frozen=True, slots=True)
class RegressionAssertion:
    """One immutable comparison made during regression execution."""

    assertion_id: str
    kind: AssertionKind
    expected: AssertionValue
    actual: AssertionValue
    status: AssertionStatus
    event_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.assertion_id, str) or not self.assertion_id:
            raise RegressionError("assertion_id must be a non-empty string")
        if not isinstance(self.kind, AssertionKind):
            raise RegressionError("kind must be an AssertionKind")
        if not isinstance(self.status, AssertionStatus):
            raise RegressionError("status must be an AssertionStatus")
        expected = _freeze_assertion_value(self.expected, "expected")
        actual = _freeze_assertion_value(self.actual, "actual")
        event_ids = _event_ids(self.event_ids, "event_ids")
        object.__setattr__(self, "expected", expected)
        object.__setattr__(self, "actual", actual)
        object.__setattr__(self, "event_ids", event_ids)

    @property
    def passed(self) -> bool:
        return self.status is AssertionStatus.PASSED


@dataclass(frozen=True, slots=True)
class RegressionResult:
    """Immutable structured result of one stored regression execution."""

    regression_event_id: str
    projection_revision: int
    question: str
    status: RegressionStatus
    actual_resolution: ResolutionResult
    expected_location: str
    expected_format: str
    assertions: tuple[RegressionAssertion, ...]
    failed_assertion_ids: tuple[str, ...]
    required_evidence_ids: tuple[str, ...]
    actual_evidence_ids: tuple[str, ...]
    generated_from_correction_id: str
    reason: RegressionReason

    def __post_init__(self) -> None:
        if (
            not isinstance(self.regression_event_id, str)
            or not self.regression_event_id
        ):
            raise RegressionError("regression_event_id must be a non-empty string")
        if isinstance(self.projection_revision, bool) or not isinstance(
            self.projection_revision, int
        ):
            raise RegressionError("projection_revision must be an integer")
        if self.projection_revision < 1:
            raise RegressionError("projection_revision must be positive")
        if not isinstance(self.question, str) or not self.question:
            raise RegressionError("question must be a non-empty string")
        if not isinstance(self.status, RegressionStatus):
            raise RegressionError("status must be a RegressionStatus")
        if not isinstance(self.actual_resolution, ResolutionResult):
            raise RegressionError("actual_resolution must be a ResolutionResult")
        if not isinstance(self.expected_location, str) or not self.expected_location:
            raise RegressionError("expected_location must be a non-empty string")
        if not isinstance(self.expected_format, str) or not self.expected_format:
            raise RegressionError("expected_format must be a non-empty string")
        if not isinstance(self.reason, RegressionReason):
            raise RegressionError("reason must be a RegressionReason")

        assertions = tuple(self.assertions)
        if not assertions or not all(
            isinstance(assertion, RegressionAssertion) for assertion in assertions
        ):
            raise RegressionError("assertions must contain regression assertions")
        assertion_ids = tuple(assertion.assertion_id for assertion in assertions)
        if len(set(assertion_ids)) != len(assertion_ids):
            raise RegressionError("assertion IDs must be unique")
        failed_assertion_ids = _event_ids(
            self.failed_assertion_ids,
            "failed_assertion_ids",
        )
        required_evidence_ids = _event_ids(
            self.required_evidence_ids,
            "required_evidence_ids",
        )
        actual_evidence_ids = _event_ids(
            self.actual_evidence_ids,
            "actual_evidence_ids",
        )
        derived_failures = tuple(
            assertion.assertion_id
            for assertion in assertions
            if assertion.status is AssertionStatus.FAILED
        )
        if failed_assertion_ids != derived_failures:
            raise RegressionError(
                "failed_assertion_ids must match failed assertions in order"
            )
        expected_status = (
            RegressionStatus.FAILED
            if derived_failures
            else RegressionStatus.PASSED
        )
        expected_reason = (
            RegressionReason.ASSERTIONS_FAILED
            if derived_failures
            else RegressionReason.ALL_ASSERTIONS_PASSED
        )
        if self.status is not expected_status or self.reason is not expected_reason:
            raise RegressionError("overall status and reason contradict assertions")
        if self.actual_resolution.projection_revision != self.projection_revision:
            raise RegressionError("resolution and regression revisions must match")
        if self.actual_resolution.question != self.question:
            raise RegressionError("resolution and regression questions must match")
        if self.actual_resolution.evidence_event_ids != actual_evidence_ids:
            raise RegressionError("actual_evidence_ids must match the resolution")

        object.__setattr__(self, "assertions", assertions)
        object.__setattr__(self, "failed_assertion_ids", failed_assertion_ids)
        object.__setattr__(self, "required_evidence_ids", required_evidence_ids)
        object.__setattr__(self, "actual_evidence_ids", actual_evidence_ids)


@dataclass(frozen=True, slots=True)
class _RegressionDefinition:
    question: str
    expected_location: str
    expected_format: str
    required_evidence_ids: tuple[str, ...]
    required_states: tuple[tuple[str, str], ...]
    forbidden_locations: tuple[str, ...]
    generated_from_correction_id: str


def _definition_error(event_id: str, message: str) -> RegressionDefinitionError:
    return RegressionDefinitionError(f"regression {event_id}: {message}")


def _exact_fields(
    value: object,
    expected_fields: frozenset[str],
    field_name: str,
    event_id: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _definition_error(event_id, f"{field_name} must be an object")
    fields = frozenset(value)
    missing = expected_fields - fields
    unknown = fields - expected_fields
    if missing:
        raise _definition_error(
            event_id,
            f"{field_name} is missing fields: {', '.join(sorted(missing))}",
        )
    if unknown:
        raise _definition_error(
            event_id,
            f"{field_name} has unknown fields: {', '.join(sorted(unknown))}",
        )
    return value


def _required_string(value: object, field_name: str, event_id: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _definition_error(event_id, f"{field_name} must be a non-empty string")
    return value


def _required_string_tuple(
    value: object,
    field_name: str,
    event_id: str,
) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not value:
        raise _definition_error(
            event_id,
            f"{field_name} must be a non-empty ordered string array",
        )
    result = tuple(value)
    if not all(isinstance(item, str) and item.strip() for item in result):
        raise _definition_error(
            event_id,
            f"{field_name} must contain non-empty strings",
        )
    if len(set(result)) != len(result):
        raise _definition_error(event_id, f"{field_name} must contain unique values")
    return result


def _validate_projected_regression(
    projection: StateProjection,
    event_id: str,
) -> tuple[ProjectedEvent, str]:
    projected = projection.by_event_id.get(event_id)
    if projected is None:
        raise RegressionNotFoundError(
            f"regression {event_id} is unavailable through revision "
            f"{projection.through_revision}"
        )
    if projected.event.kind is not EventKind.REGRESSION:
        raise _definition_error(event_id, "requested event is not a regression")
    if projected.lifecycle is not LifecycleState.HISTORICAL:
        raise _definition_error(event_id, "projected regression must be historical")
    if StateAnnotation.REGRESSION_RECORD not in projected.annotations:
        raise _definition_error(
            event_id,
            "projected event lacks the regression-record annotation",
        )

    relationships = projected.event.relationships
    if len(relationships) != 1 or (
        relationships[0].kind is not RelationshipKind.GENERATED_FROM
    ):
        raise _definition_error(
            event_id,
            "must have exactly one generated_from relationship",
        )
    correction_id = relationships[0].target_event_id
    correction = projection.by_event_id.get(correction_id)
    if correction is None:
        raise _definition_error(
            event_id,
            f"generated-from correction {correction_id} is missing",
        )
    if correction.event.kind is not EventKind.CORRECTION:
        raise _definition_error(
            event_id,
            f"generated_from target {correction_id} is not a correction",
        )
    if correction.revision >= projected.revision:
        raise _definition_error(
            event_id,
            "generated-from correction must precede the regression",
        )
    if correction.lifecycle is not LifecycleState.CURRENT or (
        StateAnnotation.AUTHORITATIVE_HUMAN_CORRECTION
        not in correction.annotations
    ):
        raise _definition_error(
            event_id,
            f"generated_from target {correction_id} is not authoritative",
        )

    generated_causes = tuple(
        cause
        for cause in projected.causes
        if cause.effect is DerivedEffect.GENERATED_FROM
        and cause.relationship is RelationshipKind.GENERATED_FROM
    )
    if len(generated_causes) != 1:
        raise _definition_error(
            event_id,
            "projected regression must retain one generated_from cause",
        )
    cause = generated_causes[0]
    if cause.source_event_id != event_id or cause.target_event_id != correction_id:
        raise _definition_error(
            event_id,
            "projected generated_from cause contradicts the stored relationship",
        )
    return projected, correction_id


def _validate_definition(
    projection: StateProjection,
    event_id: str,
) -> _RegressionDefinition:
    projected, correction_id = _validate_projected_regression(projection, event_id)
    claim = _exact_fields(
        projected.event.claim,
        _REGRESSION_CLAIM_FIELDS,
        "claim",
        event_id,
    )
    expected = _exact_fields(
        claim["expected"],
        _EXPECTED_FIELDS,
        "claim.expected",
        event_id,
    )
    question = _required_string(claim["question"], "claim.question", event_id)
    expected_location = _required_string(
        expected["location"],
        "claim.expected.location",
        event_id,
    )
    expected_format = _required_string(
        expected["format"],
        "claim.expected.format",
        event_id,
    )
    required_evidence = _required_string_tuple(
        claim["required_evidence"],
        "claim.required_evidence",
        event_id,
    )
    forbidden_locations = _required_string_tuple(
        claim["forbidden_locations"],
        "claim.forbidden_locations",
        event_id,
    )
    if expected_location in forbidden_locations:
        raise _definition_error(
            event_id,
            "expected location cannot also be a forbidden current location",
        )

    if event_id in required_evidence:
        raise _definition_error(
            event_id,
            "cannot require itself as answer evidence",
        )
    revision_by_event_id = {
        projected_event.event_id: projected_event.revision
        for projected_event in projection.events
    }
    missing_evidence = tuple(
        evidence_id
        for evidence_id in required_evidence
        if evidence_id not in revision_by_event_id
    )
    if missing_evidence:
        raise _definition_error(
            event_id,
            "required evidence is missing from the projection: "
            + ", ".join(missing_evidence),
        )
    evidence_revisions = tuple(
        revision_by_event_id[evidence_id] for evidence_id in required_evidence
    )
    if evidence_revisions != tuple(sorted(evidence_revisions)):
        raise _definition_error(
            event_id,
            "required evidence must follow projection revision order",
        )

    raw_required_states = claim["required_states"]
    if not isinstance(raw_required_states, Mapping) or not raw_required_states:
        raise _definition_error(
            event_id,
            "claim.required_states must be a non-empty object",
        )
    required_states: list[tuple[str, str]] = []
    for projected_event in projection.events:
        required_state = raw_required_states.get(projected_event.event_id)
        if required_state is None:
            continue
        if not isinstance(required_state, str) or not required_state:
            raise _definition_error(
                event_id,
                f"required state for {projected_event.event_id} must be a string",
            )
        compatible_kinds = _STATE_EVENT_KINDS.get(required_state)
        if compatible_kinds is None:
            raise _definition_error(
                event_id,
                f"unknown required-state syntax: {required_state}",
            )
        if projected_event.event.kind not in compatible_kinds:
            raise _definition_error(
                event_id,
                f"required state {required_state} is incompatible with "
                f"{projected_event.event_id}",
            )
        required_states.append((projected_event.event_id, required_state))

    raw_state_ids = tuple(raw_required_states)
    if not all(isinstance(state_id, str) and state_id for state_id in raw_state_ids):
        raise _definition_error(
            event_id,
            "claim.required_states keys must be non-empty event IDs",
        )
    ordered_state_ids = tuple(state_id for state_id, _ in required_states)
    missing_state_events = tuple(
        state_id for state_id in raw_state_ids if state_id not in revision_by_event_id
    )
    if missing_state_events:
        raise _definition_error(
            event_id,
            "required-state events are missing from the projection: "
            + ", ".join(missing_state_events),
        )
    if set(ordered_state_ids) != set(raw_state_ids):
        raise _definition_error(event_id, "required states could not be validated")

    return _RegressionDefinition(
        question=question,
        expected_location=expected_location,
        expected_format=expected_format,
        required_evidence_ids=required_evidence,
        required_states=tuple(required_states),
        forbidden_locations=forbidden_locations,
        generated_from_correction_id=correction_id,
    )


def _ordered_union(*groups: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    for group in groups:
        for event_id in group:
            if event_id not in result:
                result.append(event_id)
    return tuple(result)


def _assertion(
    assertion_id: str,
    kind: AssertionKind,
    expected: AssertionValue,
    actual: AssertionValue,
    *,
    event_ids: tuple[str, ...] = (),
) -> RegressionAssertion:
    return RegressionAssertion(
        assertion_id=assertion_id,
        kind=kind,
        expected=expected,
        actual=actual,
        status=(
            AssertionStatus.PASSED
            if expected == actual
            else AssertionStatus.FAILED
        ),
        event_ids=event_ids,
    )


def _actual_required_state(
    projected: ProjectedEvent,
    expected_state: str,
) -> str:
    if expected_state == "authoritative_correction":
        if (
            StateAnnotation.AUTHORITATIVE_HUMAN_CORRECTION
            in projected.annotations
        ):
            return "authoritative_correction"
        return "not_authoritative_correction"
    return projected.lifecycle.value


def _execute_assertions(
    projection: StateProjection,
    regression_event_id: str,
    definition: _RegressionDefinition,
    resolution: ResolutionResult,
) -> tuple[RegressionAssertion, ...]:
    actual_evidence = resolution.evidence_event_ids
    evidence_events = _ordered_union(
        definition.required_evidence_ids,
        actual_evidence,
    )
    assertions: list[RegressionAssertion] = [
        _assertion(
            "resolver.status",
            AssertionKind.RESOLVER_STATUS,
            AnswerStatus.SUPPORTED.value,
            resolution.status.value,
            event_ids=actual_evidence,
        ),
        _assertion(
            "answer.location",
            AssertionKind.EXPECTED_LOCATION,
            definition.expected_location,
            resolution.location,
            event_ids=actual_evidence,
        ),
        _assertion(
            "answer.format",
            AssertionKind.EXPECTED_FORMAT,
            definition.expected_format,
            resolution.format,
            event_ids=actual_evidence,
        ),
        _assertion(
            "answer.evidence",
            AssertionKind.REQUIRED_EVIDENCE,
            definition.required_evidence_ids,
            actual_evidence,
            event_ids=evidence_events,
        ),
    ]

    for state_event_id, expected_state in definition.required_states:
        projected = projection.get(state_event_id)
        assertions.append(
            _assertion(
                f"state.{state_event_id}",
                AssertionKind.REQUIRED_PROJECTED_STATE,
                expected_state,
                _actual_required_state(projected, expected_state),
                event_ids=(state_event_id,),
            )
        )

    for index, forbidden_location in enumerate(
        definition.forbidden_locations,
        start=1,
    ):
        assertions.append(
            _assertion(
                f"forbidden_location.{index:03d}",
                AssertionKind.FORBIDDEN_CURRENT_LOCATION,
                False,
                resolution.location == forbidden_location,
                event_ids=actual_evidence,
            )
        )

    assertions.extend(
        (
            _assertion(
                "answer.excludes.ANS-001",
                AssertionKind.EXCLUDED_ANSWER_EVIDENCE,
                False,
                "ANS-001" in actual_evidence,
                event_ids=("ANS-001",),
            ),
            _assertion(
                f"answer.excludes.{regression_event_id}",
                AssertionKind.EXCLUDED_REGRESSION_EVIDENCE,
                False,
                regression_event_id in actual_evidence,
                event_ids=(regression_event_id,),
            ),
        )
    )
    return tuple(assertions)


def run_regression(
    projection: StateProjection,
    regression_event_id: str,
) -> RegressionResult:
    """Validate and execute one projected regression through the resolver."""

    if not isinstance(projection, StateProjection):
        raise TypeError("projection must be a StateProjection")
    if not isinstance(regression_event_id, str) or not regression_event_id:
        raise TypeError("regression_event_id must be a non-empty string")

    definition = _validate_definition(projection, regression_event_id)
    try:
        resolution = resolve_question(projection, definition.question)
    except ResolutionError as error:
        raise RegressionExecutionError(
            f"regression {regression_event_id}: resolver could not execute: {error}"
        ) from error
    if resolution.status is AnswerStatus.UNSUPPORTED:
        raise _definition_error(
            regression_event_id,
            "stored question is unsupported by the resolver",
        )

    assertions = _execute_assertions(
        projection,
        regression_event_id,
        definition,
        resolution,
    )
    failed_assertion_ids = tuple(
        assertion.assertion_id
        for assertion in assertions
        if assertion.status is AssertionStatus.FAILED
    )
    status = (
        RegressionStatus.FAILED
        if failed_assertion_ids
        else RegressionStatus.PASSED
    )
    reason = (
        RegressionReason.ASSERTIONS_FAILED
        if failed_assertion_ids
        else RegressionReason.ALL_ASSERTIONS_PASSED
    )
    return RegressionResult(
        regression_event_id=regression_event_id,
        projection_revision=projection.through_revision,
        question=definition.question,
        status=status,
        actual_resolution=resolution,
        expected_location=definition.expected_location,
        expected_format=definition.expected_format,
        assertions=assertions,
        failed_assertion_ids=failed_assertion_ids,
        required_evidence_ids=definition.required_evidence_ids,
        actual_evidence_ids=resolution.evidence_event_ids,
        generated_from_correction_id=definition.generated_from_correction_id,
        reason=reason,
    )


def run_all_regressions(
    projection: StateProjection,
) -> tuple[RegressionResult, ...]:
    """Execute visible regression records in deterministic revision order."""

    if not isinstance(projection, StateProjection):
        raise TypeError("projection must be a StateProjection")
    return tuple(
        run_regression(projection, projected.event_id)
        for projected in projection.events
        if projected.event.kind is EventKind.REGRESSION
    )
