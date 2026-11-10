"""Tests for the open-engine changes: third-party sources + published schema."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from acbench.models.scenario import ScenarioSpec

REPO_ROOT = Path(__file__).resolve().parents[1]


class OpenEngineTests(unittest.TestCase):
    def _ops_payload(self, **overrides) -> dict:
        payload = {
            "scenario_id": "ext-1",
            "title": "third-party scenario",
            "mode": "ops_only",
            "service": {"application": "app", "service": "svc"},
            "ops_fault": {"source": "acme-taskpack", "problem_id": "p1",
                          "detection_keywords": ["boom"]},
            "success_criteria": {"require_detection": True},
        }
        payload.update(overrides)
        return payload

    def test_external_source_scenario_validates(self) -> None:
        # A third-party task pack uses its own source identifier, not "acbench".
        scenario = ScenarioSpec.from_dict(self._ops_payload())
        self.assertEqual(scenario.ops_fault.source, "acme-taskpack")
        self.assertEqual(scenario.schema_version, "1.0")

    def test_empty_source_is_rejected(self) -> None:
        bad = self._ops_payload(ops_fault={"source": "", "problem_id": "p1"})
        with self.assertRaises(ValueError):
            ScenarioSpec.from_dict(bad)

    def test_schema_version_roundtrips(self) -> None:
        scenario = ScenarioSpec.from_dict(self._ops_payload(schema_version="1.1"))
        self.assertEqual(scenario.schema_version, "1.1")
        self.assertEqual(scenario.to_dict()["schema_version"], "1.1")

    def test_published_schema_is_present_and_consistent(self) -> None:
        schema = json.loads((REPO_ROOT / "schemas" / "scenario.schema.json").read_text(encoding="utf-8"))
        self.assertIn("$schema", schema)
        self.assertEqual(schema["type"], "object")
        for field in ("scenario_id", "title", "mode", "service"):
            self.assertIn(field, schema["required"])
        self.assertIn("schema_version", schema["properties"])
        self.assertEqual(schema["properties"]["mode"]["enum"], ["ops_only", "code_only", "combined"])


if __name__ == "__main__":
    unittest.main()
