# Copyright (C) 2026 Peter Van Geldorp
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Human correction and durable regression-record creation for Halcyon."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
import os
from pathlib import Path
import tempfile

from .ledger import EventLedger, LedgerValidationError
from .models import (
    Event,
    EventKind,
    EventRelationship,
    Provenance,
    RelationshipKind,
)
from .projector import (
    LifecycleState,
    ProjectionError,
    StateAnnotation,
    project_ledger,
)
from .resolver import (
    AnswerStatus,
    CANONICAL_QUESTION,
    ResolutionError,
    ResolutionResult,
    resolve_question,
)


CORRECTION_EVENT_ID = "COR-001"
REGRESSION_EVENT_ID = "REG-001"
CORRECTION_DATE = date(2026, 4, 5)
EXPECTED_PRE_CORRECTION_IDS = ("DEC-001", "DEC-002", "INT-001", "ANS-001")
REQUIRED_EVIDENCE_IDS = ("DEC-001", "DEC-002", "INT-001", "COR-001")
FORBIDDEN_CURRENT_ANSWERS = ("/api/release", "release.json")

CANONICAL_HUMAN_OWNER = "Mira Chen"
CANONICAL_SOURCE_ID = "release-owner-correction"
CANONICAL_AUTHORITY = "human_owner"
CANONICAL_LOCATION = "public/release.json"
CANONICAL_FORMAT = "release-manifest/v2"


class CorrectionError(ValueError):
    """Base error for rejected correction operations."""


class CorrectionRequestError(CorrectionError):
    """Raised when a human correction request is invalid or incompatible."""


class CorrectionPreconditionError(CorrectionError):
    """Raised when the supplied ledger is not the revision-4 starting state."""


class CorrectionPersistenceError(CorrectionError):
    """Raised when durable all-or-nothing persistence cannot be completed."""


