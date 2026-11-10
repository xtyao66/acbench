"""Tests for benchmark result serialization."""

from __future__ import annotations

from enum import Enum
import unittest

from acbench.models.result import BenchmarkResult, ExecutorResult


class _ExampleStatus(Enum):
    """Local enum fixture for serialization tests."""

    OK = "ok"


class ResultModelTests(unittest.TestCase):
    def test_to_dict_normalizes_non_json_types(self) -> None:
        result = BenchmarkResult(
            scenario_id="s1",
            title="t",
            mode="ops_only",
            ops_result=ExecutorResult(
                backend="acbench-local-ops",
                success=True,
                details={"status": _ExampleStatus.OK, "items": (_ExampleStatus.OK,)},
            ),
        )

        payload = result.to_dict()

        self.assertEqual(payload["ops_result"]["details"]["status"], "ok")
        self.assertEqual(payload["ops_result"]["details"]["items"], ["ok"])


if __name__ == "__main__":
    unittest.main()
