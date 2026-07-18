from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from victoria_trace.ledger import (  # noqa: E402
    EventLedger,
    LedgerFormatError,
    LedgerValidationError,
)
from victoria_trace.models import (  # noqa: E402
    Event,
    EventKind,
    EventRelationship,
    Provenance,
    RelationshipKind,
)


FIXTURE = ROOT / "data" / "halcyon_history.jsonl"


class EventLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = EventLedger.load_jsonl(FIXTURE)

    def test_complete_synthetic_history_loads(self) -> None:
        self.assertEqual(self.ledger.last_revision, 6)
        self.assertEqual(
            [event.event_id for event in self.ledger],
            ["DEC-001", "DEC-002", "INT-001", "ANS-001", "COR-001", "REG-001"],
        )
        self.assertEqual(self.ledger.get("COR-001").revision, 5)

    def test_append_returns_new_ledger_without_mutating_original(self) -> None:
        original = EventLedger.from_events(self.ledger[:1])

        updated = original.append(self.ledger[1])

        self.assertEqual(len(original), 1)
        self.assertEqual(len(updated), 2)
        self.assertEqual(updated[-1].event_id, "DEC-002")

    def test_revision_gaps_are_rejected(self) -> None:
        wrong_revision = replace(self.ledger[1], revision=3)

        with self.assertRaisesRegex(LedgerValidationError, "expected 2"):
            EventLedger.from_events((self.ledger[0], wrong_revision))

    def test_duplicate_event_ids_are_rejected(self) -> None:
        duplicate = replace(self.ledger[0], revision=2)

        with self.assertRaisesRegex(LedgerValidationError, "duplicate event ID"):
            EventLedger.from_events((self.ledger[0], duplicate))

    def test_forward_relationships_are_rejected(self) -> None:
        interpretation = Event(
            event_id="INT-999",
            revision=1,
            kind=EventKind.INTERPRETATION,
            occurred_on=date(2026, 1, 1),
            source=Provenance("test-source", "test", True),
            claim={"status": "unresolved"},
            relationships=(
                EventRelationship(RelationshipKind.INTERPRETS, "DEC-999"),
            ),
        )

        with self.assertRaisesRegex(
            LedgerValidationError, "missing or future event DEC-999"
        ):
            EventLedger.from_events((interpretation,))

    def test_relationship_source_and_target_types_are_validated(self) -> None:
        invalid_decision = replace(
            self.ledger[1],
            relationships=(
                EventRelationship(RelationshipKind.INTERPRETS, "DEC-001"),
            ),
        )

        with self.assertRaisesRegex(
            LedgerValidationError, "decision event DEC-002 cannot use"
        ):
            EventLedger.from_events((self.ledger[0], invalid_decision))

    def test_required_relationships_are_validated(self) -> None:
        missing_relationship = replace(self.ledger[2], relationships=())

        with self.assertRaisesRegex(
            LedgerValidationError, "missing required relationships: interprets"
        ):
            EventLedger.from_events(self.ledger[:2] + (missing_relationship,))

    def test_file_append_preserves_all_existing_bytes(self) -> None:
        next_event = Event(
            event_id="DEC-003",
            revision=7,
            kind=EventKind.DECISION,
            occurred_on=date(2026, 4, 6),
            source=Provenance("test-follow-up", "test", True),
            claim={"subject": "halcyon.test_only", "status": "accepted"},
        )
        original_bytes = FIXTURE.read_bytes()

        with tempfile.TemporaryDirectory() as temporary_directory:
            ledger_path = Path(temporary_directory) / "history.jsonl"
            ledger_path.write_bytes(original_bytes)

            updated = EventLedger.append_to_jsonl(ledger_path, next_event)
            updated_bytes = ledger_path.read_bytes()

            self.assertEqual(updated_bytes[: len(original_bytes)], original_bytes)
            self.assertGreater(len(updated_bytes), len(original_bytes))
            self.assertEqual(updated.last_revision, 7)
            self.assertEqual(
                EventLedger.load_jsonl(ledger_path).get("DEC-003"), next_event
            )

    def test_file_append_rejects_unterminated_existing_record(self) -> None:
        first_event = self.ledger[0]

        with tempfile.TemporaryDirectory() as temporary_directory:
            ledger_path = Path(temporary_directory) / "history.jsonl"
            original_bytes = first_event.to_json_line().encode("utf-8")
            ledger_path.write_bytes(original_bytes)

            with self.assertRaisesRegex(
                LedgerFormatError, "not newline-terminated"
            ):
                EventLedger.append_to_jsonl(ledger_path, self.ledger[1])

            self.assertEqual(ledger_path.read_bytes(), original_bytes)


if __name__ == "__main__":
    unittest.main()