def _non_empty(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CorrectionRequestError(f"{field_name} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class CorrectionRequest:
    """Human-supplied facts accepted by the canonical correction operation."""

    human_owner: str
    source_id: str
    authority: str
    location: str
    format: str
    synthetic: bool

    def __post_init__(self) -> None:
        _non_empty(self.human_owner, "human_owner")
        _non_empty(self.source_id, "source_id")
        _non_empty(self.authority, "authority")
        _non_empty(self.location, "location")
        _non_empty(self.format, "format")
        if not isinstance(self.synthetic, bool):
            raise CorrectionRequestError("synthetic must be a boolean")


@dataclass(frozen=True, slots=True)
class CorrectionResult:
    """Immutable outcome of correction and regression-record construction."""

    original_revision: int
    resulting_revision: int
    correction_event: Event
    regression_event: Event
    resulting_ledger: EventLedger
    before_resolution: ResolutionResult
    after_resolution: ResolutionResult
    appended_event_ids: tuple[str, ...]
    persistence_requested: bool
    persistence_completed: bool

    def __post_init__(self) -> None:
        appended_event_ids = tuple(self.appended_event_ids)
        if self.original_revision != 4:
            raise CorrectionError("correction result must start at revision 4")
        if self.resulting_revision != 6:
            raise CorrectionError("correction result must end at revision 6")
        if appended_event_ids != (CORRECTION_EVENT_ID, REGRESSION_EVENT_ID):
            raise CorrectionError("correction result has unexpected appended events")
        if self.persistence_completed and not self.persistence_requested:
            raise CorrectionError(
                "persistence cannot complete when it was not requested"
            )
        object.__setattr__(self, "appended_event_ids", appended_event_ids)


def canonical_correction_request() -> CorrectionRequest:
    """Return the fixed synthetic human request used by the Halcyon demo."""

    return CorrectionRequest(
        human_owner=CANONICAL_HUMAN_OWNER,
        source_id=CANONICAL_SOURCE_ID,
        authority=CANONICAL_AUTHORITY,
        location=CANONICAL_LOCATION,
        format=CANONICAL_FORMAT,
        synthetic=True,
    )


def _validate_request(request: CorrectionRequest) -> None:
    expected = {
        "human_owner": CANONICAL_HUMAN_OWNER,
        "source_id": CANONICAL_SOURCE_ID,
        "authority": CANONICAL_AUTHORITY,
        "location": CANONICAL_LOCATION,
        "format": CANONICAL_FORMAT,
        "synthetic": True,
    }
    for field_name, expected_value in expected.items():
        actual_value = getattr(request, field_name)
        if actual_value != expected_value:
            raise CorrectionRequestError(
                f"{field_name} must be {expected_value!r} for the canonical correction"
            )


def _reject_existing_outputs(ledger: EventLedger) -> None:
    for event in ledger:
        if event.event_id == REGRESSION_EVENT_ID or event.kind is EventKind.REGRESSION:
            raise CorrectionPreconditionError(
                "ledger already contains the canonical regression record"
            )
    for event in ledger:
        if event.event_id == CORRECTION_EVENT_ID or event.kind is EventKind.CORRECTION:
            raise CorrectionPreconditionError(
                "ledger already contains an authoritative correction"
            )


def _validate_preconditions(ledger: EventLedger) -> ResolutionResult:
    _reject_existing_outputs(ledger)
    if ledger.last_revision != 4:
        raise CorrectionPreconditionError(
            "correction requires the ledger to end at revision 4"
        )
    event_ids = tuple(event.event_id for event in ledger)
    if event_ids != EXPECTED_PRE_CORRECTION_IDS:
        raise CorrectionPreconditionError(
            "revision-4 ledger must contain DEC-001, DEC-002, INT-001, and ANS-001"
        )

    try:
        projection = project_ledger(ledger)
    except ProjectionError as error:
        raise CorrectionPreconditionError(
            f"pre-correction projection is invalid: {error}"
        ) from error

    original = projection.get("DEC-001")
    decision = projection.get("DEC-002")
    interpretation = projection.get("INT-001")
    answer = projection.get("ANS-001")
    if original.lifecycle is not LifecycleState.SUPERSEDED:
        raise CorrectionPreconditionError("DEC-001 must be superseded")
    if decision.lifecycle is not LifecycleState.CURRENT:
        raise CorrectionPreconditionError("DEC-002 must be current")
    if interpretation.lifecycle is not LifecycleState.UNRESOLVED:
        raise CorrectionPreconditionError("INT-001 must be unresolved")
    if answer.lifecycle is not LifecycleState.HISTORICAL:
        raise CorrectionPreconditionError("ANS-001 must remain historical")
    if StateAnnotation.RECORDED_WRONG_ANSWER not in answer.annotations:
        raise CorrectionPreconditionError(
            "ANS-001 must be a recorded wrong answer"
        )
    if any(
        StateAnnotation.AUTHORITATIVE_HUMAN_CORRECTION in projected.annotations
        for projected in projection.events
    ):
        raise CorrectionPreconditionError(
            "pre-correction projection already contains authoritative correction"
        )

    try:
        before_resolution = resolve_question(projection, CANONICAL_QUESTION)
    except ResolutionError as error:
        raise CorrectionPreconditionError(
            f"pre-correction resolution is invalid: {error}"
        ) from error
    if before_resolution.status is not AnswerStatus.UNCERTAIN:
        raise CorrectionPreconditionError(
            "canonical question must be uncertain before correction"
        )
    if before_resolution.location is not None:
        raise CorrectionPreconditionError(
            "uncertain pre-correction answer cannot contain a location"
        )
    if before_resolution.format != CANONICAL_FORMAT:
        raise CorrectionPreconditionError(
            "pre-correction answer must already establish release-manifest/v2"
        )
    return before_resolution


def _create_correction_event(request: CorrectionRequest, revision: int) -> Event:
    return Event(
        event_id=CORRECTION_EVENT_ID,
        revision=revision,
        kind=EventKind.CORRECTION,
        occurred_on=CORRECTION_DATE,
        source=Provenance(
            source_id=request.source_id,
            source_type="human",
            synthetic=request.synthetic,
            actor=request.human_owner,
        ),
        claim={
            "authority": request.authority,
            "format": request.format,
            "incorrect_location": "release.json",
            "location": request.location,
            "subject": "halcyon.release_metadata",
        },
        relationships=(
            EventRelationship(RelationshipKind.CORRECTS, "ANS-001"),
            EventRelationship(RelationshipKind.RESOLVES, "INT-001"),
            EventRelationship(RelationshipKind.CLARIFIES, "DEC-002"),
        ),
    )


def _create_regression_event(request: CorrectionRequest, revision: int) -> Event:
    return Event(
        event_id=REGRESSION_EVENT_ID,
        revision=revision,
        kind=EventKind.REGRESSION,
        occurred_on=CORRECTION_DATE,
        source=Provenance(
            source_id="correction-regression",
            source_type="generated",
            synthetic=True,
            actor="Victoria Trace correction workflow",
        ),
        claim={
            "expected": {
                "format": request.format,
                "location": request.location,
            },
            "forbidden_locations": FORBIDDEN_CURRENT_ANSWERS,
            "question": CANONICAL_QUESTION,
            "required_evidence": REQUIRED_EVIDENCE_IDS,
            "required_states": {
                "COR-001": "authoritative_correction",
                "DEC-001": "superseded",
                "DEC-002": "current",
                "INT-001": "resolved",
            },
        },
        relationships=(
            EventRelationship(RelationshipKind.GENERATED_FROM, CORRECTION_EVENT_ID),
        ),
    )


def _validate_postconditions(
    original_ledger: EventLedger,
    resulting_ledger: EventLedger,
) -> ResolutionResult:
    if resulting_ledger.last_revision != 6:
        raise CorrectionError("corrected ledger must end at revision 6")
    if resulting_ledger.events[:4] != original_ledger.events:
        raise CorrectionError("correction changed pre-existing history")

    try:
        projection = project_ledger(resulting_ledger)
        after_resolution = resolve_question(projection, CANONICAL_QUESTION)
    except (ProjectionError, ResolutionError) as error:
        raise CorrectionError(f"corrected ledger failed validation: {error}") from error

    interpretation = projection.get("INT-001")
    answer = projection.get("ANS-001")
    correction = projection.get(CORRECTION_EVENT_ID)
    if interpretation.lifecycle is not LifecycleState.RESOLVED:
        raise CorrectionError("INT-001 was not resolved")
    if answer.lifecycle is not LifecycleState.HISTORICAL:
        raise CorrectionError("ANS-001 history was not preserved")
    if StateAnnotation.CORRECTED_BY_HUMAN not in answer.annotations:
        raise CorrectionError("ANS-001 was not marked corrected")
    if StateAnnotation.AUTHORITATIVE_HUMAN_CORRECTION not in correction.annotations:
        raise CorrectionError("COR-001 is not authoritative")
    if after_resolution.status is not AnswerStatus.SUPPORTED:
        raise CorrectionError("canonical question is not supported after correction")
    if after_resolution.location != CANONICAL_LOCATION:
        raise CorrectionError("corrected resolution has the wrong location")
    if after_resolution.format != CANONICAL_FORMAT:
        raise CorrectionError("corrected resolution has the wrong format")
    if after_resolution.evidence_event_ids != REQUIRED_EVIDENCE_IDS:
        raise CorrectionError("corrected resolution has unexpected evidence order")
    if REGRESSION_EVENT_ID in after_resolution.evidence_event_ids:
        raise CorrectionError("regression record influenced the current answer")
    return after_resolution


def apply_correction(
    ledger: EventLedger,
    request: CorrectionRequest,
) -> CorrectionResult:
    """Apply the canonical correction in memory without mutating ``ledger``."""

    if not isinstance(ledger, EventLedger):
        raise TypeError("ledger must be an EventLedger")
    if not isinstance(request, CorrectionRequest):
        raise TypeError("request must be a CorrectionRequest")
    _validate_request(request)
    before_resolution = _validate_preconditions(ledger)

    correction_event = _create_correction_event(
        request,
        ledger.last_revision + 1,
    )
    regression_event = _create_regression_event(
        request,
        ledger.last_revision + 2,
    )
    resulting_ledger = ledger.extend((correction_event, regression_event))
    after_resolution = _validate_postconditions(ledger, resulting_ledger)

    return CorrectionResult(
        original_revision=ledger.last_revision,
        resulting_revision=resulting_ledger.last_revision,
        correction_event=correction_event,
        regression_event=regression_event,
        resulting_ledger=resulting_ledger,
        before_resolution=before_resolution,
        after_resolution=after_resolution,
        appended_event_ids=(CORRECTION_EVENT_ID, REGRESSION_EVENT_ID),
        persistence_requested=False,
        persistence_completed=False,
    )


def _load_stable_file(
    ledger_path: Path,
) -> tuple[bytes, EventLedger]:
    if not ledger_path.exists() or not ledger_path.is_file():
        raise CorrectionPersistenceError(f"ledger file does not exist: {ledger_path}")
    try:
        original_bytes = ledger_path.read_bytes()
    except OSError as error:
        raise CorrectionPersistenceError(
            f"could not read ledger file: {ledger_path}"
        ) from error
    if original_bytes and not original_bytes.endswith(b"\n"):
        raise CorrectionPersistenceError(
            "existing ledger must end with a newline before atomic extension"
        )
    try:
        stored_ledger = EventLedger.load_jsonl(ledger_path)
    except (OSError, LedgerValidationError) as error:
        raise CorrectionPersistenceError(
            f"existing ledger file is invalid: {error}"
        ) from error
    try:
        verified_bytes = ledger_path.read_bytes()
    except OSError as error:
        raise CorrectionPersistenceError(
            f"could not verify ledger file: {ledger_path}"
        ) from error
    if verified_bytes != original_bytes:
        raise CorrectionPersistenceError("ledger file changed while it was validated")
    return original_bytes, stored_ledger


def _atomic_replace_ledger(
    ledger_path: Path,
    original_bytes: bytes,
    result: CorrectionResult,
) -> None:
    appended_bytes = (
        result.correction_event.to_json_line()
        + "\n"
        + result.regression_event.to_json_line()
        + "\n"
    ).encode("utf-8")
    completed_bytes = original_bytes + appended_bytes

    temporary_path: Path | None = None
    file_descriptor: int | None = None
    try:
        try:
            file_descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{ledger_path.name}.",
                suffix=".tmp",
                dir=ledger_path.parent,
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(file_descriptor, "wb") as stream:
                file_descriptor = None
                stream.write(completed_bytes)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as error:
            raise CorrectionPersistenceError(
                "could not write and fsync complete temporary ledger"
            ) from error

        try:
            temporary_ledger = EventLedger.load_jsonl(temporary_path)
        except (OSError, LedgerValidationError) as error:
            raise CorrectionPersistenceError(
                f"temporary corrected ledger is invalid: {error}"
            ) from error
        if temporary_ledger.events != result.resulting_ledger.events:
            raise CorrectionPersistenceError(
                "temporary corrected ledger does not match workflow result"
            )
        try:
            current_bytes = ledger_path.read_bytes()
        except OSError as error:
            raise CorrectionPersistenceError(
                "could not recheck ledger before atomic replacement"
            ) from error
        if current_bytes != original_bytes:
            raise CorrectionPersistenceError(
                "ledger file changed before atomic replacement"
            )

        try:
            os.replace(temporary_path, ledger_path)
        except OSError as error:
            raise CorrectionPersistenceError(
                "atomic ledger replacement failed; original file was retained"
            ) from error
        temporary_path = None
    finally:
        if file_descriptor is not None:
            try:
                os.close(file_descriptor)
            except OSError:
                pass
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def apply_correction_to_file(
    path: str | os.PathLike[str],
    ledger: EventLedger,
    request: CorrectionRequest,
) -> CorrectionResult:
    """Atomically persist both generated records to a matching local JSONL file."""

    if not isinstance(ledger, EventLedger):
        raise TypeError("ledger must be an EventLedger")
    if not isinstance(request, CorrectionRequest):
        raise TypeError("request must be a CorrectionRequest")
    ledger_path = Path(path)
    original_bytes, stored_ledger = _load_stable_file(ledger_path)
    if stored_ledger.events != ledger.events:
        raise CorrectionPersistenceError(
            "supplied ledger does not match the existing ledger file"
        )

    result = apply_correction(ledger, request)
    persisted_result = replace(
        result,
        persistence_requested=True,
        persistence_completed=True,
    )
    _atomic_replace_ledger(
        ledger_path,
        original_bytes,
        persisted_result,
    )
    return persisted_result
