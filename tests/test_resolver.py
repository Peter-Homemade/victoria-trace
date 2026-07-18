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
    Provenance,
)
from victoria_trace.projector import (  # noqa: E402
    LifecycleState,
    ProjectedEvent,
    StateAnnotation,
    StateProjection,
    project_ledger,
)
from victoria_trace.resolver import (  # noqa: E402
    AnswerStatus,
    CANONICAL_QUESTION,
    EvidenceRole,
    ResolutionError,
    ResolutionReason,
    UncertaintyKind,
    resolve_question,
)


FIXTURE = ROOT / "data" / "halcyon_history.jsonl"


class QuestionResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = EventLedger.load_jsonl(FIXTURE)

    def resolve_at(self, revision: int, question: str = CANONICAL_QUESTION):
        return resolve_question(
            project_ledger(self.ledger, through_revision=revision),
            question,
        )

    def test_exact_canonical_question_is_supported_after_correction(self) -> None:
        result = self.resolve_at(5)

        self.assertEqual(result.question, CANONICAL_QUESTION)
        self.assertEqual(result.status, AnswerStatus.SUPPORTED)

    def test_surrounding_whitespace_is_the_only_supported_normalization(self) -> None:
        question = f"  \n{CANONICAL_QUESTION}\t "

        result = self.resolve_at(5, question)

        self.assertEqual(result.question, question)
        self.assertEqual(result.status, AnswerStatus.SUPPORTED)

    def test_materially_different_questions_are_unsupported(self) -> None:
        questions = (
            CANONICAL_QUESTION.lower(),
            CANONICAL_QUESTION.removesuffix("?"),
            "Where should Halcyon publish its release notes?",
        )

        for question in questions:
            with self.subTest(question=question):
                result = self.resolve_at(6, question)
                self.assertEqual(result.status, AnswerStatus.UNSUPPORTED)
                self.assertEqual(result.reason, ResolutionReason.UNSUPPORTED_QUESTION)
                self.assertEqual(result.question, question)
                self.assertEqual(result.evidence, ())

    def test_revision_three_is_uncertain_without_choosing_a_location(self) -> None:
        result = self.resolve_at(3)

        self.assertEqual(result.projection_revision, 3)
        self.assertEqual(result.status, AnswerStatus.UNCERTAIN)
        self.assertIsNone(result.location)
        self.assertEqual(result.format, "release-manifest/v2")
        self.assertEqual(result.reason, ResolutionReason.LOCATION_UNRESOLVED)
        self.assertEqual(
            result.evidence_event_ids,
            ("DEC-001", "DEC-002", "INT-001"),
        )

    def test_revision_four_stays_uncertain_despite_recorded_answer(self) -> None:
        result = self.resolve_at(4)

        self.assertEqual(result.status, AnswerStatus.UNCERTAIN)
        self.assertIsNone(result.location)
        self.assertEqual(result.format, "release-manifest/v2")
        self.assertEqual(
            result.evidence_event_ids,
            ("DEC-001", "DEC-002", "INT-001", "ANS-001"),
        )
        self.assertEqual(
            result.evidence[-1].role,
            EvidenceRole.HISTORICAL_WRONG_ANSWER,
        )

    def test_revision_five_returns_supported_corrected_answer(self) -> None:
        result = self.resolve_at(5)

        self.assertEqual(result.status, AnswerStatus.SUPPORTED)
        self.assertEqual(result.location, "public/release.json")
        self.assertEqual(result.format, "release-manifest/v2")
        self.assertEqual(result.uncertainties, ())
        self.assertEqual(
            result.reason,
            ResolutionReason.AUTHORITATIVE_CORRECTION,
        )

    def test_revision_six_returns_same_answer_without_using_regression(self) -> None:
        revision_five = self.resolve_at(5)
        revision_six = self.resolve_at(6)

        self.assertEqual(revision_six.status, revision_five.status)
        self.assertEqual(revision_six.location, revision_five.location)
        self.assertEqual(revision_six.format, revision_five.format)
        self.assertEqual(revision_six.uncertainties, revision_five.uncertainties)
        self.assertEqual(revision_six.evidence, revision_five.evidence)
        self.assertEqual(revision_six.reason, revision_five.reason)
        self.assertNotIn("REG-001", revision_six.evidence_event_ids)

    def test_supported_evidence_chain_has_explicit_order_and_roles(self) -> None:
        result = self.resolve_at(6)

        self.assertEqual(
            result.evidence_event_ids,
            ("DEC-001", "DEC-002", "INT-001", "COR-001"),
        )
        self.assertEqual(
            tuple(reference.role for reference in result.evidence),
            (
                EvidenceRole.HISTORICAL_DECISION,
                EvidenceRole.CURRENT_DECISION,
                EvidenceRole.RESOLVED_INTERPRETATION,
                EvidenceRole.AUTHORITATIVE_CORRECTION,
            ),
        )

    def test_original_decision_never_becomes_current_authority_again(self) -> None:
        projection = project_ledger(self.ledger, through_revision=6)
        result = resolve_question(projection, CANONICAL_QUESTION)

        self.assertEqual(
            projection.get("DEC-001").lifecycle,
            LifecycleState.SUPERSEDED,
        )
        self.assertEqual(
            result.evidence[0].role,
            EvidenceRole.HISTORICAL_DECISION,
        )
        self.assertEqual(
            result.evidence[1].role,
            EvidenceRole.CURRENT_DECISION,
        )

    def test_recorded_wrong_answer_is_never_current_authority(self) -> None:
        uncertain = self.resolve_at(4)
        supported = self.resolve_at(5)

        self.assertIsNone(uncertain.location)
        self.assertEqual(
            uncertain.evidence[-1].role,
            EvidenceRole.HISTORICAL_WRONG_ANSWER,
        )
        self.assertNotIn("ANS-001", supported.evidence_event_ids)
        self.assertEqual(supported.location, "public/release.json")

    def test_uncertainty_is_structured_with_candidates_and_evidence(self) -> None:
        result = self.resolve_at(3)

        self.assertEqual(len(result.uncertainties), 1)
        uncertainty = result.uncertainties[0]
        self.assertEqual(
            uncertainty.kind,
            UncertaintyKind.UNRESOLVED_INTERPRETATION,
        )
        self.assertEqual(uncertainty.field, "location")
        self.assertEqual(
            uncertainty.candidates,
            ("release.json", "public/release.json"),
        )
        self.assertEqual(
            uncertainty.evidence_event_ids,
            ("DEC-002", "INT-001"),
        )

    def test_repeated_resolution_is_deterministic(self) -> None:
        projection = project_ledger(self.ledger, through_revision=6)

        first = resolve_question(projection, CANONICAL_QUESTION)
        second = resolve_question(projection, CANONICAL_QUESTION)

        self.assertEqual(first, second)
        self.assertEqual(first.evidence_event_ids, second.evidence_event_ids)

    def test_result_and_nested_values_are_immutable(self) -> None:
        uncertain = self.resolve_at(3)
        supported = self.resolve_at(5)

        with self.assertRaises(FrozenInstanceError):
            supported.location = "release.json"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            uncertain.uncertainties[0] = uncertain.uncertainties[0]  # type: ignore[index]
        with self.assertRaises(FrozenInstanceError):
            uncertain.uncertainties[0].field = "format"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            supported.evidence[0].role = EvidenceRole.CURRENT_DECISION  # type: ignore[misc]

    def test_projection_missing_minimum_decision_evidence_is_unsupported(self) -> None:
        result = self.resolve_at(1)

        self.assertEqual(result.status, AnswerStatus.UNSUPPORTED)
        self.assertEqual(
            result.reason,
            ResolutionReason.INSUFFICIENT_DECISION_EVIDENCE,
        )
        self.assertIsNone(result.location)
        self.assertIsNone(result.format)

    def test_projection_missing_interpretation_evidence_is_unsupported(self) -> None:
        result = self.resolve_at(2)

        self.assertEqual(result.status, AnswerStatus.UNSUPPORTED)
        self.assertEqual(
            result.reason,
            ResolutionReason.MISSING_INTERPRETATION_EVIDENCE,
        )

    def test_conflicting_current_authoritative_corrections_are_rejected(self) -> None:
        projection = project_ledger(self.ledger, through_revision=6)
        conflicting_event = Event(
            event_id="COR-002",
            revision=7,
            kind=EventKind.CORRECTION,
            occurred_on=date(2026, 4, 6),
            source=Provenance(
                "conflicting-owner-correction",
                "human",
                True,
                actor="Ravi Singh",
            ),
            claim={
                "authority": "human_owner",
                "location": "another/release.json",
                "format": "release-manifest/v2",
            },
        )
        conflicting_correction = ProjectedEvent(
            event=conflicting_event,
            lifecycle=LifecycleState.CURRENT,
            annotations=frozenset(
                {
                    StateAnnotation.AUTHORITATIVE_HUMAN_CORRECTION,
                    StateAnnotation.CORRECTED_ANSWER,
                }
            ),
        )
        conflicting_projection = StateProjection(
            through_revision=7,
            events=projection.events + (conflicting_correction,),
        )

        with self.assertRaisesRegex(
            ResolutionError,
            "multiple current authoritative corrections",
        ):
            resolve_question(conflicting_projection, CANONICAL_QUESTION)

    def test_resolved_state_without_authoritative_correction_is_rejected(self) -> None:
        projection = project_ledger(self.ledger, through_revision=5)
        correction = projection.get("COR-001")
        unauthoritative = replace(correction, annotations=frozenset())
        malformed_projection = StateProjection(
            through_revision=5,
            events=projection.events[:4] + (unauthoritative,),
        )

        with self.assertRaisesRegex(
            ResolutionError,
            "no current authoritative correction",
        ):
            resolve_question(malformed_projection, CANONICAL_QUESTION)

    def test_inconsistent_projected_decision_state_is_rejected(self) -> None:
        projection = project_ledger(self.ledger, through_revision=3)
        original = replace(
            projection.get("DEC-001"),
            lifecycle=LifecycleState.CURRENT,
        )
        malformed_projection = StateProjection(
            through_revision=3,
            events=(original,) + projection.events[1:],
        )

        with self.assertRaisesRegex(
            ResolutionError,
            "DEC-001 is not projected as superseded",
        ):
            resolve_question(malformed_projection, CANONICAL_QUESTION)

    def test_current_decision_must_establish_static_file_delivery(self) -> None:
        projection = project_ledger(self.ledger, through_revision=3)
        decision = projection.get("DEC-002")
        changed_claim = dict(decision.event.claim)
        changed_claim["delivery"] = "dynamic_endpoint"
        changed_decision = replace(
            decision,
            event=replace(decision.event, claim=changed_claim),
        )
        malformed_projection = StateProjection(
            through_revision=3,
            events=(projection.events[0], changed_decision, projection.events[2]),
        )

        with self.assertRaisesRegex(
            ResolutionError,
            "does not establish static file delivery",
        ):
            resolve_question(malformed_projection, CANONICAL_QUESTION)

    def test_timestamps_have_no_effect_on_resolution_authority(self) -> None:
        events = list(self.ledger.events)
        events[0] = replace(events[0], occurred_on=date(2099, 12, 31))
        events[4] = replace(events[4], occurred_on=date(1900, 1, 1))
        reverse_dated_ledger = EventLedger.from_events(events)

        result = resolve_question(
            project_ledger(reverse_dated_ledger),
            CANONICAL_QUESTION,
        )

        self.assertEqual(result.status, AnswerStatus.SUPPORTED)
        self.assertEqual(result.location, "public/release.json")
        self.assertEqual(result.format, "release-manifest/v2")

    def test_resolver_accepts_projection_not_event_ledger(self) -> None:
        with self.assertRaisesRegex(TypeError, "StateProjection"):
            resolve_question(self.ledger, CANONICAL_QUESTION)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
