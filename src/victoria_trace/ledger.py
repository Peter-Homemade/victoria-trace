# Copyright (C) 2026 Peter Van Geldorp
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Immutable event ledger and append-only JSON Lines persistence."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import overload

from .models import (
    Event,
    EventKind,
    EventValidationError,
    RelationshipKind,
)


class LedgerValidationError(ValueError):
    """Raised when events do not form a valid ordered ledger."""


class LedgerFormatError(LedgerValidationError):
    """Raised when a JSON Lines ledger cannot be decoded safely."""


_ALLOWED_TARGETS: dict[
    EventKind, dict[RelationshipKind, frozenset[EventKind]]
] = {
    EventKind.DECISION: {
        RelationshipKind.SUPERSEDES: frozenset({EventKind.DECISION}),
    },
    EventKind.INTERPRETATION: {
        RelationshipKind.INTERPRETS: frozenset({EventKind.DECISION}),
    },
    EventKind.ANSWER: {
        RelationshipKind.CITES: frozenset(
            {EventKind.DECISION, EventKind.INTERPRETATION}
        ),
    },
    EventKind.CORRECTION: {
        RelationshipKind.CORRECTS: frozenset({EventKind.ANSWER}),
        RelationshipKind.RESOLVES: frozenset({EventKind.INTERPRETATION}),
        RelationshipKind.CLARIFIES: frozenset({EventKind.DECISION}),
    },
    EventKind.REGRESSION: {
        RelationshipKind.GENERATED_FROM: frozenset({EventKind.CORRECTION}),
    },
}

_REQUIRED_RELATIONSHIPS: dict[EventKind, frozenset[RelationshipKind]] = {
    EventKind.INTERPRETATION: frozenset({RelationshipKind.INTERPRETS}),
    EventKind.ANSWER: frozenset({RelationshipKind.CITES}),
    EventKind.CORRECTION: frozenset(
        {RelationshipKind.CORRECTS, RelationshipKind.RESOLVES}
    ),
    EventKind.REGRESSION: frozenset({RelationshipKind.GENERATED_FROM}),
}


def _validate_events(events: tuple[Event, ...]) -> None:
    known: dict[str, Event] = {}
    for expected_revision, event in enumerate(events, start=1):
        if not isinstance(event, Event):
            raise LedgerValidationError("ledger entries must be Event values")
        if event.revision != expected_revision:
            raise LedgerValidationError(
                f"event {event.event_id} has revision {event.revision}; "
                f"expected {expected_revision}"
            )
        if event.event_id in known:
            raise LedgerValidationError(f"duplicate event ID: {event.event_id}")

        seen_relationships: set[tuple[RelationshipKind, str]] = set()
        observed_kinds: set[RelationshipKind] = set()
        allowed_for_event = _ALLOWED_TARGETS[event.kind]
        for relationship in event.relationships:
            edge = (relationship.kind, relationship.target_event_id)
            if edge in seen_relationships:
                raise LedgerValidationError(
                    f"event {event.event_id} repeats relationship "
                    f"{relationship.kind.value} -> {relationship.target_event_id}"
                )
            seen_relationships.add(edge)
            observed_kinds.add(relationship.kind)

            if relationship.target_event_id == event.event_id:
                raise LedgerValidationError(
                    f"event {event.event_id} cannot relate to itself"
                )
            target = known.get(relationship.target_event_id)
            if target is None:
                raise LedgerValidationError(
                    f"event {event.event_id} references missing or future event "
                    f"{relationship.target_event_id}"
                )
            allowed_target_kinds = allowed_for_event.get(relationship.kind)
            if allowed_target_kinds is None:
                raise LedgerValidationError(
                    f"{event.kind.value} event {event.event_id} cannot use "
                    f"relationship {relationship.kind.value}"
                )
            if target.kind not in allowed_target_kinds:
                allowed_names = ", ".join(
                    sorted(kind.value for kind in allowed_target_kinds)
                )
                raise LedgerValidationError(
                    f"{relationship.kind.value} from {event.event_id} cannot "
                    f"target {target.kind.value} event {target.event_id}; "
                    f"expected {allowed_names}"
                )

        missing_relationships = _REQUIRED_RELATIONSHIPS.get(
            event.kind, frozenset()
        ) - observed_kinds
        if missing_relationships:
            missing_names = ", ".join(
                sorted(kind.value for kind in missing_relationships)
            )
            raise LedgerValidationError(
                f"event {event.event_id} is missing required relationships: "
                f"{missing_names}"
            )
        known[event.event_id] = event


