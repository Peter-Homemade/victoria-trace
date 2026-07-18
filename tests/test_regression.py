from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from victoria_trace.correction import (  # noqa: E402
    apply_correction,
    canonical_correction_request,
)
from victoria_trace.ledger import EventLedger  # noqa: E402
from victoria_trace.models import (  # noqa: E402
    EventKind,
    EventRelationship,
    RelationshipKind,
)
from victoria_trace.projector import (  # noqa: E402
    LifecycleState,
    StateAnnotation,
    StateProjection,
    project_ledger,
)
from victoria_trace.regression import (  # noqa: E402
    AssertionKind,
    AssertionStatus,
    RegressionDefinitionError,
    RegressionExecutionError,
    RegressionNotFoundError,
    RegressionReason,
    RegressionStatus,
    run_all_regressions,
    run_regression,
)
from victoria_trace.resolver import (  # noqa: E402
    AnswerStatus,
    CANONICAL_QUESTION,
    ResolutionError,
    resolve_question,
)


FIXTURE = ROOT / "data" / "halcyon_history.jsonl"


class RegressionRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = EventLedger.load_jsonl(FIXTURE)
        self.projection = project_ledger(self.ledger)

    def replace_projected_event(
        self,
        projection: StateProjection,
        event_id: str,
        **changes: object,
    ) -> StateProjection:
        changed = replace(projection.get(event_id), **changes)
        return StateProjection(
            through_revision=projection.through_revision,
            events=tuple(
                changed if projected.event_id == event_id else projected
                for projected in projection.events
            ),
        )

    def replace_event(
        self,
        projection: StateProjection,
        event_id: str,
        **changes: object,
    ) -> StateProjection:
        projected = projection.get(event_id)
        changed_event = replace(projected.event, **changes)
        return self.replace_projected_event(
            projection,
            event_id,
            event=changed_event,
        )

    def replace_regression_claim(
        self,
        projection: StateProjection | None = None,
        **changes: object,
    ) -> StateProjection:
        selected = self.projection if projection is None else projection
        claim = dict(selected.get("REG-001").event.claim)
        claim.update(changes)
        return self.replace_event(selected, "REG-001", claim=claim)

    def assertion(self, result, assertion_id: str):
        return next(
            assertion
            for assertion in result.assertions
            if assertion.assertion_id == assertion_id
        )

    def test_successful_execution_of_regression_at_revision_six(self) -> None:
        result = run_regression(self.projection, "REG-001")

        self.assertEqual(result.regression_event_id, "REG-001")
        self.assertEqual(result.projection_revision, 6)
        self.assertEqual(result.question, CANONICAL_QUESTION)
        self.assertEqual(result.status, RegressionStatus.PASSED)
        self.assertEqual(result.reason, RegressionReason.ALL_ASSERTIONS_PASSED)
        self.assertEqual(result.failed_assertion_ids, ())
        self.assertTrue(all(assertion.passed for assertion in result.assertions))

    def test_existing_resolver_is_the_only_answering_path(self) -> None:
        with patch(
            "victoria_trace.regression.resolve_question",
            wraps=resolve_question,
        ) as resolver_call:
            result = run_regression(self.projection, "REG-001")

        resolver_call.assert_called_once_with(self.projection, CANONICAL_QUESTION)
        self.assertEqual(
            result.actual_resolution,
            resolve_question(self.projection, CANONICAL_QUESTION),
        )

    def test_corrected_location_and_format_are_exact(self) -> None:
        result = run_regression(self.projection, "REG-001")

        self.assertEqual(result.expected_location, "public/release.json")
        self.assertEqual(result.expected_format, "release-manifest/v2")
        self.assertEqual(result.actual_resolution.location, result.expected_location)
        self.assertEqual(result.actual_resolution.format, result.expected_format)
        self.assertEqual(
            self.assertion(result, "answer.location").status,
            AssertionStatus.PASSED,
        )
        self.assertEqual(
            self.assertion(result, "answer.format").status,
            AssertionStatus.PASSED,
        )

    def test_required_evidence_order_is_exact(self) -> None:
        result = run_regression(self.projection, "REG-001")
        expected = ("DEC-001", "DEC-002", "INT-001", "COR-001")

        self.assertEqual(result.required_evidence_ids, expected)
        self.assertEqual(result.actual_evidence_ids, expected)
        evidence_assertion = self.assertion(result, "answer.evidence")
        self.assertEqual(evidence_assertion.expected, expected)
        self.assertEqual(evidence_assertion.actual, expected)
        self.assertEqual(evidence_assertion.status, AssertionStatus.PASSED)

    def test_required_lifecycle_states_are_projector_values(self) -> None:
        result = run_regression(self.projection, "REG-001")
        expected = {
            "state.DEC-001": "superseded",
            "state.DEC-002": "current",
            "state.INT-001": "resolved",
        }

        for assertion_id, state in expected.items():
            with self.subTest(assertion_id=assertion_id):
                assertion = self.assertion(result, assertion_id)
                self.assertEqual(
                    assertion.kind,
                    AssertionKind.REQUIRED_PROJECTED_STATE,
                )
                self.assertEqual(assertion.expected, state)
                self.assertEqual(assertion.actual, state)
                self.assertEqual(assertion.status, AssertionStatus.PASSED)

    def test_required_correction_authority_uses_projector_annotation(self) -> None:
        result = run_regression(self.projection, "REG-001")
        assertion = self.assertion(result, "state.COR-001")

        self.assertIn(
            StateAnnotation.AUTHORITATIVE_HUMAN_CORRECTION,
            self.projection.get("COR-001").annotations,
        )
        self.assertEqual(assertion.expected, "authoritative_correction")
        self.assertEqual(assertion.actual, "authoritative_correction")
        self.assertEqual(assertion.event_ids, ("COR-001",))
        self.assertEqual(assertion.status, AssertionStatus.PASSED)

    def test_assertion_order_is_stable_and_documented_by_identifiers(self) -> None:
        result = run_regression(self.projection, "REG-001")

        self.assertEqual(
            tuple(assertion.assertion_id for assertion in result.assertions),
            (
                "resolver.status",
                "answer.location",
                "answer.format",
                "answer.evidence",
                "state.DEC-001",
                "state.DEC-002",
                "state.INT-001",
                "state.COR-001",
                "forbidden_location.001",
                "forbidden_location.002",
                "answer.excludes.ANS-001",
                "answer.excludes.REG-001",
            ),
        )

    def test_forbidden_api_location_fails_only_as_current_answer(self) -> None:
        correction = self.projection.get("COR-001")
        changed_claim = dict(correction.event.claim)
        changed_claim["location"] = "/api/release"
        changed_projection = self.replace_event(
            self.projection,
            "COR-001",
            claim=changed_claim,
        )

        result = run_regression(changed_projection, "REG-001")

        self.assertEqual(result.status, RegressionStatus.FAILED)
        self.assertEqual(result.actual_resolution.location, "/api/release")
        self.assertIn("forbidden_location.001", result.failed_assertion_ids)
        forbidden = self.assertion(result, "forbidden_location.001")
        self.assertEqual(forbidden.expected, False)
        self.assertEqual(forbidden.actual, True)

    def test_forbidden_archive_root_location_fails_only_as_current_answer(self) -> None:
        correction = self.projection.get("COR-001")
        changed_claim = dict(correction.event.claim)
        changed_claim["location"] = "release.json"
        changed_projection = self.replace_event(
            self.projection,
            "COR-001",
            claim=changed_claim,
        )

        result = run_regression(changed_projection, "REG-001")

        self.assertEqual(result.status, RegressionStatus.FAILED)
        self.assertEqual(result.actual_resolution.location, "release.json")
        self.assertIn("forbidden_location.002", result.failed_assertion_ids)

    def test_historical_forbidden_values_do_not_fail_the_regression(self) -> None:
        self.assertEqual(
            self.projection.get("DEC-001").event.claim["location"],
            "/api/release",
        )
        self.assertEqual(
            self.projection.get("ANS-001").event.claim["location"],
            "release.json",
        )

        result = run_regression(self.projection, "REG-001")

        self.assertEqual(result.status, RegressionStatus.PASSED)
        self.assertTrue(self.assertion(result, "forbidden_location.001").passed)
        self.assertTrue(self.assertion(result, "forbidden_location.002").passed)

    def test_historical_answer_is_not_current_authority(self) -> None:
        result = run_regression(self.projection, "REG-001")
        assertion = self.assertion(result, "answer.excludes.ANS-001")

        self.assertEqual(
            self.projection.get("ANS-001").lifecycle,
            LifecycleState.HISTORICAL,
        )
        self.assertNotIn("ANS-001", result.actual_evidence_ids)
        self.assertEqual(assertion.actual, False)
        self.assertEqual(assertion.status, AssertionStatus.PASSED)

    def test_regression_record_is_not_answer_evidence(self) -> None:
        result = run_regression(self.projection, "REG-001")
        assertion = self.assertion(result, "answer.excludes.REG-001")

        self.assertNotIn("REG-001", result.actual_evidence_ids)
        self.assertEqual(assertion.actual, False)
        self.assertEqual(assertion.status, AssertionStatus.PASSED)

    def test_revision_five_has_no_regression_to_execute(self) -> None:
        projection = project_ledger(self.ledger, through_revision=5)

        with self.assertRaisesRegex(RegressionNotFoundError, "unavailable"):
            run_regression(projection, "REG-001")
        self.assertEqual(run_all_regressions(projection), ())

    def test_revisions_one_through_four_never_fabricate_regression(self) -> None:
        for revision in range(1, 5):
            with self.subTest(revision=revision):
                projection = project_ledger(self.ledger, through_revision=revision)
                with self.assertRaises(RegressionNotFoundError):
                    run_regression(projection, "REG-001")
                self.assertEqual(run_all_regressions(projection), ())

    def test_non_regression_event_id_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            RegressionDefinitionError,
            "not a regression",
        ):
            run_regression(self.projection, "COR-001")

    def test_empty_expected_location_or_format_is_invalid(self) -> None:
        for field_name in ("location", "format"):
            with self.subTest(field_name=field_name):
                expected = dict(
                    self.projection.get("REG-001").event.claim["expected"]
                )
                expected[field_name] = ""
                malformed = self.replace_regression_claim(expected=expected)

                with self.assertRaisesRegex(
                    RegressionDefinitionError,
                    f"expected.{field_name} must be a non-empty string",
                ):
                    run_regression(malformed, "REG-001")

    def test_missing_expected_format_is_invalid(self) -> None:
        expected = dict(self.projection.get("REG-001").event.claim["expected"])
        expected.pop("format")
        malformed = self.replace_regression_claim(expected=expected)

        with self.assertRaisesRegex(
            RegressionDefinitionError,
            "claim.expected is missing fields: format",
        ):
            run_regression(malformed, "REG-001")

    def test_duplicate_required_evidence_is_invalid(self) -> None:
        malformed = self.replace_regression_claim(
            required_evidence=("DEC-001", "DEC-002", "DEC-002", "COR-001")
        )

        with self.assertRaisesRegex(RegressionDefinitionError, "unique"):
            run_regression(malformed, "REG-001")

    def test_missing_required_evidence_event_is_invalid(self) -> None:
        malformed = self.replace_regression_claim(
            required_evidence=("DEC-001", "DEC-002", "INT-001", "COR-999")
        )

        with self.assertRaisesRegex(
            RegressionDefinitionError,
            "missing from the projection: COR-999",
        ):
            run_regression(malformed, "REG-001")

    def test_missing_required_evidence_field_is_invalid(self) -> None:
        claim = dict(self.projection.get("REG-001").event.claim)
        claim.pop("required_evidence")
        malformed = self.replace_event(
            self.projection,
            "REG-001",
            claim=claim,
        )

        with self.assertRaisesRegex(
            RegressionDefinitionError,
            "claim is missing fields: required_evidence",
        ):
            run_regression(malformed, "REG-001")

    def test_self_referential_required_evidence_is_invalid(self) -> None:
        malformed = self.replace_regression_claim(
            required_evidence=("DEC-001", "DEC-002", "INT-001", "REG-001")
        )

        with self.assertRaisesRegex(RegressionDefinitionError, "require itself"):
            run_regression(malformed, "REG-001")

    def test_required_evidence_must_follow_projection_order(self) -> None:
        malformed = self.replace_regression_claim(
            required_evidence=("DEC-002", "DEC-001", "INT-001", "COR-001")
        )

        with self.assertRaisesRegex(RegressionDefinitionError, "revision order"):
            run_regression(malformed, "REG-001")

    def test_unknown_required_state_syntax_is_invalid(self) -> None:
        required_states = dict(
            self.projection.get("REG-001").event.claim["required_states"]
        )
        required_states["INT-001"] = "settled_somehow"
        malformed = self.replace_regression_claim(required_states=required_states)

        with self.assertRaisesRegex(
            RegressionDefinitionError,
            "unknown required-state syntax",
        ):
            run_regression(malformed, "REG-001")

    def test_missing_generated_from_relationship_is_invalid(self) -> None:
        malformed = self.replace_event(
            self.projection,
            "REG-001",
            relationships=(),
        )

        with self.assertRaisesRegex(
            RegressionDefinitionError,
            "exactly one generated_from",
        ):
            run_regression(malformed, "REG-001")

    def test_projected_regression_must_retain_visibility_annotation(self) -> None:
        malformed = self.replace_projected_event(
            self.projection,
            "REG-001",
            annotations=frozenset(),
        )

        with self.assertRaisesRegex(
            RegressionDefinitionError,
            "regression-record annotation",
        ):
            run_regression(malformed, "REG-001")

    def test_missing_generated_from_correction_is_invalid(self) -> None:
        correction = self.projection.get("COR-001")
        renamed_event = replace(correction.event, event_id="COR-999")
        renamed_correction = replace(correction, event=renamed_event)
        malformed = StateProjection(
            through_revision=6,
            events=self.projection.events[:4]
            + (renamed_correction, self.projection.events[5]),
        )

        with self.assertRaisesRegex(
            RegressionDefinitionError,
            "correction COR-001 is missing",
        ):
            run_regression(malformed, "REG-001")

    def test_generated_from_correction_must_remain_authoritative(self) -> None:
        correction = replace(
            self.projection.get("COR-001"),
            annotations=frozenset({StateAnnotation.CORRECTED_ANSWER}),
        )
        malformed = StateProjection(
            through_revision=6,
            events=self.projection.events[:4]
            + (correction, self.projection.events[5]),
        )

        with self.assertRaisesRegex(
            RegressionDefinitionError,
            "not authoritative",
        ):
            run_regression(malformed, "REG-001")

    def test_unsupported_stored_question_is_invalid(self) -> None:
        malformed = self.replace_regression_claim(
            question="Where are Halcyon's release notes?"
        )

        with self.assertRaisesRegex(
            RegressionDefinitionError,
            "unsupported by the resolver",
        ):
            run_regression(malformed, "REG-001")

    def test_unknown_claim_assertion_field_is_invalid(self) -> None:
        malformed = self.replace_regression_claim(silent_assertion=True)

        with self.assertRaisesRegex(
            RegressionDefinitionError,
            "unknown fields: silent_assertion",
        ):
            run_regression(malformed, "REG-001")

    def test_malformed_forbidden_location_structure_is_invalid(self) -> None:
        malformed_values = (
            "/api/release",
            ("/api/release", ""),
            ("/api/release", "/api/release"),
        )
        for value in malformed_values:
            with self.subTest(value=value):
                malformed = self.replace_regression_claim(
                    forbidden_locations=value
                )
                with self.assertRaises(RegressionDefinitionError):
                    run_regression(malformed, "REG-001")

    def test_expected_location_cannot_also_be_forbidden(self) -> None:
        expected = dict(self.projection.get("REG-001").event.claim["expected"])
        expected["location"] = "/api/release"
        malformed = self.replace_regression_claim(expected=expected)

        with self.assertRaisesRegex(
            RegressionDefinitionError,
            "cannot also be a forbidden",
        ):
            run_regression(malformed, "REG-001")

    def test_valid_expectation_mismatch_returns_failed_not_invalid(self) -> None:
        expected = dict(self.projection.get("REG-001").event.claim["expected"])
        expected["location"] = "somewhere-else/release.json"
        changed = self.replace_regression_claim(expected=expected)

        result = run_regression(changed, "REG-001")

        self.assertEqual(result.status, RegressionStatus.FAILED)
        self.assertEqual(result.reason, RegressionReason.ASSERTIONS_FAILED)
        self.assertEqual(result.failed_assertion_ids, ("answer.location",))
        self.assertEqual(
            self.assertion(result, "answer.location").status,
            AssertionStatus.FAILED,
        )

    def test_valid_required_state_mismatch_returns_failed(self) -> None:
        required_states = dict(
            self.projection.get("REG-001").event.claim["required_states"]
        )
        required_states["DEC-001"] = "current"
        changed = self.replace_regression_claim(required_states=required_states)

        result = run_regression(changed, "REG-001")

        self.assertEqual(result.status, RegressionStatus.FAILED)
        self.assertIn("state.DEC-001", result.failed_assertion_ids)
        assertion = self.assertion(result, "state.DEC-001")
        self.assertEqual(assertion.expected, "current")
        self.assertEqual(assertion.actual, "superseded")

    def test_valid_resolver_evidence_mismatch_returns_failed(self) -> None:
        actual = resolve_question(self.projection, CANONICAL_QUESTION)
        reordered = replace(actual, evidence=actual.evidence[::-1])

        with patch(
            "victoria_trace.regression.resolve_question",
            return_value=reordered,
        ):
            result = run_regression(self.projection, "REG-001")

        self.assertEqual(result.status, RegressionStatus.FAILED)
        self.assertIn("answer.evidence", result.failed_assertion_ids)
        self.assertEqual(result.actual_evidence_ids, tuple(reversed(
            ("DEC-001", "DEC-002", "INT-001", "COR-001")
        )))

    def test_resolver_inconsistency_raises_execution_error(self) -> None:
        with patch(
            "victoria_trace.regression.resolve_question",
            side_effect=ResolutionError("synthetic resolver inconsistency"),
        ):
            with self.assertRaisesRegex(
                RegressionExecutionError,
                "resolver could not execute",
            ):
                run_regression(self.projection, "REG-001")

    def test_repeated_execution_is_deterministic(self) -> None:
        first = run_regression(self.projection, "REG-001")
        second = run_regression(self.projection, "REG-001")

        self.assertEqual(first, second)
        self.assertEqual(first.assertions, second.assertions)
        self.assertEqual(first.failed_assertion_ids, second.failed_assertion_ids)

    def test_result_and_nested_assertions_are_immutable(self) -> None:
        result = run_regression(self.projection, "REG-001")

        with self.assertRaises(FrozenInstanceError):
            result.status = RegressionStatus.FAILED  # type: ignore[misc]
        with self.assertRaises(TypeError):
            result.assertions[0] = result.assertions[0]  # type: ignore[index]
        with self.assertRaises(FrozenInstanceError):
            result.assertions[0].status = AssertionStatus.FAILED  # type: ignore[misc]
        with self.assertRaises(TypeError):
            result.required_evidence_ids[0] = "changed"  # type: ignore[index]
        with self.assertRaises(TypeError):
            evidence = self.assertion(result, "answer.evidence")
            evidence.expected[0] = "changed"  # type: ignore[index]

    def test_supplied_projection_remains_unchanged(self) -> None:
        original_events = self.projection.events
        original_mapping = tuple(self.projection.by_event_id.items())

        run_regression(self.projection, "REG-001")

        self.assertEqual(self.projection.events, original_events)
        self.assertEqual(tuple(self.projection.by_event_id.items()), original_mapping)
        for before, after in zip(
            original_events,
            self.projection.events,
            strict=True,
        ):
            self.assertIs(before, after)

    def test_run_all_regressions_is_stable_and_revision_ordered(self) -> None:
        first = run_all_regressions(self.projection)
        second = run_all_regressions(self.projection)

        self.assertEqual(first, second)
        self.assertEqual(
            tuple(result.regression_event_id for result in first),
            ("REG-001",),
        )
        self.assertEqual(first[0].status, RegressionStatus.PASSED)

    def test_correction_generated_regression_executes_end_to_end(self) -> None:
        revision_four = EventLedger.from_events(self.ledger[:4])
        correction = apply_correction(
            revision_four,
            canonical_correction_request(),
        )
        projection = project_ledger(correction.resulting_ledger)
        normal_resolution = resolve_question(projection, CANONICAL_QUESTION)

        regression = run_regression(projection, "REG-001")

        self.assertEqual(normal_resolution.status, AnswerStatus.SUPPORTED)
        self.assertEqual(regression.actual_resolution, normal_resolution)
        self.assertEqual(regression.status, RegressionStatus.PASSED)
        self.assertEqual(regression.failed_assertion_ids, ())
        self.assertEqual(
            regression.actual_evidence_ids,
            ("DEC-001", "DEC-002", "INT-001", "COR-001"),
        )


if __name__ == "__main__":
    unittest.main()
