# Copyright (C) 2026 Peter Van Geldorp
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from victoria_trace.models import Event, EventValidationError  # noqa: E402


FIXTURE = ROOT / "data" / "halcyon_history.jsonl"


class EventModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.raw_events = [
            json.loads(line)
            for line in FIXTURE.read_text(encoding="utf-8").splitlines()
        ]

    def test_event_round_trips_through_serialized_form(self) -> None:
        event = Event.from_dict(self.raw_events[4])

        self.assertEqual(Event.from_dict(event.to_dict()), event)
        self.assertEqual(json.loads(event.to_json_line()), event.to_dict())

    def test_event_claim_is_deeply_immutable(self) -> None:
        event = Event.from_dict(self.raw_events[5])

        with self.assertRaises(TypeError):
            event.claim["question"] = "changed"  # type: ignore[index]

        required_states = event.claim["required_states"]
        with self.assertRaises(TypeError):
            required_states["DEC-001"] = "current"  # type: ignore[index]

        required_evidence = event.claim["required_evidence"]
        self.assertIsInstance(required_evidence, tuple)

    def test_non_synthetic_provenance_is_rejected(self) -> None:
        raw_event = json.loads(json.dumps(self.raw_events[0]))
        raw_event["source"]["synthetic"] = False

        with self.assertRaisesRegex(EventValidationError, "must be true"):
            Event.from_dict(raw_event)

    def test_event_kind_must_match_identifier_prefix(self) -> None:
        raw_event = json.loads(json.dumps(self.raw_events[0]))
        raw_event["event_id"] = "INT-999"

        with self.assertRaisesRegex(EventValidationError, "DEC prefix"):
            Event.from_dict(raw_event)

    def test_unknown_fields_are_rejected(self) -> None:
        raw_event = json.loads(json.dumps(self.raw_events[0]))
        raw_event["silent_schema_drift"] = True

        with self.assertRaisesRegex(EventValidationError, "unknown fields"):
            Event.from_dict(raw_event)


if __name__ == "__main__":
    unittest.main()

