"""Tests for the localized pairing-state reproduction."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from openclaw_pairing_state.pairing_state import (
    approve_device_pairing,
    load_state,
    request_device_pairing,
)


class ArrayBackedStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="pairing-state-fixture-"))

    def tearDown(self) -> None:
        for child in sorted(self.temp_dir.glob("**/*"), reverse=True):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        self.temp_dir.rmdir()

    def test_array_typed_state_is_coerced_before_approval(self) -> None:
        (self.temp_dir / "pending.json").write_text("[]", encoding="utf-8")
        (self.temp_dir / "paired.json").write_text("[]", encoding="utf-8")

        request_device_pairing(self.temp_dir, "req-001", "device-a")
        approved = approve_device_pairing(self.temp_dir, "req-001")

        self.assertIsNotNone(approved)
        self.assertEqual(approved["status"], "approved")

    def test_object_backed_state_still_round_trips(self) -> None:
        (self.temp_dir / "pending.json").write_text("{}", encoding="utf-8")
        (self.temp_dir / "paired.json").write_text("{}", encoding="utf-8")

        request_device_pairing(self.temp_dir, "req-002", "device-b")
        approved = approve_device_pairing(self.temp_dir, "req-002")

        self.assertIsNotNone(approved)
        self.assertEqual(approved["device_id"], "device-b")
        paired_payload = json.loads((self.temp_dir / "paired.json").read_text(encoding="utf-8"))
        self.assertIn("device-b", paired_payload)

    def test_missing_state_files_default_to_empty_mappings(self) -> None:
        state = load_state(self.temp_dir)
        self.assertIsInstance(state["pending_by_id"], dict)
        self.assertIsInstance(state["paired_by_device_id"], dict)


if __name__ == "__main__":
    unittest.main()
