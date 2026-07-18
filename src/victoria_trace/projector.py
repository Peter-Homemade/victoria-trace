"""Deterministic projection of immutable ledger events into auditable state."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from types import MappingProxyType

from .ledger import EventLedger
from .models import Event, EventKind, EventRelationship, RelationshipKind


class ProjectionError(ValueError):
    """Raised when a requested projection or state transition is inconsistent."""


class LifecycleState(StrEnum):
    """The lifecycle dimension derived for an event at a ledger revision."""

    CURRENT = "current"
    SUPERSEDED = "superseded"
    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"
    HISTORICAL = "historical"


class StateAnnotation(StrEnum):
    """Semantic facts kept separate from an event's lifecycle."""

    RECORDED_WRONG_ANSWER = "recorded_wrong_answer"
    CORRECTED_BY_HUMAN = "corrected_by_human"
    CORRECTED_ANSWER = "corrected_answer"
    AUTHORITATIVE_HUMAN_CORRECTION = "authoritative_human_correction"
    CLARIFIED_BY_HUMAN = "clarified_by_human"
    REGRESSION_RECORD = "regression_record"


class DerivedEffect(StrEnum):
    """The precise projected effect associated with a ledger relationship."""

    SUPERSEDED = "superseded"
    INTERPRETS = "interprets"
    CITES = "cites"
    CORRECTED = "corrected"
    RESOLVED = "resolved"
    CLARIFIED = "clarified"
    GENERATED_FROM = "generated_from"


@dataclass(frozen=True, slots=True)
class StateCause:
    """A ledger edge that caused or supports one part of projected state."""

    effect: DerivedEffect
    relationship: RelationshipKind
    source_event_id: str
    target_event_id: str


@dataclass(frozen=True, slots=True)
class ProjectedEvent:
    """One original event plus immutable state derived through a revision."""

    event: Event
    lifecycle: LifecycleState
    annotations: frozenset[StateAnnotation] = frozenset()
    causes: tuple[StateCause, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "annotations", frozenset(self.annotations))
        object.__setattr__(self, "causes", tuple(self.causes))

    @property
    def event_id(self) -> str:
        return self.event.event_id

    @property
    def revision(self) -> int:
        return self.event.revision

    @property
    def evidence_event_ids(self) -> tuple[str, ...]:
        """Return stable, ordered event identifiers supporting this state."""

        evidence: list[str] = []

        def add(event_id: str) -> None:
            if event_id not in evidence:
                evidence.append(event_id)

        add(self.event_id)
        for relationship in self.event.relationships:
            add(relationship.target_event_id)
        for cause in self.causes:
            add(cause.source_event_id)
            add(cause.target_event_id)
        return tuple(evidence)


@dataclass(frozen=True, slots=True)
class StateProjection:
    """Immutable result of replaying a ledger through an inclusive revision."""

    through_revision: int
    events: tuple[ProjectedEvent, ...]
    _by_event_id: Mapping[str, ProjectedEvent] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        events = tuple(self.events)
        if isinstance(self.through_revision, bool) or not isinstance(
            self.through_revision, int
        ):
            raise ProjectionError("through_revision must be an integer")
        if self.through_revision != len(events):
            raise ProjectionError(
                "through_revision must equal the number of projected events"
            )
        by_event_id: dict[str, ProjectedEvent] = {}
        for expected_revision, projected_event in enumerate(events, start=1):
            if projected_event.revision != expected_revision:
                raise ProjectionError(
                    f"projected event {projected_event.event_id} is out of order"
                )
            if projected_event.event_id in by_event_id:
                raise ProjectionError(
                    f"duplicate projected event ID: {projected_event.event_id}"
                )
            by_event_id[projected_event.event_id] = projected_event
        object.__setattr__(self, "events", events)
        object.__setattr__(self, "_by_event_id", MappingProxyType(by_event_id))

    @property
    def by_event_id(self) -> Mapping[str, ProjectedEvent]:
        return self._by_event_id

    def get(self, event_id: str) -> ProjectedEvent:
        return self._by_event_id[event_id]

    def __iter__(self) -> Iterator[ProjectedEvent]:
        return iter(self.events)

    def __len__(self) -> int:
        return len(self.events)


