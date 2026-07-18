"""Immutable domain models for versioned memory events."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
import json
import math
import re
from types import MappingProxyType
from typing import TypeAlias


JsonScalar: TypeAlias = str | int | float | bool | None
FrozenJson: TypeAlias = (
    JsonScalar | tuple["FrozenJson", ...] | Mapping[str, "FrozenJson"]
)

SCHEMA_VERSION = 1
_EVENT_ID_PATTERN = re.compile(r"^[A-Z]{3}-[0-9]{3}$")


class EventValidationError(ValueError):
    """Raised when serialized or constructed event data is invalid."""


class EventKind(StrEnum):
    """Kinds of evidence represented in the vertical-slice history."""

    DECISION = "decision"
    INTERPRETATION = "interpretation"
    ANSWER = "answer"
    CORRECTION = "correction"
    REGRESSION = "regression"


class RelationshipKind(StrEnum):
    """Directed relationships from a newer event to an earlier event."""

    SUPERSEDES = "supersedes"
    INTERPRETS = "interprets"
    CITES = "cites"
    CORRECTS = "corrects"
    RESOLVES = "resolves"
    CLARIFIES = "clarifies"
    GENERATED_FROM = "generated_from"


_EVENT_PREFIXES = {
    EventKind.DECISION: "DEC",
    EventKind.INTERPRETATION: "INT",
    EventKind.ANSWER: "ANS",
    EventKind.CORRECTION: "COR",
    EventKind.REGRESSION: "REG",
}


def _non_empty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EventValidationError(f"{field_name} must be a non-empty string")
    return value


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise EventValidationError(f"{field_name} must be an object")
    return value


def _check_keys(
    value: Mapping[str, object],
    *,
    field_name: str,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> None:
    keys = frozenset(value)
    missing = required - keys
    unknown = keys - required - optional
    if missing:
        raise EventValidationError(
            f"{field_name} is missing required fields: {', '.join(sorted(missing))}"
        )
    if unknown:
        raise EventValidationError(
            f"{field_name} has unknown fields: {', '.join(sorted(unknown))}"
        )


def _freeze_json(value: object, field_name: str = "claim") -> FrozenJson:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EventValidationError(f"{field_name} cannot contain NaN or infinity")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, FrozenJson] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise EventValidationError(
                    f"{field_name} object keys must be non-empty strings"
                )
            frozen[key] = _freeze_json(item, f"{field_name}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_json(item, f"{field_name}[{index}]")
            for index, item in enumerate(value)
        )
    raise EventValidationError(
        f"{field_name} contains unsupported value type {type(value).__name__}"
    )


def _thaw_json(value: FrozenJson) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class Provenance:
    """Synthetic origin information attached to every memory event."""

    source_id: str
    source_type: str
    synthetic: bool
    actor: str | None = None

    def __post_init__(self) -> None:
        _non_empty_string(self.source_id, "source.source_id")
        _non_empty_string(self.source_type, "source.source_type")
        if self.synthetic is not True:
            raise EventValidationError(
                "source.synthetic must be true for the public Build Week fixture"
            )
        if self.actor is not None:
            _non_empty_string(self.actor, "source.actor")

    @classmethod
    def from_dict(cls, value: object) -> Provenance:
        source = _mapping(value, "source")
        _check_keys(
            source,
            field_name="source",
            required=frozenset({"source_id", "source_type", "synthetic"}),
            optional=frozenset({"actor"}),
        )
        synthetic = source["synthetic"]
        if not isinstance(synthetic, bool):
            raise EventValidationError("source.synthetic must be a boolean")
        actor = source.get("actor")
        if actor is not None and not isinstance(actor, str):
            raise EventValidationError("source.actor must be a string or null")
        return cls(
            source_id=_non_empty_string(source["source_id"], "source.source_id"),
            source_type=_non_empty_string(
                source["source_type"], "source.source_type"
            ),
            synthetic=synthetic,
            actor=actor,
        )

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "synthetic": self.synthetic,
        }
        if self.actor is not None:
            result["actor"] = self.actor
        return result


@dataclass(frozen=True, slots=True)
class EventRelationship:
    """A typed edge from one event to an earlier ledger event."""

    kind: RelationshipKind
    target_event_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, RelationshipKind):
            raise EventValidationError("relationship.kind must be a RelationshipKind")
        _non_empty_string(
            self.target_event_id, "relationship.target_event_id"
        )
        if not _EVENT_ID_PATTERN.fullmatch(self.target_event_id):
            raise EventValidationError(
                "relationship.target_event_id must match AAA-000"
            )

    @classmethod
    def from_dict(cls, value: object) -> EventRelationship:
        relationship = _mapping(value, "relationship")
        _check_keys(
            relationship,
            field_name="relationship",
            required=frozenset({"kind", "target_event_id"}),
        )
        raw_kind = _non_empty_string(relationship["kind"], "relationship.kind")
        try:
            kind = RelationshipKind(raw_kind)
        except ValueError as error:
            raise EventValidationError(
                f"unknown relationship kind: {raw_kind}"
            ) from error
        return cls(
            kind=kind,
            target_event_id=_non_empty_string(
                relationship["target_event_id"],
                "relationship.target_event_id",
            ),
        )

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind.value, "target_event_id": self.target_event_id}


@dataclass(frozen=True, slots=True)
class Event:
    """One deeply immutable record in the versioned memory ledger."""

    event_id: str
    revision: int
    kind: EventKind
    occurred_on: date
    source: Provenance
    claim: Mapping[str, FrozenJson]
    relationships: tuple[EventRelationship, ...] = ()

    def __post_init__(self) -> None:
        _non_empty_string(self.event_id, "event_id")
        if not _EVENT_ID_PATTERN.fullmatch(self.event_id):
            raise EventValidationError("event_id must match AAA-000")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int):
            raise EventValidationError("revision must be an integer")
        if self.revision < 1:
            raise EventValidationError("revision must be positive")
        if not isinstance(self.kind, EventKind):
            raise EventValidationError("kind must be an EventKind")
        expected_prefix = _EVENT_PREFIXES[self.kind]
        if not self.event_id.startswith(f"{expected_prefix}-"):
            raise EventValidationError(
                f"{self.kind.value} event IDs must use the {expected_prefix} prefix"
            )
        if isinstance(self.occurred_on, datetime) or not isinstance(
            self.occurred_on, date
        ):
            raise EventValidationError("occurred_on must be a date")
        if not isinstance(self.source, Provenance):
            raise EventValidationError("source must be Provenance")
        if not isinstance(self.claim, Mapping) or not self.claim:
            raise EventValidationError("claim must be a non-empty object")
        frozen_claim = _freeze_json(self.claim)
        if not isinstance(frozen_claim, Mapping):
            raise EventValidationError("claim must be an object")
        object.__setattr__(self, "claim", frozen_claim)

        relationships = tuple(self.relationships)
        if not all(
            isinstance(relationship, EventRelationship)
            for relationship in relationships
        ):
            raise EventValidationError(
                "relationships must contain EventRelationship values"
            )
        object.__setattr__(self, "relationships", relationships)

    @classmethod
    def from_dict(cls, value: object) -> Event:
        event = _mapping(value, "event")
        _check_keys(
            event,
            field_name="event",
            required=frozenset(
                {
                    "schema_version",
                    "event_id",
                    "revision",
                    "kind",
                    "occurred_on",
                    "source",
                    "claim",
                    "relationships",
                }
            ),
        )
        schema_version = event["schema_version"]
        if schema_version != SCHEMA_VERSION or isinstance(schema_version, bool):
            raise EventValidationError(
                f"schema_version must be {SCHEMA_VERSION}"
            )
        revision = event["revision"]
        if isinstance(revision, bool) or not isinstance(revision, int):
            raise EventValidationError("revision must be an integer")

        raw_kind = _non_empty_string(event["kind"], "kind")
        try:
            kind = EventKind(raw_kind)
        except ValueError as error:
            raise EventValidationError(f"unknown event kind: {raw_kind}") from error

        raw_date = _non_empty_string(event["occurred_on"], "occurred_on")
        try:
            occurred_on = date.fromisoformat(raw_date)
        except ValueError as error:
            raise EventValidationError(
                "occurred_on must be an ISO 8601 calendar date"
            ) from error

        raw_relationships = event["relationships"]
        if not isinstance(raw_relationships, list):
            raise EventValidationError("relationships must be an array")

        claim = _mapping(event["claim"], "claim")
        return cls(
            event_id=_non_empty_string(event["event_id"], "event_id"),
            revision=revision,
            kind=kind,
            occurred_on=occurred_on,
            source=Provenance.from_dict(event["source"]),
            claim=claim,
            relationships=tuple(
                EventRelationship.from_dict(item) for item in raw_relationships
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "event_id": self.event_id,
            "revision": self.revision,
            "kind": self.kind.value,
            "occurred_on": self.occurred_on.isoformat(),
            "source": self.source.to_dict(),
            "claim": _thaw_json(self.claim),
            "relationships": [
                relationship.to_dict() for relationship in self.relationships
            ],
        }

    def to_json_line(self) -> str:
        """Serialize deterministically for the append-only JSON Lines store."""

        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

