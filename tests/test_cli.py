from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from io import StringIO
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from victoria_trace.cli import main  # noqa: E402
from victoria_trace.correction import apply_correction_to_file  # noqa: E402
from victoria_trace.ledger import EventLedger  # noqa: E402
from victoria_trace.projector import project_ledger  # noqa: E402
from victoria_trace.regression import run_regression  # noqa: E402
from victoria_trace.resolver import resolve_question  # noqa: E402


FIXTURE = ROOT / "data" / "halcyon_history.jsonl"


class CommandLineInterfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reference_ledger = EventLedger.load_jsonl(FIXTURE)
        self.fixture_bytes = FIXTURE.read_bytes()

    def invoke(self, *arguments: str) -> tuple[int, str, str]:
        output = StringIO()
        errors = StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            try:
                exit_code = main(
                    list(arguments),
                    stdout=output,
                    stderr=errors,
                )
            except SystemExit as error:
                exit_code = int(error.code or 0)
        return exit_code, output.getvalue(), errors.getvalue()

    def write_ledger(
        self,
        directory: str,
        ledger: EventLedger,
        *,
        name: str = "working.jsonl",
    ) -> tuple[Path, bytes]:
        path = Path(directory) / name
        encoded = b"".join(
            (event.to_json_line() + "\n").encode("utf-8")
            for event in ledger
        )
        path.write_bytes(encoded)
        return path, encoded

    def write_revision_four(self, directory: str) -> tuple[Path, bytes]:
        revision_four = EventLedger.from_events(self.reference_ledger[:4])
        return self.write_ledger(directory, revision_four)

    def write_failing_regression(self, directory: str) -> Path:
        regression = self.reference_ledger.get("REG-001")
        claim = dict(regression.claim)
        expected = dict(claim["expected"])
        expected["location"] = "somewhere-else/release.json"
        claim["expected"] = expected
        changed_regression = replace(regression, claim=claim)
        changed_ledger = EventLedger.from_events(
            self.reference_ledger[:5] + (changed_regression,)
        )
        path, _ = self.write_ledger(directory, changed_ledger)
        return path

    def test_help_discovers_every_command(self) -> None:
        exit_code, output, errors = self.invoke("--help")

        self.assertEqual(exit_code, 0)
        self.assertEqual(errors, "")
        for command in ("show-history", "ask", "correct", "verify", "demo"):
            self.assertIn(command, output)
        self.assertIn("Local, deterministic demonstration", output)

    def test_invalid_arguments_return_argparse_exit_code_two(self) -> None:
        invalid_commands = (
            ("correct",),
            ("verify",),
            ("ask", "--revision", "0"),
        )

        for arguments in invalid_commands:
            with self.subTest(arguments=arguments):
                exit_code, output, errors = self.invoke(*arguments)
                self.assertEqual(exit_code, 2)
                self.assertEqual(output, "")
                self.assertIn("error:", errors)
                self.assertNotIn("PASS", errors)

    def test_show_history_is_stable_and_revision_ordered(self) -> None:
        exit_code, output, errors = self.invoke("show-history")

        self.assertEqual(exit_code, 0)
        self.assertEqual(errors, "")
        expected_markers = tuple(
            f"Revision {index}: {event_id}"
            for index, event_id in enumerate(
                (
                    "DEC-001",
                    "DEC-002",
                    "INT-001",
                    "ANS-001",
                    "COR-001",
                    "REG-001",
                ),
                start=1,
            )
        )
        positions = tuple(output.index(marker) for marker in expected_markers)
        self.assertEqual(positions, tuple(sorted(positions)))
        self.assertIn("lifecycle: superseded", output)
        self.assertIn("lifecycle: historical", output)
        self.assertIn("authoritative_human_correction", output)

    def test_ask_revision_three_displays_structured_uncertainty(self) -> None:
        exit_code, output, errors = self.invoke("ask", "--revision", "3")

        self.assertEqual(exit_code, 0)
        self.assertEqual(errors, "")
        self.assertIn("Projection revision: 3", output)
        self.assertIn("Status: UNCERTAIN", output)
        self.assertIn("Location: unresolved (no location selected)", output)
        self.assertIn("candidates: release.json, public/release.json", output)
        self.assertIn("INT-001: unresolved_interpretation", output)

    def test_ask_revision_four_does_not_repeat_wrong_answer_as_truth(self) -> None:
        exit_code, output, _ = self.invoke("ask", "--revision", "4")

        self.assertEqual(exit_code, 0)
        self.assertIn("Status: UNCERTAIN", output)
        self.assertIn("Location: unresolved (no location selected)", output)
        self.assertNotIn("Location: release.json", output)
        self.assertIn("ANS-001: historical_wrong_answer", output)

    def test_ask_revision_five_returns_corrected_answer(self) -> None:
        exit_code, output, errors = self.invoke("ask", "--revision", "5")

        self.assertEqual(exit_code, 0)
        self.assertEqual(errors, "")
        self.assertIn("Projection revision: 5", output)
        self.assertIn("Status: SUPPORTED", output)
        self.assertIn("Location: public/release.json", output)
        self.assertIn("Format: release-manifest/v2", output)
        self.assertIn("COR-001: authoritative_correction", output)

    def test_ask_revision_six_returns_the_same_corrected_answer(self) -> None:
        code_five, revision_five, _ = self.invoke("ask", "--revision", "5")
        code_six, revision_six, _ = self.invoke("ask", "--revision", "6")

        self.assertEqual((code_five, code_six), (0, 0))
        comparable_five = revision_five.replace(
            "Projection revision: 5",
            "Projection revision: selected",
        )
        comparable_six = revision_six.replace(
            "Projection revision: 6",
            "Projection revision: selected",
        )
        self.assertEqual(comparable_five, comparable_six)
        self.assertNotIn("REG-001:", revision_six)

    def test_unsupported_ask_returns_nonzero(self) -> None:
        exit_code, output, errors = self.invoke("ask", "--revision", "1")

        self.assertEqual(exit_code, 1)
        self.assertEqual(errors, "")
        self.assertIn("Status: UNSUPPORTED", output)
        self.assertNotIn("Status: SUPPORTED", output)

    def test_correct_starts_from_temporary_revision_four_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger_path, _ = self.write_revision_four(directory)

            exit_code, output, errors = self.invoke(
                "correct",
                "--ledger",
                str(ledger_path),
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(errors, "")
            self.assertIn("Original revision: 4", output)
            self.assertIn("Resulting revision: 6", output)
            self.assertIn("Before correction", output)
            self.assertIn("After correction", output)

    def test_correct_creates_correction_and_regression_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger_path, _ = self.write_revision_four(directory)

            exit_code, output, _ = self.invoke(
                "correct",
                "--ledger",
                str(ledger_path),
            )
            corrected = EventLedger.load_jsonl(ledger_path)

            self.assertEqual(exit_code, 0)
            self.assertEqual(corrected.last_revision, 6)
            self.assertEqual(corrected[4].event_id, "COR-001")
            self.assertEqual(corrected[5].event_id, "REG-001")
            self.assertIn("Appended events: COR-001, REG-001", output)
            self.assertIn("Created revision 5: COR-001", output)
            self.assertIn("Created revision 6: REG-001", output)
            self.assertIn("persisted together", output)

    def test_correct_preserves_exact_original_record_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger_path, original_bytes = self.write_revision_four(directory)

            exit_code, output, _ = self.invoke(
                "correct",
                "--ledger",
                str(ledger_path),
            )
            corrected_bytes = ledger_path.read_bytes()

            self.assertEqual(exit_code, 0)
            self.assertEqual(corrected_bytes[: len(original_bytes)], original_bytes)
            self.assertIn("revisions 1-4 preserved unchanged", output)

    def test_duplicate_correction_is_rejected_without_success_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger_path, _ = self.write_revision_four(directory)
            first_code, _, _ = self.invoke(
                "correct",
                "--ledger",
                str(ledger_path),
            )
            bytes_after_first = ledger_path.read_bytes()

            second_code, output, errors = self.invoke(
                "correct",
                "--ledger",
                str(ledger_path),
            )

            self.assertEqual(first_code, 0)
            self.assertEqual(second_code, 1)
            self.assertIn("already contains", errors)
            self.assertNotIn("History preservation: PASS", output)
            self.assertEqual(ledger_path.read_bytes(), bytes_after_first)

    def test_verify_executes_and_reports_all_twelve_assertions(self) -> None:
        exit_code, output, errors = self.invoke(
            "verify",
            "--ledger",
            str(FIXTURE),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(errors, "")
        self.assertEqual(output.count("[PASS]"), 12)
        self.assertNotIn("[FAIL]", output)
        self.assertIn("Summary: 12/12 assertions passed", output)
        self.assertIn("Overall: PASSED", output)

    def test_verify_returns_nonzero_for_executed_regression_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger_path = self.write_failing_regression(directory)

            exit_code, output, errors = self.invoke(
                "verify",
                "--ledger",
                str(ledger_path),
            )

            self.assertEqual(exit_code, 1)
            self.assertEqual(errors, "")
            self.assertIn(
                "[FAIL] Current location matches the human correction",
                output,
            )
            self.assertIn("Assertion ID: answer.location", output)
            self.assertIn("Summary: 11/12 assertions passed", output)
            self.assertIn("Overall: FAILED", output)
            self.assertNotIn("Overall: PASSED", output)

    def test_verify_missing_regression_returns_nonzero_without_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger_path, _ = self.write_revision_four(directory)

            exit_code, output, errors = self.invoke(
                "verify",
                "--ledger",
                str(ledger_path),
            )

            self.assertEqual(exit_code, 1)
            self.assertEqual(output, "")
            self.assertIn("REG-001 is unavailable", errors)
            self.assertNotIn("assertions passed", errors)

    def test_demo_performs_the_complete_sequence(self) -> None:
        exit_code, output, errors = self.invoke("demo")

        self.assertEqual(exit_code, 0)
        self.assertEqual(errors, "")
        expected_steps = (
            "STAGE 1/6 - READ THE MEMORY BEFORE CORRECTION",
            "STAGE 2/6 - ASK BEFORE CORRECTION",
            "STAGE 3/6 - APPEND THE HUMAN-OWNER CORRECTION",
            "STAGE 4/6 - ASK THE SAME QUESTION AFTER CORRECTION",
            "STAGE 5/6 - RUN THE STORED REGRESSION",
            "STAGE 6/6 - CONFIRM THE APPEND-ONLY AUDIT TRAIL",
        )
        positions = tuple(output.index(step) for step in expected_steps)
        self.assertEqual(positions, tuple(sorted(positions)))
        self.assertIn("Status: UNCERTAIN", output)
        self.assertIn("Status: SUPPORTED", output)
        self.assertIn("Summary: 12/12 assertions passed", output)
        self.assertIn("PROOF SUMMARY", output)
        self.assertIn("Result: PASS", output)
        self.assertIn("reference fixture remains unchanged", output)

    def test_demo_explains_the_problem_and_answer_change(self) -> None:
        exit_code, output, errors = self.invoke("demo")

        self.assertEqual(exit_code, 0)
        self.assertEqual(errors, "")
        self.assertIn("This demonstration shows what changed", output)
        self.assertIn(
            "Before: UNCERTAIN | location unresolved | "
            "format release-manifest/v2",
            output,
        )
        self.assertIn(
            "After:  SUPPORTED | location public/release.json | "
            "format release-manifest/v2",
            output,
        )
        self.assertIn("The same deterministic resolver", output)

    def test_demo_makes_append_only_correction_explicit(self) -> None:
        exit_code, output, _ = self.invoke("demo")

        self.assertEqual(exit_code, 0)
        self.assertIn("Created revision 5: COR-001", output)
        self.assertIn("Created revision 6: REG-001", output)
        self.assertIn("no earlier revision was overwritten", output)
        self.assertIn("CORRECTED HISTORICAL ERROR", output)
        self.assertIn("REGRESSION-PROTECTED RECORD", output)

    def test_regression_assertions_have_jury_readable_labels(self) -> None:
        exit_code, output, errors = self.invoke(
            "verify",
            "--ledger",
            str(FIXTURE),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(errors, "")
        self.assertIn("Forbidden current location: /api/release", output)
        self.assertIn(
            "Forbidden current location: archive-root release.json",
            output,
        )
        self.assertIn("Returned as current answer: no", output)
        self.assertIn("ANS-001 remains history, not current authority", output)
        self.assertIn("corrected answer is regression-protected", output)

    def test_demo_is_repeatable(self) -> None:
        first_code, first_output, first_errors = self.invoke("demo")
        second_code, second_output, second_errors = self.invoke("demo")

        self.assertEqual((first_code, second_code), (0, 0))
        self.assertEqual(first_errors, "")
        self.assertEqual(second_errors, "")
        self.assertIn("Result: PASS", first_output)
        self.assertIn("Result: PASS", second_output)

    def test_demo_output_is_deterministic_ascii(self) -> None:
        _, first_output, _ = self.invoke("demo")
        _, second_output, _ = self.invoke("demo")

        self.assertEqual(first_output, second_output)
        self.assertTrue(first_output.isascii())
        self.assertNotIn("victoria-trace-demo-", first_output)
        self.assertNotIn(str(ROOT), first_output)

    def test_demo_does_not_modify_reference_fixture(self) -> None:
        before = FIXTURE.read_bytes()

        exit_code, _, _ = self.invoke("demo")

        self.assertEqual(exit_code, 0)
        self.assertEqual(FIXTURE.read_bytes(), before)
        self.assertEqual(before, self.fixture_bytes)

    def test_output_distinguishes_history_from_current_authority(self) -> None:
        exit_code, output, _ = self.invoke("show-history")

        self.assertEqual(exit_code, 0)
        decision_one = output[output.index("Revision 1: DEC-001"):]
        decision_one = decision_one[: decision_one.index("Revision 2: DEC-002")]
        decision_two = output[output.index("Revision 2: DEC-002"):]
        decision_two = decision_two[: decision_two.index("Revision 3: INT-001")]
        answer = output[output.index("Revision 4: ANS-001"):]
        answer = answer[: answer.index("Revision 5: COR-001")]
        correction = output[output.index("Revision 5: COR-001"):]
        correction = correction[: correction.index("Revision 6: REG-001")]

        self.assertIn("lifecycle: superseded", decision_one)
        self.assertIn("lifecycle: current", decision_two)
        self.assertIn("lifecycle: historical", answer)
        self.assertIn("recorded_wrong_answer", answer)
        self.assertIn("lifecycle: current", correction)
        self.assertIn("authoritative_human_correction", correction)

    def test_commands_delegate_to_existing_public_domain_apis(self) -> None:
        with patch(
            "victoria_trace.cli.project_ledger",
            wraps=project_ledger,
        ) as projector_call:
            show_code, _, _ = self.invoke("show-history")
        self.assertEqual(show_code, 0)
        self.assertEqual(projector_call.call_count, 1)

        with patch(
            "victoria_trace.cli.resolve_question",
            wraps=resolve_question,
        ) as resolver_call:
            ask_code, _, _ = self.invoke("ask", "--revision", "4")
        self.assertEqual(ask_code, 0)
        self.assertEqual(resolver_call.call_count, 1)

        with tempfile.TemporaryDirectory() as directory:
            ledger_path, _ = self.write_revision_four(directory)
            with patch(
                "victoria_trace.cli.apply_correction_to_file",
                wraps=apply_correction_to_file,
            ) as correction_call:
                correct_code, _, _ = self.invoke(
                    "correct",
                    "--ledger",
                    str(ledger_path),
                )
            self.assertEqual(correct_code, 0)
            self.assertEqual(correction_call.call_count, 1)

        with patch(
            "victoria_trace.cli.run_regression",
            wraps=run_regression,
        ) as regression_call:
            verify_code, _, _ = self.invoke(
                "verify",
                "--ledger",
                str(FIXTURE),
            )
        self.assertEqual(verify_code, 0)
        self.assertEqual(regression_call.call_count, 1)

    def test_real_module_entry_point_runs_demo_from_clean_checkout(self) -> None:
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)

        completed = subprocess.run(
            [sys.executable, "-m", "src.victoria_trace", "demo"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        self.assertIn("VICTORIA TRACE - GUIDED LOCAL PROOF", completed.stdout)
        self.assertIn("Summary: 12/12 assertions passed", completed.stdout)
        self.assertIn("Result: PASS", completed.stdout)
        self.assertNotIn(str(ROOT), completed.stdout)
        self.assertEqual(FIXTURE.read_bytes(), self.fixture_bytes)


if __name__ == "__main__":
    unittest.main()