def _is_authoritative_human_correction(event: Event) -> bool:
    return (
        event.kind is EventKind.CORRECTION
        and event.source.source_type == "human"
        and event.source.actor is not None
        and event.claim.get("authority") == "human_owner"
    )


def _initial_state(event: Event) -> ProjectedEvent:
    annotations: set[StateAnnotation] = set()

    if event.kind is EventKind.DECISION:
        lifecycle = LifecycleState.CURRENT
    elif event.kind is EventKind.INTERPRETATION:
        if event.claim.get("status") != "unresolved":
            raise ProjectionError(
                f"interpretation {event.event_id} must begin unresolved"
            )
        lifecycle = LifecycleState.UNRESOLVED
    elif event.kind is EventKind.ANSWER:
        lifecycle = LifecycleState.HISTORICAL
        if event.claim.get("outcome") == "incorrect":
            annotations.add(StateAnnotation.RECORDED_WRONG_ANSWER)
    elif event.kind is EventKind.CORRECTION:
        if not _is_authoritative_human_correction(event):
            raise ProjectionError(
                f"correction {event.event_id} is not an explicit authoritative "
                "human correction"
            )
        location = event.claim.get("location")
        answer_format = event.claim.get("format")
        if not isinstance(location, str) or not location:
            raise ProjectionError(
                f"correction {event.event_id} has no corrected location"
            )
        if not isinstance(answer_format, str) or not answer_format:
            raise ProjectionError(
                f"correction {event.event_id} has no corrected format"
            )
        lifecycle = LifecycleState.CURRENT
        annotations.update(
            {
                StateAnnotation.AUTHORITATIVE_HUMAN_CORRECTION,
                StateAnnotation.CORRECTED_ANSWER,
            }
        )
    elif event.kind is EventKind.REGRESSION:
        lifecycle = LifecycleState.HISTORICAL
        annotations.add(StateAnnotation.REGRESSION_RECORD)
    else:  # pragma: no cover - EventKind is closed, but fail if it expands.
        raise ProjectionError(f"unsupported event kind: {event.kind!r}")

    return ProjectedEvent(
        event=event,
        lifecycle=lifecycle,
        annotations=frozenset(annotations),
    )


def _cause(
    event: Event,
    relationship: EventRelationship,
    effect: DerivedEffect,
) -> StateCause:
    return StateCause(
        effect=effect,
        relationship=relationship.kind,
        source_event_id=event.event_id,
        target_event_id=relationship.target_event_id,
    )


def _add_source_cause(
    states: dict[str, ProjectedEvent],
    event: Event,
    relationship: EventRelationship,
    effect: DerivedEffect,
) -> None:
    source = states[event.event_id]
    states[event.event_id] = replace(
        source,
        causes=source.causes + (_cause(event, relationship, effect),),
    )


def _require_authoritative_source(
    event: Event,
    relationship: EventRelationship,
) -> None:
    if not _is_authoritative_human_correction(event):
        raise ProjectionError(
            f"{relationship.kind.value} from {event.event_id} requires an "
            "authoritative human correction"
        )


