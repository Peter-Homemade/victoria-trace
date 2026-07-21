# Copyright (C) 2026 Peter Van Geldorp
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from victoria_trace.ledger import EventLedger  # noqa: E402
from victoria_trace.models import (  # noqa: E402
    Event,
    EventKind,
    EventRelationship,
    Provenance,
    RelationshipKind,
)
from victoria_trace.projector import (  # noqa: E402
    DerivedEffect,
    LifecycleState,
    ProjectionError,
    StateAnnotation,
    project_ledger,
)


FIXTURE = ROOT / "data" / "halcyon_history.jsonl"


class StateProjectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = EventLedger.load_jsonl(FIXTURE)

    def test_projection_at_revision_one(self) -> None:
        projection = project_ledger(self.ledger, through_revision=1)

        self.assertEqual(projection.through_revision, 1)
        self.assertEqual([event.event_id for event in projection], ["DEC-001"])
        self.assertEqual(
            projection.get("DEC-001").lifecycle,
            LifecycleState.CURRENT,
        )
        self.assertEqual(projection.get("DEC-001").causes, ())

    def test_projection_through_revision_four_preserves_uncertainty(self) -> None:
        projection = project_ledger(self.ledger, through_revision=4)
        interpretation = projection.get("INT-001")
        answer = projection.get("ANS-001")

        self.assertEqual(projection.through_revision, 4)
        self.assertEqual(interpretation.lifecycle, LifecycleState.UNRESOLVED)
        self.assertEqual(
            interpretation.event.claim["candidates"],
            ("release.json", "public/release.json"),
        )
        self.assertEqual(interpretation.annotations, frozenset())
        self.assertEqual(answer.lifecycle, LifecycleState.HISTORICAL)
        self.assertIn(
            StateAnnotation.RECORDED_WRONG_ANSWER,
            answer.annotations,
        )
        self.assertNotIn(StateAnnotation.CORRECTED_BY_HUMAN, answer.annotations)
        self.assertNotIn("COR-001", projection.by_event_id)

    def test_complete_projection_has_required_halcyon_states(self) -> None:
        projection = project_ledger(self.ledger)

        self.assertEqual(projection.through_revision, 6)
        self.assertEqual(
            projection.get("DEC-001").lifecycle,
            LifecycleState.SUPERSEDED,
        )
        self.assertEqual(
            projection.get("DEC-002").lifecycle,
            LifecycleState.CURRENT,
        )
        self.assertEqual(
            projection.get("INT-001").lifecycle,
            LifecycleState.RESOLVED,
        )
        self.assertEqual(
            projection.get("ANS-001").lifecycle,
            LifecycleState.HISTORICAL,
        )
        self.assertEqual(
            projection.get("COR-001").lifecycle,
            LifecycleState.CURRENT,
        )
        self.assertEqual(
            projection.get("REG-001").lifecycle,
            LifecycleState.HISTORICAL,
        )

    def test_supersession_has_explicit_causal_edge(self) -> None:
        decision = project_ledger(self.ledger, through_revision=2).get("DEC-001")

        self.assertEqual(decision.lifecycle, LifecycleState.SUPERSEDED)
        self.assertEqual(len(decision.causes), 1)
        cause = decision.causes[0]
        self.assertEqual(cause.effect, DerivedEffect.SUPERSEDED)
        self.assertEqual(cause.relationship, RelationshipKind.SUPERSEDES)
        self.assertEqual(cause.source_event_id, "DEC-002")
        self.assertEqual(cause.target_event_id, "DEC-001")
        self.assertEqual(decision.evidence_event_ids, ("DEC-001", "DEC-002"))

    def test_interpretation_transitions_from_unresolved_to_resolved(self) -> None:
        before = project_ledger(self.ledger, through_revision=4).get("INT-001")
        after = project_ledger(self.ledger, through_revision=6).get("INT-001")

        self.assertEqual(before.lifecycle, LifecycleState.UNRESOLVED)
        self.assertEqual(after.lifecycle, LifecycleState.RESOLVED)
        self.assertEqual(
            [cause.effect for cause in after.causes],
            [DerivedEffect.INTERPRETS, DerivedEffect.RESOLVED],
        )
        resolution = after.causes[-1]
        self.assertEqual(resolution.relationship, RelationshipKind.RESOLVES)
        self.assertEqual(resolution.source_event_id, "COR-001")
        self.assertEqual(resolution.target_event_id, "INT-001")
        self.assertEqual(
            after.evidence_event_ids,
            ("INT-001", "DEC-002", "COR-001"),
        )

    def test_wrong_answer_is_preserved_and_annotated_as_corrected(self) -> None:
        before = project_ledger(self.ledger, through_revision=4).get("ANS-001")
        after = project_ledger(self.ledger).get("ANS-001")

        self.assertEqual(before.event, after.event)
        self.assertEqual(after.lifecycle, LifecycleState.HISTORICAL)
        self.assertEqual(
            after.annotations,
            frozenset(
                {
                    StateAnnotation.RECORDED_WRONG_ANSWER,
                    StateAnnotation.CORRECTED_BY_HUMAN,
                }
            ),
        )
        correction = after.causes[-1]
        self.assertEqual(correction.effect, DerivedEffect.CORRECTED)
        self.assertEqual(correction.relationship, RelationshipKind.CORRECTS)
        self.assertEqual(correction.source_event_id, "COR-001")

    def test_human_correction_is_visible_and_authoritative(self) -> None:
        correction = project_ledger(self.ledger).get("COR-001")

        self.assertEqual(correction.lifecycle, LifecycleState.CURRENT)
        self.assertEqual(
            correction.annotations,
            frozenset(
                {
                    StateAnnotation.AUTHORITATIVE_HUMAN_CORRECTION,
                    StateAnnotation.CORRECTED_ANSWER,
                }
            ),
        )
        self.assertEqual(
            correction.evidence_event_ids,
            ("COR-001", "ANS-001", "INT-001", "DEC-002"),
        )

    def test_current_decision_retains_authoritative_clarification_cause(self) -> None:
        decision = project_ledger(self.ledger).get("DEC-002")

        self.assertEqual(decision.lifecycle, LifecycleState.CURRENT)
        self.assertIn(StateAnnotation.CLARIFIED_BY_HUMAN, decision.annotations)
        clarification = decision.causes[-1]
        self.assertEqual(clarification.effect, DerivedEffect.CLARIFIED)
        self.assertEqual(clarification.relationship, RelationshipKind.CLARIFIES)
        self.assertEqual(clarification.source_event_id, "COR-001")
        self.assertEqual(clarification.target_event_id, "DEC-002")

    def test_regression_is_visible_but_only_annotated_as_a_record(self) -> None:
        regression = project_ledger(self.ledger).get("REG-001")

        self.assertEqual(regression.lifecycle, LifecycleState.HISTORICAL)
        self.assertEqual(
            regression.annotations,
            frozenset({StateAnnotation.REGRESSION_RECORD}),
        )
        self.assertEqual(len(regression.causes), 1)
        self.assertEqual(regression.causes[0].effect, DerivedEffect.GENERATED_FROM)
        self.assertEqual(regression.evidence_event_ids, ("REG-001", "COR-001"))

    def test_complete_projection_preserves_every_event_in_revision_order(self) -> None:
        projection = project_ledger(self.ledger)

        self.assertEqual(
            [event.event_id for event in projection.events],
            ["DEC-001", "DEC-002", "INT-001", "ANS-001", "COR-001", "REG-001"],
        )
        self.assertEqual(
            [event.event for event in projection.events],
            list(self.ledger.events),
        )

    def test_repeated_projection_is_deterministic(self) -> None:
        first = project_ledger(self.ledger)
        second = project_ledger(self.ledger)

        self.assertEqual(first, second)
        self.assertEqual(first.events, second.events)
        self.assertEqual(
            tuple(first.by_event_id),
            tuple(second.by_event_id),
        )

    def test_projection_and_nested_values_are_immutable(self) -> None:
        projection = project_ledger(self.ledger)
        interpretation = projection.get("INT-001")

        with self.assertRaises(TypeError):
            projection.by_event_id["INT-001"] = interpretation  # type: ignore[index]
        with self.assertRaises(FrozenInstanceError):
            interpretation.lifecycle = LifecycleState.UNRESOLVED  # type: ignore[misc]
        with self.assertRaises(AttributeError):
            interpretation.annotations.add(StateAnnotation.CORRECTED_ANSWER)  # type: ignore[attr-defined]
        with self.assertRaises(FrozenInstanceError):
            interpretation.causes[-1].source_event_id = "COR-999"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            interpretation.event.claim["status"] = "unresolved"  # type: ignore[index]

    def test_invalid_prefix_revisions_are_rejected(self) -> None:
        for invalid_revision in (0, -1, 7, True, 1.5, "4"):
            with self.subTest(through_revision=invalid_revision):
                with self.assertRaisesRegex(ProjectionError, "through_revision"):
                    project_ledger(
                        self.ledger,
                        through_revision=invalid_revision,  # type: ignore[arg-type]
                    )

    def test_second_authoritative_resolution_is_rejected_as_conflicting(self) -> None:
        second_wrong_answer = Event(
            event_id="ANS-002",
            revision=6,
            kind=EventKind.ANSWER,
            occurred_on=date(2026, 4, 6),
            source=Provenance(
                "second-recorded-answer",
                "agent",
                True,
                actor="Halcyon build agent",
            ),
            claim={
                "outcome": "incorrect",
                "location": "another/release.json",
                "format": "release-manifest/v2",
            },
            relationships=(
                EventRelationship(RelationshipKind.CITES, "DEC-002"),
            ),
        )
        second_correction = Event(
            event_id="COR-002",
            revision=7,
            kind=EventKind.CORRECTION,
            occurred_on=date(2026, 4, 6),
            source=Provenance(
                "second-owner-correction",
                "human",
                True,
                actor="Ravi Singh",
            ),
            claim={
                "authority": "human_owner",
                "location": "another/release.json",
                "format": "release-manifest/v2",
            },
            relationships=(
                EventRelationship(RelationshipKind.CORRECTS, "ANS-002"),
                EventRelationship(RelationshipKind.RESOLVES, "INT-001"),
            ),
        )
        conflicting_ledger = EventLedger.from_events(
            self.ledger[:5] + (second_wrong_answer, second_correction)
        )

        with self.assertRaisesRegex(
            ProjectionError, "target is already resolved"
        ):
            project_ledger(conflicting_ledger)

    def test_repeated_terminal_supersession_is_rejected(self) -> None:
        repeated_supersession = Event(
            event_id="DEC-003",
            revision=3,
            kind=EventKind.DECISION,
            occurred_on=date(2026, 3, 13),
            source=Provenance("repeat-decision", "document", True),
            claim={"subject": "halcyon.release_metadata", "status": "accepted"},
            relationships=(
                EventRelationship(RelationshipKind.SUPERSEDES, "DEC-001"),
            ),
        )
        conflicting_ledger = EventLedger.from_events(
            self.ledger[:2] + (repeated_supersession,)
        )

        with self.assertRaisesRegex(ProjectionError, "already superseded"):
            project_ledger(conflicting_ledger)

    def test_non_authoritative_correction_is_rejected(self) -> None:
        non_authoritative = replace(
            self.ledger[4],
            source=Provenance(
                "automated-correction",
                "agent",
                True,
                actor="Synthetic agent",
            ),
        )
        malformed_ledger = EventLedger.from_events(
            self.ledger[:4] + (non_authoritative,)
        )

        with self.assertRaisesRegex(
            ProjectionError, "not an explicit authoritative human correction"
        ):
            project_ledger(malformed_ledger)

    def test_timestamps_do_not_override_revision_relationships(self) -> None:
        later_dated_original = replace(
            self.ledger[0],
            occurred_on=date(2026, 12, 31),
        )
        earlier_dated_supersession = replace(
            self.ledger[1],
            occurred_on=date(2026, 1, 1),
        )
        reverse_dated_ledger = EventLedger.from_events(
            (later_dated_original, earlier_dated_supersession)
        )

        projection = project_ledger(reverse_dated_ledger)

        self.assertEqual(
            projection.get("DEC-001").lifecycle,
            LifecycleState.SUPERSEDED,
        )
        self.assertEqual(
            projection.get("DEC-002").lifecycle,
            LifecycleState.CURRENT,
        )


if __name__ == "__main__":
    unittest.main()
