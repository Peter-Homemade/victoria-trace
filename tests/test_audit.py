# Copyright (C) 2026 Peter Van Geldorp
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from dataclasses import FrozenInstanceError
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from victoria_trace.audit import (  # noqa: E402
    AuditIntent,
    AuditSession,
    recognize_intent,
)
from victoria_trace.correction import apply_correction  # noqa: E402
from victoria_trace.ledger import EventLedger  # noqa: E402
from victoria_trace.regression import run_regression  # noqa: E402
from victoria_trace.resolver import resolve_question  # noqa: E402


FIXTURE = ROOT / "data" / "halcyon_history.jsonl"


class InteractiveAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture_bytes = FIXTURE.read_bytes()
        self.reference = EventLedger.load_jsonl(FIXTURE)
        self.session = AuditSession.from_reference_ledger(self.reference)

    def apply_correction(self) -> None:
        proposal = self.session.handle("Apply the correction.")
        self.assertTrue(proposal.awaiting_confirmation)
        accepted = self.session.handle("yes")
        self.assertEqual(accepted.revision, 6)

    def test_supported_phrasing_maps_to_explicit_intents(self) -> None:
        examples = {
            "What is the current answer?": AuditIntent.CURRENT_ANSWER,
            "Where should Halcyon publish the manifest?": (
                AuditIntent.CURRENT_ANSWER
            ),
            "What remains uncertain?": AuditIntent.UNCERTAINTY,
            "Why not /api/release?": AuditIntent.SUPERSEDED_DECISION,
            "What mistake was made?": AuditIntent.WRONG_ANSWER,
            "Show the evidence.": AuditIntent.EVIDENCE,
            "Was anything overwritten?": AuditIntent.HISTORY_PRESERVATION,
            "Apply the correction.": AuditIntent.APPLY_CORRECTION,
            "Compare before and after.": AuditIntent.DIFFERENCE,
            "Run the regression.": AuditIntent.VERIFY_REGRESSION,
            "Show the full history.": AuditIntent.FULL_HISTORY,
            "?": AuditIntent.HELP,
            "quit": AuditIntent.EXIT,
        }
        for phrase, expected in examples.items():
            with self.subTest(phrase=phrase):
                self.assertIs(recognize_intent(phrase), expected)

    def test_session_starts_at_revision_four_with_immutable_prefix(self) -> None:
        self.assertEqual(self.session.revision, 4)
        self.assertEqual(
            tuple(event.event_id for event in self.session.ledger),
            ("DEC-001", "DEC-002", "INT-001", "ANS-001"),
        )
        with self.assertRaises(FrozenInstanceError):
            self.session.ledger._events = ()  # type: ignore[misc]

    def test_current_answer_before_correction_is_uncertain(self) -> None:
        turn = self.session.handle("What is the current answer?")

        self.assertIs(turn.intent, AuditIntent.CURRENT_ANSWER)
        self.assertIn("State: UNCERTAIN", turn.message)
        self.assertIn("Revision: 4", turn.message)
        self.assertIn("Location: unresolved (no candidate selected)", turn.message)
        self.assertIn("Format: release-manifest/v2", turn.message)
        self.assertNotIn("State: SUPPORTED", turn.message)

    def test_unsupported_input_does_not_fabricate_an_answer(self) -> None:
        turn = self.session.handle("What is the weather in Brussels?")

        self.assertIs(turn.intent, AuditIntent.UNSUPPORTED)
        self.assertIn("only supports questions about the synthetic Halcyon", turn.message)
        self.assertIn('Type "help"', turn.message)
        self.assertNotIn("public/release.json", turn.message)

    def test_superseded_api_decision_is_historical_not_current(self) -> None:
        turn = self.session.handle("Why not /api/release?")

        self.assertIn("DEC-001 state: SUPERSEDED", turn.message)
        self.assertIn("Historical location: /api/release", turn.message)
        self.assertIn("Superseded by: DEC-002", turn.message)
        self.assertIn("historical, not current authority", turn.message)

    def test_wrong_answer_remains_visible_as_history(self) -> None:
        before = self.session.handle("Show the wrong answer.")
        self.apply_correction()
        after = self.session.handle("Show the wrong answer.")

        self.assertIn("Event: ANS-001", before.message)
        self.assertIn("State: HISTORICAL ERROR", before.message)
        self.assertIn("Recorded location: release.json", before.message)
        self.assertIn("Current answer authority: no", before.message)
        self.assertIn("State: CORRECTED HISTORICAL ERROR", after.message)
        self.assertIn("Corrected by: COR-001", after.message)
        self.assertIn("was not deleted", after.message)

    def test_correction_requires_explicit_confirmation(self) -> None:
        turn = self.session.handle("correct")

        self.assertTrue(turn.awaiting_confirmation)
        self.assertEqual(self.session.revision, 4)
        self.assertIn("Human owner: Mira Chen", turn.message)
        self.assertIn("Location: public/release.json", turn.message)
        self.assertIn("Format: release-manifest/v2", turn.message)
        self.assertIn("corrects ANS-001", turn.message)
        self.assertIn("resolves INT-001", turn.message)
        self.assertIn("clarifies DEC-002", turn.message)
        self.assertIn("Will append: COR-001 and REG-001", turn.message)
        self.assertIn("Type yes or no", turn.message)

    def test_invalid_confirmation_does_not_change_ledger(self) -> None:
        original = self.session.ledger
        self.session.handle("correct")

        turn = self.session.handle("maybe")

        self.assertEqual(self.session.ledger, original)
        self.assertEqual(turn.revision, 4)
        self.assertTrue(turn.awaiting_confirmation)
        self.assertIn("type yes or no", turn.message)
        self.assertIn("No events were appended", turn.message)

    def test_declining_confirmation_does_not_change_ledger(self) -> None:
        original = self.session.ledger
        self.session.handle("correct")

        turn = self.session.handle("no")

        self.assertEqual(self.session.ledger, original)
        self.assertEqual(turn.revision, 4)
        self.assertFalse(turn.awaiting_confirmation)
        self.assertIn("No events were appended", turn.message)

    def test_accepting_correction_appends_exactly_two_events(self) -> None:
        self.apply_correction()

        self.assertEqual(self.session.revision, 6)
        self.assertEqual(
            tuple(event.event_id for event in self.session.ledger),
            (
                "DEC-001",
                "DEC-002",
                "INT-001",
                "ANS-001",
                "COR-001",
                "REG-001",
            ),
        )

    def test_accepting_correction_preserves_revisions_one_through_four(self) -> None:
        original_events = self.session.ledger.events
        self.apply_correction()

        self.assertEqual(self.session.ledger.events[:4], original_events)
        history = self.session.handle("Was anything overwritten?")
        self.assertIn("Revisions 1-4 unchanged: yes", history.message)
        self.assertIn("Old answer deleted: no", history.message)

    def test_same_question_after_correction_is_supported(self) -> None:
        self.apply_correction()

        turn = self.session.handle("What is the current answer?")

        self.assertIn("State: SUPPORTED", turn.message)
        self.assertIn("Revision: 6", turn.message)
        self.assertIn("Location: public/release.json", turn.message)
        self.assertIn("Format: release-manifest/v2", turn.message)
        self.assertIn("Authority: human-owner correction COR-001", turn.message)

    def test_evidence_before_and_after_correction_is_exact(self) -> None:
        before = self.session.handle("evidence")
        self.apply_correction()
        after = self.session.handle("evidence")

        self.assertIn(
            "Answer evidence order: DEC-001 -> DEC-002 -> INT-001",
            before.message,
        )
        self.assertIn("ANS-001: role=historical_wrong_answer", before.message)
        self.assertIn(
            "Answer evidence order: DEC-001 -> DEC-002 -> INT-001 -> COR-001",
            after.message,
        )
        self.assertIn("COR-001: role=authoritative_correction", after.message)
        self.assertIn("REG-001: stored verifier; not used", after.message)

    def test_duplicate_correction_is_reported_without_appending(self) -> None:
        self.apply_correction()
        corrected = self.session.ledger

        turn = self.session.handle("Apply the correction.")

        self.assertEqual(self.session.ledger, corrected)
        self.assertEqual(self.session.revision, 6)
        self.assertFalse(turn.awaiting_confirmation)
        self.assertIn("already applied at revision 6", turn.message)
        self.assertIn("were not duplicated", turn.message)

    def test_regression_is_unavailable_before_correction(self) -> None:
        turn = self.session.handle("Run the regression.")

        self.assertIn("REG-001 is unavailable before the correction", turn.message)
        self.assertIn("Nothing was fabricated or executed", turn.message)

    def test_stored_regression_passes_all_twelve_assertions(self) -> None:
        self.apply_correction()

        with patch(
            "victoria_trace.audit.run_regression",
            wraps=run_regression,
        ) as regression_call:
            turn = self.session.handle("Run the regression.")

        self.assertEqual(regression_call.call_count, 1)
        self.assertIn("Regression: REG-001", turn.message)
        self.assertIn("Assertions: 12/12 passed", turn.message)
        self.assertIn("Overall: PASSED", turn.message)

    def test_regression_is_never_presented_as_answer_authority(self) -> None:
        self.apply_correction()

        answer = self.session.handle("ask")
        evidence = self.session.handle("Show the evidence.")
        regression = self.session.handle("verify")

        self.assertIn("REG-001 answer authority: no", answer.message)
        self.assertIn("not used as answer evidence", evidence.message)
        self.assertIn("it is not answer authority", regression.message)

    def test_reset_restores_revision_four_disposable_state(self) -> None:
        self.apply_correction()

        reset = self.session.handle("reset")
        answer = self.session.handle("ask")

        self.assertEqual(reset.revision, 4)
        self.assertEqual(self.session.revision, 4)
        self.assertEqual(self.session.ledger.events, self.reference.events[:4])
        self.assertIn("State: UNCERTAIN", answer.message)
        self.assertIn("repository fixture was never modified", reset.message)

    def test_exit_terminates_cleanly(self) -> None:
        self.apply_correction()
        turn = self.session.handle("exit")

        self.assertTrue(turn.should_exit)
        self.assertEqual(self.session.revision, 4)
        self.assertIn("Disposable state was discarded", turn.message)

    def test_full_history_uses_projected_revision_order(self) -> None:
        self.apply_correction()

        turn = self.session.handle("Show the full history.")

        positions = tuple(
            turn.message.index(event_id)
            for event_id in (
                "DEC-001",
                "DEC-002",
                "INT-001",
                "ANS-001",
                "COR-001",
                "REG-001",
            )
        )
        self.assertEqual(positions, tuple(sorted(positions)))
        self.assertIn("All visible events are preserved", turn.message)

    def test_existing_domain_apis_are_the_truth_path(self) -> None:
        session = AuditSession.from_reference_ledger(self.reference)
        with patch(
            "victoria_trace.audit.resolve_question",
            wraps=resolve_question,
        ) as resolver_call:
            session.handle("ask")
        self.assertEqual(resolver_call.call_count, 1)

        with patch(
            "victoria_trace.audit.apply_correction",
            wraps=apply_correction,
        ) as correction_call:
            session.handle("correct")
        self.assertEqual(correction_call.call_count, 1)

    def test_no_api_key_or_network_is_required(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("socket.socket", side_effect=AssertionError("network used")),
        ):
            session = AuditSession.from_reference_ledger(self.reference)
            self.assertIn("State: UNCERTAIN", session.handle("ask").message)
            session.handle("correct")
            session.handle("yes")
            self.assertIn("12/12 passed", session.handle("verify").message)

    def test_reference_fixture_remains_byte_for_byte_unchanged(self) -> None:
        self.apply_correction()
        self.session.handle("verify")
        self.session.handle("reset")

        self.assertEqual(FIXTURE.read_bytes(), self.fixture_bytes)

    def test_real_chat_subprocess_accepts_scripted_input_and_exits(self) -> None:
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        scripted_input = "ask\ncorrect\nyes\nverify\nexit\n"

        completed = subprocess.run(
            [sys.executable, "-m", "src.victoria_trace", "chat"],
            cwd=ROOT,
            env=environment,
            input=scripted_input,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        self.assertIn("INTERACTIVE AUDIT", completed.stdout)
        self.assertIn("State: UNCERTAIN", completed.stdout)
        self.assertIn("CORRECTION APPLIED", completed.stdout)
        self.assertIn("Assertions: 12/12 passed", completed.stdout)
        self.assertIn("Audit session ended", completed.stdout)
        self.assertEqual(FIXTURE.read_bytes(), self.fixture_bytes)


if __name__ == "__main__":
    unittest.main()
