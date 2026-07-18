from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from victoria_trace.correction import (  # noqa: E402
    CANONICAL_FORMAT,
    CANONICAL_LOCATION,
    CORRECTION_DATE,
    CorrectionPersistenceError,
    CorrectionPreconditionError,
    CorrectionRequest,
    CorrectionRequestError,
    apply_correction,
    apply_correction_to_file,
    canonical_correction_request,
)
from victoria_trace.ledger import EventLedger  # noqa: E402
from victoria_trace.models import (  # noqa: E402
    Event,
    EventKind,
    EventRelationship,
    Provenance,
    RelationshipKind,
)
from victoria_trace.projector import (  # noqa: E402
    LifecycleState,
    StateAnnotation,
    project_ledger,
)
from victoria_trace.resolver import AnswerStatus, CANONICAL_QUESTION  # noqa: E402


FIXTURE = ROOT / "data" / "halcyon_history.jsonl"


class HumanCorrectionWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reference_ledger = EventLedger.load_jsonl(FIXTURE)
        self.prefix_ledger = EventLedger.from_events(self.reference_ledger[:4])
        self.request = canonical_correction_request()

    def prefix_bytes(self) -> bytes:
        return b"".join(FIXTURE.read_bytes().splitlines(keepends=True)[:4])

    def write_prefix(self, directory: str) -> tuple[Path, bytes]:
        ledger_path = Path(directory) / "history.jsonl"
        original_bytes = self.prefix_bytes()
        ledger_path.write_bytes(original_bytes)
        return ledger_path, original_bytes

    def test_successful_correction_from_revision_four_prefix(self) -> None:
        result = apply_correction(self.prefix_ledger, self.request)

        self.assertEqual(result.original_revision, 4)
        self.assertEqual(result.resulting_revision, 6)
        self.assertEqual(result.resulting_ledger.last_revision, 6)
        self.assertEqual(result.appended_event_ids, ("COR-001", "REG-001"))
        self.assertFalse(result.persistence_requested)
        self.assertFalse(result.persistence_completed)

    def test_correction_event_is_revision_five_with_exact_relationships(self) -> None:
        event = apply_correction(self.prefix_ledger, self.request).correction_event

        self.assertEqual(event.event_id, "COR-001")
        self.assertEqual(event.revision, 5)
        self.assertEqual(event.kind, EventKind.CORRECTION)
        self.assertEqual(event.occurred_on, date(2026, 4, 5))
        self.assertEqual(
            event.relationships,
            (
                EventRelationship(RelationshipKind.CORRECTS, "ANS-001"),
                EventRelationship(RelationshipKind.RESOLVES, "INT-001"),
                EventRelationship(RelationshipKind.CLARIFIES, "DEC-002"),
            ),
        )

    def test_correction_event_has_exact_synthetic_human_provenance_and_claim(self) -> None:
        event = apply_correction(self.prefix_ledger, self.request).correction_event

        self.assertEqual(
            event.source,
            Provenance(
                source_id="release-owner-correction",
                source_type="human",
                synthetic=True,
                actor="Mira Chen",
            ),
        )
        self.assertEqual(
            event.to_dict()["claim"],
            {
                "authority": "human_owner",
                "format": "release-manifest/v2",
                "incorrect_location": "release.json",
                "location": "public/release.json",
                "subject": "halcyon.release_metadata",
            },
        )

    def test_regression_event_is_revision_six_with_machine_readable_expectations(self) -> None:
        event = apply_correction(self.prefix_ledger, self.request).regression_event

        self.assertEqual(event.event_id, "REG-001")
        self.assertEqual(event.revision, 6)
        self.assertEqual(event.kind, EventKind.REGRESSION)
        self.assertEqual(event.occurred_on, CORRECTION_DATE)
        self.assertEqual(
            event.relationships,
            (EventRelationship(RelationshipKind.GENERATED_FROM, "COR-001"),),
        )
        self.assertEqual(event.event_id, "REG-001")
        self.assertEqual(event.claim["question"], CANONICAL_QUESTION)
        self.assertEqual(
            event.claim["expected"],
            {"format": CANONICAL_FORMAT, "location": CANONICAL_LOCATION},
        )
        self.assertEqual(
            event.claim["required_evidence"],
            ("DEC-001", "DEC-002", "INT-001", "COR-001"),
        )
        self.assertEqual(
            event.claim["required_states"],
            {
                "COR-001": "authoritative_correction",
                "DEC-001": "superseded",
                "DEC-002": "current",
                "INT-001": "resolved",
            },
        )
        self.assertEqual(
            event.claim["forbidden_locations"],
            ("/api/release", "release.json"),
        )

    def test_resolver_results_change_from_uncertain_to_supported(self) -> None:
        result = apply_correction(self.prefix_ledger, self.request)

        self.assertEqual(result.before_resolution.status, AnswerStatus.UNCERTAIN)
        self.assertIsNone(result.before_resolution.location)
        self.assertEqual(result.before_resolution.format, CANONICAL_FORMAT)
        self.assertEqual(result.after_resolution.status, AnswerStatus.SUPPORTED)
        self.assertEqual(result.after_resolution.location, CANONICAL_LOCATION)
        self.assertEqual(result.after_resolution.format, CANONICAL_FORMAT)

    def test_supported_evidence_order_excludes_regression_record(self) -> None:
        result = apply_correction(self.prefix_ledger, self.request)

        self.assertEqual(
            result.after_resolution.evidence_event_ids,
            ("DEC-001", "DEC-002", "INT-001", "COR-001"),
        )
        self.assertNotIn("REG-001", result.after_resolution.evidence_event_ids)

    def test_projection_postconditions_preserve_and_correct_history(self) -> None:
        result = apply_correction(self.prefix_ledger, self.request)
        projection = project_ledger(result.resulting_ledger)

        self.assertEqual(
            projection.get("INT-001").lifecycle,
            LifecycleState.RESOLVED,
        )
        self.assertEqual(
            projection.get("ANS-001").lifecycle,
            LifecycleState.HISTORICAL,
        )
        self.assertIn(
            StateAnnotation.CORRECTED_BY_HUMAN,
            projection.get("ANS-001").annotations,
        )
        self.assertIn(
            StateAnnotation.AUTHORITATIVE_HUMAN_CORRECTION,
            projection.get("COR-001").annotations,
        )

    def test_revisions_one_through_four_and_input_ledger_are_unchanged(self) -> None:
        original_events = self.prefix_ledger.events

        result = apply_correction(self.prefix_ledger, self.request)

        self.assertEqual(self.prefix_ledger.events, original_events)
        self.assertEqual(result.resulting_ledger.events[:4], original_events)
        for original, preserved in zip(
            original_events,
            result.resulting_ledger.events[:4],
            strict=True,
        ):
            self.assertIs(original, preserved)

    def test_repeated_construction_is_deterministic(self) -> None:
        first = apply_correction(self.prefix_ledger, self.request)
        second = apply_correction(self.prefix_ledger, self.request)

        self.assertEqual(first.correction_event, second.correction_event)
        self.assertEqual(first.regression_event, second.regression_event)
        self.assertEqual(first.resulting_ledger, second.resulting_ledger)
        self.assertEqual(first.before_resolution, second.before_resolution)
        self.assertEqual(first.after_resolution, second.after_resolution)

    def test_request_result_events_and_nested_values_are_immutable(self) -> None:
        result = apply_correction(self.prefix_ledger, self.request)

        with self.assertRaises(FrozenInstanceError):
            self.request.location = "release.json"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            result.resulting_revision = 5  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            result.correction_event.revision = 9  # type: ignore[misc]
        with self.assertRaises(TypeError):
            result.regression_event.claim["question"] = "changed"  # type: ignore[index]
        with self.assertRaises(TypeError):
            result.regression_event.claim["expected"]["location"] = "changed"  # type: ignore[index]
        with self.assertRaises(TypeError):
            result.appended_event_ids[0] = "COR-999"  # type: ignore[index]

    def test_workflow_uses_fixed_scenario_timestamp(self) -> None:
        result = apply_correction(self.prefix_ledger, self.request)

        self.assertEqual(result.correction_event.occurred_on, date(2026, 4, 5))
        self.assertEqual(result.regression_event.occurred_on, date(2026, 4, 5))

    def test_generated_events_match_reference_fixture_semantically(self) -> None:
        result = apply_correction(self.prefix_ledger, self.request)

        self.assertEqual(
            result.correction_event.to_dict(),
            self.reference_ledger[4].to_dict(),
        )
        self.assertEqual(
            result.regression_event.to_dict(),
            self.reference_ledger[5].to_dict(),
        )

    def test_ledger_before_recorded_answer_is_rejected(self) -> None:
        early_ledger = EventLedger.from_events(self.reference_ledger[:3])

        with self.assertRaisesRegex(
            CorrectionPreconditionError,
            "end at revision 4",
        ):
            apply_correction(early_ledger, self.request)

    def test_duplicate_application_is_rejected(self) -> None:
        corrected = apply_correction(self.prefix_ledger, self.request).resulting_ledger

        with self.assertRaisesRegex(
            CorrectionPreconditionError,
            "already contains the canonical regression record",
        ):
            apply_correction(corrected, self.request)

    def test_already_resolved_reference_prefix_is_rejected(self) -> None:
        resolved_ledger = EventLedger.from_events(self.reference_ledger[:5])

        with self.assertRaisesRegex(
            CorrectionPreconditionError,
            "already contains an authoritative correction",
        ):
            apply_correction(resolved_ledger, self.request)

    def test_current_original_decision_is_rejected(self) -> None:
        current_original = EventLedger.from_events(
            (
                self.prefix_ledger[0],
                replace(self.prefix_ledger[1], relationships=()),
                self.prefix_ledger[2],
                self.prefix_ledger[3],
            )
        )

        with self.assertRaisesRegex(
            CorrectionPreconditionError,
            "DEC-001 must be superseded",
        ):
            apply_correction(current_original, self.request)

    def test_noncurrent_replacement_decision_is_rejected(self) -> None:
        replacement_decision = Event(
            event_id="DEC-003",
            revision=3,
            kind=EventKind.DECISION,
            occurred_on=date(2026, 3, 12),
            source=Provenance("replacement", "document", True),
            claim={"subject": "halcyon.release_metadata", "status": "accepted"},
            relationships=(
                EventRelationship(RelationshipKind.SUPERSEDES, "DEC-002"),
            ),
        )
        answer = replace(
            self.prefix_ledger[3],
            relationships=(
                EventRelationship(RelationshipKind.CITES, "DEC-003"),
            ),
        )
        noncanonical = EventLedger.from_events(
            (
                self.prefix_ledger[0],
                self.prefix_ledger[1],
                replacement_decision,
                answer,
            )
        )

        with self.assertRaisesRegex(
            CorrectionPreconditionError,
            "revision-4 ledger must contain",
        ):
            apply_correction(noncanonical, self.request)

    def test_pre_correction_resolution_must_be_structurally_uncertain(self) -> None:
        changed_claim = dict(self.prefix_ledger[2].claim)
        changed_claim.pop("candidates")
        malformed_interpretation = replace(
            self.prefix_ledger[2],
            claim=changed_claim,
        )
        malformed_ledger = EventLedger.from_events(
            self.prefix_ledger[:2]
            + (malformed_interpretation,)
            + self.prefix_ledger[3:]
        )

        with self.assertRaisesRegex(
            CorrectionPreconditionError,
            "pre-correction resolution is invalid",
        ):
            apply_correction(malformed_ledger, self.request)

    def test_missing_or_incompatible_authority_is_rejected(self) -> None:
        with self.assertRaisesRegex(CorrectionRequestError, "authority"):
            CorrectionRequest(
                human_owner="Mira Chen",
                source_id="release-owner-correction",
                authority="",
                location=CANONICAL_LOCATION,
                format=CANONICAL_FORMAT,
                synthetic=True,
            )

        with self.assertRaisesRegex(CorrectionRequestError, "authority must be"):
            apply_correction(
                self.prefix_ledger,
                replace(self.request, authority="reviewer"),
            )

    def test_mismatched_or_non_synthetic_provenance_is_rejected(self) -> None:
        incompatible_requests = (
            replace(self.request, human_owner="Someone Else"),
            replace(self.request, source_id="other-source"),
            replace(self.request, synthetic=False),
        )

        for request in incompatible_requests:
            with self.subTest(request=request):
                with self.assertRaises(CorrectionRequestError):
                    apply_correction(self.prefix_ledger, request)

    def test_incompatible_correction_content_is_rejected(self) -> None:
        incompatible_requests = (
            replace(self.request, location="release.json"),
            replace(self.request, format="halcyon-release/v1"),
        )

        for request in incompatible_requests:
            with self.subTest(request=request):
                with self.assertRaises(CorrectionRequestError):
                    apply_correction(self.prefix_ledger, request)

    def test_successful_persistence_to_revision_four_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger_path, _ = self.write_prefix(directory)

            result = apply_correction_to_file(
                ledger_path,
                self.prefix_ledger,
                self.request,
            )

            self.assertTrue(result.persistence_requested)
            self.assertTrue(result.persistence_completed)
            self.assertEqual(result.resulting_revision, 6)

    def test_persistence_preserves_existing_bytes_and_appends_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger_path, original_bytes = self.write_prefix(directory)

            result = apply_correction_to_file(
                ledger_path,
                self.prefix_ledger,
                self.request,
            )
            persisted_bytes = ledger_path.read_bytes()

            self.assertEqual(persisted_bytes[: len(original_bytes)], original_bytes)
            appended_lines = persisted_bytes[len(original_bytes) :].splitlines()
            self.assertEqual(len(appended_lines), 2)
            self.assertEqual(
                Event.from_dict(json.loads(appended_lines[0])).event_id,
                "COR-001",
            )
            self.assertEqual(
                Event.from_dict(json.loads(appended_lines[1])).event_id,
                "REG-001",
            )
            self.assertEqual(result.appended_event_ids, ("COR-001", "REG-001"))

    def test_persisted_file_reloads_as_same_six_event_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger_path, _ = self.write_prefix(directory)

            result = apply_correction_to_file(
                ledger_path,
                self.prefix_ledger,
                self.request,
            )

            self.assertEqual(
                EventLedger.load_jsonl(ledger_path),
                result.resulting_ledger,
            )

    def test_atomic_replace_failure_leaves_original_file_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger_path, original_bytes = self.write_prefix(directory)

            with patch(
                "victoria_trace.correction.os.replace",
                side_effect=OSError("synthetic replacement failure"),
            ):
                with self.assertRaisesRegex(
                    CorrectionPersistenceError,
                    "original file was retained",
                ):
                    apply_correction_to_file(
                        ledger_path,
                        self.prefix_ledger,
                        self.request,
                    )

            self.assertEqual(ledger_path.read_bytes(), original_bytes)
            self.assertEqual(
                tuple(Path(directory).iterdir()),
                (ledger_path,),
            )

    def test_mismatched_supplied_ledger_and_file_are_rejected_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger_path, original_bytes = self.write_prefix(directory)
            changed_claim = dict(self.prefix_ledger[0].claim)
            changed_claim["status"] = "draft"
            mismatched_ledger = EventLedger.from_events(
                (replace(self.prefix_ledger[0], claim=changed_claim),)
                + self.prefix_ledger[1:]
            )

            with self.assertRaisesRegex(
                CorrectionPersistenceError,
                "does not match",
            ):
                apply_correction_to_file(
                    ledger_path,
                    mismatched_ledger,
                    self.request,
                )

            self.assertEqual(ledger_path.read_bytes(), original_bytes)

    def test_unterminated_file_is_rejected_without_modification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger_path = Path(directory) / "history.jsonl"
            original_bytes = self.prefix_bytes().removesuffix(b"\n")
            ledger_path.write_bytes(original_bytes)

            with self.assertRaisesRegex(
                CorrectionPersistenceError,
                "end with a newline",
            ):
                apply_correction_to_file(
                    ledger_path,
                    self.prefix_ledger,
                    self.request,
                )

            self.assertEqual(ledger_path.read_bytes(), original_bytes)


if __name__ == "__main__":
    unittest.main()