@dataclass(frozen=True, slots=True)
class EventLedger(Sequence[Event]):
    """An immutable, ordered collection of validated memory events.

    ``append`` and ``extend`` return new values. Existing ledger instances and
    their events are never mutated.
    """

    _events: tuple[Event, ...] = field(default_factory=tuple, repr=False)

    def __post_init__(self) -> None:
        events = tuple(self._events)
        _validate_events(events)
        object.__setattr__(self, "_events", events)

    @classmethod
    def from_events(cls, events: Iterable[Event]) -> EventLedger:
        return cls(tuple(events))

    @classmethod
    def load_jsonl(cls, path: str | os.PathLike[str]) -> EventLedger:
        ledger_path = Path(path)
        events: list[Event] = []
        try:
            with ledger_path.open("r", encoding="utf-8", newline="") as stream:
                for line_number, line in enumerate(stream, start=1):
                    if not line.strip():
                        raise LedgerFormatError(
                            f"{ledger_path}:{line_number}: blank lines are not allowed"
                        )
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError as error:
                        raise LedgerFormatError(
                            f"{ledger_path}:{line_number}: invalid JSON: {error.msg}"
                        ) from error
                    try:
                        events.append(Event.from_dict(value))
                    except EventValidationError as error:
                        raise LedgerFormatError(
                            f"{ledger_path}:{line_number}: {error}"
                        ) from error
        except UnicodeDecodeError as error:
            raise LedgerFormatError(f"{ledger_path}: ledger is not valid UTF-8") from error

        try:
            return cls.from_events(events)
        except LedgerValidationError as error:
            raise LedgerValidationError(f"{ledger_path}: {error}") from error

    @classmethod
    def append_to_jsonl(
        cls,
        path: str | os.PathLike[str],
        event: Event,
    ) -> EventLedger:
        """Validate and append one event without rewriting prior bytes.

        The path may be absent for revision 1. Existing files must be valid UTF-8
        JSON Lines and end in a newline before an append is attempted.
        """

        ledger_path = Path(path)
        if ledger_path.exists():
            if not ledger_path.is_file():
                raise LedgerFormatError(f"{ledger_path} is not a file")
            existing_bytes = ledger_path.read_bytes()
            if existing_bytes and not existing_bytes.endswith(b"\n"):
                raise LedgerFormatError(
                    f"{ledger_path}: final record is not newline-terminated"
                )
            current = cls.load_jsonl(ledger_path)
        else:
            current = cls()

        updated = current.append(event)
        encoded_event = (event.to_json_line() + "\n").encode("utf-8")
        with ledger_path.open("ab") as stream:
            stream.write(encoded_event)
            stream.flush()
            os.fsync(stream.fileno())
        return updated

    @property
    def events(self) -> tuple[Event, ...]:
        return self._events

    @property
    def last_revision(self) -> int:
        return len(self._events)

    def append(self, event: Event) -> EventLedger:
        return type(self)(self._events + (event,))

    def extend(self, events: Iterable[Event]) -> EventLedger:
        return type(self)(self._events + tuple(events))

    def get(self, event_id: str) -> Event:
        for event in self._events:
            if event.event_id == event_id:
                return event
        raise KeyError(event_id)

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self) -> Iterator[Event]:
        return iter(self._events)

    @overload
    def __getitem__(self, index: int) -> Event: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[Event, ...]: ...

    def __getitem__(self, index: int | slice) -> Event | tuple[Event, ...]:
        return self._events[index]