def _apply_relationship(
    states: dict[str, ProjectedEvent],
    event: Event,
    relationship: EventRelationship,
) -> None:
    target = states.get(relationship.target_event_id)
    if target is None:
        raise ProjectionError(
            f"{event.event_id} cannot project {relationship.kind.value}: "
            f"earlier event {relationship.target_event_id} is unavailable"
        )

    if relationship.kind is RelationshipKind.SUPERSEDES:
        if target.lifecycle is not LifecycleState.CURRENT:
            raise ProjectionError(
                f"{event.event_id} cannot supersede {target.event_id}: "
                f"target is already {target.lifecycle.value}"
            )
        states[target.event_id] = replace(
            target,
            lifecycle=LifecycleState.SUPERSEDED,
            causes=target.causes
            + (_cause(event, relationship, DerivedEffect.SUPERSEDED),),
        )
        return

    if relationship.kind is RelationshipKind.INTERPRETS:
        source = states[event.event_id]
        if source.lifecycle is not LifecycleState.UNRESOLVED:
            raise ProjectionError(
                f"interpretation {event.event_id} is not unresolved"
            )
        _add_source_cause(
            states, event, relationship, DerivedEffect.INTERPRETS
        )
        return

    if relationship.kind is RelationshipKind.CITES:
        _add_source_cause(states, event, relationship, DerivedEffect.CITES)
        return

    if relationship.kind is RelationshipKind.CORRECTS:
        _require_authoritative_source(event, relationship)
        if StateAnnotation.RECORDED_WRONG_ANSWER not in target.annotations:
            raise ProjectionError(
                f"{event.event_id} cannot correct {target.event_id}: "
                "target is not a recorded wrong answer"
            )
        if StateAnnotation.CORRECTED_BY_HUMAN in target.annotations:
            raise ProjectionError(
                f"{target.event_id} is already corrected by an authoritative event"
            )
        states[target.event_id] = replace(
            target,
            annotations=target.annotations
            | frozenset({StateAnnotation.CORRECTED_BY_HUMAN}),
            causes=target.causes
            + (_cause(event, relationship, DerivedEffect.CORRECTED),),
        )
        return

    if relationship.kind is RelationshipKind.RESOLVES:
        _require_authoritative_source(event, relationship)
        if target.lifecycle is not LifecycleState.UNRESOLVED:
            raise ProjectionError(
                f"{event.event_id} cannot resolve {target.event_id}: "
                f"target is already {target.lifecycle.value}"
            )
        states[target.event_id] = replace(
            target,
            lifecycle=LifecycleState.RESOLVED,
            causes=target.causes
            + (_cause(event, relationship, DerivedEffect.RESOLVED),),
        )
        return

    if relationship.kind is RelationshipKind.CLARIFIES:
        _require_authoritative_source(event, relationship)
        if target.lifecycle is not LifecycleState.CURRENT:
            raise ProjectionError(
                f"{event.event_id} cannot clarify {target.event_id}: "
                f"target is {target.lifecycle.value}, not current"
            )
        if StateAnnotation.CLARIFIED_BY_HUMAN in target.annotations:
            raise ProjectionError(
                f"{target.event_id} already has an authoritative clarification"
            )
        states[target.event_id] = replace(
            target,
            annotations=target.annotations
            | frozenset({StateAnnotation.CLARIFIED_BY_HUMAN}),
            causes=target.causes
            + (_cause(event, relationship, DerivedEffect.CLARIFIED),),
        )
        return

    if relationship.kind is RelationshipKind.GENERATED_FROM:
        if StateAnnotation.AUTHORITATIVE_HUMAN_CORRECTION not in target.annotations:
            raise ProjectionError(
                f"regression {event.event_id} was not generated from an "
                "authoritative human correction"
            )
        _add_source_cause(
            states, event, relationship, DerivedEffect.GENERATED_FROM
        )
        return

    raise ProjectionError(
        f"unsupported relationship in projector: {relationship.kind!r}"
    )


def project_ledger(
    ledger: EventLedger,
    *,
    through_revision: int | None = None,
) -> StateProjection:
    """Replay ``ledger`` through an inclusive revision and derive event state."""

    if not isinstance(ledger, EventLedger):
        raise TypeError("ledger must be an EventLedger")

    if through_revision is None:
        selected_revision = ledger.last_revision
    else:
        if isinstance(through_revision, bool) or not isinstance(
            through_revision, int
        ):
            raise ProjectionError("through_revision must be an integer")
        if through_revision < 1 or through_revision > ledger.last_revision:
            raise ProjectionError(
                f"through_revision must be between 1 and {ledger.last_revision}"
            )
        selected_revision = through_revision

    states: dict[str, ProjectedEvent] = {}
    selected_events = ledger[:selected_revision]
    for event in selected_events:
        states[event.event_id] = _initial_state(event)
        for relationship in event.relationships:
            _apply_relationship(states, event, relationship)

    ordered_states = tuple(states[event.event_id] for event in selected_events)
    return StateProjection(
        through_revision=selected_revision,
        events=ordered_states,
    )
